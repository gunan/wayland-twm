#!/usr/bin/env python3
"""Exercise Milestone 6 bindings, nested menus, functions, and window actions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_line(process: subprocess.Popen[str], expected: str) -> None:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 10)
    if not ready or process.stdout.readline().rstrip("\n") != expected:
        raise RuntimeError(f"timed out waiting for {expected!r}")


def wait_display(control: Control, path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value.startswith(":"):
                return value
        control.state()
    raise RuntimeError("startup command did not publish DISPLAY")


def wait_windows(control: Control) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if len(state["windows"]) == 2:
            return state
        time.sleep(0.01)
    raise RuntimeError(f"two windows did not map: {control.state()!r}")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"missing {title!r}: {state!r}")
    return matches[0]


def frame_point(item: dict[str, object]) -> tuple[int, int]:
    return (int(item["x"]) + 1, int(item["y"]) + int(item["outer_height"]) // 2)


def content_point(item: dict[str, object]) -> tuple[int, int]:
    return (int(item["x"]) + int(item["content_x"]) + int(item["width"]) // 2,
            int(item["y"]) + int(item["content_y"]) + int(item["height"]) // 2)


def click(control: Control, point: tuple[int, int], code: int) -> None:
    control.command(f"POINTER {point[0]} {point[1]}")
    control.command(f"BUTTON {code} press")
    control.command(f"BUTTON {code} release")


def stack_index(state: dict[str, object], title: str) -> int:
    return int(window(state, title)["stack"])


def run(compositor_binary: Path, client_binary: Path) -> None:
    compositor_binary = compositor_binary.resolve()
    client_binary = client_binary.resolve()
    with tempfile.TemporaryDirectory(prefix="wtwm-m6-actions-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "display"
        config_path = temporary / "actions.twmrc"
        config_path.write_text(
            'NoDefaults\n'
            'DefaultFunction f.raise\n'
            'WindowFunction f.iconify\n'
            'Button1 = : root : f.menu "root-menu"\n'
            'Button3 = : frame : f.function "outer"\n'
            'Button4 = : frame : f.fullzoom\n'
            'Button2 = : icon : f.move\n'
            'Button3 = : icon : f.iconify\n'
            'Button4 = : icon : f.resize\n'
            'Button5 = : root : f.warpto "focus-a"\n'
            'Button6 = : root : f.warpnext\n'
            'Button7 = : frame : f.function "stop-after-move"\n'
            'Button9 = : root : f.function "menu-from-function"\n'
            '"F2" = : "focus-" : f.lower\n'
            '"F3" = shift : root : f.raise\n'
            '"F4" = lock : root : f.menu "root-menu"\n'
            '"F5" = : root : f.menu "root-menu"\n'
            '"F6" = : "focus-" : f.resize\n'
            'Function "inner" { f.raise f.lower }\n'
            'Function "outer" { f.function "inner" f.raise }\n'
            'Function "stop-after-move" { f.move f.deltastop f.lower }\n'
            'Function "menu-from-function" { f.menu "root-menu" }\n'
            'Menu "root-menu" {\n'
            '  "Actions" f.title\n'
            '  "Nested" f.menu "child-menu"\n'
            '  "Windows" f.menu "TwmWindows"\n'
            '}\n'
            'Menu "child-menu" { "Refresh" f.refresh }\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        socket_name = f"wtwm-m6-actions-{os.getpid()}"
        startup = "printf '%s\\n' \"$DISPLAY\" > " + shlex.quote(str(display_path))
        compositor = subprocess.Popen(
            [str(compositor_binary), "-f", str(config_path), "-s", startup,
             "--test-control", str(control_path), "--test-socket", socket_name,
             "--test-backend", "headless"],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            display = wait_display(control, display_path)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            state = wait_windows(control)

            # Exact modifier matching is live: F3 alone misses, while Shift+F3
            # reaches the root raise action and defers window selection.
            control.command("POINTER 10 10")
            control.command("KEY 61 press")
            control.command("KEY 61 release")
            if control.state()["deferred_root_action"]:
                raise RuntimeError("unmodified F3 matched a Shift binding")
            control.command("KEY 42 press")
            control.command("KEY 61 press")
            control.command("KEY 61 release")
            control.command("KEY 42 release")
            if not control.state()["deferred_root_action"]:
                raise RuntimeError("Shift+F3 did not match its root binding")
            target = window(control.state(), "focus-a")
            click(control, frame_point(target), 272)

            # A key or named-function f.menu reaches upstream ExecuteFunction and
            # is deliberately inert; pointer-menu routing remains active below.
            control.command("POINTER 10 10")
            control.command("KEY 63 press")
            control.command("KEY 63 release")
            if control.state()["menu"] is not None:
                raise RuntimeError("key f.menu unexpectedly opened a menu")
            click(control, (10, 10), 280)
            if control.state()["menu"] is not None:
                raise RuntimeError("nested-function f.menu unexpectedly opened a menu")

            # Press/drag/release into the pull-right half opens a child immediately.
            control.command("POINTER 10 10")
            control.command("BUTTON 272 press")
            menu = control.state()["menu"]
            pull_x = int(menu["x"]) + int(menu["width"]) * 3 // 4
            pull_y = int(menu["y"]) + int(menu["row_height"]) * 3 // 2
            control.command(f"POINTER {pull_x} {pull_y}")
            child = control.state()["menu"]
            if child["name"] != "child-menu" or child["depth"] != 2:
                raise RuntimeError(f"submenu did not open on hover: {child!r}")
            control.command("BUTTON 273 press")
            if control.state()["menu"] is not None:
                raise RuntimeError("a second button press did not cancel the menu")
            control.command("BUTTON 273 release")

            # Open the same path again to exercise release dispatch in the child.
            control.command("POINTER 10 10")
            control.command("BUTTON 272 press")
            menu = control.state()["menu"]
            pull_x = int(menu["x"]) + int(menu["width"]) * 3 // 4
            pull_y = int(menu["y"]) + int(menu["row_height"]) * 3 // 2
            control.command(f"POINTER {pull_x} {pull_y}")
            child = control.state()["menu"]
            control.command(
                f"POINTER {int(child['x']) + int(child['width']) // 2} "
                f"{int(child['y']) + int(child['row_height']) // 2}"
            )
            control.command("BUTTON 272 release")
            if control.state()["menu"] is not None:
                raise RuntimeError("submenu action did not close the complete stack")

            # Nested named functions preserve action order across the two frames.
            state = control.state()
            control.command("TRACE CLEAR")
            click(control, frame_point(window(state, "focus-a")), 273)
            ordering = [event["event"] for event in control.trace()["events"]
                        if event["event"] in {"raise", "lower"}]
            if ordering[-3:] != ["raise", "lower", "raise"]:
                raise RuntimeError(f"nested function order is wrong: {ordering!r}")

            # A named function pauses for its gesture. Delta-stop continues if
            # no movement occurred, and stops the same frame after a real move.
            target = window(control.state(), "focus-a")
            control.command("TRACE CLEAR")
            click(control, frame_point(target), 278)
            stationary = [event["event"] for event in control.trace()["events"]]
            if "lower" not in stationary:
                raise RuntimeError(f"stationary f.deltastop did not continue: {stationary!r}")
            target = window(control.state(), "focus-a")
            point = frame_point(target)
            control.command("TRACE CLEAR")
            control.command(f"POINTER {point[0]} {point[1]}")
            control.command("BUTTON 278 press")
            control.command(f"POINTER {point[0] + 30} {point[1] + 20}")
            control.command("BUTTON 278 release")
            moved = [event["event"] for event in control.trace()["events"]]
            if "commit" not in moved or "lower" in moved:
                raise RuntimeError(f"moved f.deltastop did not interrupt: {moved!r}")

            # Full zoom toggles back to the exact saved client geometry.
            before = window(control.state(), "focus-a")
            original = (before["x"], before["y"], before["width"], before["height"])
            click(control, frame_point(before), 275)
            zoomed = window(control.state(), "focus-a")
            if int(zoomed["x"]) != 0 or int(zoomed["y"]) != 0:
                raise RuntimeError(f"full zoom did not fill from the output origin: {zoomed!r}")
            click(control, frame_point(zoomed), 275)
            restored = window(control.state(), "focus-a")
            if (restored["x"], restored["y"], restored["width"], restored["height"]) != original:
                raise RuntimeError(f"full zoom did not restore geometry: {restored!r}")

            # A C_NAME key executes for every title-prefix match.
            control.command("TRACE CLEAR")
            control.command("KEY 60 press")
            control.command("KEY 60 release")
            named = [event for event in control.trace()["events"]
                     if event["event"] == "binding" and event["context"] == "frame"]
            if {event["window"]["title"] for event in named} != {"focus-a", "focus-b"}:
                raise RuntimeError(f"named binding did not visit both clients: {named!r}")

            # DefaultFunction defers a root action until a window is selected.
            control.command("TRACE CLEAR")
            control.command("POINTER 10 10")
            control.command("BUTTON 279 press")
            if control.state()["deferred_root_action"] is not True:
                raise RuntimeError("DefaultFunction did not defer its root action")
            target = window(control.state(), "focus-a")
            target_point = content_point(target)
            control.command(f"POINTER {target_point[0]} {target_point[1]}")
            control.command("BUTTON 279 press")
            control.command("BUTTON 279 release")
            state = control.state()
            raised = [event for event in control.trace()["events"]
                      if event["event"] == "raise" and
                      event["window"]["title"] == "focus-a"]
            if state["deferred_root_action"] or not raised:
                raise RuntimeError(f"deferred DefaultFunction did not raise focus-a: {state!r}")

            # WindowFunction is applied by the dynamic TwmWindows menu.
            control.command("POINTER 10 10")
            control.command("BUTTON 272 press")
            menu = control.state()["menu"]
            windows_y = int(menu["y"]) + int(menu["row_height"]) * 5 // 2
            control.command(
                f"POINTER {int(menu['x']) + int(menu['width']) * 3 // 4} {windows_y}"
            )
            windows = control.state()["menu"]
            if windows["name"] != "TwmWindows" or windows["depth"] != 2:
                raise RuntimeError(f"dynamic windows menu did not open: {windows!r}")
            control.command(
                f"POINTER {int(windows['x']) + int(windows['width']) // 2} "
                f"{int(windows['y']) + int(windows['row_height']) * 5 // 2}"
            )
            control.command("BUTTON 272 release")
            state = control.state()
            if (sum(bool(item["iconified"]) for item in state["windows"]) != 1 or
                    state["icon_views"][0]["title"] != "focus-a"):
                raise RuntimeError(f"WindowFunction iconified the wrong window: {state!r}")

            # Reference twm rejects key-initiated resize before selecting a client.
            control.command("KEY 64 press")
            if control.state()["interactive"]:
                raise RuntimeError("a named key binding started f.resize")
            control.command("KEY 64 release")

            # Icons can be moved, but cannot be resized. f.iconify toggles them back.
            icon = control.state()["icon_views"][0]
            icon_point = (int(icon["x"]) + int(icon["width"]) // 2,
                          int(icon["y"]) + int(icon["height"]) // 2)
            control.command(f"POINTER {icon_point[0]} {icon_point[1]}")
            control.command("BUTTON 275 press")
            if control.state()["interactive"]:
                raise RuntimeError("f.resize started on an icon")
            control.command("BUTTON 275 release")
            control.command("BUTTON 274 press")
            control.command(f"POINTER {icon_point[0] + 30} {icon_point[1] + 20}")
            control.command("BUTTON 274 release")
            moved_icon = control.state()["icon_views"][0]
            if (moved_icon["x"], moved_icon["y"]) == (icon["x"], icon["y"]):
                raise RuntimeError(f"f.move did not move the icon view: {control.state()!r}")
            moved_point = (int(moved_icon["x"]) + int(moved_icon["width"]) // 2,
                           int(moved_icon["y"]) + int(moved_icon["height"]) // 2)
            click(control, moved_point, 273)
            if control.state()["icon_views"]:
                raise RuntimeError("f.iconify did not toggle the iconified client")
        finally:
            if client is not None:
                if client.stdin is not None and client.poll() is None:
                    client.stdin.write("EXIT\n")
                    client.stdin.flush()
                try:
                    client.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
            try:
                compositor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
            if compositor.returncode not in {0, -15}:
                stderr = compositor.stderr.read() if compositor.stderr is not None else ""
                raise RuntimeError(f"compositor failed ({compositor.returncode}):\n{stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", required=True, type=Path)
    parser.add_argument("--client", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.compositor, arguments.client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
