#!/usr/bin/env python3
"""Compare live reference-twm and wtwm icon-manager structure and navigation."""

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


SCREEN = (640, 480)
REGION = (300, 260, 300, 160)
MANAGER_COLUMNS = 2
PALETTE = {
    "manager_foreground": (0x22, 0xFF, 0x44),
    "manager_background": (0x11, 0x33, 0x55),
    "manager_highlight": (0xFF, 0x00, 0xFF),
    "icon_foreground": (0xEE, 0xDD, 0xAA),
    "icon_background": (0x73, 0x31, 0x17),
    "icon_border": (0x00, 0xAA, 0xFF),
}


def wait_line(process: subprocess.Popen[str], expected: str) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if process.poll() is not None:
            break
        raise RuntimeError(f"unexpected client output: {line!r}")
    raise RuntimeError(f"timed out waiting for client output {expected!r}")


def wait_display(control: Control, marker: Path) -> str:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if marker.exists():
            display = marker.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("Xwayland DISPLAY marker was not published")


def wait_xvfb(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], deadline - time.monotonic()
        )
        if readable:
            number = process.stdout.readline().strip()
            if number.isdigit():
                return f":{number}"
            raise RuntimeError(f"Xvfb returned invalid display number {number!r}")
        if process.poll() is not None:
            break
    raise RuntimeError("Xvfb did not publish a display number")


def stop(process: subprocess.Popen[str] | None) -> tuple[str, str]:
    if process is None:
        return "", ""
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("capture is not an un-commented 8-bit P6 PPM")
    width, height = (int(value) for value in fields[1].split())
    if len(fields[3]) != width * height * 3:
        raise RuntimeError("capture payload has the wrong length")
    return width, height, fields[3]


def color_stats(
    width: int, height: int, payload: bytes, color: tuple[int, int, int]
) -> dict[str, object]:
    target = bytes(color)
    count = 0
    minimum_x = width
    minimum_y = height
    maximum_x = -1
    maximum_y = -1
    for index in range(width * height):
        if payload[index * 3:index * 3 + 3] != target:
            continue
        x = index % width
        y = index // width
        count += 1
        minimum_x = min(minimum_x, x)
        minimum_y = min(minimum_y, y)
        maximum_x = max(maximum_x, x)
        maximum_y = max(maximum_y, y)
    box = None
    if count:
        box = {
            "x": minimum_x,
            "y": minimum_y,
            "width": maximum_x - minimum_x + 1,
            "height": maximum_y - minimum_y + 1,
        }
    return {"count": count, "box": box}


def screenshot_structure(data: bytes) -> dict[str, object]:
    width, height, payload = parse_ppm(data)
    return {
        "size": [width, height],
        "sha256": hashlib.sha256(data).hexdigest(),
        "palette": {
            name: color_stats(width, height, payload, color)
            for name, color in PALETTE.items()
        },
    }


def box(summary: dict[str, object], color: str) -> dict[str, int]:
    value = summary["palette"][color]["box"]
    if not isinstance(value, dict):
        raise RuntimeError(f"screenshot omitted {color} structural pixels")
    return {key: int(value[key]) for key in ("x", "y", "width", "height")}


def validate_structure(backend: str, summary: dict[str, object]) -> None:
    if summary["size"] != list(SCREEN):
        raise RuntimeError(f"{backend} capture size changed: {summary!r}")
    manager = box(summary, "manager_background")
    icon = box(summary, "icon_background")
    if manager["x"] > 3 or manager["y"] > 3 or not (250 <= manager["width"] <= 324):
        raise RuntimeError(f"{backend} manager geometry is structurally wrong: {manager!r}")
    if not (8 <= manager["height"] <= 64):
        raise RuntimeError(f"{backend} manager row height is structurally wrong: {manager!r}")
    region_x, region_y, region_width, region_height = REGION
    center_x = icon["x"] + icon["width"] // 2
    center_y = icon["y"] + icon["height"] // 2
    if not (region_x <= center_x < region_x + region_width and
            region_y <= center_y < region_y + region_height):
        raise RuntimeError(f"{backend} icon was not placed in IconRegion: {icon!r}")
    if (center_x - region_x) // 100 != 0 or (center_y - region_y) // 80 != 0:
        raise RuntimeError(f"{backend} first icon did not take the first grid cell: {icon!r}")
    for required in ("manager_foreground", "icon_foreground", "icon_border"):
        if int(summary["palette"][required]["count"]) == 0:
            raise RuntimeError(f"{backend} capture omitted {required} pixels")


