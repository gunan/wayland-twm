#!/usr/bin/env python3
"""Run one long-lived, evidence-producing native/Xwayland wtwm soak."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from run_compositor import Control


SCHEMA = "wtwm-mixed-soak-v1"
DEFAULT_DURATION_SECONDS = 72 * 60 * 60
SMOKE_ITERATIONS = 2
DEFAULT_MAX_RSS_GROWTH_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_FD_GROWTH = 32
DEFAULT_MAX_THREAD_GROWTH = 8
WAIT_SECONDS = 10.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile(smoke: bool, duration_seconds: float | None) -> dict[str, Any]:
    if smoke:
        return {
            "name": "smoke",
            "requested_duration_seconds": None,
            "requested_iterations": SMOKE_ITERATIONS,
        }
    requested = (
        DEFAULT_DURATION_SECONDS
        if duration_seconds is None
        else duration_seconds
    )
    return {
        "name": "72-hour" if requested == DEFAULT_DURATION_SECONDS else "duration",
        "requested_duration_seconds": float(requested),
        "requested_iterations": None,
    }


def expected_operations(iterations: int) -> dict[str, int]:
    return {
        "title_changes": iterations * 2,
        "map_unmap_cycles": iterations * 2,
        "resize_commits": iterations * 2,
        "focus_liveness_checks": iterations * 2,
        "crash_replacements": iterations,
        "native_crash_replacements": (iterations + 1) // 2,
        "x11_crash_replacements": iterations // 2,
        "trace_batches_checked": iterations,
    }


def validate_evidence(
    evidence: dict[str, Any], expected_harness_sha256: str | None = None
) -> list[str]:
    """Return contract violations without trusting the result label."""
    errors: list[str] = []
    if evidence.get("schema") != SCHEMA:
        errors.append("schema is not wtwm-mixed-soak-v1")
    run_profile = evidence.get("profile")
    if not isinstance(run_profile, dict):
        return errors + ["profile is not an object"]
    result = evidence.get("result")
    if result not in {"pass", "fail"}:
        errors.append("result is not pass or fail")
    elapsed = evidence.get("elapsed_seconds")
    iterations = evidence.get("iterations_completed")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0:
        errors.append("elapsed_seconds is not a nonnegative number")
        elapsed = 0.0
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 0:
        errors.append("iterations_completed is not a nonnegative integer")
        iterations = 0

    requested_duration = run_profile.get("requested_duration_seconds")
    requested_iterations = run_profile.get("requested_iterations")
    if requested_duration is not None and (
        not isinstance(requested_duration, (int, float))
        or isinstance(requested_duration, bool)
        or requested_duration <= 0
    ):
        errors.append("requested_duration_seconds is invalid")
    if requested_iterations is not None and (
        not isinstance(requested_iterations, int)
        or isinstance(requested_iterations, bool)
        or requested_iterations <= 0
    ):
        errors.append("requested_iterations is invalid")
    if (requested_duration is None) == (requested_iterations is None):
        errors.append("profile must select exactly one stopping target")
    if run_profile.get("name") == "smoke" and requested_iterations != SMOKE_ITERATIONS:
        errors.append("smoke profile does not request the canonical iteration count")
    if run_profile.get("name") == "72-hour" and requested_duration != DEFAULT_DURATION_SECONDS:
        errors.append("72-hour profile does not request exactly 259200 seconds")

    target_met = (
        elapsed >= requested_duration
        if isinstance(requested_duration, (int, float))
        else iterations >= requested_iterations
        if isinstance(requested_iterations, int)
        else False
    )
    criteria = evidence.get("pass_criteria")
    if not isinstance(criteria, dict) or any(
        not isinstance(value, bool) for value in criteria.values()
    ):
        errors.append("pass_criteria is not a boolean object")
        criteria = {}
    if criteria.get("stopping_target_met") is not target_met:
        errors.append("stopping_target_met disagrees with measured progress")

    operations = evidence.get("operations")
    if not isinstance(operations, dict):
        errors.append("operations is not an object")
    elif result == "pass" and operations != expected_operations(iterations):
        errors.append("passing operation counters do not cover every iteration")

    resources = evidence.get("resources")
    if not isinstance(resources, dict):
        errors.append("resources is not an object")
    else:
        initial = resources.get("initial")
        current = resources.get("current")
        peak = resources.get("peak")
        limits = resources.get("growth_limits")
        samples = resources.get("samples_observed")
        if not isinstance(samples, int) or samples < 0:
            errors.append("resource sample count is invalid")
            samples = 0
        if result == "pass" and samples < 1:
            errors.append("passing resource evidence has no observations")
        if samples == 0 and result == "fail":
            if any(item is not None for item in (initial, current, peak)):
                errors.append("zero-sample resource evidence contains observations")
        elif not all(isinstance(item, dict) for item in (initial, current, peak, limits)):
            errors.append("resource observation objects are incomplete")
        else:
            resource_limit_ok = True
            for metric, limit_name in (
                ("rss_bytes", "rss_bytes"),
                ("open_fds", "open_fds"),
                ("threads", "threads"),
            ):
                values = (initial.get(metric), current.get(metric), peak.get(metric))
                limit = limits.get(limit_name)
                valid_values = all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in values
                )
                if not valid_values:
                    errors.append(f"resource metric {metric} is invalid")
                    continue
                if not isinstance(limit, int) or limit < 0:
                    errors.append(f"resource growth limit {limit_name} is invalid")
                    continue
                if peak.get(metric) < max(initial.get(metric), current.get(metric)):
                    errors.append(f"peak {metric} is below an observed endpoint")
                if current.get(metric) - initial.get(metric) > limit:
                    resource_limit_ok = False
            if criteria.get("resource_limits_met") is not resource_limit_ok:
                errors.append("resource_limits_met disagrees with current growth")

    qualifying = result == "pass" and elapsed >= DEFAULT_DURATION_SECONDS
    if evidence.get("qualified_72_hour") is not qualifying:
        errors.append("qualified_72_hour disagrees with measured elapsed time")
    if result == "pass":
        if evidence.get("error") is not None:
            errors.append("passing evidence contains an error")
        if not criteria or not all(criteria.values()):
            errors.append("passing evidence has an unmet pass criterion")
    elif result == "fail" and evidence.get("error") is None:
        errors.append("failing evidence does not identify an error")

    provenance = evidence.get("provenance")
    harness_hash = provenance.get("harness_sha256") if isinstance(provenance, dict) else None
    if not isinstance(harness_hash, str) or len(harness_hash) != 64:
        errors.append("harness_sha256 is missing or malformed")
    if expected_harness_sha256 is not None and harness_hash != expected_harness_sha256:
        errors.append("harness_sha256 does not match the runner under validation")
    return errors


def read_linux_resources(pid: int) -> dict[str, int]:
    """Read current compositor resources; fail rather than invent observations."""
    proc = Path("/proc") / str(pid)
    status = (proc / "status").read_text(encoding="utf-8")
    fields: dict[str, int] = {}
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            fields["rss_bytes"] = int(line.split()[1]) * 1024
        elif line.startswith("Threads:"):
            fields["threads"] = int(line.split()[1])
    fields["open_fds"] = len(list((proc / "fd").iterdir()))
    missing = {"rss_bytes", "threads", "open_fds"} - fields.keys()
    if missing:
        raise RuntimeError(f"/proc resource sample omitted {sorted(missing)}")
    return fields


class ResourceLedger:
    def __init__(self, limits: dict[str, int]) -> None:
        self.limits = limits
        self.initial: dict[str, int] | None = None
        self.current: dict[str, int] | None = None
        self.peak: dict[str, int] | None = None
        self.peak_iteration: dict[str, int] = {}
        self.samples = 0
        self.checkpoints: list[dict[str, Any]] = []
        self.next_checkpoint_seconds = 3600.0

    def observe(self, pid: int, iteration: int, elapsed: float, final: bool = False) -> None:
        sample = read_linux_resources(pid)
        self.samples += 1
        self.current = sample
        if self.initial is None:
            self.initial = sample.copy()
            self.peak = sample.copy()
            self.peak_iteration = {key: iteration for key in sample}
        assert self.peak is not None
        for key, value in sample.items():
            if value > self.peak[key]:
                self.peak[key] = value
                self.peak_iteration[key] = iteration
        if self.samples == 1 or elapsed >= self.next_checkpoint_seconds or final:
            self.checkpoints.append({
                "elapsed_seconds": round(elapsed, 6),
                "iteration": iteration,
                **sample,
            })
            while elapsed >= self.next_checkpoint_seconds:
                self.next_checkpoint_seconds += 3600.0

    def limits_met(self) -> bool:
        if self.initial is None or self.current is None:
            return False
        return all(
            self.current[key] - self.initial[key] <= limit
            for key, limit in self.limits.items()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "sampler": "linux-proc-v1",
            "samples_observed": self.samples,
            "initial": self.initial,
            "current": self.current,
            "peak": self.peak,
            "peak_iteration": self.peak_iteration,
            "growth_limits": self.limits,
            "current_growth": {
                key: self.current[key] - self.initial[key]
                for key in self.limits
            } if self.initial is not None and self.current is not None else None,
            "hourly_and_endpoint_checkpoints": self.checkpoints,
        }


class ClientChannel:
    def __init__(self, process: subprocess.Popen[bytes], label: str) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError(f"{label} lacks control pipes")
        self.process = process
        self.label = label
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.buffer = bytearray()
        self.lines: list[str] = []
        os.set_blocking(self.stdout.fileno(), False)

    def line(self, deadline: float) -> str:
        while not self.lines:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"timed out waiting for {self.label}")
            readable, _, _ = select.select([self.stdout], [], [], remaining)
            if not readable:
                raise RuntimeError(f"timed out waiting for {self.label}")
            chunk = os.read(self.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError(
                    f"{self.label} exited while awaiting output "
                    f"(status={self.process.poll()})"
                )
            self.buffer.extend(chunk)
            while b"\n" in self.buffer:
                raw, _, remainder = self.buffer.partition(b"\n")
                self.buffer = bytearray(remainder)
                self.lines.append(raw.decode("utf-8", errors="strict"))
        return self.lines.pop(0)

    def expect(self, expected: str) -> None:
        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            line = self.line(deadline)
            if line == expected:
                return
            if not line.startswith("EVENT "):
                raise RuntimeError(
                    f"unexpected {self.label} response {line!r}; expected {expected!r}"
                )

    def expect_prefix(self, prefix: str) -> str:
        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            line = self.line(deadline)
            if line.startswith(prefix):
                return line
            if not line.startswith("EVENT "):
                raise RuntimeError(
                    f"unexpected {self.label} response {line!r}; expected {prefix!r}"
                )

    def command(self, command: str, expected: str) -> None:
        self.stdin.write((command + "\n").encode("utf-8"))
        self.stdin.flush()
        self.expect(expected)

    def expect_key_pair(self, token: str) -> None:
        expected = {
            f"EVENT KEY {token} 30 press",
            f"EVENT KEY {token} 30 release",
        }
        seen: set[str] = set()
        deadline = time.monotonic() + WAIT_SECONDS
        while seen != expected:
            line = self.line(deadline)
            if line in expected and line not in seen:
                seen.add(line)
            elif line not in {f"EVENT ENTER {token}", f"EVENT LEAVE {token}"}:
                raise RuntimeError(f"unexpected native liveness event {line!r}")


@dataclass
class SoakClient:
    protocol: str
    process: subprocess.Popen[bytes]
    channel: ClientChannel
    title: str
    generation: int
    cycle: int = 0
    xid: int | None = None


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
        if value:
            return value
        time.sleep(0.01)
    raise RuntimeError(f"startup command did not populate {path}")


def wait_state(control: Control, predicate, description: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def window(state: dict[str, Any], title: str) -> dict[str, Any]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {title!r} window: {state!r}")
    return matches[0]


def assert_pair(state: dict[str, Any], clients: dict[str, SoakClient]) -> None:
    if state["popups"] or state["override_redirect"] or state["interactive"]:
        raise RuntimeError(f"stale auxiliary or interactive scene state: {state!r}")
    if len(state["windows"]) != 2:
        raise RuntimeError(f"expected exactly two mixed windows: {state!r}")
    titles = {client.title for client in clients.values()}
    if {item["title"] for item in state["windows"]} != titles:
        raise RuntimeError(f"mixed window identities are stale or duplicated: {state!r}")
    if {item["stack"] for item in state["windows"]} != {0, 1}:
        raise RuntimeError(f"mixed stack is not contiguous: {state!r}")
    for protocol, client in clients.items():
        item = window(state, client.title)
        if item["type"] != protocol or not item["mapped"] or not item["decorated"]:
            raise RuntimeError(f"{protocol} window is not a live managed toplevel: {item!r}")
        if protocol == "wayland" and item["app_id"] != "org.wtwm.M9Soak":
            raise RuntimeError(f"native app_id changed: {item!r}")
        if protocol == "x11" and (
            item["xid"] != client.xid
            or item["instance"] != "wtwm-m9-soak"
            or item["class"] != "WtwmM9Soak"
        ):
            raise RuntimeError(f"X11 identity changed: {item!r}")
    lifecycle = state["xwayland_lifecycle"]
    x11 = clients["x11"]
    if len(lifecycle) != 1:
        raise RuntimeError(f"Xwayland lifecycle contains stale entries: {state!r}")
    entry = lifecycle[0]
    if (
        entry["xid"] != x11.xid
        or not entry["associated"]
        or not entry["mapped"]
        or not entry["has_buffer"]
        or entry["override_redirect"]
    ):
        raise RuntimeError(f"Xwayland association is not live: {state!r}")
    if state["active"] != state["focus"]:
        raise RuntimeError(f"logical and protocol focus disagree: {state!r}")


def pair_ready(state: dict[str, Any], clients: dict[str, SoakClient]) -> bool:
    try:
        assert_pair(state, clients)
    except (KeyError, RuntimeError, TypeError):
        return False
    return True


def visible_content_point(
    state: dict[str, Any], title: str
) -> tuple[int, int]:
    target = window(state, title)
    above = [
        item for item in state["windows"]
        if int(item["stack"]) < int(target["stack"])
    ]
    left = int(target["x"]) + int(target["content_x"])
    top = int(target["y"]) + int(target["content_y"])
    right = left + int(target["width"])
    bottom = top + int(target["height"])
    xs = (left + 12, right - 12, (left + right) // 2)
    ys = (top + 12, bottom - 12, (top + bottom) // 2)
    for point_y in ys:
        for point_x in xs:
            covered = any(
                int(other["x"]) <= point_x
                < int(other["x"]) + int(other["outer_width"])
                and int(other["y"]) <= point_y
                < int(other["y"]) + int(other["outer_height"])
                for other in above
            )
            if not covered:
                return point_x, point_y
    raise RuntimeError(f"no visible content point for {title!r}: {state!r}")


def point_and_wait(
    control: Control, title: str, point: tuple[int, int], context: str
) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        control.command(f"POINTER {point[0]} {point[1]}")
        control.command("WAIT 1")
        state = control.state()
        if state["pointer_window"] == title and state["pointer_context"] == context:
            return state
        time.sleep(0.01)
    raise RuntimeError(f"pointer did not reach {title!r} {context}: {control.state()!r}")


def focus_and_raise(
    control: Control, clients: dict[str, SoakClient], protocol: str, token: str
) -> None:
    client = clients[protocol]
    if protocol == "wayland":
        client.channel.command(f"ARM {token}", f"OK ARMED {token}")
    state = control.state()
    point = visible_content_point(state, client.title)
    point_and_wait(control, client.title, point, "window")
    control.command("BUTTON 273 press")
    control.command("BUTTON 273 release")
    wait_state(
        control,
        lambda candidate: candidate["focus_root"]
        and candidate["active"] is None
        and candidate["focus"] is None,
        f"{protocol} deterministic PointerRoot reset",
    )
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")
    state = wait_state(
        control,
        lambda candidate: candidate["focus"] == client.title
        and window(candidate, client.title)["stack"] == 0,
        f"{protocol} focus/raise liveness",
    )
    assert_pair(state, clients)
    if protocol == "wayland":
        control.command("KEY 30 press")
        control.command("KEY 30 release")
        client.channel.expect_key_pair(token)
        client.channel.command(
            f"REPORT {token}", f"OK REPORT {token} keys=2 focus=1 close=0"
        )
    else:
        client.channel.command(
            "REPORT", f"OK REPORT close=0 mapped=1 cycle={client.cycle}"
        )


def resize(control: Control, clients: dict[str, SoakClient], protocol: str,
           iteration: int) -> None:
    client = clients[protocol]
    focus_and_raise(control, clients, protocol, f"resize-{protocol}-{iteration}")
    before = window(control.state(), client.title)
    old = (int(before["width"]), int(before["height"]))
    point = (
        int(before["x"]) + int(before["width"]) * 5 // 6,
        int(before["y"]) + int(before["title_height"])
        + int(before["height"]) * 5 // 6,
    )
    point_and_wait(control, client.title, point, "window")
    control.command("BUTTON 274 press")
    active = control.state()["interaction"]
    if not isinstance(active, dict) or active.get("mode") != "resize":
        raise RuntimeError(f"f.resize did not start for {protocol}: {active!r}")
    delta = 11 if iteration % 2 else -11
    control.command(f"POINTER {point[0] + delta} {point[1] + delta}")
    preview = control.state()["interaction"]
    if not isinstance(preview, dict) or not preview.get("started"):
        raise RuntimeError(f"resize motion did not start for {protocol}: {preview!r}")
    expected = (int(preview["preview"]["width"]), int(preview["preview"]["height"]))
    control.command("BUTTON 274 release")
    state = wait_state(
        control,
        lambda candidate: (
            int(window(candidate, client.title)["width"]),
            int(window(candidate, client.title)["height"]),
        ) == expected and not candidate["interactive"],
        f"{protocol} resize commit",
    )
    if expected == old:
        raise RuntimeError(f"{protocol} resize produced no size change: {state!r}")
    assert_pair(state, clients)


def assert_single_after_unmap(
    state: dict[str, Any], clients: dict[str, SoakClient], unmapped: str
) -> None:
    other = "x11" if unmapped == "wayland" else "wayland"
    if len(state["windows"]) != 1 or state["windows"][0]["title"] != clients[other].title:
        raise RuntimeError(f"{unmapped} unmap left stale managed state: {state!r}")
    if state["popups"] or state["override_redirect"] or state["interactive"]:
        raise RuntimeError(f"{unmapped} unmap left auxiliary state: {state!r}")
    lifecycle = state["xwayland_lifecycle"]
    if len(lifecycle) != 1 or lifecycle[0]["xid"] != clients["x11"].xid:
        raise RuntimeError(f"{unmapped} unmap damaged Xwayland identity: {state!r}")
    expected_live = unmapped != "x11"
    if any(bool(lifecycle[0][key]) != expected_live for key in
           ("associated", "mapped", "has_buffer")):
        raise RuntimeError(f"{unmapped} unmap lifecycle state is wrong: {state!r}")


def map_unmap(control: Control, clients: dict[str, SoakClient], protocol: str) -> None:
    client = clients[protocol]
    client.cycle += 1
    client.channel.command(f"UNMAP {client.cycle}", f"OK UNMAPPED {client.cycle}")
    state = wait_state(
        control,
        lambda candidate: len(candidate["windows"]) == 1,
        f"{protocol} unmap cleanup",
    )
    assert_single_after_unmap(state, clients, protocol)
    client.channel.command(f"REMAP {client.cycle}", f"OK REMAPPED {client.cycle}")
    state = wait_state(control, lambda candidate: pair_ready(candidate, clients),
                       f"{protocol} remap")
    assert_pair(state, clients)


def trace_check(control: Control, titles: set[str]) -> None:
    trace = control.trace()
    if trace["version"] != 1 or trace["dropped"] != 0 or not trace["events"]:
        raise RuntimeError(f"incomplete per-iteration trace evidence: {trace!r}")
    relevant = [event for event in trace["events"]
                if event["window"]["title"] in titles]
    kinds = {event["event"] for event in relevant}
    required = {"title", "map", "unmap", "configure", "focus"}
    if not required.issubset(kinds):
        raise RuntimeError(f"iteration trace omitted {sorted(required - kinds)}: {trace!r}")


def wait_process(process: subprocess.Popen[bytes], label: str) -> int:
    try:
        return process.wait(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"timed out waiting for {label} process") from error


def run_live(arguments: argparse.Namespace, evidence: dict[str, Any]) -> None:
    run_profile = evidence["profile"]
    operations = evidence["operations"]
    limits = {
        "rss_bytes": arguments.max_rss_growth_bytes,
        "open_fds": arguments.max_fd_growth,
        "threads": arguments.max_thread_growth,
    }
    ledger = ResourceLedger(limits)
    evidence["resources"] = ledger.as_dict()
    monotonic_start = time.monotonic()
    compositor: subprocess.Popen[str] | None = None
    control: Control | None = None
    clients: dict[str, SoakClient] = {}
    all_processes: list[subprocess.Popen[bytes]] = []
    compositor_log = evidence["artifacts"]["compositor_log"]
    client_log = evidence["artifacts"]["client_log"]

    with tempfile.TemporaryDirectory(prefix="wtwm-m9-soak-") as directory, \
            Path(compositor_log).open("wb") as compositor_errors, \
            Path(client_log).open("wb") as client_errors:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "m9-soak.twmrc"
        config_text = (
            "NoDefaults\nRandomPlacement\nNoGrabServer\nNoIconManagers\n"
            'Function "focus-raise" { f.focus f.raise }\n'
            'Button1 = : window : f.function "focus-raise"\n'
            "Button2 = : window : f.resize\n"
            "Button3 = : window : f.unfocus\n"
        )
        config.write_text(config_text, encoding="utf-8")
        evidence["provenance"]["configuration_sha256"] = hashlib.sha256(
            config_text.encode("utf-8")
        ).hexdigest()
        display_name = f"wtwm-m9-soak-{os.getpid()}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        compositor = subprocess.Popen(
            [
                str(arguments.compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", display_name,
                "--test-backend", "headless",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=compositor_errors,
            text=True,
        )
        # Evidence duration is compositor-session lifetime, not harness setup time.
        monotonic_start = time.monotonic()
        wayland_environment = environment.copy()
        wayland_environment["WAYLAND_DISPLAY"] = display_name
        x11_environment = environment.copy()

        def launch(protocol: str, generation: int) -> SoakClient:
            title = f"wtwm-m9-{protocol}-g{generation}"
            if protocol == "wayland":
                command = [str(arguments.wayland_client), title, "org.wtwm.M9Soak"]
                child_environment = wayland_environment
            else:
                command = [
                    str(arguments.x11_client), title,
                    "wtwm-m9-soak", "WtwmM9Soak",
                ]
                child_environment = x11_environment
            child = subprocess.Popen(
                command,
                env=child_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=client_errors,
            )
            all_processes.append(child)
            channel = ClientChannel(child, title)
            xid = None
            if protocol == "wayland":
                channel.expect(f"OK READY {title}")
            else:
                ready = channel.expect_prefix(f"OK READY {title} ")
                xid = int(ready.rsplit(" ", 1)[1])
            return SoakClient(protocol, child, channel, title, generation, xid=xid)

        try:
            control = Control(control_path, compositor)
            control.socket.settimeout(WAIT_SECONDS)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 800 600")
            control.command("SET CURSOR 8 8")
            control.command("WAIT 2")
            x11_environment["DISPLAY"] = wait_path(display_marker)
            clients["wayland"] = launch("wayland", 0)
            clients["x11"] = launch("x11", 0)
            state = wait_state(control, lambda candidate: pair_ready(candidate, clients),
                               "initial mixed clients")
            assert_pair(state, clients)
            ledger.observe(compositor.pid, 0, time.monotonic() - monotonic_start)

            while True:
                elapsed = time.monotonic() - monotonic_start
                requested_iterations = run_profile["requested_iterations"]
                requested_duration = run_profile["requested_duration_seconds"]
                if requested_iterations is not None:
                    if evidence["iterations_completed"] >= requested_iterations:
                        break
                elif evidence["iterations_completed"] > 0 and elapsed >= requested_duration:
                    break

                iteration = evidence["iterations_completed"] + 1
                control.command("TRACE CLEAR")
                old_titles = {client.title for client in clients.values()}
                for protocol in ("wayland", "x11"):
                    client = clients[protocol]
                    new_title = f"wtwm-m9-{protocol}-g{client.generation}-i{iteration}"
                    client.channel.command(f"TITLE {new_title}", f"OK TITLE {new_title}")
                    client.title = new_title
                    wait_state(
                        control,
                        lambda candidate, title=new_title: any(
                            item["title"] == title for item in candidate["windows"]
                        ),
                        f"{protocol} title mutation",
                    )
                    operations["title_changes"] += 1
                assert_pair(control.state(), clients)

                for protocol in ("wayland", "x11"):
                    focus_and_raise(control, clients, protocol,
                                    f"focus-{protocol}-{iteration}")
                    operations["focus_liveness_checks"] += 1
                    resize(control, clients, protocol, iteration)
                    operations["resize_commits"] += 1
                    map_unmap(control, clients, protocol)
                    operations["map_unmap_cycles"] += 1

                trace_check(control, old_titles | {client.title for client in clients.values()})
                operations["trace_batches_checked"] += 1

                crash_protocol = "wayland" if iteration % 2 else "x11"
                crashed = clients[crash_protocol]
                crashed.channel.command("CRASH", "OK CRASH")
                status = wait_process(crashed.process, f"{crash_protocol} crash")
                if status != -signal.SIGABRT:
                    raise RuntimeError(
                        f"{crash_protocol} crash exited {status}, expected {-signal.SIGABRT}"
                    )
                wait_state(
                    control,
                    lambda candidate: len(candidate["windows"]) == 1
                    and candidate["windows"][0]["title"]
                    == clients["x11" if crash_protocol == "wayland" else "wayland"].title
                    and (
                        crash_protocol != "x11"
                        or not candidate["xwayland_lifecycle"]
                    ),
                    f"{crash_protocol} crash cleanup",
                )
                replacement = launch(crash_protocol, crashed.generation + 1)
                clients[crash_protocol] = replacement
                state = wait_state(control, lambda candidate: pair_ready(candidate, clients),
                                   f"{crash_protocol} replacement")
                assert_pair(state, clients)
                operations["crash_replacements"] += 1
                operations[f"{crash_protocol}_crash_replacements"] += 1

                evidence["iterations_completed"] = iteration
                elapsed = time.monotonic() - monotonic_start
                ledger.observe(compositor.pid, iteration, elapsed)
                if not ledger.limits_met():
                    raise RuntimeError(
                        f"compositor current resource growth exceeded a limit: "
                        f"{ledger.as_dict()!r}"
                    )

            for client in clients.values():
                client.channel.command("EXIT", "OK EXIT")
                if wait_process(client.process, f"{client.protocol} clean exit") != 0:
                    raise RuntimeError(f"{client.protocol} did not exit cleanly")
            wait_state(
                control,
                lambda candidate: not candidate["windows"]
                and not candidate["xwayland_lifecycle"]
                and candidate["focus"] is None,
                "empty final compositor state",
            )
            ledger.observe(
                compositor.pid,
                evidence["iterations_completed"],
                time.monotonic() - monotonic_start,
                final=True,
            )
            control.command("QUIT")
            compositor.wait(timeout=WAIT_SECONDS)
            evidence["pass_criteria"]["compositor_clean_exit"] = compositor.returncode == 0
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor returned {compositor.returncode}")
            evidence["pass_criteria"]["workload_completed"] = (
                operations == expected_operations(evidence["iterations_completed"])
            )
            evidence["pass_criteria"]["resource_limits_met"] = ledger.limits_met()
        finally:
            evidence["elapsed_seconds"] = round(time.monotonic() - monotonic_start, 6)
            evidence["resources"] = ledger.as_dict()
            for child in all_processes:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=WAIT_SECONDS)
            if control is not None:
                control.close()
            if compositor is not None and compositor.poll() is None:
                compositor.terminate()
                try:
                    compositor.wait(timeout=WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=WAIT_SECONDS)


def make_initial_evidence(arguments: argparse.Namespace) -> dict[str, Any]:
    runner = Path(__file__).resolve()
    run_profile = profile(arguments.smoke, arguments.duration_seconds)
    return {
        "schema": SCHEMA,
        "result": "fail",
        "profile": run_profile,
        "started_at_utc": utc_now(),
        "ended_at_utc": None,
        "elapsed_seconds": 0.0,
        "iterations_completed": 0,
        "qualified_72_hour": False,
        "pass_criteria": {
            "stopping_target_met": False,
            "workload_completed": False,
            "resource_limits_met": False,
            "compositor_clean_exit": False,
        },
        "operations": {key: 0 for key in expected_operations(0)},
        "resources": {},
        "error": None,
        "provenance": {
            "harness": str(runner),
            "harness_sha256": sha256_file(runner),
            "compositor": str(arguments.compositor),
            "compositor_sha256": sha256_file(arguments.compositor),
            "wayland_client": str(arguments.wayland_client),
            "wayland_client_sha256": sha256_file(arguments.wayland_client),
            "x11_client": str(arguments.x11_client),
            "x11_client_sha256": sha256_file(arguments.x11_client),
            "configuration_sha256": None,
            "argv": sys.argv,
            "python": sys.version,
        },
        "artifacts": {
            "evidence": str(arguments.output),
            "compositor_log": str(arguments.output) + ".compositor.log",
            "client_log": str(arguments.output) + ".clients.log",
        },
    }


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one 72-hour mixed native/Xwayland soak by default"
    )
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--wayland-client", type=Path, required=True)
    parser.add_argument("--x11-client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--smoke", action="store_true",
        help=f"run the bounded {SMOKE_ITERATIONS}-iteration CI profile",
    )
    target.add_argument(
        "--duration-seconds", type=float,
        help="override the default 259200-second soak duration",
    )
    parser.add_argument("--max-rss-growth-bytes", type=int,
                        default=DEFAULT_MAX_RSS_GROWTH_BYTES)
    parser.add_argument("--max-fd-growth", type=int, default=DEFAULT_MAX_FD_GROWTH)
    parser.add_argument("--max-thread-growth", type=int,
                        default=DEFAULT_MAX_THREAD_GROWTH)
    parser.add_argument(
        "--overwrite", action="store_true",
        help="replace prior generated evidence/log artifacts (for repeatable CI runs)",
    )
    arguments = parser.parse_args()
    if arguments.duration_seconds is not None and arguments.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    for name in ("max_rss_growth_bytes", "max_fd_growth", "max_thread_growth"):
        if getattr(arguments, name) < 0:
            parser.error(f"--{name.replace('_', '-')} must be nonnegative")
    arguments.compositor = arguments.compositor.resolve()
    arguments.wayland_client = arguments.wayland_client.resolve()
    arguments.x11_client = arguments.x11_client.resolve()
    arguments.output = arguments.output.resolve()
    for name in ("compositor", "wayland_client", "x11_client"):
        path = getattr(arguments, name)
        if not path.is_file():
            parser.error(f"--{name.replace('_', '-')} is not a file: {path}")
    if not arguments.output.parent.is_dir():
        parser.error(f"--output parent does not exist: {arguments.output.parent}")
    artifact_paths = [
        arguments.output,
        Path(str(arguments.output) + ".compositor.log"),
        Path(str(arguments.output) + ".clients.log"),
    ]
    existing = [str(path) for path in artifact_paths if path.exists()]
    if existing and not arguments.overwrite:
        parser.error(f"refusing to overwrite existing artifacts: {existing}")
    return arguments


def main() -> int:
    arguments = parse_arguments()
    evidence = make_initial_evidence(arguments)
    try:
        run_live(arguments, evidence)
        run_profile = evidence["profile"]
        evidence["pass_criteria"]["stopping_target_met"] = (
            evidence["elapsed_seconds"] >= run_profile["requested_duration_seconds"]
            if run_profile["requested_duration_seconds"] is not None
            else evidence["iterations_completed"] >= run_profile["requested_iterations"]
        )
        if not all(evidence["pass_criteria"].values()):
            raise RuntimeError(f"one or more pass criteria failed: {evidence['pass_criteria']!r}")
        evidence["result"] = "pass"
    except BaseException as error:
        evidence["result"] = "fail"
        evidence["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        evidence["ended_at_utc"] = utc_now()
        run_profile = evidence["profile"]
        requested_duration = run_profile["requested_duration_seconds"]
        requested_iterations = run_profile["requested_iterations"]
        evidence["pass_criteria"]["stopping_target_met"] = (
            evidence["elapsed_seconds"] >= requested_duration
            if requested_duration is not None
            else evidence["iterations_completed"] >= requested_iterations
        )
        resources = evidence.get("resources", {})
        initial = resources.get("initial")
        current = resources.get("current")
        limits = resources.get("growth_limits")
        evidence["pass_criteria"]["resource_limits_met"] = (
            isinstance(initial, dict)
            and isinstance(current, dict)
            and isinstance(limits, dict)
            and all(current[key] - initial[key] <= limits[key] for key in limits)
        )
        evidence["qualified_72_hour"] = (
            evidence["result"] == "pass"
            and evidence["elapsed_seconds"] >= DEFAULT_DURATION_SECONDS
        )
        contract_errors = validate_evidence(
            evidence, sha256_file(Path(__file__).resolve())
        )
        if contract_errors:
            evidence["result"] = "fail"
            evidence["qualified_72_hour"] = False
            evidence["error"] = {
                "type": "EvidenceContractError",
                "message": "; ".join(contract_errors),
            }
        write_evidence(arguments.output, evidence)
    failure = evidence.get("error")
    failure_summary = (
        f" error={failure.get('type')}: {failure.get('message')}"
        if isinstance(failure, dict) else ""
    )
    print(
        f"m9 mixed soak {evidence['result']}: iterations="
        f"{evidence['iterations_completed']} elapsed={evidence['elapsed_seconds']:.3f}s "
        f"qualified_72_hour={str(evidence['qualified_72_hour']).lower()} "
        f"evidence={arguments.output}{failure_summary}"
    )
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
