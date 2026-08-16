#!/usr/bin/env python3
"""Exercise twm focus contexts and overlap-dependent stacking under Xwayland."""

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


def wait_line(process: subprocess.Popen[str], expected: str) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], deadline - time.monotonic())
        if not ready:
            break
        line = process.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        raise RuntimeError(f"unexpected client output {line!r}")
    raise RuntimeError(f"timed out waiting for {expected!r}")


def client_command(process: subprocess.Popen[str], command: str,
                   expected: str) -> str:
    assert process.stdin is not None
    process.stdin.write(command + "\n")
    process.stdin.flush()
    return wait_line(process, expected)


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def wait_display(control: Control, path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            display = path.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("startup command did not publish DISPLAY")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"missing unique {title!r}: {state!r}")
    return matches[0]


def point(item: dict[str, object], context: str) -> tuple[int, int]:
    x, y = int(item["x"]), int(item["y"])
    border = int(item["border_width"])
    if context == "window":
        return (x + int(item["content_x"]) + 12,
                y + int(item["content_y"]) + 12)
    if context == "title":
        return (x + int(item["outer_width"]) // 2, y + border + 6)
    if context == "frame":
        return (x + 1,
                y + int(item["outer_height"]) // 2)
    raise ValueError(context)


def click(control: Control, at: tuple[int, int], code: int) -> None:
    control.command(f"POINTER {at[0]} {at[1]}")
    control.command(f"BUTTON {code} press")
    control.command(f"BUTTON {code} release")


def assert_stack(state: dict[str, object], top: str, bottom: str) -> None:
    if int(window(state, top)["stack"]) >= int(window(state, bottom)["stack"]):
        raise RuntimeError(f"expected {top!r} above {bottom!r}: {state!r}")


def run(compositor_binary: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-focus-stack-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "display"
        config_path = temporary / "focus-stack.twmrc"
        config_path.write_text(
            'NoTitleFocus\n'
            'AutoRaise { "focus-b" }\n'
            'Button1 = : window : f.focus\n'
            'Button1 = : title : f.iconify\n'
            'Button1 = : icon : f.deiconify\n'
            'Button2 = : window|title|frame|icon : f.raise\n'
            'Button3 = : window|title|frame|icon : f.raiselower\n'
            'Button4 = : window|title|frame|icon : f.lower\n'
            'Button5 = : root : f.circleup\n'
            'Button6 = : root : f.circledown\n'
            'Button3 = : root : f.menu "focus-menu"\n'
            'Menu "focus-menu" { "Focus stays put" f.nop }\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        socket_name = f"wtwm-focus-stack-{os.getpid()}"
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
            control.command("SET CURSOR 10 10")
            display = wait_display(control, display_path)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            state = wait_state(control, lambda item: len(item["windows"]) == 2,
                               "two managed windows")
            if state["focus_root"] is not True or state["active"] is not None:
                raise RuntimeError(f"mapping away from the pointer stole focus: {state!r}")
            a = window(state, "focus-a")
            b = window(state, "focus-b")
            assert_stack(state, "focus-b", "focus-a")

            control.command("TRACE CLEAR")
            control.command(f"POINTER {point(a, 'title')[0]} {point(a, 'title')[1]}")
            state = control.state()
            if state["active"] != "focus-a" or state["focus"] is not None:
                raise RuntimeError(f"NoTitleFocus did not separate activation: {state!r}")
            control.command("WAIT 2")
            status = client_command(client, "STATUS", "STATUS")
            if int(status.split()[1]) != 1 or status.split()[3] != "root":
                raise RuntimeError(f"WM_TAKE_FOCUS was not sent to input=true client: {status}")

            click(control, point(a, "window"), 272)
            state = control.state()
            if state["focus_root"] is not False or state["focus"] != "focus-a":
                raise RuntimeError(f"f.focus did not lock client focus: {state!r}")
            control.command("WAIT 2")
            status = client_command(client, "STATUS", "STATUS")
            if int(status.split()[1]) != 1 or status.split()[3] != "a":
                raise RuntimeError(f"f.focus conflated direct focus with TAKE_FOCUS: {status}")

            control.command(f"POINTER {point(b, 'window')[0]} {point(b, 'window')[1]}")
            state = control.state()
            if state["active"] != "focus-a" or state["focus"] != "focus-a":
                raise RuntimeError(f"locked focus followed pointer or AutoRaise: {state!r}")
            assert_stack(state, "focus-b", "focus-a")
            control.command("WAIT 2")
            status = client_command(client, "STATUS", "STATUS")
            if int(status.split()[2]) != 0 or status.split()[3] != "a":
                raise RuntimeError(f"locked pointer crossing sent TAKE_FOCUS: {status}")

            click(control, point(a, "frame"), 274)
            state = control.state()
            assert_stack(state, "focus-a", "focus-b")
            if state["focus"] != "focus-a":
                raise RuntimeError(f"raise changed focus: {state!r}")

            b_exposed = (int(b["x"]) + int(b["outer_width"]) // 2,
                         int(b["y"]) + int(b["outer_height"]) - 1)
            click(control, b_exposed, 273)
            assert_stack(control.state(), "focus-b", "focus-a")
            click(control, b_exposed, 273)
            assert_stack(control.state(), "focus-a", "focus-b")

            root = (620, 460)
            click(control, root, 276)
            assert_stack(control.state(), "focus-b", "focus-a")
            click(control, root, 277)
            assert_stack(control.state(), "focus-a", "focus-b")

            click(control, point(a, "window"), 272)
            state = control.state()
            if state["focus_root"] is not True or state["active"] is not None:
                raise RuntimeError(f"second f.focus did not restore PointerRoot: {state!r}")
            control.command("WAIT 2")
            status = client_command(client, "STATUS", "STATUS")
            if status.split()[3] != "root":
                raise RuntimeError(f"f.focus toggle did not restore X PointerRoot: {status}")

            control.command(f"POINTER {point(b, 'window')[0]} {point(b, 'window')[1]}")
            state = control.state()
            if state["active"] != "focus-b" or state["focus"] is not None:
                raise RuntimeError(f"input=false TAKE_FOCUS changed direct input: {state!r}")
            control.command("WAIT 2")
            status = client_command(client, "STATUS", "STATUS")
            if int(status.split()[2]) != 1 or status.split()[3] != "root":
                raise RuntimeError(f"input=false TAKE_FOCUS protocol split failed: {status}")
            click(control, point(b, "window"), 272)
            state = control.state()
            if (state["focus_root"] is not False or state["active"] != "focus-b"
                    or state["focus"] is not None):
                raise RuntimeError(f"input=false f.focus did not lock logically: {state!r}")
            status = client_command(client, "STATUS", "STATUS")
            if int(status.split()[2]) != 1 or status.split()[3] != "root":
                raise RuntimeError(f"input=false f.focus changed X input or sent TAKE: {status}")
            click(control, point(b, "window"), 272)

            click(control, point(a, "title"), 272)
            state = wait_state(control, lambda item: len(item["icon_views"]) == 1,
                               "minimal icon hit target")
            icon = state["icon_views"][0]
            icon_point = (int(icon["x"]) + int(icon["width"]) // 2,
                          int(icon["y"]) + int(icon["height"]) // 2)
            click(control, icon_point, 274)
            click(control, icon_point, 272)
            state = wait_state(control, lambda item: not item["icon_views"],
                               "icon deiconify")
            if window(state, "focus-a")["iconified"]:
                raise RuntimeError(f"icon context did not deiconify: {state!r}")

            client_command(client, "CLEAR_HINTS_A", "HINTS_A_CLEARED")
            control.command("WAIT 2")
            click(control, point(window(state, "focus-a"), "window"), 272)
            locked = control.state()
            status = client_command(client, "STATUS", "STATUS")
            if status.split()[3] != "a":
                raise RuntimeError(f"absent WM_HINTS did not accept f.focus: {status}")
            control.command(f"POINTER {root[0]} {root[1]}")
            control.command("BUTTON 273 press")
            menu_state = wait_state(control, lambda item: item["menu"] is not None,
                                    "root menu")
            if menu_state["active"] != locked["active"] or menu_state["focus"] != locked["focus"]:
                raise RuntimeError(f"menu acquired a binding/focus context: {menu_state!r}")
            menu = menu_state["menu"]
            control.command(f"POINTER {int(menu['x']) + 4} {int(menu['y']) + 4}")
            control.command("BUTTON 273 release")

            trace = control.trace()
            bindings = {event["context"] for event in trace["events"]
                        if event["event"] == "binding"}
            if not {"window", "title", "frame", "icon"}.issubset(bindings):
                raise RuntimeError(f"binding contexts missing from TRACE: {trace!r}")
            if any(event["context"] == "menu" for event in trace["events"]):
                raise RuntimeError(f"menu leaked a binding context: {trace!r}")
            if not any(event["event"] == "raise" and
                       event["window"]["title"] == "focus-b" and
                       event["state"]["focused"] is False
                       for event in trace["events"]):
                raise RuntimeError(f"AutoRaise was not independent of focus: {trace!r}")

            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            client = None
            control.command("QUIT")
            compositor.wait(timeout=5)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor exited with {compositor.returncode}")
        except Exception as error:
            if compositor.poll() is None:
                compositor.terminate()
            try:
                _, compositor_error = compositor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
                _, compositor_error = compositor.communicate()
            client_error = ""
            if client is not None:
                if client.poll() is None:
                    client.terminate()
                _, client_error = client.communicate(timeout=5)
            raise RuntimeError(f"{error}\ncompositor:\n{compositor_error}\nclient:\n{client_error}") from error
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
                compositor.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.client.resolve())


if __name__ == "__main__":
    main()