def classify_manager_pointer(
    summary: dict[str, object], pointer: dict[str, int]
) -> list[int]:
    manager = box(summary, "manager_background")
    x = int(pointer["x"])
    y = int(pointer["y"])
    if not (manager["x"] - 3 <= x < manager["x"] + manager["width"] + 3 and
            manager["y"] - 3 <= y < manager["y"] + manager["height"] + 3):
        raise RuntimeError(f"navigation missed the icon manager: {pointer!r}, {manager!r}")
    relative_x = min(max(x - manager["x"], 0), manager["width"] - 1)
    column = relative_x * MANAGER_COLUMNS // manager["width"]
    return [0, column]


def compare_structures(
    reference: dict[str, object], wtwm: dict[str, object]
) -> dict[str, object]:
    validate_structure("reference", reference)
    validate_structure("wtwm", wtwm)
    reference_manager = box(reference, "manager_background")
    wtwm_manager = box(wtwm, "manager_background")
    reference_icon = box(reference, "icon_background")
    wtwm_icon = box(wtwm, "icon_background")
    manager_delta = {
        key: abs(reference_manager[key] - wtwm_manager[key])
        for key in reference_manager
    }
    icon_center_delta = [
        abs((reference_icon[axis] + reference_icon[size] // 2) -
            (wtwm_icon[axis] + wtwm_icon[size] // 2))
        for axis, size in (("x", "width"), ("y", "height"))
    ]
    if manager_delta["x"] > 3 or manager_delta["y"] > 3:
        raise RuntimeError(f"manager origins differ: {manager_delta!r}")
    if manager_delta["width"] > 12 or manager_delta["height"] > 12:
        raise RuntimeError(f"manager extents differ beyond font tolerance: {manager_delta!r}")
    if max(icon_center_delta) > 16:
        raise RuntimeError(f"icon placement centers differ: {icon_center_delta!r}")
    ratios: dict[str, float] = {}
    for name in ("manager_background", "manager_foreground", "icon_background",
                 "icon_foreground", "icon_border"):
        expected = int(reference["palette"][name]["count"])
        actual = int(wtwm["palette"][name]["count"])
        ratio = actual / expected
        ratios[name] = round(ratio, 6)
        if not 0.4 <= ratio <= 2.5:
            raise RuntimeError(f"{name} pixel-area ratio is implausible: {ratio}")
    return {
        "manager_extent_delta": manager_delta,
        "icon_center_delta": icon_center_delta,
        "configured_pixel_area_ratios": ratios,
    }


def capture_reference_stable(
    observer: Path, environment: dict[str, str], evidence: Path
) -> tuple[bytes, dict[str, object]]:
    previous: bytes | None = None
    consecutive = 0
    deadline = time.monotonic() + 20
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        candidate = evidence / f"reference-sample-{attempt}.ppm"
        subprocess.run(
            [str(observer), "capture", str(candidate)], env=environment,
            check=True, timeout=10,
        )
        data = candidate.read_bytes()
        try:
            validate_structure("reference", screenshot_structure(data))
        except RuntimeError:
            previous = None
            consecutive = 0
            time.sleep(0.05)
            continue
        if data == previous:
            consecutive += 1
        else:
            previous = data
            consecutive = 1
        if consecutive >= 2:
            final = evidence / "reference-initial.ppm"
            final.write_bytes(data)
            for sample in evidence.glob("reference-sample-*.ppm"):
                sample.unlink()
            return data, screenshot_structure(data)
        time.sleep(0.05)
    raise RuntimeError("reference icon screenshot did not converge")


def input_event(
    driver: Path, environment: dict[str, str], *arguments: str
) -> None:
    subprocess.run([str(driver), *arguments], env=environment, check=True, timeout=10)


def observed_pointer(observer: Path, environment: dict[str, str]) -> dict[str, int]:
    result = subprocess.run(
        [str(observer), "pointer"], env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10,
    )
    value = json.loads(result.stdout)
    return {"x": int(value["x"]), "y": int(value["y"])}


def reference_navigation(
    driver: Path, observer: Path, environment: dict[str, str],
    summary: dict[str, object],
) -> list[dict[str, object]]:
    input_event(driver, environment, "pointer", "630", "470")
    destinations = []
    for key, label in (("F6", "named-bravo"), ("F2", "back-to-alpha")):
        input_event(driver, environment, "key", key, "press")
        input_event(driver, environment, "key", key, "release")
        time.sleep(0.05)
        pointer = observed_pointer(observer, environment)
        destinations.append({
            "action": label,
            "pointer": pointer,
            "cell": classify_manager_pointer(summary, pointer),
        })
    return destinations


def run_reference(arguments: argparse.Namespace, evidence: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "GDK_BACKEND": "x11"})
    xvfb = subprocess.Popen(
        ["/usr/bin/Xvfb", "-displayfd", "1", "-screen", "0", "640x480x24",
         "-nolisten", "tcp"], cwd=arguments.source_root, env=environment,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    twm: subprocess.Popen[str] | None = None
    client: subprocess.Popen[str] | None = None
    logs: list[str] = []
    try:
        environment["DISPLAY"] = wait_xvfb(xvfb)
        twm = subprocess.Popen(
            [str(arguments.reference_twm), "-display", environment["DISPLAY"],
             "-single", "-f", str(arguments.config), "-quiet"],
            cwd=arguments.source_root, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            [str(arguments.observer), "ready"], cwd=arguments.source_root,
            env=environment, check=True, timeout=15,
        )
        client = subprocess.Popen(
            [str(arguments.client)], cwd=arguments.source_root, env=environment,
            text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1,
        )
        wait_line(client, "READY")
        pixels, summary = capture_reference_stable(
            arguments.observer, environment, evidence
        )
        navigation = reference_navigation(
            arguments.input_driver, arguments.observer, environment, summary
        )
        if twm.poll() is not None:
            raise RuntimeError(f"reference twm exited with {twm.returncode}")
        return {"screenshot": summary, "navigation": navigation,
                "pixel_bytes": len(pixels)}
    finally:
        if client is not None and client.poll() is None:
            assert client.stdin is not None
            client.stdin.write("QUIT\n")
            client.stdin.flush()
            try:
                wait_line(client, "QUITTING")
            except RuntimeError:
                pass
        stdout, stderr = stop(client)
        logs.append(f"client stdout:\n{stdout}\nstderr:\n{stderr}")
        stdout, stderr = stop(twm)
        logs.append(f"twm stdout:\n{stdout}\nstderr:\n{stderr}")
        stdout, stderr = stop(xvfb)
        logs.append(f"Xvfb stdout:\n{stdout}\nstderr:\n{stderr}")
        (evidence / "reference-session.log").write_text(
            "\n".join(logs), encoding="utf-8"
        )


def wtwm_ready(state: dict[str, object]) -> bool:
    titles = {item["title"] for item in state["windows"]}
    if titles != {"Reference Alpha", "Reference Bravo"}:
        return False
    bravo = next(item for item in state["windows"] if item["title"] == "Reference Bravo")
    managers = state["icon_managers"]
    return (bool(bravo["iconified"]) and len(state["icon_views"]) == 1 and
            len(managers) == 1 and len(managers[0]["entries"]) == 2)


def wait_wtwm(control: Control) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = control.state()
        if wtwm_ready(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"wtwm icon scene did not converge: {control.state()!r}")


def wtwm_navigation(
    control: Control, summary: dict[str, object]
) -> list[dict[str, object]]:
    control.command("POINTER 630 470")
    destinations = []
    for code, label in ((64, "named-bravo"), (60, "back-to-alpha")):
        control.command(f"KEY {code} press")
        control.command(f"KEY {code} release")
        control.command("WAIT 2")
        cursor = control.state()["cursor"]
        pointer = {"x": int(float(cursor["x"])), "y": int(float(cursor["y"]))}
        destinations.append({
            "action": label,
            "pointer": pointer,
            "cell": classify_manager_pointer(summary, pointer),
        })
    return destinations


def run_wtwm(arguments: argparse.Namespace, evidence: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="wtwm-m7-icon-differential-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [str(arguments.compositor), "-f", str(arguments.config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-m7-differential-{os.getpid()}",
             "--test-backend", "headless"],
            cwd=arguments.source_root, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("SET ANIMATION_MS 0")
            control.command("OUTPUT 640 480")
            display = wait_display(control, display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(arguments.client)], cwd=arguments.source_root,
                env=client_environment, text=True, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
            )
            wait_line(client, "READY")
            state = wait_wtwm(control)
            control.command("WAIT 3")
            first = evidence / "wtwm-initial.ppm"
            repeat = temporary / "wtwm-repeat.ppm"
            control.command(f"CAPTURE {first}")
            control.command("WAIT 3")
            control.command(f"CAPTURE {repeat}")
            pixels = first.read_bytes()
            if pixels != repeat.read_bytes():
                raise RuntimeError("wtwm icon capture was not stable")
            summary = screenshot_structure(pixels)
            validate_structure("wtwm", summary)
            navigation = wtwm_navigation(control, summary)
            normalized_state = {
                "icon": state["icon_views"][0],
                "manager": state["icon_managers"][0],
                "windows": [
                    {key: item[key] for key in ("title", "iconified")}
                    for item in state["windows"]
                ],
            }
            (evidence / "wtwm-state.json").write_text(
                json.dumps(normalized_state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return {"screenshot": summary, "navigation": navigation,
                    "pixel_bytes": len(pixels)}
        finally:
            if client is not None and client.poll() is None:
                assert client.stdin is not None
                client.stdin.write("QUIT\n")
                client.stdin.flush()
                try:
                    wait_line(client, "QUITTING")
                except RuntimeError:
                    pass
            client_stdout, client_stderr = stop(client)
            if control is not None and process.poll() is None:
                try:
                    control.command("QUIT")
                except (BrokenPipeError, ConnectionError, RuntimeError):
                    process.terminate()
                control.close()
            compositor_stdout, compositor_stderr = stop(process)
            (evidence / "wtwm-session.log").write_text(
                f"client stdout:\n{client_stdout}\nclient stderr:\n{client_stderr}\n"
                f"compositor stdout:\n{compositor_stdout}\n"
                f"compositor stderr:\n{compositor_stderr}\n",
                encoding="utf-8",
            )


def synthetic_ppm(icon_x: int = 330) -> bytes:
    width, height = SCREEN
    pixels = bytearray(bytes((0x25, 0x25, 0x25)) * width * height)

    def rectangle(x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for row in range(y, y + h):
            for column in range(x, x + w):
                offset = (row * width + column) * 3
                pixels[offset:offset + 3] = bytes(color)

    rectangle(0, 0, 320, 24, PALETTE["manager_background"])
    rectangle(8, 8, 8, 4, PALETTE["manager_foreground"])
    rectangle(icon_x - 2, 278, 44, 44, PALETTE["icon_border"])
    rectangle(icon_x, 280, 40, 40, PALETTE["icon_background"])
    rectangle(icon_x + 8, 288, 8, 8, PALETTE["icon_foreground"])
    return f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(pixels)


def self_test() -> None:
    reference = screenshot_structure(synthetic_ppm())
    wtwm = screenshot_structure(synthetic_ppm())
    compare_structures(reference, wtwm)
    if classify_manager_pointer(reference, {"x": 240, "y": 12}) != [0, 1]:
        raise RuntimeError("self-test did not classify the named manager cell")
    if classify_manager_pointer(reference, {"x": 80, "y": 12}) != [0, 0]:
        raise RuntimeError("self-test did not classify backward navigation")
    tampered = screenshot_structure(synthetic_ppm(icon_x=100))
    try:
        validate_structure("tampered", tampered)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("tampered out-of-region icon passed structural validation")
    print("Milestone 7 icon differential self-test passed")


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    for path in arguments.evidence.iterdir():
        if path.is_file():
            path.unlink()
    result: dict[str, object] = {
        "schema_version": 1,
        "comparison": "live-twm-1.0.13.1-vs-wtwm-Xwayland-icons",
        "result": "failed",
    }
    try:
        version = subprocess.run(
            [str(arguments.reference_twm), "-V"], cwd=arguments.source_root,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True, timeout=10,
        ).stdout.strip()
        if version != "twm 1.0.13.1":
            raise RuntimeError(f"unexpected reference version: {version!r}")
        reference = run_reference(arguments, arguments.evidence)
        wtwm = run_wtwm(arguments, arguments.evidence)
        structural = compare_structures(reference["screenshot"], wtwm["screenshot"])
        expected_navigation = [[0, 1], [0, 0]]
        reference_cells = [item["cell"] for item in reference["navigation"]]
        wtwm_cells = [item["cell"] for item in wtwm["navigation"]]
        if reference_cells != expected_navigation or wtwm_cells != expected_navigation:
            raise RuntimeError(
                "icon-manager navigation destinations differ: "
                f"reference={reference_cells!r}, wtwm={wtwm_cells!r}"
            )
        result.update({
            "reference": reference,
            "wtwm": wtwm,
            "structural_comparison": structural,
            "navigation_cells": expected_navigation,
            "result": "equivalent",
        })
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--reference-twm", type=Path)
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--input-driver", type=Path)
    parser.add_argument("--observer", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    required = (
        "source_root", "reference_twm", "compositor", "client", "input_driver",
        "observer", "config", "output", "evidence",
    )
    missing = [name for name in required if getattr(arguments, name) is None]
    if missing:
        parser.error("missing live arguments: " + ", ".join(missing))
    for name in ("source_root", "reference_twm", "compositor", "client",
                 "input_driver", "observer", "config"):
        setattr(arguments, name, getattr(arguments, name).resolve(strict=True))
    arguments.output = arguments.output.resolve()
    arguments.evidence = arguments.evidence.resolve()
    run(arguments)


if __name__ == "__main__":
    main()
