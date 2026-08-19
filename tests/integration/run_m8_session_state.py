#!/usr/bin/env python3
"""Verify f.saveyourself/RestartPreviousState across compositor lifetimes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import time

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-state-native"
X11_TITLE = "wtwm-state-x11"


def config_text() -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        "RestartPreviousState\n"
        "NoRaiseOnMove\n"
        "NoRaiseOnResize\n"
        "Zoom 1\n"
        "Button1 = : all : f.focus\n"
        "Button2 = : all : f.move\n"
        "Button3 = : all : f.iconify\n"
        "Button4 = : all : f.saveyourself\n"
        "Button5 = : all : f.raise\n"
        "Button6 = : all : f.fullzoom\n"
        "Button7 = : all : f.autoraise\n"
    )


def mapped_titles(state: dict[str, object], titles: set[str]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == len(titles)
        and {str(item["title"]) for item in windows} == titles
        and all(item["mapped"] for item in windows)
    )


def window(state: dict[str, object], title: str) -> dict[str, object]:
    return next(item for item in state["windows"] if item["title"] == title)


def pointer_inside(control: Control, item: dict[str, object]) -> None:
    x = int(item["x"]) + int(item["content_x"]) + 12
    y = int(item["y"]) + int(item["content_y"]) + 12
    control.command(f"POINTER {x} {y}")


def click(control: Control, item: dict[str, object], raw_button: int) -> None:
    pointer_inside(control, item)
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 2")


def move_window(
    control: Control,
    item: dict[str, object],
    target_x: int,
    target_y: int,
) -> None:
    pointer_x = int(item["x"]) + int(item["content_x"]) + 12
    pointer_y = int(item["y"]) + int(item["content_y"]) + 12
    control.command(f"POINTER {pointer_x} {pointer_y}")
    control.command("BUTTON 274 press")
    control.command(
        f"POINTER {pointer_x + target_x - int(item['x'])} "
        f"{pointer_y + target_y - int(item['y'])}"
    )
    control.command("BUTTON 274 release")
    control.command("WAIT 2")


def move_icon(
    control: Control,
    state: dict[str, object],
    title: str,
    target_x: int,
    target_y: int,
) -> None:
    icon = next(item for item in state["icon_views"] if item["title"] == title)
    pointer_x = int(icon["x"]) + int(icon["width"]) // 2
    pointer_y = int(icon["y"]) + int(icon["height"]) // 2
    control.command(f"POINTER {pointer_x} {pointer_y}")
    control.command("BUTTON 274 press")
    control.command(
        f"POINTER {pointer_x + target_x - int(icon['x'])} "
        f"{pointer_y + target_y - int(icon['y'])}"
    )
    control.command("BUTTON 274 release")
    control.command("WAIT 2")


def saved_snapshot(state: dict[str, object]) -> dict[str, object]:
    fields = ("x", "y", "width", "height", "stack", "iconified", "auto_raise")
    return {
        "focus_root": state["focus_root"],
        "active": state["active"],
        "focus": state["focus"],
        "windows": {
            str(item["title"]): {key: item[key] for key in fields}
            for item in state["windows"]
        },
        "icons": {
            str(item["title"]): (int(item["x"]), int(item["y"]))
            for item in state["icon_views"]
        },
    }


def wait_nonempty_file(path: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if path.stat().st_size > 0:
                return
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    raise RuntimeError(f"session state file was not published: {path}")


class Lifetime:
    def __init__(
        self,
        root: Path,
        label: str,
        compositor: Path,
        config: Path,
        state_home: Path,
        placement_seed: int,
    ) -> None:
        runtime = root / f"runtime-{label}"
        runtime.mkdir(mode=0o700)
        self.control_path = root / f"control-{label}.sock"
        self.display_marker = root / f"display-{label}"
        self.display_name = f"wtwm-m8-state-{label}-{os.getpid()}"
        self.environment = os.environ.copy()
        self.environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_STATE_HOME": str(state_home),
            "WLR_RENDERER": "pixman",
        })
        startup = (
            f'printf "%s\\n" "$DISPLAY" > '
            f"{shlex.quote(str(self.display_marker))}"
        )
        self.process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(self.control_path),
                "--test-socket", self.display_name,
                "--test-backend", "headless",
            ],
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control = Control(self.control_path, self.process)
        self.control.socket.settimeout(10)
        self.control.command("SET ANIMATION_MS 0")
        self.control.command("OUTPUT 800 600")
        self.control.command(f"SET PLACEMENT_SEED {placement_seed}")
        self.control.command("WAIT 2")
        self.clients: dict[str, tuple[subprocess.Popen[bytes], ClientChannel]] = {}

    def spawn_native(self, client: Path) -> None:
        environment = self.environment.copy()
        environment["WAYLAND_DISPLAY"] = self.display_name
        process = subprocess.Popen(
            [str(client), NATIVE_TITLE, "org.wtwm.SessionState"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, NATIVE_TITLE)
        channel.expect(f"OK READY {NATIVE_TITLE}")
        self.clients[NATIVE_TITLE] = (process, channel)

    def spawn_x11(self, client: Path) -> None:
        environment = self.environment.copy()
        environment["DISPLAY"] = wait_path(self.display_marker)
        process = subprocess.Popen(
            [str(client), X11_TITLE, "state", "WtwmState"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, X11_TITLE)
        channel.expect_prefix(f"OK READY {X11_TITLE} ")
        self.clients[X11_TITLE] = (process, channel)

    def sync_native(self, token: str) -> None:
        process, channel = self.clients[NATIVE_TITLE]
        if process.poll() is not None:
            raise RuntimeError("native client exited before protocol barrier")
        channel.command(f"ARM {token}", f"OK ARMED {token}")

    def stop(self) -> str:
        for title, (process, channel) in list(self.clients.items()):
            if process.poll() is not None:
                raise RuntimeError(f"{title} exited before session shutdown")
            channel.command("EXIT", "OK EXIT")
            if wait_process(process, title) != 0:
                raise RuntimeError(f"{title} did not exit cleanly")
        self.clients.clear()
        self.control.command("QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"state compositor failed: {stderr}")
        return self.process.stderr.read() if self.process.stderr else ""

    def abort(self) -> None:
        self.control.close()
        for process, _ in self.clients.values():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)


def run(
    compositor: Path,
    wayland_client: Path,
    x11_client: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-state-") as directory:
        root = Path(directory)
        config = root / "state.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        state_home = root / "state-home"
        state_path = state_home / "wtwm" / "state"

        first = Lifetime(root, "first", compositor, config, state_home, 3)
        try:
            first.spawn_native(wayland_client)
            first.spawn_x11(x11_client)
            state = wait_state(
                first.control,
                lambda value: mapped_titles(value, {NATIVE_TITLE, X11_TITLE}),
                "first state session clients",
            )

            move_window(first.control, window(state, X11_TITLE), 70, 110)
            state = first.control.state()
            click(first.control, window(state, X11_TITLE), 273)
            state = wait_state(
                first.control,
                lambda value: window(value, X11_TITLE)["iconified"],
                "iconified state client",
            )
            move_icon(first.control, state, X11_TITLE, 55, 500)

            state = first.control.state()
            move_window(first.control, window(state, NATIVE_TITLE), 390, 260)
            state = first.control.state()
            native_unzoomed = {
                key: window(state, NATIVE_TITLE)[key]
                for key in ("x", "y", "width", "height")
            }
            click(first.control, window(state, NATIVE_TITLE), 277)
            state = first.control.state()
            click(first.control, window(state, NATIVE_TITLE), 278)
            state = first.control.state()
            click(first.control, window(state, NATIVE_TITLE), 276)
            state = first.control.state()
            click(first.control, window(state, NATIVE_TITLE), 272)
            state = wait_state(
                first.control,
                lambda value: not value["focus_root"]
                and value["active"] == NATIVE_TITLE
                and value["focus"] == NATIVE_TITLE,
                "saved state focus",
            )
            # A compositor WAIT advances frames but does not prove that the
            # native client has acknowledged and committed a pending resize.
            # Complete a Wayland roundtrip so the saved and expected geometry
            # describe the same protocol state on every architecture.
            first.sync_native("session-save")
            click(first.control, window(state, NATIVE_TITLE), 275)
            wait_nonempty_file(state_path)
            expected = saved_snapshot(first.control.state())
            first.stop()
        finally:
            if first.process.poll() is None:
                first.abort()

        if stat.S_IMODE(state_path.stat().st_mode) != 0o600:
            raise RuntimeError("session state file is not private mode 0600")

        second = Lifetime(root, "second", compositor, config, state_home, 97)
        try:
            second.spawn_x11(x11_client)
            second.spawn_native(wayland_client)
            # The initial map can schedule the restored size after the
            # client's READY roundtrip.  Drain it before comparing state.
            second.sync_native("session-restore")
            restored = wait_state(
                second.control,
                lambda value: mapped_titles(value, {NATIVE_TITLE, X11_TITLE})
                and saved_snapshot(value) == expected,
                "restored compositor-owned session state",
            )
            native = window(restored, NATIVE_TITLE)
            click(second.control, native, 277)
            unzoomed = wait_state(
                second.control,
                lambda value: all(
                    window(value, NATIVE_TITLE)[key] == expected_value
                    for key, expected_value in native_unzoomed.items()
                ),
                "restored pre-zoom geometry",
            )
            if not window(unzoomed, X11_TITLE)["iconified"]:
                raise RuntimeError("zoom restore disturbed saved iconic state")
            second.stop()
        finally:
            if second.process.poll() is None:
                second.abort()

        state_path.write_text("wtwm-state\t999\n", encoding="utf-8")
        third = Lifetime(root, "invalid", compositor, config, state_home, 151)
        try:
            third.spawn_native(wayland_client)
            wait_state(
                third.control,
                lambda value: mapped_titles(value, {NATIVE_TITLE}),
                "client after invalid saved state",
            )
            if third.control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("invalid saved state damaged compositor liveness")
            stderr = third.stop()
            if "RestartPreviousState rejected saved state" not in stderr:
                raise RuntimeError("invalid saved state produced no diagnostic")
        finally:
            if third.process.poll() is None:
                third.abort()


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
