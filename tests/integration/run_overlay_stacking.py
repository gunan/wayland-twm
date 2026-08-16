#!/usr/bin/env python3
"""Prove native popup, X11 override-redirect, and menu overlay ordering."""

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


GREEN = (0, 204, 68)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BLUE = (32, 64, 128)
YELLOW = (255, 255, 0)


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
        raise RuntimeError(f"unexpected client event: {line!r}")
    raise RuntimeError(f"timed out waiting for client event {expected!r}")


def client_command(client: subprocess.Popen[str], command: str, expected: str) -> str:
    assert client.stdin is not None
    client.stdin.write(command + "\n")
    client.stdin.flush()
    return wait_line(client, expected)


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def wait_display(control: Control, path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            display = path.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("startup command did not record the Xwayland DISPLAY")


def native_window(state: dict[str, object]) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == "overlay-native"]
    if len(matches) != 1:
        raise RuntimeError(f"expected one native overlay window: {state!r}")
    return matches[0]


def popup(state: dict[str, object]) -> dict[str, object]:
    popups = state["popups"]
    if len(popups) != 1 or not popups[0]["mapped"] or not popups[0]["visible"]:
        raise RuntimeError(f"expected one visible native popup: {state!r}")
    return popups[0]


def override_redirect(state: dict[str, object]) -> dict[str, object]:
    windows = state["override_redirect"]
    if len(windows) != 1 or windows[0]["title"] != "overlay-override-redirect":
        raise RuntimeError(f"expected one override-redirect window: {state!r}")
    return windows[0]


