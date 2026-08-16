#!/usr/bin/env python3
"""Verify reference-ordered .twmrc window lists against real Xwayland clients."""

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
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_line(client: subprocess.Popen[str], expected: str) -> str:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([client.stdout], [], [], deadline - time.monotonic())
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected X11 client event: {line!r}")
    raise RuntimeError(f"timed out waiting for X11 client event {expected!r}")


def command(client: subprocess.Popen[str], text: str, expected: str) -> str:
    assert client.stdin is not None
    client.stdin.write(text + "\n")
    client.stdin.flush()
    return wait_line(client, expected)


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def window_by_title(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {title!r} window: {state!r}")
    return matches[0]


def window_by_xid(state: dict[str, object], xid: int) -> dict[str, object]:
    matches = [item for item in state["windows"] if item.get("xid") == xid]
    if len(matches) != 1:
        raise RuntimeError(f"expected one X11 window 0x{xid:x}: {state!r}")
    return matches[0]


def lifecycle_matches(state: dict[str, object], xid: int, associated: bool) -> bool:
    return any(
        item["xid"] == xid and item["associated"] == associated
        for item in state["xwayland_lifecycle"]
    )


def assert_decorated(state: dict[str, object], expected: dict[str, bool]) -> None:
    for title, decorated in expected.items():
        item = window_by_title(state, title)
        if item["decorated"] != decorated:
            raise RuntimeError(
                f"{title!r} decoration expected {decorated}: {item!r}"
            )


def click_content(control: Control, item: dict[str, object]) -> None:
    border = 2 if item["decorated"] else 0
    title = int(item["title_height"]) if item["decorated"] else 0
    x = int(item["x"]) + border + int(item["width"]) // 2
    y = int(item["y"]) + border + title + int(item["height"]) // 2
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")


def point_at_content(control: Control, item: dict[str, object]) -> None:
    border = 2 if item["decorated"] else 0
    title = int(item["title_height"]) if item["decorated"] else 0
    x = int(item["x"]) + border + int(item["width"]) // 2
    y = int(item["y"]) + border + title + int(item["height"]) // 2
    control.command(f"POINTER {x} {y}")


def exercise_selective(
    control: Control, client: subprocess.Popen[str], state: dict[str, object]
) -> None:
    assert_decorated(state, {
        "RuleTitle": False,
        "Instance Window": False,
        "Class Window": False,
        "case-sensitive": True,
        "Collision Window": False,
        "Plain Window": True,
    })
    auto = window_by_title(state, "Auto Window")
    if not auto["auto_raise"]:
        raise RuntimeError(f"AutoRaise instance match was not captured: {auto!r}")
    start = window_by_title(state, "Start Window")
    if not start["iconified"] or "Start Window" not in state["icons"]:
        raise RuntimeError(f"StartIconified title match was not applied: {state!r}")

    plain = window_by_title(state, "Plain Window")
    plain_xid = int(plain["xid"])
    command(client, "UPDATE_PLAIN_TITLE", "PLAIN_TITLE_UPDATED")
    state = wait_state(
        control,
        lambda item: window_by_xid(item, plain_xid)["title"] == "RuleTitle"
        and not window_by_xid(item, plain_xid)["decorated"],
        "live WM_NAME NoTitle match",
    )
    command(client, "UPDATE_PLAIN_CLASS", "PLAIN_CLASS_UPDATED")
    state = wait_state(
        control,
        lambda item: window_by_xid(item, plain_xid)["title"] == "Plain Window"
        and window_by_xid(item, plain_xid)["class"] == "RuleClass"
        and not window_by_xid(item, plain_xid)["decorated"],
        "live WM_CLASS NoTitle match",
    )
    command(client, "RESET_PLAIN", "PLAIN_RESET")
    state = wait_state(
        control,
        lambda item: window_by_xid(item, plain_xid)["class"] == "PlainClass"
        and window_by_xid(item, plain_xid)["decorated"],
        "live X11 decoration restoration",
    )

    plain = window_by_xid(state, plain_xid)
    click_content(control, plain)
    state = wait_state(control, lambda item: item["focus"] == "Plain Window",
                       "explicit focus before AutoRaise")
    command(client, "UPDATE_AUTO_CLASS", "AUTO_CLASS_UPDATED")
    state = wait_state(
        control,
        lambda item: window_by_title(item, "Auto Window")["instance"]
        == "auto-instance-updated"
        and window_by_title(item, "Auto Window")["auto_raise"],
        "manage-time AutoRaise snapshot after WM_CLASS change",
    )
    auto = window_by_title(state, "Auto Window")
    point_at_content(control, auto)
    state = wait_state(
        control,
        lambda item: item["focus"] == "Plain Window"
        and window_by_title(item, "Auto Window")["stack"] == 0,
        "focus-neutral AutoRaise instance hover",
    )

    auto_xid = int(auto["xid"])
    command(client, "UNMAP_AUTO", "AUTO_UNMAPPED")
    wait_state(control, lambda item: lifecycle_matches(item, auto_xid, False),
               "AutoRaise client dissociation")
    command(client, "REMAP_AUTO", "AUTO_REMAPPED")
    state = wait_state(
        control,
        lambda item: lifecycle_matches(item, auto_xid, True)
        and any(entry.get("xid") == auto_xid and not entry["auto_raise"]
                for entry in item["windows"]),
        "AutoRaise snapshot on a fresh X management cycle",
    )
    plain = window_by_xid(state, plain_xid)
    if state["focus"] != "Plain Window":
        raise RuntimeError(f"X remanagement changed locked focus: {state!r}")
    point_at_content(control, window_by_xid(state, auto_xid))
    state = control.state()
    if state["focus"] != "Plain Window":
        raise RuntimeError(f"stale AutoRaise survived X remanagement: {state!r}")

    start_xid = int(start["xid"])
    command(client, "UNMAP_START", "START_UNMAPPED")
    wait_state(
        control,
        lambda item: lifecycle_matches(item, start_xid, False),
        "StartIconified client dissociation",
    )
    command(client, "REMAP_START", "START_REMAPPED")
    state = wait_state(
        control,
        lambda item: lifecycle_matches(item, start_xid, True)
        and any(entry.get("xid") == start_xid and entry["iconified"]
                for entry in item["windows"]),
        "StartIconified on a fresh X management cycle",
    )
    remapped = window_by_xid(state, start_xid)
    if not remapped["mapped"] or "Start Window" not in state["icons"]:
        raise RuntimeError(f"remapped StartIconified client is stale: {remapped!r}")


def exercise_global(
    control: Control, client: subprocess.Popen[str], state: dict[str, object]
) -> None:
    del control, client
    assert_decorated(state, {
        "RuleTitle": True,
        "Instance Window": True,
        "Class Window": True,
        "case-sensitive": False,
        "Auto Window": False,
        "Start Window": False,
        "Plain Window": False,
        "Collision Window": False,
    })


def run_case(
    compositor: Path,
    client_binary: Path,
    name: str,
    config_text: str,
    exercise: Callable[[Control, subprocess.Popen[str], dict[str, object]], None],
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"wtwm-xwayland-rules-{name}-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "rules.twmrc"
        config.write_text(config_text, encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", f"wtwm-xrules-{name}-{os.getpid()}",
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 840 480")
            display = wait_path(display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            state = wait_state(
                control,
                lambda item: len(item["windows"]) == 8
                and len(item["xwayland_lifecycle"]) == 8,
                f"{name} Xwayland rule windows",
            )
            exercise(control, client, state)
            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"X11 rules client returned {client.returncode}")
            client = None
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
        except Exception as error:
            client_error = ""
            if client is not None and client.poll() is None:
                client.terminate()
            if client is not None:
                try:
                    _, client_error = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    _, client_error = client.communicate()
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
            raise RuntimeError(
                f"{error}\nX11 client stderr:\n{client_error}\n"
                f"compositor stderr:\n{compositor_error}"
            ) from error
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def run(compositor: Path, client_binary: Path) -> None:
    run_case(
        compositor,
        client_binary,
        "selective",
        'NoTitle { "RuleTitle" "rule-instance" "RuleClass" '
        '"Case-Sensitive" "Collision Window" }\n'
        'MakeTitle { "Collision Window" }\n'
        'AutoRaise { "auto-instance" }\n'
        'StartIconified { "Start Window" }\n'
        'NoTitleFocus\n'
        'Button1 = : window : f.focus\n',
        exercise_selective,
    )
    run_case(
        compositor,
        client_binary,
        "global",
        'NoTitle\n'
        'MakeTitle { "RuleTitle" "rule-instance" "RuleClass" "Case-Sensitive" }\n',
        exercise_global,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.client.resolve())


if __name__ == "__main__":
    main()
