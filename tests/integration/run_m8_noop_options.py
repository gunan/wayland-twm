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
        "NoRaiseOnMove\nMoveDelta 1\n",
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
        self.clients = {
            NATIVE_TITLE: native_process,
            X11_TITLE: x11_process,
        }
        wait_state(self.control, mapped_pair, f"{label} mixed client pair")
        self.control.command("WAIT 3")
        self.control.command("TRACE CLEAR")
        self.observations: dict[str, dict[str, object]] = {}

    def observe(self, root: Path, phase: str) -> None:
        self.control.command("WAIT 3")
        state = normalized(self.control.state())
        trace = normalized(self.control.trace())
        capture = root / f"{phase}.ppm"
        self.control.command(f"CAPTURE {capture}")
        pixels = capture.read_bytes()
        expected_size = len(b"P6\n640 480\n255\n") + 640 * 480 * 3
        if not pixels.startswith(b"P6\n640 480\n255\n") or len(pixels) != expected_size:
            raise RuntimeError(f"invalid full-output capture for {phase}: {len(pixels)} bytes")
        self.observations[phase] = {
            "state": state,
            "trace": trace,
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
    parser.add_argument("--compositor", required=True, type=Path)
    parser.add_argument("--wayland-client", required=True, type=Path)
    parser.add_argument("--x11-client", required=True, type=Path)
    args = parser.parse_args()
    run(
        args.compositor.resolve(),
        args.wayland_client.resolve(),
        args.x11_client.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
