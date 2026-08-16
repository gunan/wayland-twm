#!/usr/bin/env python3
"""Capture and validate every Milestone 5 compositor-owned visual state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


MODE_COLORS = {
    "color": {
        "root": (24, 40, 56),
        "border": (17, 34, 51),
        "title": (32, 64, 96),
    },
    "grayscale": {
        "root": (48, 48, 48),
        "border": (85, 85, 85),
        "title": (119, 119, 119),
    },
    "monochrome": {
        "root": (0, 0, 0),
        "border": (255, 255, 255),
        "title": (0, 0, 0),
    },
}


def wait_line(client: subprocess.Popen[str], expected: str) -> str:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [client.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected visual client event: {line!r}")
    raise RuntimeError(f"timed out waiting for visual client event {expected!r}")


def client_command(client: subprocess.Popen[str], command: str, expected: str) -> str:
    assert client.stdin is not None
    client.stdin.write(command + "\n")
    client.stdin.flush()
    return wait_line(client, expected)


def wait_display(control: Control, marker: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            display = marker.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("startup command did not publish Xwayland DISPLAY")


def bravo(state: dict[str, object]) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["instance"] == "bravo"]
    if len(matches) != 1:
        raise RuntimeError(f"expected one bravo window: {state!r}")
    return matches[0]


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("capture is not an 8-bit PPM P6 image")
    width, height = (int(value) for value in fields[1].split())
    if len(fields[3]) != width * height * 3:
        raise RuntimeError("capture has a truncated pixel payload")
    return width, height, fields[3]


def pixel(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    width, height, payload = parse_ppm(data)
    if x < 0 or y < 0 or x >= width or y >= height:
        raise RuntimeError(f"sample ({x}, {y}) lies outside {width}x{height}")
    offset = (y * width + x) * 3
    return tuple(payload[offset:offset + 3])


def capture(control: Control, directory: Path, name: str) -> bytes:
    first = directory / f"{name}.ppm"
    repeat = directory / f".{name}.repeat.ppm"
    control.command("WAIT 3")
    control.command(f"CAPTURE {first}")
    control.command("WAIT 3")
    control.command(f"CAPTURE {repeat}")
    data = first.read_bytes()
    if data != repeat.read_bytes():
        raise RuntimeError(f"{name} changed between consecutive stable captures")
    repeat.unlink()
    width, height, _ = parse_ppm(data)
    if (width, height) != (260, 180):
        raise RuntimeError(f"{name} has unexpected size {width}x{height}")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_config(path: Path, asset: Path) -> None:
    quoted_asset = str(asset).replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(
        'BorderWidth 2\n'
        'FramePadding 2\n'
        'TitlePadding 8\n'
        'ButtonIndent 1\n'
        'TitleButtonBorderWidth 1\n'
        'MenuBorderWidth 2\n'
        'IconBorderWidth 2\n'
        'TitleFont "fixed"\nMenuFont "fixed"\nIconFont "fixed"\n'
        'InterpolateMenuColors\n'
        'Color {\n'
        ' DefaultBackground "#182838" BorderColor "#112233"\n'
        ' BorderTileForeground "#112233" BorderTileBackground "#99aabb"\n'
        ' TitleForeground "#ffffff" TitleBackground "#204060"\n'
        ' MenuForeground "#f0f0f0" MenuBackground "#203040"\n'
        ' MenuTitleForeground "#ffffff" MenuTitleBackground "#405060"\n'
        ' MenuBorderColor "#e0e0e0" MenuShadowColor "#080808"\n'
        ' IconForeground "#ffff00" IconBackground "#202020"\n'
        ' IconBorderColor "#00ffff" PointerForeground "#ff0000"\n'
        ' PointerBackground "#00ff00"\n'
        '}\n'
        'Grayscale {\n'
        ' DefaultBackground "#303030" BorderColor "#555555"\n'
        ' BorderTileForeground "#555555" BorderTileBackground "#aaaaaa"\n'
        ' TitleForeground "#eeeeee" TitleBackground "#777777"\n'
        ' MenuForeground "#eeeeee" MenuBackground "#666666"\n'
        ' MenuTitleForeground "#ffffff" MenuTitleBackground "#888888"\n'
        ' MenuBorderColor "#dddddd" MenuShadowColor "#222222"\n'
        ' IconForeground "#ffffff" IconBackground "#444444"\n'
        ' IconBorderColor "#bbbbbb" PointerForeground "#ffffff"\n'
        ' PointerBackground "#000000"\n'
        '}\n'
        'Monochrome {\n'
        ' DefaultBackground "black" BorderColor "white"\n'
        ' BorderTileForeground "white" BorderTileBackground "black"\n'
        ' TitleForeground "white" TitleBackground "black"\n'
        ' MenuForeground "white" MenuBackground "black"\n'
        ' MenuTitleForeground "black" MenuTitleBackground "white"\n'
        ' MenuBorderColor "white" MenuShadowColor "black"\n'
        ' IconForeground "white" IconBackground "black"\n'
        ' IconBorderColor "white" PointerForeground "white"\n'
        ' PointerBackground "black"\n'
        '}\n'
        f'Pixmaps {{ TitleHighlight "{quoted_asset}" }}\n'
        f'Icons {{ "bravo" "{quoted_asset}" }}\n'
        f'LeftTitleButton "{quoted_asset}" = f.nop\n'
        'Button3 = : root : f.menu "visual"\n'
        'Menu "child" { "Child title" f.title "Child action" f.nop }\n'
        'Menu "visual" ("#ffcc00":"#102030") {\n'
        ' "Visual states" f.title\n'
        ' "First" ("#ffffff":"#500000") f.nop\n'
        ' "Interpolated" f.nop\n'
        ' "Submenu" ("#000000":"#005000") f.menu "child"\n'
        '}\n',
        encoding="utf-8",
    )


def run_mode(arguments: argparse.Namespace, config: Path, mode: str,
             temporary: Path) -> dict[str, object]:
    mode_dir = arguments.evidence / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    runtime = temporary / f"runtime-{mode}"
    runtime.mkdir(mode=0o700)
    control_path = temporary / f"control-{mode}.sock"
    display_marker = temporary / f"display-{mode}"
    socket_name = f"wtwm-m5-states-{mode}-{os.getpid()}"
    startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C.UTF-8",
        "XDG_RUNTIME_DIR": str(runtime),
        "WLR_RENDERER": "pixman",
    })
    compositor = subprocess.Popen(
        [
            str(arguments.compositor), "-f", str(config), "-s", startup,
            "--visual-mode", mode, "--test-control", str(control_path),
            "--test-socket", socket_name, "--test-backend", "headless",
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    control: Control | None = None
    client: subprocess.Popen[str] | None = None
    report: dict[str, object] = {"captures": {}}
    try:
        control = Control(control_path, compositor)
        control.command("SET ANIMATION_MS 0")
        control.command("SET PLACEMENT_SEED 0")
        control.command("OUTPUT 260 180")
        display = wait_display(control, display_marker)
        client_environment = environment.copy()
        client_environment["DISPLAY"] = display
        client = subprocess.Popen(
            [str(arguments.client)],
            env=client_environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        wait_line(client, "READY")
        state = wait_state(control, lambda value: len(value["windows"]) == 2,
                           "both visual clients")
        client_command(client, "PHASE bravo", "PHASE bravo")
        state = wait_state(
            control, lambda value: bravo(value)["active"], "bravo focus"
        )
        item = bravo(state)

        images: dict[str, bytes] = {}
        images["focused"] = capture(control, mode_dir, "focused")
        colors = MODE_COLORS[mode]
        samples = {
            "root": pixel(images["focused"], 0, 179),
            "border": pixel(images["focused"], int(item["x"]), int(item["y"])),
            "title": pixel(
                images["focused"], int(item["x"]) + int(item["border_width"]) + 1,
                int(item["y"]) + int(item["border_width"]) + 1,
            ),
        }
        if samples != colors:
            raise RuntimeError(
                f"{mode} configured-color samples differ: {samples!r} != {colors!r}"
            )

        border = int(item["border_width"])
        custom_button_x = int(item["x"]) + border + 23
        button_y = int(item["y"]) + border + 8
        control.command(f"POINTER {custom_button_x} {button_y}")
        images["button-hover"] = capture(control, mode_dir, "button-hover")
        control.command("BUTTON 272 press")
        images["button-pressed"] = capture(control, mode_dir, "button-pressed")
        control.command("BUTTON 272 release")
        if not (images["focused"] == images["button-hover"] ==
                images["button-pressed"]):
            raise RuntimeError("twm-compatible title button states changed pixels")

        title_cases = (
            ("title-long", "L" * 180),
            ("title-empty", ""),
            ("title-nonascii", "Grüße 中"),
        )
        title_hashes: dict[str, str] = {}
        for name, title in title_cases:
            client_command(client, f"TITLE bravo {title}", "TITLE bravo")
            wait_state(control, lambda value, title=title: bravo(value)["title"] == title,
                       f"{name} metadata")
            images[name] = capture(control, mode_dir, name)
            title_hashes[name] = sha256(images[name])
        client_command(client, "RAPID bravo 64", "RAPID bravo 64")
        wait_state(
            control,
            lambda value: bravo(value)["title"] == "rapid-title-063",
            "rapid final title",
        )
        images["title-rapid"] = capture(control, mode_dir, "title-rapid")
        title_hashes["title-rapid"] = sha256(images["title-rapid"])
        if len(set(title_hashes.values())) != len(title_hashes):
            raise RuntimeError(f"title variants did not produce distinct captures: {title_hashes}")

        client_command(client, "TITLE bravo Reference Bravo", "TITLE bravo")
        state = wait_state(
            control, lambda value: bravo(value)["title"] == "Reference Bravo",
            "restored title",
        )
        item = bravo(state)
        iconify_x = int(item["x"]) + int(item["border_width"]) + 8
        iconify_y = int(item["y"]) + int(item["border_width"]) + 8
        control.command(f"POINTER {iconify_x} {iconify_y}")
        control.command("BUTTON 272 press")
        control.command("BUTTON 272 release")
        state = wait_state(
            control,
            lambda value: bravo(value)["iconified"] and len(value["icon_views"]) == 1,
            "configured XBM icon",
        )
        icon_view = state["icon_views"][0]
        if int(icon_view["width"]) <= 4 or int(icon_view["height"]) <= 4:
            raise RuntimeError(f"icon view omitted text/bitmap/border geometry: {icon_view!r}")
        images["icon"] = capture(control, mode_dir, "icon")

        control.command("POINTER 180 20")
        control.command("BUTTON 273 press")
        state = wait_state(control, lambda value: value["menu"] is not None,
                           "visual menu")
        menu = state["menu"]
        if menu["name"] != "visual" or int(menu["width"]) <= 4:
            raise RuntimeError(f"visual menu state is invalid: {menu!r}")
        images["menu-normal"] = capture(control, mode_dir, "menu-normal")
        menu_x = int(menu["x"])
        menu_y = int(menu["y"])
        row_height = int(menu["row_height"])
        menu_border = 2
        control.command(
            f"POINTER {menu_x + 8} {menu_y + menu_border + row_height // 2}"
        )
        state = control.state()
        if state["menu"]["selected"] != -1:
            raise RuntimeError("F_TITLE row became selectable")
        images["menu-title"] = capture(control, mode_dir, "menu-title")
        control.command(
            f"POINTER {menu_x + 8} {menu_y + menu_border + row_height + row_height // 2}"
        )
        state = wait_state(
            control, lambda value: value["menu"]["selected"] == 1,
            "highlighted menu row",
        )
        images["menu-highlight"] = capture(control, mode_dir, "menu-highlight")
        control.command(
            f"POINTER {menu_x + 8} {menu_y + menu_border + 3 * row_height + row_height // 2}"
        )
        wait_state(control, lambda value: value["menu"]["selected"] == 3,
                   "submenu row")
        images["menu-pull"] = capture(control, mode_dir, "menu-pull")
        control.command("BUTTON 273 release")
        wait_state(
            control,
            lambda value: value["menu"] is not None and
            value["menu"]["name"] == "child",
            "child submenu",
        )
        images["submenu"] = capture(control, mode_dir, "submenu")

        report["configured_color_samples"] = {
            name: list(value) for name, value in samples.items()
        }
        report["button_states_pixel_identical"] = True
        report["title_variant_hashes"] = title_hashes
        report["icon_geometry"] = icon_view
        report["captures"] = {name: sha256(data) for name, data in images.items()}

        client_command(client, "QUIT", "QUITTING")
        client.wait(timeout=5)
        client = None
        control.command("QUIT")
        compositor.wait(timeout=5)
        if compositor.returncode != 0:
            raise RuntimeError(f"compositor exited with {compositor.returncode}")
        return report
    except Exception as error:
        if compositor.poll() is None:
            compositor.terminate()
        try:
            stdout, stderr = compositor.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            compositor.kill()
            stdout, stderr = compositor.communicate()
        (mode_dir / "session.log").write_text(
            f"error: {error}\nstdout:\n{stdout}\nstderr:\n{stderr}\n",
            encoding="utf-8",
        )
        raise
    finally:
        if client is not None and client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
        if control is not None:
            control.close()
        if compositor.poll() is None:
            compositor.terminate()
            compositor.wait(timeout=5)


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wtwm-m5-states-") as directory:
        temporary = Path(directory)
        config = temporary / "states.twmrc"
        write_config(config, arguments.asset)
        report = {
            "schema_version": 1,
            "masks": [],
            "modes": {
                mode: run_mode(arguments, config, mode, temporary)
                for mode in ("color", "grayscale", "monochrome")
            },
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.compositor = arguments.compositor.resolve(strict=True)
    arguments.client = arguments.client.resolve(strict=True)
    arguments.asset = arguments.asset.resolve(strict=True)
    run(arguments)


if __name__ == "__main__":
    main()
