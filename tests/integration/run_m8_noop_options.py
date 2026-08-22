#!/usr/bin/env python3
"""Prove X11 server-resource options have no Wayland-visible effect."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from typing import Any

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-noop-native"
X11_TITLE = "wtwm-noop-x11"
TITLES = {NATIVE_TITLE, X11_TITLE}
OPTION_SPELLINGS = (
    "nObAcKiNgStOrE",
    "nOsAvEuNdErS",
    "nOgRaBsErVeR",
)
DYNAMIC_FIELDS = {
    "frame",
    "id",
    "xid",
    "parent",
    "icon_pixmap",
    "icon_mask",
    "icon_window",
    "seq",
    "first_seq",
    "next_seq",
}
PORTABLE_UNIX_SOCKET_PATH_BYTES = 103
FULL_OUTPUT_HEADER = b"P6\n640 480\n255\n"
FULL_OUTPUT_CAPTURE_BYTES = len(FULL_OUTPUT_HEADER) + 640 * 480 * 3
READINESS_CAPTURE_ATTEMPTS = 12
OBSERVATION_STABLE_SAMPLES = 3
OBSERVATION_MAX_ATTEMPTS = 24


def session_socket_names(
    socket_root: Path, label: str,
) -> tuple[Path, Path, str]:
    token = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
    runtime = socket_root / f"r-{token}"
    control = socket_root / f"c-{token}"
    display = f"w-{token}"
    for purpose, path in (
        ("test control", control),
        ("Wayland display", runtime / display),
    ):
        path_bytes = len(os.fsencode(path))
        if path_bytes > PORTABLE_UNIX_SOCKET_PATH_BYTES:
            raise RuntimeError(
                f"{label} {purpose} socket path is not portable: "
                f"{path_bytes} bytes ({path})"
            )
    return runtime, control, display


def config_text(option_mask: int, *, opaque: bool) -> str:
    options = "".join(
        spelling + "\n"
        for index, spelling in enumerate(OPTION_SPELLINGS)
        if option_mask & (1 << index)
    )
    return "".join((
        "NoDefaults\nRandomPlacement\nNoIconManagers\n",
        "OpaqueMove\n" if opaque else "",
        "NoRaiseOnMove\nMoveDelta 1\nConstrainedMoveTime 0\n",
        options,
        "Button1 = : title : f.move\n",
        'Button3 = : root : f.menu "noop-menu"\n',
        'Menu "noop-menu" { "Select" f.nop "Refresh" f.refresh }\n',
    ))


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {item["title"] for item in windows} == TITLES
        and all(item["mapped"] for item in windows)
        and len(state["xwayland_lifecycle"]) == 1
        and state["xwayland_lifecycle"][0]["associated"]
        and state["xwayland_lifecycle"][0]["mapped"]
        and state["xwayland_lifecycle"][0]["has_buffer"]
    )


def canonical_title_geometry(state: dict[str, object]) -> bool:
    if not mapped_pair(state):
        return False
    title_geometry = {
        (item["title_bar_height"], item["title_height"])
        for item in state["windows"]
    }
    return len(title_geometry) == 1


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {title!r}: {state!r}")
    return matches[0]


def normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalized(item)
            for key, item in value.items()
            if key not in DYNAMIC_FIELDS
        }
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def trace_window_key(event: Any) -> tuple[str, str, str, str, str] | None:
    if not isinstance(event, dict) or not isinstance(event.get("window"), dict):
        return None
    window_value = event["window"]
    fields = ("type", "title", "app_id", "instance", "class")
    if not all(isinstance(window_value.get(field), str) for field in fields):
        return None
    return tuple(window_value[field] for field in fields)


def trace_client_geometry(event: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(event, dict) or not isinstance(event.get("geometry"), dict):
        return None
    client = event["geometry"].get("client")
    fields = ("x", "y", "width", "height")
    if not isinstance(client, dict) or not all(
        isinstance(client.get(field), int) for field in fields
    ):
        return None
    return tuple(client[field] for field in fields)


def event_without_geometry(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "geometry"}


def is_redundant_xwayland_configure_echo(
    events: list[Any], index: int,
) -> bool:
    if index < 2 or index + 1 >= len(events):
        return False
    old_echo, new_echo = events[index:index + 2]
    if not isinstance(old_echo, dict) or not isinstance(new_echo, dict):
        return False
    if any(
        event.get("event") != "configure" or event.get("context") != "client"
        for event in (old_echo, new_echo)
    ):
        return False
    key = trace_window_key(old_echo)
    if key is None or key[0] != "x11" or trace_window_key(new_echo) != key:
        return False
    old_geometry = trace_client_geometry(old_echo)
    new_geometry = trace_client_geometry(new_echo)
    if old_geometry is None or new_geometry is None or old_geometry == new_geometry:
        return False
    if event_without_geometry(old_echo) != event_without_geometry(new_echo):
        return False

    # A compositor move configures the X11 client and records the matching
    # semantic move immediately afterwards.  Xwayland can later echo the
    # pre-move and post-move geometries back through set_geometry.  Recognize
    # only that already-recorded transition; unique, reordered, or novel
    # configure events remain part of the oracle.
    for prior_index in range(index - 1):
        configured = events[prior_index]
        moved = events[prior_index + 1]
        if not isinstance(configured, dict) or not isinstance(moved, dict):
            continue
        if (
            configured.get("event") == "configure"
            and configured.get("context") == "client"
            and moved.get("event") == "move"
            and moved.get("context") == "frame"
            and trace_window_key(configured) == key
            and trace_window_key(moved) == key
            and trace_client_geometry(configured) == new_geometry
            and trace_client_geometry(moved) == new_geometry
        ):
            if any(
                trace_window_key(prior) == key
                and trace_client_geometry(prior) == old_geometry
                for prior in events[:prior_index]
            ):
                return True
    return False


def canonical_trace(value: Any) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        return value
    events = list(value["events"])
    index = 0
    while index + 1 < len(events):
        if is_redundant_xwayland_configure_echo(events, index):
            del events[index:index + 2]
            continue
        index += 1
    result = dict(value)
    result["events"] = events
    return result


def self_test_trace_normalization() -> None:
    def event(kind: str, x: int, *, window_type: str = "x11") -> dict[str, Any]:
        return {
            "event": kind,
            "context": "client" if kind == "configure" else "frame",
            "window": {
                "type": window_type,
                "title": "client",
                "app_id": "App",
                "instance": "app",
                "class": "App",
            },
            "geometry": {
                "client": {"x": x, "y": 20, "width": 100, "height": 80},
            },
            "state": {"mapped": True},
        }

    semantic = [
        event("pointer", 10),
        event("configure", 30),
        event("move", 30),
        event("commit", 30),
    ]
    echo = [event("configure", 10), event("configure", 30)]
    trace = {"version": 1, "dropped": 0, "events": semantic + echo}
    if canonical_trace(trace)["events"] != semantic:
        raise RuntimeError("redundant Xwayland configure echo was not canonicalized")
    if canonical_trace({**trace, "events": semantic + echo[:1]})["events"] != (
        semantic + echo[:1]
    ):
        raise RuntimeError("a unique Xwayland configure was canonicalized")
    changed_final = [event("configure", 10), event("configure", 31)]
    if canonical_trace({**trace, "events": semantic + changed_final})["events"] != (
        semantic + changed_final
    ):
        raise RuntimeError("an unproven configure transition was canonicalized")
    native_echo = [
        event("configure", 10, window_type="wayland"),
        event("configure", 30, window_type="wayland"),
    ]
    if canonical_trace({**trace, "events": semantic + native_echo})["events"] != (
        semantic + native_echo
    ):
        raise RuntimeError("native Wayland configure events were canonicalized")


def read_full_output_capture(capture: Path, label: str) -> bytes:
    pixels = capture.read_bytes()
    if (
        not pixels.startswith(FULL_OUTPUT_HEADER)
        or len(pixels) != FULL_OUTPUT_CAPTURE_BYTES
    ):
        raise RuntimeError(
            f"invalid full-output capture for {label}: {len(pixels)} bytes"
        )
    return pixels


def wait_for_stable_full_output(
    control: Control,
    root: Path,
    label: str,
    *,
    max_attempts: int = READINESS_CAPTURE_ATTEMPTS,
) -> None:
    previous: bytes | None = None
    previous_digest = "none"
    for attempt in range(1, max_attempts + 1):
        control.command("WAIT 3")
        capture = root / f"readiness-{attempt:02d}.ppm"
        control.command(f"CAPTURE {capture}")
        pixels = read_full_output_capture(
            capture, f"{label} readiness attempt {attempt}"
        )
        digest = hashlib.sha256(pixels).hexdigest()
        if pixels == previous:
            return
        previous = pixels
        previous_digest = digest
    raise RuntimeError(
        f"{label} full output did not stabilize after {max_attempts} "
        f"readiness captures; last capture sha256={previous_digest}"
    )


class Session:
    def __init__(
        self,
        root: Path,
        socket_root: Path,
        label: str,
        compositor: Path,
        config: Path,
        wayland_client: Path,
        x11_client: Path,
    ) -> None:
        runtime, control_path, display_name = session_socket_names(
            socket_root, label,
        )
        runtime.mkdir(mode=0o700)
        display_marker = root / f"display-{label}"
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        startup = (
            f'printf "%s\\n" "$DISPLAY" > '
            f"{shlex.quote(str(display_marker))}"
        )
        self.process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", display_name,
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.control = Control(control_path, self.process)
        except RuntimeError as error:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(
                    f"{label} compositor startup failed: {error}\n{stderr}"
                ) from error
            raise
        self.control.socket.settimeout(10)
        self.control.command("SET ANIMATION_MS 0")
        self.control.command("SET PLACEMENT_SEED 0")
        self.control.command("SET FONT DejaVu Sans 10")
        self.control.command("OUTPUT 640 480")

        native_environment = environment.copy()
        native_environment["WAYLAND_DISPLAY"] = display_name
        native_process = subprocess.Popen(
            [str(wayland_client), NATIVE_TITLE, "org.wtwm.NoopOptions"],
            env=native_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.native = ClientChannel(native_process, f"{label} native")
        self.native.expect(f"OK READY {NATIVE_TITLE}")

        x11_environment = environment.copy()
        x11_environment["DISPLAY"] = wait_path(display_marker)
        x11_process = subprocess.Popen(
            [str(x11_client), X11_TITLE, "noop", "WtwmNoopOptions"],
            env=x11_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.x11 = ClientChannel(x11_process, f"{label} X11")
        self.x11.expect_prefix(f"OK READY {X11_TITLE} ")
        self.x11.command("FREEZE", "OK FROZEN 0x007030a0")
        self.clients = {
            NATIVE_TITLE: native_process,
            X11_TITLE: x11_process,
        }
        wait_state(self.control, mapped_pair, f"{label} mixed client pair")
        # Reapply the controlled font after both protocol paths have mapped so
        # every A/B process compares the same rebuilt decoration cache.  The
        # initial command remains before mapping to control first-frame output.
        self.control.command("SET FONT DejaVu Sans 10")
        wait_state(
            self.control,
            canonical_title_geometry,
            f"{label} canonical mixed title geometry",
        )
        wait_for_stable_full_output(self.control, root, label)
        self.control.command("TRACE CLEAR")
        self.observations: dict[str, dict[str, object]] = {}

    def observe(self, root: Path, phase: str) -> None:
        previous: dict[str, object] | None = None
        consecutive = 0
        observation: dict[str, object] | None = None
        for _ in range(OBSERVATION_MAX_ATTEMPTS):
            self.control.command("WAIT 3")
            observation = {
                "state": normalized(self.control.state()),
                "trace": canonical_trace(normalized(self.control.trace())),
            }
            if observation == previous:
                consecutive += 1
            else:
                previous = observation
                consecutive = 1
            if consecutive >= OBSERVATION_STABLE_SAMPLES:
                break
            time.sleep(0.01)
        else:
            raise RuntimeError(
                f"{phase} state/trace did not converge after "
                f"{OBSERVATION_MAX_ATTEMPTS} samples"
            )
        if observation is None:
            raise RuntimeError(f"{phase} produced no state/trace observation")
        capture = root / f"{phase}.ppm"
        self.control.command(f"CAPTURE {capture}")
        pixels = read_full_output_capture(capture, phase)
        self.observations[phase] = {
            "state": observation["state"],
            "trace": observation["trace"],
            "pixels": pixels,
        }

    def move(self, root: Path, title: str, phase: str, *, opaque: bool) -> None:
        before = window(self.control.state(), title)
        original = (int(before["x"]), int(before["y"]))
        point = (
            int(before["x"]) + int(before["border_width"]) +
            int(before["width"]) // 2,
            int(before["y"]) + int(before["border_width"]) +
            max(1, int(before["title_bar_height"]) // 2),
        )
        self.control.command(f"POINTER {point[0]} {point[1]}")
        self.control.command("WAIT 2")
        pointed = self.control.state()
        if pointed["pointer_window"] != title or pointed["pointer_context"] != "title":
            raise RuntimeError(f"pointer did not reach {title!r} title: {pointed!r}")
        self.control.command("BUTTON 272 press")
        self.control.command(f"POINTER {point[0] + 23} {point[1] + 17}")
        moved = wait_state(
            self.control,
            lambda state: state["interactive"] and (
                (
                    window(state, title)["x"], window(state, title)["y"]
                ) == (original[0] + 23, original[1] + 17)
                if opaque else
                (
                    state["interaction"]["preview"]["x"],
                    state["interaction"]["preview"]["y"],
                ) == (original[0] + 23, original[1] + 17)
            ),
            f"{'opaque' if opaque else 'outlined'} {title} move",
        )
        if bool(moved["interaction"]["opaque"]) != opaque:
            raise RuntimeError(f"{title!r} selected the wrong move path: {moved!r}")
        live_geometry = (window(moved, title)["x"], window(moved, title)["y"])
        expected_live = (
            (original[0] + 23, original[1] + 17) if opaque else original
        )
        if live_geometry != expected_live:
            raise RuntimeError(f"{title!r} live geometry used the wrong move path: {moved!r}")
        has_outline = any(
            event["event"] == "outline" for event in self.control.trace()["events"]
        )
        if has_outline == opaque:
            raise RuntimeError(f"{title!r} outline trace disagrees with move mode")
        self.observe(root, f"{phase}-moving")
        self.control.command("BUTTON 272 release")
        settled = wait_state(
            self.control,
            lambda state: not state["interactive"],
            f"settled {title} move",
        )
        if (window(settled, title)["x"], window(settled, title)["y"]) != (
            original[0] + 23,
            original[1] + 17,
        ):
            raise RuntimeError(f"{title!r} move did not commit: {settled!r}")
        self.observe(root, f"{phase}-settled")

    def exercise_menu(self, root: Path) -> None:
        self.control.command("POINTER 630 470")
        self.control.command("WAIT 2")
        if self.control.state()["pointer_context"] != "root":
            raise RuntimeError("menu test point is not in the root context")
        self.control.command("BUTTON 273 press")
        opened = self.control.state()["menu"]
        if not isinstance(opened, dict) or opened["name"] != "noop-menu":
            raise RuntimeError(f"root menu did not open: {opened!r}")
        self.observe(root, "menu-open-select")
        self.control.command(
            f"POINTER {int(opened['x']) + int(opened['width']) // 2} "
            f"{int(opened['y']) + int(opened['row_height']) // 2}"
        )
        self.control.command("WAIT 2")
        selected = self.control.state()["menu"]
        if not isinstance(selected, dict) or selected["selected"] != 0:
            raise RuntimeError(f"menu row was not selected: {selected!r}")
        self.control.command("BUTTON 273 release")
        if self.control.state()["menu"] is not None:
            raise RuntimeError("menu selection did not close the popup")
        self.observe(root, "menu-selected")

        self.control.command("POINTER 630 470")
        self.control.command("BUTTON 273 press")
        if self.control.state()["menu"] is None:
            raise RuntimeError("menu did not reopen for cancellation")
        self.observe(root, "menu-open-cancel")
        self.control.command("BUTTON 274 press")
        if self.control.state()["menu"] is not None:
            raise RuntimeError("second button press did not cancel the menu")
        self.control.command("BUTTON 274 release")
        self.control.command("BUTTON 273 release")
        self.observe(root, "menu-cancelled")

    def prove_responsive(self, label: str) -> None:
        if any(process.poll() is not None for process in self.clients.values()):
            raise RuntimeError(f"{label} option exercise disconnected a client")
        self.native.command(f"ARM {label}", f"OK ARMED {label}")
        self.native.stdin.write((f"REPORT {label}\n").encode("utf-8"))
        self.native.stdin.flush()
        self.native.expect_prefix(f"OK REPORT {label} ")
        self.x11.stdin.write(b"REPORT\n")
        self.x11.stdin.flush()
        self.x11.expect_prefix("OK REPORT close=0 mapped=1 cycle=0")
        if self.control.command("PING") != "OK WTWM_TEST_CONTROL 1":
            raise RuntimeError(f"{label} option exercise stalled the compositor")

    def finish(self) -> str:
        self.native.command("EXIT", "OK EXIT")
        self.x11.command("EXIT", "OK EXIT")
        for title, process in self.clients.items():
            if wait_process(process, title) != 0:
                raise RuntimeError(f"{title} did not exit cleanly")
        self.control.command("QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"no-op option compositor failed: {stderr}")
        return self.process.stderr.read() if self.process.stderr else ""

    def abort(self) -> None:
        self.control.close()
        for process in self.clients.values():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)


def run_variant(
    root: Path,
    socket_root: Path,
    label: str,
    compositor: Path,
    wayland_client: Path,
    x11_client: Path,
    option_mask: int,
    opaque: bool,
) -> dict[str, dict[str, object]]:
    variant_root = root / label
    variant_root.mkdir()
    config = variant_root / "options.twmrc"
    config.write_text(config_text(option_mask, opaque=opaque), encoding="utf-8")
    session = Session(
        variant_root, socket_root, label, compositor, config,
        wayland_client, x11_client,
    )
    try:
        session.observe(variant_root, "ready")
        session.move(variant_root, NATIVE_TITLE, "native", opaque=opaque)
        session.move(variant_root, X11_TITLE, "x11", opaque=opaque)
        session.exercise_menu(variant_root)
        session.prove_responsive(label)
        session.observe(variant_root, "responsive")
        session.finish()
        return session.observations
    finally:
        if session.process.poll() is None:
            session.abort()


def compare_variants(
    baseline: dict[str, dict[str, object]],
    options: dict[str, dict[str, object]],
) -> None:
    if baseline.keys() != options.keys():
        raise RuntimeError("A/B no-op runs produced different observation phases")
    for phase in baseline:
        for kind in ("state", "trace"):
            if baseline[phase][kind] != options[phase][kind]:
                raise RuntimeError(
                    f"NoBackingStore/NoSaveUnders/NoGrabServer changed "
                    f"normalized {kind} at {phase}:\n"
                    f"baseline={baseline[phase][kind]!r}\n"
                    f"options={options[phase][kind]!r}"
                )
        baseline_pixels = baseline[phase]["pixels"]
        option_pixels = options[phase]["pixels"]
        if baseline_pixels != option_pixels:
            raise RuntimeError(
                f"NoBackingStore/NoSaveUnders/NoGrabServer changed full "
                f"capture pixels at {phase}: "
                f"baseline={hashlib.sha256(baseline_pixels).hexdigest()} "
                f"options={hashlib.sha256(option_pixels).hexdigest()}"
            )


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    self_test_trace_normalization()
    with (
        tempfile.TemporaryDirectory(prefix="wtwm-m8-noop-options-") as directory,
        tempfile.TemporaryDirectory(prefix="wm8-", dir="/tmp") as socket_directory,
    ):
        root = Path(directory)
        socket_root = Path(socket_directory)
        for opaque in (False, True):
            mode = "opaque" if opaque else "outlined"
            baseline = run_variant(
                root,
                socket_root,
                f"{mode}-subset-000",
                compositor,
                wayland_client,
                x11_client,
                0,
                opaque,
            )
            for option_mask in range(1, 1 << len(OPTION_SPELLINGS)):
                options = run_variant(
                    root,
                    socket_root,
                    f"{mode}-subset-{option_mask:03b}",
                    compositor,
                    wayland_client,
                    x11_client,
                    option_mask,
                    opaque,
                )
                compare_variants(baseline, options)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--wayland-client", type=Path)
    parser.add_argument("--x11-client", type=Path)
    parser.add_argument("--self-test-trace-normalization", action="store_true")
    args = parser.parse_args()
    if args.self_test_trace_normalization:
        self_test_trace_normalization()
        return 0
    if args.compositor is None or args.wayland_client is None or args.x11_client is None:
        parser.error(
            "--compositor, --wayland-client, and --x11-client are required"
        )
    run(
        args.compositor.resolve(),
        args.wayland_client.resolve(),
        args.x11_client.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