def overlap_point(first: dict[str, object], second: dict[str, object]) -> tuple[int, int]:
    left = max(int(first["x"]), int(second["x"]))
    top = max(int(first["y"]), int(second["y"]))
    right = min(int(first["x"]) + int(first["width"]),
                int(second["x"]) + int(second["width"]))
    bottom = min(int(first["y"]) + int(first["height"]),
                 int(second["y"]) + int(second["height"]))
    if right - left < 20 or bottom - top < 20:
        raise RuntimeError(f"test surfaces do not overlap: {first!r}, {second!r}")
    return ((left + right) // 2, (top + bottom) // 2)


def read_ppm_pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    data = path.read_bytes()
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError(f"invalid PPM capture header in {path}")
    width, height = (int(value) for value in fields[1].split())
    if x < 0 or y < 0 or x >= width or y >= height:
        raise RuntimeError(f"capture sample ({x}, {y}) lies outside {width}x{height}")
    offset = (y * width + x) * 3
    pixel = fields[3][offset:offset + 3]
    if len(pixel) != 3:
        raise RuntimeError(f"truncated PPM capture in {path}")
    return (pixel[0], pixel[1], pixel[2])


def assert_top_color(control: Control, directory: Path, name: str,
                     point: tuple[int, int], expected: tuple[int, int, int]) -> None:
    path = directory / f"{name}.ppm"
    deadline = time.monotonic() + 10
    actual = (-1, -1, -1)
    while time.monotonic() < deadline:
        control.command("WAIT 2")
        control.command(f"CAPTURE {path}")
        actual = read_ppm_pixel(path, *point)
        if all(abs(channel - target) <= 4
               for channel, target in zip(actual, expected)):
            return
    raise RuntimeError(
        f"{name} topmost pixel at {point} is {actual}, expected {expected}"
    )


def assert_top_color_any(control: Control, directory: Path, name: str,
                         point: tuple[int, int],
                         expected: tuple[tuple[int, int, int], ...]) -> None:
    path = directory / f"{name}.ppm"
    deadline = time.monotonic() + 10
    actual = (-1, -1, -1)
    while time.monotonic() < deadline:
        control.command("WAIT 2")
        control.command(f"CAPTURE {path}")
        actual = read_ppm_pixel(path, *point)
        if any(all(abs(channel - target) <= 4
                   for channel, target in zip(actual, color))
               for color in expected):
            return
    raise RuntimeError(
        f"{name} topmost pixel at {point} is {actual}, expected one of {expected}"
    )


def stop_client(client: subprocess.Popen[str]) -> None:
    if client.poll() is not None:
        return
    client_command(client, "EXIT", "EXITING")
    client.wait(timeout=5)
    if client.returncode != 0:
        raise RuntimeError(f"client exited with status {client.returncode}")


def run(compositor_binary: Path, wayland_binary: Path, x11_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-overlay-stacking-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "display"
        config_path = temporary / "overlay.twmrc"
        config_path.write_text(
            'Color {\n'
            '  MenuBackground "#ffff00"\n'
            '  MenuForeground "black"\n'
            '  MenuBorderColor "black"\n'
            '}\n'
            'MenuBorderWidth 1\n'
            'Button3 = : all : f.menu "stacking"\n'
            'Menu "stacking" { "Overlay Menu" f.nop }\n',
            encoding="utf-8",
        )
        socket_name = f"wtwm-overlay-{os.getpid()}"
        startup = "printf '%s\\n' \"$DISPLAY\" > " + shlex.quote(str(display_path))
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor = subprocess.Popen(
            [
                str(compositor_binary), "-f", str(config_path), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", socket_name,
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        clients: list[subprocess.Popen[str]] = []
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            display = wait_display(control, display_path)

            wayland_environment = environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = socket_name
            native = subprocess.Popen(
                [str(wayland_binary)], env=wayland_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1,
            )
            clients.append(native)
            wait_line(native, "READY")
            wait_state(control, lambda state: len(state["windows"]) == 1,
                       "native toplevel map")

            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = display
            x11 = subprocess.Popen(
                [str(x11_binary)], env=x11_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1,
            )
            clients.append(x11)
            wait_line(x11, "READY")

            client_command(x11, "MAP", "MAPPED")
            state = wait_state(control, lambda item: len(item["override_redirect"]) == 1,
                               "override-redirect map")
            x_window = override_redirect(state)
            client_command(native, "MAP_POPUP", "POPUP_MAPPED")
            state = wait_state(control, lambda item: len(item["popups"]) == 1,
                               "native popup map")
            native_popup = popup(state)
            point = overlap_point(native_popup, x_window)
            assert_top_color(control, temporary, "popup-after-x-map", point, GREEN)

            window = native_window(state)
            old_popup_position = (int(native_popup["x"]), int(native_popup["y"]))
            title_x = int(window["x"]) + 60
            title_y = int(window["y"]) + 8
            control.command(f"POINTER {title_x} {title_y}")
            control.command("BUTTON 272 press")
            control.command(f"POINTER {title_x + 30} {title_y + 24}")
            control.command("BUTTON 272 release")
            state = wait_state(
                control,
                lambda item: len(item["popups"]) == 1 and
                int(item["popups"][0]["x"]) == old_popup_position[0] + 30 and
                int(item["popups"][0]["y"]) == old_popup_position[1] + 24,
                "popup movement with its parent",
            )
            native_popup = popup(state)
            x_window = override_redirect(state)
            point = overlap_point(native_popup, x_window)
            assert_top_color(control, temporary, "popup-after-parent-move", point, GREEN)

            client_command(x11, "UNMAP", "UNMAPPED")
            wait_state(control, lambda item: not item["override_redirect"],
                       "override-redirect unmap")
            assert_top_color(control, temporary, "popup-after-x-unmap", point, GREEN)

            client_command(x11, "MAP", "MAPPED")
            state = wait_state(control, lambda item: len(item["override_redirect"]) == 1,
                               "override-redirect remap")
            x_window = override_redirect(state)
            point = overlap_point(popup(state), x_window)
            assert_top_color_any(control, temporary, "x-after-remap", point,
                                 (BLACK, WHITE))

            client_command(x11, "UNMAP", "UNMAPPED")
            wait_state(control, lambda item: not item["override_redirect"],
                       "second override-redirect unmap")
            client_command(native, "DESTROY_POPUP", "POPUP_DESTROYED")
            state = wait_state(control, lambda item: not item["popups"],
                               "native popup destroy")
            window = native_window(state)
            base_point = (int(window["x"]) + 20,
                          int(window["y"]) + int(window["title_height"]) + 20)
            assert_top_color(control, temporary, "native-after-popup-destroy",
                             base_point, BLUE)

            client_command(native, "MAP_POPUP", "POPUP_MAPPED")
            wait_state(control, lambda item: len(item["popups"]) == 1,
                       "native popup recreation")
            client_command(x11, "MAP", "MAPPED")
            state = wait_state(control, lambda item: len(item["override_redirect"]) == 1,
                               "third override-redirect map")
            point = overlap_point(popup(state), override_redirect(state))
            assert_top_color_any(control, temporary, "x-before-menu", point,
                                 (BLACK, WHITE))

            control.command(f"POINTER {point[0]} {point[1]}")
            control.command("BUTTON 273 press")
            state = wait_state(control, lambda item: item["menu"] is not None,
                               "compositor menu map")
            menu = state["menu"]
            menu_point = (int(menu["x"]) + 3,
                          int(menu["y"]) + int(menu["row_height"]) - 3)
            assert_top_color(control, temporary, "menu-above-overlay", menu_point, YELLOW)
            control.command("BUTTON 273 release")
            wait_state(control, lambda item: item["menu"] is None,
                       "compositor menu dismissal")
            assert_top_color_any(control, temporary, "x-after-menu", menu_point,
                                 (BLACK, WHITE))

            client_command(x11, "UNMAP", "UNMAPPED")
            wait_state(control, lambda item: not item["override_redirect"],
                       "final override-redirect unmap")
            state = control.state()
            old_window_position = (int(native_window(state)["x"]),
                                   int(native_window(state)["y"]))
            old_popup_position = (int(popup(state)["x"]), int(popup(state)["y"]))
            client_command(native, "UNMAP_TOPLEVEL", "TOPLEVEL_UNMAPPED")
            state = wait_state(
                control,
                lambda item: not item["windows"] and not item["popups"],
                "parent unmap popup cleanup",
            )
            if state["focus"] is not None or state["menu"] is not None:
                raise RuntimeError(f"parent cleanup retained focus or menu: {state!r}")
            client_command(native, "DROP_DISMISSED_POPUP",
                           "DISMISSED_POPUP_DROPPED")
            client_command(native, "REMAP_TOPLEVEL", "TOPLEVEL_REMAPPED")
            state = wait_state(control, lambda item: len(item["windows"]) == 1,
                               "parent remap")
            remapped = native_window(state)
            if (int(remapped["x"]), int(remapped["y"])) != old_window_position:
                raise RuntimeError(f"parent remap changed placement: {state!r}")
            client_command(native, "MAP_POPUP", "POPUP_MAPPED")
            state = wait_state(control, lambda item: len(item["popups"]) == 1,
                               "popup after parent remap")
            remapped_popup = popup(state)
            if (int(remapped_popup["x"]), int(remapped_popup["y"])) != old_popup_position:
                raise RuntimeError(f"popup remap lost its parent anchor: {state!r}")
            final_point = (int(remapped_popup["x"]) + 40,
                           int(remapped_popup["y"]) + 40)
            assert_top_color(control, temporary, "popup-after-parent-remap",
                             final_point, GREEN)

            stop_client(x11)
            clients.remove(x11)
            stop_client(native)
            clients.remove(native)
            control.command("QUIT")
            compositor.wait(timeout=5)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor returned {compositor.returncode}")
        except Exception as error:
            client_errors: list[str] = []
            for client in clients:
                if client.poll() is None:
                    client.terminate()
                try:
                    _, stderr = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    _, stderr = client.communicate()
                if stderr:
                    client_errors.append(stderr)
            if compositor.poll() is None:
                compositor.terminate()
            try:
                _, compositor_error = compositor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
                _, compositor_error = compositor.communicate()
            raise RuntimeError(
                f"{error}\nclient stderr:\n{''.join(client_errors)}"
                f"compositor stderr:\n{compositor_error}"
            ) from error
        finally:
            for client in clients:
                if client.poll() is None:
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
    parser.add_argument("--wayland-client", type=Path, required=True)
    parser.add_argument("--x11-client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.wayland_client.resolve(),
        arguments.x11_client.resolve())


if __name__ == "__main__":
    main()
