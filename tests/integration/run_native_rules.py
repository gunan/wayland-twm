#!/usr/bin/env python3
"""Verify the documented native xdg-shell mapping for twm window lists."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_client_line(client: subprocess.Popen[str], expected: str) -> None:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [client.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected:
            return
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected native rules client event: {line!r}")
    raise RuntimeError(f"timed out waiting for native rules event {expected!r}")


def client_command(client: subprocess.Popen[str], command: str, expected: str) -> None:
    assert client.stdin is not None
    client.stdin.write(command + "\n")
    client.stdin.flush()
    wait_client_line(client, expected)


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


def window_by_app_id(state: dict[str, object], app_id: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["app_id"] == app_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {app_id!r} app_id: {state!r}")
    return matches[0]


def assert_decorated(state: dict[str, object], expected: dict[str, bool]) -> None:
    for title, decorated in expected.items():
        window = window_by_title(state, title)
        if window["type"] != "wayland" or window["decorated"] != decorated:
            raise RuntimeError(
                f"{title!r} native decoration expected {decorated}: {window!r}"
            )


def content_point(window: dict[str, object], side: str) -> tuple[int, int]:
    border = 2 if window["decorated"] else 0
    title_height = int(window["title_height"]) if window["decorated"] else 0
    if side == "left":
        x = int(window["x"]) + border + 5
    else:
        x = int(window["x"]) + border + int(window["width"]) - 5
    y = int(window["y"]) + border + title_height + int(window["height"]) // 2
    return x, y


def click_content(control: Control, window: dict[str, object], side: str) -> None:
    x, y = content_point(window, side)
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")


def run(compositor: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-native-rules-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_name = f"wtwm-native-rules-{os.getpid()}"
        config = temporary / "native-rules.twmrc"
        config.write_text(
            'BorderWidth 2\n'
            'NoTitle { "NativeTitle" "org.wtwm.NativeApp" "NativeCase" '
            '"org.wtwm.NativeCase" "*" "Collision Window" }\n'
            'MakeTitle { "Collision Window" }\n'
            'AutoRaise { "org.wtwm.AutoRaise" }\n'
            'StartIconified { "org.wtwm.StartIconified" }\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config),
                "--test-control", str(control_path),
                "--test-socket", display_name,
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
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 960 540")
            client_environment = environment.copy()
            client_environment["WAYLAND_DISPLAY"] = display_name
            client = subprocess.Popen(
                [str(client_binary)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_client_line(client, "READY")
            state = wait_state(
                control,
                lambda item: len(item["windows"]) == 9,
                "initial native rule windows",
            )
            assert_decorated(state, {
                "NativeTitle": False,
                "App Window": False,
                "nativecase": True,
                "Case App Window": True,
                "*": False,
                "Collision Window": False,
                "Plain Window": True,
            })
            auto = window_by_title(state, "Auto Window")
            if not auto["auto_raise"]:
                raise RuntimeError(f"native app_id AutoRaise was not captured: {auto!r}")
            start = window_by_title(state, "Start Window")
            if not start["iconified"] or "Start Window" not in state["icons"]:
                raise RuntimeError(
                    f"native app_id StartIconified was not applied: {state!r}"
                )

            client_command(client, "UPDATE_PLAIN_TITLE", "PLAIN_TITLE_UPDATED")
            state = wait_state(
                control,
                lambda item: window_by_app_id(item, "org.wtwm.Plain")["title"]
                == "NativeTitle"
                and not window_by_app_id(item, "org.wtwm.Plain")["decorated"],
                "live native title match",
            )
            client_command(client, "UPDATE_PLAIN_APP_ID", "PLAIN_APP_ID_UPDATED")
            state = wait_state(
                control,
                lambda item: not window_by_title(item, "Plain Window")["decorated"]
                and window_by_title(item, "Plain Window")["app_id"]
                == "org.wtwm.NativeApp",
                "live native app_id match",
            )
            client_command(client, "RESET_PLAIN", "PLAIN_RESET")
            state = wait_state(
                control,
                lambda item: window_by_title(item, "Plain Window")["decorated"],
                "live native decoration restoration",
            )

            client_command(client, "UPDATE_AUTO_APP_ID", "AUTO_APP_ID_UPDATED")
            state = wait_state(
                control,
                lambda item: window_by_title(item, "Auto Window")["app_id"]
                == "org.wtwm.NoAutoRaise"
                and window_by_title(item, "Auto Window")["auto_raise"],
                "native AutoRaise metadata snapshot",
            )
            client_command(client, "UNMAP_AUTO", "AUTO_UNMAPPED")
            wait_state(
                control,
                lambda item: not any(
                    entry["title"] == "Auto Window" for entry in item["windows"]
                ),
                "native AutoRaise protocol unmap",
            )
            client_command(client, "REMAP_AUTO", "AUTO_REMAPPED")
            state = wait_state(
                control,
                lambda item: any(
                    entry["title"] == "Auto Window" and entry["auto_raise"]
                    for entry in item["windows"]
                ),
                "native AutoRaise object snapshot after remap",
            )
            plain = window_by_title(state, "Plain Window")
            click_content(control, plain, "right")
            state = wait_state(
                control,
                lambda item: item["focus"] == "Plain Window",
                "explicit focus before native AutoRaise",
            )
            auto = window_by_title(state, "Auto Window")
            x, y = content_point(auto, "left")
            control.command(f"POINTER {x} {y}")
            wait_state(
                control,
                lambda item: item["focus"] == "Auto Window",
                "native AutoRaise after metadata change and remap",
            )

            client_command(client, "UNMAP_START", "START_UNMAPPED")
            wait_state(
                control,
                lambda item: not any(
                    entry["title"] == "Start Window" for entry in item["windows"]
                ),
                "native StartIconified protocol unmap",
            )
            client_command(client, "REMAP_START", "START_REMAPPED")
            state = wait_state(
                control,
                lambda item: any(
                    entry["title"] == "Start Window" and entry["mapped"]
                    and not entry["iconified"] for entry in item["windows"]
                ),
                "native StartIconified object remap",
            )
            if "Start Window" in state["icons"]:
                raise RuntimeError(f"native remap re-applied StartIconified: {state!r}")

            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"native rules client returned {client.returncode}")
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
                f"{error}\nnative client stderr:\n{client_error}\n"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.client.resolve())


if __name__ == "__main__":
    main()
