#!/usr/bin/env python3
"""Exercise twm-compatible move/resize interactions through synthetic input."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time
from typing import Callable

from run_compositor import Control


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_line(client: subprocess.Popen[str], expected: str) -> None:
    assert client.stdout is not None
    readable, _, _ = select.select([client.stdout], [], [], 10)
    if not readable or client.stdout.readline().rstrip("\n") != expected:
        raise RuntimeError(f"timed out waiting for X11 client {expected!r}")


def state_window(control: Control, title: str = "interaction-primary") -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        matches = [item for item in state["windows"] if item["title"] == title]
        if len(matches) == 1 and matches[0]["mapped"]:
            return matches[0]
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {title!r}: {control.state()!r}")


def title_point(item: dict[str, object]) -> tuple[int, int]:
    return (
        int(item["x"]) + int(item["border_width"]) + int(item["width"]) // 2,
        int(item["y"]) + int(item["border_width"]) +
        max(1, int(item["title_bar_height"]) // 2),
    )


def press_at(control: Control, point: tuple[int, int], button: int = 272) -> None:
    control.command(f"POINTER {point[0]} {point[1]}")
    # Xwayland metadata and its scene buffer can become visible in adjacent
    # event-loop turns under sanitizers.  Render before refreshing the hit test
    # at the same coordinate so the press targets the completed scene.
    control.command("WAIT 2")
    control.command(f"POINTER {point[0]} {point[1]}")
    control.command(f"BUTTON {button} press")


def release(control: Control, button: int = 272) -> None:
    control.command(f"BUTTON {button} release")


def interaction(control: Control) -> dict[str, object]:
    value = control.state()["interaction"]
    if not isinstance(value, dict):
        raise RuntimeError(f"expected active interaction: {control.state()!r}")
    return value


def assert_geometry(item: dict[str, object], expected: tuple[int, int]) -> None:
    actual = (int(item["x"]), int(item["y"]))
    if actual != expected:
        raise RuntimeError(f"expected geometry {expected!r}, got {actual!r}: {item!r}")


def outline_scenario(control: Control) -> None:
    item = state_window(control)
    original = (int(item["x"]), int(item["y"]))
    start = title_point(item)
    control.command("TRACE CLEAR")
    press_at(control, start)
    control.command(f"POINTER {start[0] + 2} {start[1] - 2}")
    pending = interaction(control)
    if pending["started"] or pending["moved"]:
        raise RuntimeError(f"MoveDelta below-threshold motion started: {pending!r}")
    assert_geometry(state_window(control), original)
    control.command(f"POINTER {start[0] + 3} {start[1]}")
    pending = interaction(control)
    if not pending["started"] or not pending["moved"]:
        raise RuntimeError(f"MoveDelta equality did not start: {pending!r}")
    preview = pending["preview"]
    if (preview["x"], preview["y"]) != (original[0] + 3, original[1]):
        raise RuntimeError(f"outline preview geometry is wrong: {pending!r}")
    assert_geometry(state_window(control), original)
    events = control.trace()["events"]
    if not any(event["event"] == "outline" and event["context"] == "move"
               for event in events):
        raise RuntimeError(f"outline motion was not traced: {events!r}")
    release(control)
    assert_geometry(state_window(control), (original[0] + 3, original[1]))

    item = state_window(control)
    original = (int(item["x"]), int(item["y"]))
    start = title_point(item)
    control.command("TRACE CLEAR")
    press_at(control, start)
    control.command(f"POINTER {start[0] + 20} {start[1] + 10}")
    control.command("BUTTON 274 press")
    assert_geometry(state_window(control), original)
    if control.state()["interactive"]:
        raise RuntimeError("second-button press did not abort outline move")
    if not any(event["event"] == "abort" for event in control.trace()["events"]):
        raise RuntimeError("outline abort was not recorded in TRACE")
    control.command("BUTTON 274 release")

    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    grab_x = start[0] - int(item["x"])
    control.command(f"POINTER {grab_x - 20} {start[1]}")
    if int(interaction(control)["preview"]["x"]) != 0:
        raise RuntimeError(f"DontMoveOff did not clamp outer frame: {control.state()!r}")
    release(control)
    item = state_window(control)
    assert_geometry(item, (0, int(item["y"])))

    start = title_point(item)
    press_at(control, start, 274)
    grab_x = start[0] - int(item["x"])
    control.command(f"POINTER {grab_x - 20} {start[1]}")
    if int(interaction(control)["preview"]["x"]) != -20:
        raise RuntimeError(f"f.forcemove was incorrectly clamped: {control.state()!r}")
    release(control, 274)


def constrained_scenario(control: Control) -> None:
    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    release(control)
    item = state_window(control)
    original = (int(item["x"]), int(item["y"]))
    start = title_point(item)
    press_at(control, start)
    pending = interaction(control)
    if not pending["constrained"]:
        raise RuntimeError(f"rapid second move was not constrained: {pending!r}")
    target_x = original[0] + int(item["outer_width"]) - 1
    target_y = original[1] + int(item["outer_height"]) // 2
    control.command(f"POINTER {target_x} {target_y}")
    pending = interaction(control)
    if pending["axis"] != "horizontal" or pending["preview"]["y"] != original[1]:
        raise RuntimeError(f"constrained horizontal motion drifted: {pending!r}")
    release(control)


def resize_scenario(control: Control) -> None:
    item = state_window(control)
    original = {
        key: int(item[key]) for key in ("x", "y", "width", "height", "content_x", "content_y")
    }
    top_left = (original["x"] + original["content_x"] + 10,
                original["y"] + original["content_y"] + 5)
    press_at(control, top_left, 273)
    edges = int(interaction(control)["edges"])
    if edges != 5:
        raise RuntimeError(f"AutoRelativeResize did not select top-left: {interaction(control)!r}")
    control.command(f"POINTER {top_left[0] - 37} {top_left[1] - 29}")
    preview = interaction(control)["preview"]
    width, height = int(preview["width"]), int(preview["height"])
    if (width - 40) % 20 or (height - 30) % 10:
        raise RuntimeError(f"resize increments were not applied: {preview!r}")
    if width * 3 < height * 4 or width * 9 > height * 16:
        raise RuntimeError(f"resize aspect constraints were not applied: {preview!r}")
    if (int(preview["x"]) + width != original["x"] + original["width"] or
            int(preview["y"]) + height != original["y"] + original["height"]):
        raise RuntimeError(f"left/top constrained anchoring drifted: {preview!r}")
    assert_geometry(state_window(control), (original["x"], original["y"]))
    release(control, 273)
    item = state_window(control)
    if (int(item["x"]), int(item["y"]), int(item["width"]), int(item["height"])) != (
            int(preview["x"]), int(preview["y"]), width, height):
        raise RuntimeError(f"resize outline did not commit on release: {item!r}")

    original = {key: int(item[key]) for key in
                ("x", "y", "width", "height", "content_x", "content_y")}
    # Xwayland applies the ConfigureWindow from the first resize asynchronously.
    # Probe well inside the bottom-right third so the point remains within both
    # the old surface buffer and the newly configured frame while they converge.
    bottom_right = (
        original["x"] + original["content_x"] + original["width"] * 5 // 6,
        original["y"] + original["content_y"] + original["height"] * 5 // 6,
    )
    press_at(control, bottom_right, 273)
    if int(interaction(control)["edges"]) != 10:
        raise RuntimeError(f"AutoRelativeResize did not select bottom-right: {interaction(control)!r}")
    control.command(f"POINTER {bottom_right[0] + 31} {bottom_right[1] + 21}")
    control.command("BUTTON 274 press")
    item = state_window(control)
    if (int(item["x"]), int(item["y"]), int(item["width"]), int(item["height"])) != (
            original["x"], original["y"], original["width"], original["height"]):
        raise RuntimeError(f"resize abort changed live geometry: {item!r}")
    control.command("BUTTON 274 release")


def opaque_and_no_raise_scenario(control: Control) -> None:
    item = state_window(control)
    original = (int(item["x"]), int(item["y"]))
    start = title_point(item)
    press_at(control, start)
    control.command(f"POINTER {start[0] + 12} {start[1] + 8}")
    assert_geometry(state_window(control), (original[0] + 12, original[1] + 8))
    if not interaction(control)["opaque"]:
        raise RuntimeError("OpaqueMove did not select the live-window path")
    if any(event["event"] == "outline" for event in control.trace()["events"]):
        raise RuntimeError("OpaqueMove emitted an outline preview")
    control.command("BUTTON 274 press")
    assert_geometry(state_window(control), original)
    control.command("BUTTON 274 release")

    item = state_window(control)
    lower = title_point(item)
    press_at(control, lower, 273)
    release(control, 273)
    if int(state_window(control)["stack"]) != 1:
        raise RuntimeError("test setup failed to lower primary window")
    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    control.command(f"POINTER {start[0] + 10} {start[1]}")
    release(control)
    if int(state_window(control)["stack"]) != 1:
        raise RuntimeError("NoRaiseOnMove did not preserve stacking")

    item = state_window(control)
    point = (int(item["x"]) + int(item["content_x"]) + int(item["width"]) - 4,
             int(item["y"]) + int(item["content_y"]) + int(item["height"]) - 4)
    press_at(control, point, 274)
    control.command(f"POINTER {point[0] + 20} {point[1] + 10}")
    release(control, 274)
    if int(state_window(control)["stack"]) != 1:
        raise RuntimeError("NoRaiseOnResize did not preserve stacking")


def delta_stop_scenario(control: Control) -> None:
    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    control.command(f"POINTER {start[0] + 2} {start[1]}")
    release(control)
    if int(state_window(control)["stack"]) != 1:
        raise RuntimeError("f.deltastop stopped a below-threshold function")
    item = state_window(control)
    point = title_point(item)
    press_at(control, point, 273)
    release(control, 273)
    if int(state_window(control)["stack"]) != 0:
        raise RuntimeError("test setup failed to raise primary window")
    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    control.command(f"POINTER {start[0] + 3} {start[1]}")
    release(control)
    if int(state_window(control)["stack"]) != 0:
        raise RuntimeError("f.deltastop did not stop after threshold movement")


def menu_position_scenario(control: Control) -> None:
    item = state_window(control)
    start = title_point(item)
    press_at(control, start, 273)
    menu = control.state()["menu"]
    if not isinstance(menu, dict):
        raise RuntimeError("window menu did not open")
    control.command(f"POINTER {int(menu['x']) + 5} {int(menu['y']) + 5}")
    release(control, 273)
    positioning = interaction(control)
    if positioning["intent"] != "menu-position":
        raise RuntimeError(f"window-menu f.move did not enter click placement: {positioning!r}")
    control.command("POINTER 360 300")
    preview = interaction(control)["preview"]
    control.command("BUTTON 272 press")
    if control.state()["interactive"]:
        raise RuntimeError("menu-position confirming press was treated as an aborting grab")
    placed = state_window(control)
    if (int(placed["x"]), int(placed["y"])) != (
            int(preview["x"]), int(preview["y"])):
        raise RuntimeError(f"menu-position press did not commit: {placed!r} {preview!r}")
    release(control)

    # A root menu defers f.move until the next press selects its target. That
    # selecting press starts an ordinary drag and its release commits it.
    control.command("POINTER 5 5")
    control.command("BUTTON 273 press")
    menu = control.state()["menu"]
    if not isinstance(menu, dict):
        raise RuntimeError("root menu did not open")
    control.command(f"POINTER {int(menu['x']) + 5} {int(menu['y']) + 5}")
    release(control, 273)
    if not control.state()["deferred_root_action"]:
        raise RuntimeError("root-menu f.move was not deferred")
    item = state_window(control)
    start = title_point(item)
    press_at(control, start)
    pending = interaction(control)
    if pending["intent"] != "drag":
        raise RuntimeError(f"root-deferred f.move used the wrong intent: {pending!r}")
    control.command(f"POINTER {start[0] + 18} {start[1] + 12}")
    preview = interaction(control)["preview"]
    release(control)
    placed = state_window(control)
    if (int(placed["x"]), int(placed["y"])) != (
            int(preview["x"]), int(preview["y"])):
        raise RuntimeError(f"root-deferred f.move did not commit on release: {placed!r}")


def run_session(compositor: Path, client_binary: Path, config_text: str,
                scenario: Callable[[Control], None], number: int) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-move-resize-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "interaction.twmrc"
        config.write_text(config_text, encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        process = subprocess.Popen([
            str(compositor), "-f", str(config), "-s", startup,
            "--test-control", str(control_path),
            "--test-socket", f"wtwm-interaction-{os.getpid()}-{number}",
            "--test-backend", "headless",
        ], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            client_environment = environment.copy()
            client_environment["DISPLAY"] = wait_path(display_marker)
            client = subprocess.Popen([str(client_binary)], env=client_environment,
                                      text=True, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      bufsize=1)
            wait_line(client, "READY")
            state_window(control)
            state_window(control, "interaction-secondary")
            # Mapping metadata can precede the first fully hittable Xwayland
            # scene buffer under debug and sanitizer instrumentation.
            control.command("WAIT 2")
            control.command("TRACE CLEAR")
            scenario(control)
            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            client = None
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor exited with {process.returncode}")
        except Exception as error:
            if process.poll() is None:
                process.terminate()
            try:
                _, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate()
            raise RuntimeError(f"session {number}: {error}\n{stderr}") from error
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    common = 'BorderWidth 2\nFramePadding 2\nTitleFont "DejaVu Sans 10"\n'
    sessions = [
        (common + "MoveDelta 3\nDontMoveOff\nConstrainedMoveTime 0\n"
         "Button1 = : title : f.move\nButton2 = : title : f.forcemove\n",
         outline_scenario),
        (common + "MoveDelta 3\nConstrainedMoveTime 400\n"
         "Button1 = : title : f.move\n", constrained_scenario),
        (common + "MoveDelta 3\nAutoRelativeResize\n"
         "Button3 = : window : f.resize\n", resize_scenario),
        (common + "MoveDelta 3\nOpaqueMove\nAutoRelativeResize\n"
         "NoRaiseOnMove\nNoRaiseOnResize\n"
         "Button1 = : title : f.move\nButton2 = : window : f.resize\n"
         "Button3 = : title : f.lower\n", opaque_and_no_raise_scenario),
        (common + "MoveDelta 3\n"
         'Function "move-or-lower" { f.move f.deltastop f.lower }\n'
         'Button1 = : title : f.function "move-or-lower"\n'
         "Button3 = : title : f.raise\n", delta_stop_scenario),
        (common + "MoveDelta 0\nConstrainedMoveTime 0\n"
         'Button3 = : title|root : f.menu "position"\n'
         'Menu "position" { "Move" f.move }\n', menu_position_scenario),
    ]
    for index, (config, scenario) in enumerate(sessions):
        run_session(arguments.compositor.resolve(), arguments.client.resolve(),
                    config, scenario, index)
    print("move/resize interaction integration passed")


if __name__ == "__main__":
    main()
