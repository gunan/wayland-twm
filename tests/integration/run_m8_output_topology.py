#!/usr/bin/env python3
"""Verify atomic headless output-topology transactions and their invariants."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
from typing import Callable

from run_client_stress import ClientChannel
from run_compositor import Control


NATIVE_TITLE = "wtwm-topology-native"
NATIVE_APP_ID = "org.wtwm.OutputTopology"
X11_TITLE = "wtwm-topology-x11"
BUTTON_CODES = {1: 272, 2: 274, 3: 273, 4: 275}
TRANSFORMS = (
    "normal",
    "90",
    "180",
    "270",
    "flipped",
    "flipped-90",
    "flipped-180",
    "flipped-270",
)
OUTPUT_KEYS = {
    "name",
    "ordinal",
    "index",
    "enabled",
    "mode",
    "scale",
    "transform",
    "box",
    "background",
}


def config_text() -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        'Button1 = : all : f.warptoscreen "0"\n'
        'Button2 = : all : f.warptoscreen "1"\n'
        'Button3 = : all : f.warptoscreen "2"\n'
        'Button4 = : all : f.warptoscreen "back"\n'
    )


@dataclass(frozen=True)
class ModelOutput:
    name: str
    ordinal: int
    enabled: bool = True
    width: int = 320
    height: int = 240
    refresh_mhz: int = 0
    scale: float = 1.0
    transform: str = "normal"
    position: tuple[int, int] | None = None

    def logical_size(self) -> tuple[int, int]:
        width = self.width
        height = self.height
        if self.transform in {"90", "270", "flipped-90", "flipped-270"}:
            width, height = height, width
        return round(width / self.scale), round(height / self.scale)


class TopologyModel:
    def __init__(self) -> None:
        self.outputs: list[ModelOutput] = []
        self.next_ordinal = 0
        self.current: str | None = None
        self.previous: str | None = None
        self.pointer = (0, 0)

    def add(self, name: str, width: int, height: int) -> None:
        self.outputs.append(
            ModelOutput(name, self.next_ordinal, width=width, height=height)
        )
        self.next_ordinal += 1
        self.outputs.sort(key=lambda output: (output.name.encode("utf-8"), output.ordinal))
        if self.current is None:
            self.current = name

    def item(self, name: str) -> tuple[int, ModelOutput]:
        for index, output in enumerate(self.outputs):
            if output.name == name:
                return index, output
        raise KeyError(name)

    def update(self, name: str, **changes: object) -> None:
        index, output = self.item(name)
        self.outputs[index] = replace(output, **changes)

    def active(self) -> list[ModelOutput]:
        return [output for output in self.outputs if output.enabled]

    def destroy(self, name: str) -> None:
        index, _ = self.item(name)
        del self.outputs[index]
        if self.previous == name:
            self.previous = None
        if self.current == name:
            active = self.active()
            self.current = active[0].name if active else None

    def warp(self, target_index: int) -> None:
        active = self.active()
        if not (0 <= target_index < len(active)):
            return
        target = active[target_index].name
        if target != self.current:
            self.previous, self.current = self.current, target

    def back(self) -> None:
        if self.previous is None or self.previous not in {
            output.name for output in self.active()
        }:
            self.previous = None
            return
        self.previous, self.current = self.current, self.previous

    def snapshot(self) -> tuple[object, ...]:
        return (
            tuple(self.outputs),
            self.next_ordinal,
            self.current,
            self.previous,
            self.pointer,
        )


def validate_model() -> None:
    if TRANSFORMS != (
        "normal",
        "90",
        "180",
        "270",
        "flipped",
        "flipped-90",
        "flipped-180",
        "flipped-270",
    ):
        raise RuntimeError("frozen output transform spellings changed")

    reordered = TopologyModel()
    reordered.add("HEADLESS-3", 320, 240)
    reordered.add("HEADLESS-1", 300, 200)
    reordered.add("HEADLESS-2", 240, 180)
    if [(item.name, item.ordinal) for item in reordered.outputs] != [
        ("HEADLESS-1", 1),
        ("HEADLESS-2", 2),
        ("HEADLESS-3", 0),
    ]:
        raise RuntimeError("canonical identity order followed announcement order")

    model = TopologyModel()
    model.add("HEADLESS-1", 300, 200)
    model.add("HEADLESS-2", 240, 180)
    model.add("HEADLESS-3", 320, 240)
    if [(item.name, item.ordinal) for item in model.outputs] != [
        ("HEADLESS-1", 0),
        ("HEADLESS-2", 1),
        ("HEADLESS-3", 2),
    ]:
        raise RuntimeError("announcement order or immutable ordinals changed")

    model.update(
        "HEADLESS-2",
        width=400,
        height=300,
        refresh_mhz=60_000,
        scale=1.25,
        position=(700, 40),
    )
    if model.item("HEADLESS-2")[1].logical_size() != (320, 240):
        raise RuntimeError("fractional output scale model changed")
    model.update("HEADLESS-2", transform="90")
    if model.item("HEADLESS-2")[1].logical_size() != (240, 320):
        raise RuntimeError("quarter-turn transform did not swap logical axes")
    model.update("HEADLESS-2", transform="normal", scale=2.0)
    if model.item("HEADLESS-2")[1].logical_size() != (200, 150):
        raise RuntimeError("integer output scale model changed")

    model.update("HEADLESS-2", enabled=False)
    before_failed_mode = model.snapshot()
    try:
        if not model.item("HEADLESS-2")[1].enabled:
            raise ValueError("mode requires enabled output")
        model.update("HEADLESS-2", width=1, height=1)
    except ValueError:
        pass
    if model.snapshot() != before_failed_mode:
        raise RuntimeError("failed disabled-output mode was not atomic")
    if [item.name for item in model.active()] != ["HEADLESS-1", "HEADLESS-3"]:
        raise RuntimeError("disabled output was not removed from dense active order")
    model.update("HEADLESS-2", enabled=True)
    if [item.name for item in model.active()] != [
        "HEADLESS-1",
        "HEADLESS-2",
        "HEADLESS-3",
    ]:
        raise RuntimeError("re-enabled output did not regain canonical ordinal slot")

    model.warp(2)
    model.back()
    if (model.current, model.previous) != ("HEADLESS-1", "HEADLESS-3"):
        raise RuntimeError("screen history did not retain immutable output identity")
    model.destroy("HEADLESS-2")
    model.back()
    if (model.current, model.previous) != ("HEADLESS-3", "HEADLESS-1"):
        raise RuntimeError("survivor renumbering corrupted screen history")
    model.back()
    model.destroy("HEADLESS-3")
    model.back()
    if (model.current, model.previous) != ("HEADLESS-1", None):
        raise RuntimeError("destroyed previous-screen identity remained actionable")

    before_unknown = model.snapshot()
    try:
        model.item("MISSING")
    except KeyError:
        pass
    if model.snapshot() != before_unknown:
        raise RuntimeError("unknown-output failure mutated topology state")
    model.update("HEADLESS-1", enabled=False)
    if model.active():
        raise RuntimeError("zero-active-output state was not representable")
    model.update("HEADLESS-1", enabled=True)
    model.add("HEADLESS-4", 640, 480)
    if model.item("HEADLESS-4")[1].ordinal != 3:
        raise RuntimeError("destroyed output ordinal was reused")
    model.destroy("HEADLESS-1")
    model.destroy("HEADLESS-4")
    if model.outputs or model.active():
        raise RuntimeError("zero-managed-output state was not representable")


def validate_generated_config(config_tool: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-topology-config-") as directory:
        path = Path(directory) / "output-topology.twmrc"
        path.write_text(config_text(), encoding="utf-8")
        result = subprocess.run(
            [str(config_tool), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "portable wtwm-config rejected generated topology config: "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        if "bindings=4\n" not in result.stdout:
            raise RuntimeError(f"topology config lost a binding: {result.stdout!r}")
        if "compatibility-warnings=0\n" not in result.stdout:
            raise RuntimeError(
                f"topology config emitted a compatibility warning: {result.stdout!r}"
            )


def read_prefixed_line(
    process: subprocess.Popen[bytes], prefix: str, label: str
) -> str:
    if process.stdout is None:
        raise RuntimeError(f"{label} lacks stdout")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    buffer = bytearray()
    deadline = time.monotonic() + 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"timed out waiting for {label} {prefix!r}")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise RuntimeError(f"timed out waiting for {label} {prefix!r}")
        chunk = os.read(descriptor, 4096)
        if not chunk:
            raise RuntimeError(
                f"{label} exited before {prefix!r} (status={process.poll()})"
            )
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw, _, remainder = buffer.partition(b"\n")
            buffer = bytearray(remainder)
            line = raw.decode("utf-8", errors="strict")
            if line.startswith(prefix):
                return line


def box_tuple(value: object, label: str) -> tuple[int, int, int, int]:
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise RuntimeError(f"{label} box schema changed: {value!r}")
    result = tuple(value[key] for key in ("x", "y", "width", "height"))
    if not all(isinstance(item, int) for item in result):
        raise RuntimeError(f"{label} box contains a non-integer: {value!r}")
    return result  # type: ignore[return-value]


def output_map(state: dict[str, object]) -> dict[str, dict[str, object]]:
    records = state.get("outputs")
    if not isinstance(records, list):
        raise RuntimeError(f"STATE omitted managed output inventory: {state!r}")
    result: dict[str, dict[str, object]] = {}
    active_index = 0
    ordinals: list[int] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != OUTPUT_KEYS:
            raise RuntimeError(f"STATE output schema changed: {record!r}")
        name = record["name"]
        ordinal = record["ordinal"]
        if not isinstance(name, str) or not isinstance(ordinal, int):
            raise RuntimeError(f"STATE output identity is invalid: {record!r}")
        if name in result:
            raise RuntimeError(f"STATE duplicated managed output {name!r}")
        ordinals.append(ordinal)
        mode = record["mode"]
        if not isinstance(mode, dict) or set(mode) != {
            "width",
            "height",
            "refresh_mhz",
        }:
            raise RuntimeError(f"STATE output mode schema changed: {record!r}")
        if not all(isinstance(mode[key], int) for key in mode):
            raise RuntimeError(f"STATE output mode is non-integral: {record!r}")
        if not isinstance(record["scale"], (int, float)) or not math.isfinite(
            float(record["scale"])
        ):
            raise RuntimeError(f"STATE output scale is invalid: {record!r}")
        if record["transform"] not in TRANSFORMS:
            raise RuntimeError(f"STATE output transform is invalid: {record!r}")
        if record["enabled"] is True:
            if record["index"] != active_index:
                raise RuntimeError(f"active output index is not dense: {records!r}")
            box = box_tuple(record["box"], f"{name} layout")
            background = box_tuple(record["background"], f"{name} background")
            if box != background or box[2] <= 0 or box[3] <= 0:
                raise RuntimeError(f"output background/layout diverged: {record!r}")
            active_index += 1
        elif record["enabled"] is False:
            if any(record[key] is not None for key in ("index", "box", "background")):
                raise RuntimeError(f"disabled output retained active scene state: {record!r}")
        else:
            raise RuntimeError(f"output enabled state is not boolean: {record!r}")
        result[name] = record
    if ordinals != sorted(ordinals) or len(set(ordinals)) != len(ordinals):
        raise RuntimeError(f"managed outputs lost immutable announcement order: {records!r}")
    return result


def assert_output(
    state: dict[str, object],
    name: str,
    *,
    ordinal: int,
    index: int | None,
    enabled: bool,
    mode: tuple[int, int, int] | None = None,
    scale: float | None = None,
    transform: str | None = None,
    box: tuple[int, int, int, int] | None = None,
) -> dict[str, object]:
    record = output_map(state).get(name)
    if record is None:
        raise RuntimeError(f"STATE omitted output {name!r}: {state!r}")
    if (record["ordinal"], record["index"], record["enabled"]) != (
        ordinal,
        index,
        enabled,
    ):
        raise RuntimeError(f"{name} identity/active state changed: {record!r}")
    if mode is not None:
        observed_mode = record["mode"]
        assert isinstance(observed_mode, dict)
        observed = tuple(
            observed_mode[key] for key in ("width", "height", "refresh_mhz")
        )
        if observed != mode:
            raise RuntimeError(f"{name} mode mismatch {observed!r} != {mode!r}")
    if scale is not None and not math.isclose(
        float(record["scale"]), scale, rel_tol=0.0, abs_tol=0.000_001
    ):
        raise RuntimeError(f"{name} scale mismatch: {record!r}")
    if transform is not None and record["transform"] != transform:
        raise RuntimeError(f"{name} transform mismatch: {record!r}")
    if box is not None and box_tuple(record["box"], name) != box:
        raise RuntimeError(f"{name} box mismatch: {record!r}")
    return record


def state_windows_ready(state: dict[str, object]) -> bool:
    windows = state.get("windows")
    return isinstance(windows, list) and len(windows) == 2 and {
        item.get("title") for item in windows if isinstance(item, dict)
    } == {NATIVE_TITLE, X11_TITLE} and all(
        item.get("mapped") is True for item in windows if isinstance(item, dict)
    )


def bounded_state(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    label: str,
    attempts: int = 64,
) -> dict[str, object]:
    last: dict[str, object] | None = None
    for _ in range(attempts):
        last = control.state()
        if predicate(last):
            return last
        control.command("WAIT 1")
    raise RuntimeError(f"bounded STATE barrier failed for {label}: {last!r}")


def raw_command(control: Control, command: str) -> str:
    control.stream.write(command + "\n")
    control.stream.flush()
    return control.stream.readline().rstrip("\n")


def expect_command(control: Control, command: str, expected: str) -> None:
    observed = control.command(command)
    if observed != expected:
        raise RuntimeError(
            f"{command!r}: expected {expected!r}, observed {observed!r}"
        )


def frame_barrier(control: Control, label: str) -> dict[str, object]:
    before = control.state()
    response = control.command("WAIT 2")
    match = re.fullmatch(r"OK FRAME ([0-9]+)", response)
    after = control.state()
    if match is None:
        raise RuntimeError(f"{label}: malformed frame barrier {response!r}")
    sequence = int(match.group(1))
    if sequence <= int(before["frame"]) or after["frame"] != sequence:
        raise RuntimeError(
            f"{label}: frame barrier mismatch before={before['frame']!r}, "
            f"response={response!r}, after={after['frame']!r}"
        )
    return after


def cursor_point(state: dict[str, object]) -> tuple[float, float]:
    cursor = state.get("cursor")
    if not isinstance(cursor, dict) or set(cursor) != {"x", "y"}:
        raise RuntimeError(f"STATE cursor schema changed: {state!r}")
    point = float(cursor["x"]), float(cursor["y"])
    if not all(math.isfinite(value) for value in point):
        raise RuntimeError(f"STATE cursor is non-finite: {state!r}")
    return point


def assert_pointer_valid(state: dict[str, object], label: str) -> None:
    point = cursor_point(state)
    active = [item for item in output_map(state).values() if item["enabled"]]
    if not active:
        if state.get("pointer_context") != "none" or state.get("pointer_window") is not None:
            raise RuntimeError(f"{label}: zero-output pointer retained a scene hit: {state!r}")
        return
    contained = False
    for item in active:
        x, y, width, height = box_tuple(item["box"], str(item["name"]))
        contained |= x <= point[0] < x + width and y <= point[1] < y + height
    if not contained:
        raise RuntimeError(f"{label}: pointer escaped all active outputs: {state!r}")


def pointer(control: Control, point: tuple[int, int], label: str) -> dict[str, object]:
    expect_command(
        control,
        f"POINTER {point[0]} {point[1]}",
        f"OK CURSOR {point[0]:.3f} {point[1]:.3f}",
    )
    state = frame_barrier(control, label)
    if cursor_point(state) != (float(point[0]), float(point[1])):
        raise RuntimeError(f"{label}: pointer command was not exact: {state!r}")
    return state


def root_point(
    control: Control, record: dict[str, object], label: str
) -> tuple[int, int]:
    x, y, width, height = box_tuple(record["box"], str(record["name"]))
    candidates = (
        (x, y),
        (x + width - 1, y),
        (x, y + height - 1),
        (x + width - 1, y + height - 1),
        (x + width // 2, y + height // 2),
    )
    for candidate in candidates:
        state = pointer(control, candidate, f"{label} candidate {candidate!r}")
        if state.get("pointer_context") == "root" and state.get("pointer_window") is None:
            return candidate
    raise RuntimeError(f"{label}: no bounded root hit in output {record!r}")


def button(control: Control, number: int, label: str) -> dict[str, object]:
    code = BUTTON_CODES[number]
    expect_command(control, f"BUTTON {code} press", f"OK BUTTON {code} press")
    expect_command(control, f"BUTTON {code} release", f"OK BUTTON {code} release")
    return frame_barrier(control, label)


def point_output(state: dict[str, object], point: tuple[float, float]) -> str | None:
    for item in output_map(state).values():
        if not item["enabled"]:
            continue
        x, y, width, height = box_tuple(item["box"], str(item["name"]))
        if x <= point[0] < x + width and y <= point[1] < y + height:
            return str(item["name"])
    return None


def assert_client_survival(
    native_process: subprocess.Popen[bytes],
    native: ClientChannel,
    x11_process: subprocess.Popen[bytes],
    x11: ClientChannel,
    token: str,
) -> None:
    if native_process.poll() is not None or x11_process.poll() is not None:
        raise RuntimeError(
            f"{token}: client exited native={native_process.poll()} "
            f"x11={x11_process.poll()}"
        )
    native.command(f"ARM {token}", f"OK ARMED {token}")
    native.stdin.write(f"REPORT {token}\n".encode("utf-8"))
    native.stdin.flush()
    report = native.expect_prefix(f"OK REPORT {token} ")
    if re.fullmatch(
        rf"OK REPORT {re.escape(token)} keys=0 focus=[01] close=0", report
    ) is None:
        raise RuntimeError(f"{token}: invalid native liveness report {report!r}")
    x11.command("REPORT", "OK REPORT close=0 mapped=1 cycle=0")


def assert_trace(control: Control, identities: dict[str, int]) -> None:
    trace = control.trace()
    if set(trace) != {"version", "first_seq", "next_seq", "dropped", "events"}:
        raise RuntimeError(f"TRACE top-level schema changed: {trace!r}")
    if trace["version"] != 1 or trace["dropped"] != 0:
        raise RuntimeError(f"TRACE was incomplete: {trace!r}")
    events = trace["events"]
    if not isinstance(events, list):
        raise RuntimeError(f"TRACE events is not a list: {trace!r}")
    sequences = [item.get("seq") for item in events if isinstance(item, dict)]
    if sequences != list(range(1, len(events) + 1)):
        raise RuntimeError(f"TRACE sequence was not normalized: {trace!r}")
    expected_first = 1
    expected_next = len(events)
    if trace["first_seq"] != expected_first or trace["next_seq"] != expected_next:
        raise RuntimeError(f"TRACE bounds disagree with events: {trace!r}")
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "seq",
            "event",
            "context",
            "window",
            "geometry",
            "state",
        }:
            raise RuntimeError(f"TRACE event schema changed: {event!r}")
        identity = event["window"]
        if not isinstance(identity, dict):
            raise RuntimeError(f"TRACE window identity is invalid: {event!r}")
        title = identity.get("title")
        if title not in identities or identity.get("id") != identities[title]:
            raise RuntimeError(f"TRACE lost stable client identity: {event!r}")
        if event["event"] in {"unmap", "destroy"}:
            raise RuntimeError(f"topology transaction killed a client: {event!r}")


class Session:
    def __init__(
        self,
        root: Path,
        compositor: Path,
        config_tool: Path,
        wayland_client: Path,
        x11_client: Path,
    ) -> None:
        validate_generated_config(config_tool)
        config = root / "output-topology.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        self.socket_name = f"wtwm-m8-topology-{os.getpid()}"
        control_path = root / "control.sock"
        startup = 'printf "WTWM_DISPLAY=%s\\n" "$DISPLAY"'
        environment = {
            **os.environ,
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        }
        self.process = subprocess.Popen(
            [
                str(compositor),
                "-f",
                str(config),
                "-s",
                startup,
                "--test-control",
                str(control_path),
                "--test-socket",
                self.socket_name,
                "--test-backend",
                "headless",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control: Control | None = None
        self.native_process: subprocess.Popen[bytes] | None = None
        self.native: ClientChannel | None = None
        self.x11_process: subprocess.Popen[bytes] | None = None
        self.x11: ClientChannel | None = None
        try:
            self.control = Control(control_path, self.process)  # type: ignore[arg-type]
            self.control.socket.settimeout(10)
            expect_command(self.control, "SET ANIMATION_MS 0", "OK ANIMATION_MS 0")
            expect_command(self.control, "SET PLACEMENT_SEED 0", "OK PLACEMENT_SEED 0")
            display_line = read_prefixed_line(self.process, "WTWM_DISPLAY=", "compositor")
            display = display_line.removeprefix("WTWM_DISPLAY=")
            if not display:
                raise RuntimeError(f"Xwayland startup printed an empty DISPLAY: {display_line!r}")

            wayland_environment = {**environment, "WAYLAND_DISPLAY": self.socket_name}
            self.native_process = subprocess.Popen(
                [str(wayland_client), NATIVE_TITLE, NATIVE_APP_ID],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.native = ClientChannel(self.native_process, "native topology client")

            x11_environment = {**environment, "DISPLAY": display}
            self.x11_process = subprocess.Popen(
                [str(x11_client), X11_TITLE, "topology", "WtwmTopology"],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.x11 = ClientChannel(self.x11_process, "X11 topology client")
        except Exception:
            self.abort()
            raise

    def launch_ready(self) -> None:
        assert self.control is not None
        assert self.native is not None and self.x11 is not None
        self.native.expect(f"OK READY {NATIVE_TITLE}")
        self.x11.expect_prefix(f"OK READY {X11_TITLE} ")
        self.x11.command("FREEZE", "OK FROZEN 0x007030a0")
        state = bounded_state(
            self.control, state_windows_ready, "one mapped native and Xwayland client"
        )
        windows = state["windows"]
        assert isinstance(windows, list)
        identities = {
            str(item["title"]): int(item["id"])
            for item in windows
            if isinstance(item, dict) and item.get("title") in {NATIVE_TITLE, X11_TITLE}
        }
        if len(identities) != 2 or any(value <= 0 for value in identities.values()):
            raise RuntimeError(f"clients lack stable trace identities: {state!r}")
        self.identities = identities
        expect_command(self.control, "TRACE CLEAR", "OK TRACE CLEAR")
        if self.control.trace() != {
            "version": 1,
            "first_seq": 1,
            "next_seq": 0,
            "dropped": 0,
            "events": [],
        }:
            raise RuntimeError("TRACE CLEAR did not create an exact empty epoch")

    def clients_alive(self, token: str) -> None:
        assert self.control is not None
        assert self.native_process is not None and self.native is not None
        assert self.x11_process is not None and self.x11 is not None
        state = self.control.state()
        if not state_windows_ready(state):
            raise RuntimeError(f"{token}: client scene identities are not live: {state!r}")
        if (
            state.get("menu") is not None
            or state.get("interactive") is not False
            or state.get("interaction") is not None
            or state.get("popups") != []
            or state.get("override_redirect") != []
        ):
            raise RuntimeError(
                f"{token}: topology mutation changed non-spatial interaction state: "
                f"{state!r}"
            )
        assert_client_survival(
            self.native_process,
            self.native,
            self.x11_process,
            self.x11,
            token,
        )

    def finish(self) -> str:
        assert self.control is not None
        assert self.native is not None and self.native_process is not None
        assert self.x11 is not None and self.x11_process is not None
        assert_trace(self.control, self.identities)
        self.native.command("EXIT", "OK EXIT")
        self.x11.command("EXIT", "OK EXIT")
        if self.native_process.wait(timeout=10) != 0:
            raise RuntimeError("native topology client failed")
        if self.x11_process.wait(timeout=10) != 0:
            raise RuntimeError("X11 topology client failed")
        expect_command(self.control, "QUIT", "OK QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read().decode() if self.process.stderr else ""
            raise RuntimeError(f"topology compositor failed: {stderr}")
        return self.process.stderr.read().decode() if self.process.stderr else ""

    def abort(self) -> str:
        for channel in (self.native, self.x11):
            if channel is not None:
                try:
                    channel.stdin.close()
                except OSError:
                    pass
        for process in (self.native_process, self.x11_process):
            if process is not None and process.poll() is None:
                process.kill()
        if self.control is not None:
            try:
                self.control.close()
            except (OSError, ValueError):
                pass
        if self.process.poll() is None:
            self.process.kill()
        _, stderr = self.process.communicate(timeout=10)
        return stderr.decode(errors="replace") if stderr else ""


def assert_names(state: dict[str, object], expected: list[str]) -> None:
    observed = list(output_map(state))
    if observed != expected:
        raise RuntimeError(f"managed output order {observed!r} != {expected!r}")


def output_transaction(
    control: Control, command: str, expected: str, label: str
) -> dict[str, object]:
    expect_command(control, command, expected)
    state = frame_barrier(control, label)
    assert_pointer_valid(state, label)
    return state


def run(
    compositor: Path,
    config_tool: Path,
    wayland_client: Path,
    x11_client: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-output-topology-") as directory:
        session = Session(
            Path(directory), compositor, config_tool, wayland_client, x11_client
        )
        control = session.control
        assert control is not None
        try:
            for index, (width, height) in enumerate(
                ((300, 200), (240, 180), (320, 240)), start=1
            ):
                expect_command(
                    control,
                    f"OUTPUT {width} {height}",
                    f"OK OUTPUT HEADLESS-{index} {width} {height}",
                )
                frame_barrier(control, f"HEADLESS-{index} add")
            initial = control.state()
            assert_names(initial, ["HEADLESS-1", "HEADLESS-2", "HEADLESS-3"])
            for index, (width, height) in enumerate(
                ((300, 200), (240, 180), (320, 240))
            ):
                assert_output(
                    initial,
                    f"HEADLESS-{index + 1}",
                    ordinal=index,
                    index=index,
                    enabled=True,
                    mode=(width, height, 0),
                    scale=1.0,
                    transform="normal",
                )
            assert_pointer_valid(initial, "initial three-output topology")

            session.launch_ready()
            session.clients_alive("initial")

            state = output_transaction(
                control,
                "OUTPUT POSITION HEADLESS-2 700 40",
                "OK OUTPUT POSITION HEADLESS-2 700 40",
                "explicit output position",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                box=(700, 40, 240, 180),
            )
            state = output_transaction(
                control,
                "OUTPUT MODE HEADLESS-2 400 300 60000",
                "OK OUTPUT MODE HEADLESS-2 400 300 60000",
                "custom output mode",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                mode=(400, 300, 60_000),
                box=(700, 40, 400, 300),
            )
            state = output_transaction(
                control,
                "OUTPUT SCALE HEADLESS-2 1.25",
                "OK OUTPUT SCALE HEADLESS-2 1.250",
                "fractional output scale",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                scale=1.25,
                box=(700, 40, 320, 240),
            )
            state = output_transaction(
                control,
                "OUTPUT TRANSFORM HEADLESS-2 90",
                "OK OUTPUT TRANSFORM HEADLESS-2 90",
                "quarter-turn output transform",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                transform="90",
                box=(700, 40, 240, 320),
            )
            state = output_transaction(
                control,
                "OUTPUT TRANSFORM HEADLESS-2 flipped-270",
                "OK OUTPUT TRANSFORM HEADLESS-2 flipped-270",
                "reflected output transform",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                transform="flipped-270",
                box=(700, 40, 240, 320),
            )
            state = output_transaction(
                control,
                "OUTPUT TRANSFORM HEADLESS-2 normal",
                "OK OUTPUT TRANSFORM HEADLESS-2 normal",
                "normal output transform restore",
            )
            state = output_transaction(
                control,
                "OUTPUT SCALE HEADLESS-2 2",
                "OK OUTPUT SCALE HEADLESS-2 2.000",
                "integer output scale",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                scale=2.0,
                transform="normal",
                box=(700, 40, 200, 150),
            )
            assert_names(state, ["HEADLESS-1", "HEADLESS-2", "HEADLESS-3"])
            session.clients_alive("mutated")

            before = control.state()
            error = raw_command(control, "OUTPUT POSITION MISSING 0 0")
            if error != "ERROR OUTPUT unknown output: MISSING":
                raise RuntimeError(f"unknown-output error changed: {error!r}")
            after = control.state()
            if after != before:
                raise RuntimeError(
                    f"unknown-output failure was not atomic: before={before!r}, after={after!r}"
                )

            state = output_transaction(
                control,
                "OUTPUT DISABLE HEADLESS-2",
                "OK OUTPUT DISABLE HEADLESS-2",
                "disable middle output",
            )
            assert_names(state, ["HEADLESS-1", "HEADLESS-2", "HEADLESS-3"])
            assert_output(
                state, "HEADLESS-1", ordinal=0, index=0, enabled=True
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=None,
                enabled=False,
                mode=(400, 300, 60_000),
                scale=2.0,
                transform="normal",
            )
            assert_output(
                state, "HEADLESS-3", ordinal=2, index=1, enabled=True
            )
            before = control.state()
            error = raw_command(control, "OUTPUT MODE HEADLESS-2 800 600 60000")
            if error != "ERROR OUTPUT MODE requires enabled output: HEADLESS-2":
                raise RuntimeError(f"disabled MODE error changed: {error!r}")
            after = control.state()
            if after != before:
                raise RuntimeError(
                    f"failed disabled MODE was not atomic: before={before!r}, after={after!r}"
                )
            session.clients_alive("disabled")

            state = output_transaction(
                control,
                "OUTPUT ENABLE HEADLESS-2",
                "OK OUTPUT ENABLE HEADLESS-2",
                "re-enable middle output",
            )
            assert_output(
                state,
                "HEADLESS-2",
                ordinal=1,
                index=1,
                enabled=True,
                mode=(400, 300, 60_000),
                scale=2.0,
                transform="normal",
                box=(700, 40, 200, 150),
            )
            state = output_transaction(
                control,
                "OUTPUT POSITION HEADLESS-2 AUTO",
                "OK OUTPUT POSITION HEADLESS-2 AUTO",
                "return middle output to auto layout",
            )
            middle = assert_output(
                state, "HEADLESS-2", ordinal=1, index=1, enabled=True
            )
            if box_tuple(middle["box"], "HEADLESS-2")[:2] == (700, 40):
                raise RuntimeError("POSITION AUTO retained stale explicit coordinates")
            assert_names(state, ["HEADLESS-1", "HEADLESS-2", "HEADLESS-3"])

            first = output_map(state)["HEADLESS-1"]
            root_point(control, first, "history starting output")
            state = button(control, 3, "numeric warp to third output")
            if point_output(state, cursor_point(state)) != "HEADLESS-3":
                raise RuntimeError(f"numeric warp did not reach HEADLESS-3: {state!r}")
            state = button(control, 4, "back warp to first output")
            if point_output(state, cursor_point(state)) != "HEADLESS-1":
                raise RuntimeError(f"back warp did not reach HEADLESS-1: {state!r}")

            state = output_transaction(
                control,
                "OUTPUT DESTROY HEADLESS-2",
                "OK OUTPUT DESTROY HEADLESS-2",
                "destroy middle output",
            )
            assert_names(state, ["HEADLESS-1", "HEADLESS-3"])
            assert_output(
                state, "HEADLESS-3", ordinal=2, index=1, enabled=True
            )
            state = button(control, 4, "history survives survivor renumber")
            if point_output(state, cursor_point(state)) != "HEADLESS-3":
                raise RuntimeError(f"renumbered survivor history was lost: {state!r}")
            state = button(control, 4, "history toggle returns to first output")
            if point_output(state, cursor_point(state)) != "HEADLESS-1":
                raise RuntimeError(f"history did not toggle to first output: {state!r}")
            state = output_transaction(
                control,
                "OUTPUT DESTROY HEADLESS-3",
                "OK OUTPUT DESTROY HEADLESS-3",
                "destroy previous-screen identity",
            )
            before_point = cursor_point(state)
            state = button(control, 4, "missing previous-screen no-op")
            if cursor_point(state) != before_point or point_output(
                state, cursor_point(state)
            ) != "HEADLESS-1":
                raise RuntimeError(f"destroyed history identity remained actionable: {state!r}")

            expect_command(
                control,
                "OUTPUT DISABLE HEADLESS-1",
                "OK OUTPUT DISABLE HEADLESS-1",
            )
            zero_active = control.state()
            assert_names(zero_active, ["HEADLESS-1"])
            assert_output(
                zero_active,
                "HEADLESS-1",
                ordinal=0,
                index=None,
                enabled=False,
            )
            assert_pointer_valid(zero_active, "zero-active-output state")
            expect_command(control, "PING", "OK WTWM_TEST_CONTROL 1")
            session.clients_alive("zero_active")

            state = output_transaction(
                control,
                "OUTPUT ENABLE HEADLESS-1",
                "OK OUTPUT ENABLE HEADLESS-1",
                "restore first output",
            )
            assert_output(
                state, "HEADLESS-1", ordinal=0, index=0, enabled=True
            )
            state = output_transaction(
                control,
                "OUTPUT 640 480",
                "OK OUTPUT HEADLESS-4 640 480",
                "add after destroyed ordinals",
            )
            assert_names(state, ["HEADLESS-1", "HEADLESS-4"])
            assert_output(
                state, "HEADLESS-4", ordinal=3, index=1, enabled=True
            )
            state = output_transaction(
                control,
                "OUTPUT DESTROY HEADLESS-1",
                "OK OUTPUT DESTROY HEADLESS-1",
                "destroy first survivor",
            )
            assert_output(
                state, "HEADLESS-4", ordinal=3, index=0, enabled=True
            )
            expect_command(
                control,
                "OUTPUT DESTROY HEADLESS-4",
                "OK OUTPUT DESTROY HEADLESS-4",
            )
            zero_managed = control.state()
            assert_names(zero_managed, [])
            assert_pointer_valid(zero_managed, "zero-managed-output state")
            expect_command(control, "PING", "OK WTWM_TEST_CONTROL 1")
            session.clients_alive("zero_managed")

            session.finish()
        except Exception as error:
            stderr = session.abort()
            raise RuntimeError(
                f"output-topology live session failed: {error}\n"
                f"compositor stderr:\n{stderr}"
            ) from error


def executable(parser: argparse.ArgumentParser, path: Path | None, name: str) -> Path:
    if path is None:
        parser.error(f"--{name} is required")
    resolved = path.resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        parser.error(f"--{name} is not executable: {resolved}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="exercise Milestone 8 transactional output topology changes"
    )
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--config-tool", type=Path)
    parser.add_argument("--wayland-client", type=Path)
    parser.add_argument("--x11-client", type=Path)
    arguments = parser.parse_args()

    validate_model()
    if arguments.config_tool is not None:
        validate_generated_config(
            executable(parser, arguments.config_tool, "config-tool")
        )
    if arguments.self_test_model:
        print("Milestone 8 output-topology model self-test passed")
        return 0
    if sys.platform != "linux":
        print("Milestone 8 output-topology live integration requires Linux")
        return 77
    run(
        executable(parser, arguments.compositor, "compositor"),
        executable(parser, arguments.config_tool, "config-tool"),
        executable(parser, arguments.wayland_client, "wayland-client"),
        executable(parser, arguments.x11_client, "x11-client"),
    )
    print("Milestone 8 output-topology live integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
