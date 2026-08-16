#!/usr/bin/env python3
"""Run the frozen reference geometry case structure against wtwm/Xwayland."""

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
from typing import Any

from run_compositor import Control


MATRIX_PATH = Path("reference/geometry/twm-1.0.13.1/matrix.json")
REQUEST_X = 160
REQUEST_Y = 120


def wait_path(path: Path, process: subprocess.Popen[str]) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        if process.poll() is not None:
            raise RuntimeError(f"compositor exited early with {process.returncode}")
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_line(process: subprocess.Popen[str], expected: str) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], max(0, deadline - time.monotonic())
        )
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if process.poll() is not None:
            break
        raise RuntimeError(f"unexpected geometry client output: {line!r}")
    raise RuntimeError(f"timed out waiting for geometry client {expected!r}")


def wait_window(
    control: Control, case_id: str, process: subprocess.Popen[str],
    required_stable: int,
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    previous: dict[str, object] | None = None
    consecutive = 0
    while time.monotonic() < deadline:
        state = control.state()
        matches = [
            item for item in state["windows"]
            if item.get("type") == "x11" and item.get("instance") == case_id
            and item.get("mapped") is True
        ]
        if len(matches) == 1:
            current = matches[0]
            if current == previous:
                consecutive += 1
            else:
                previous = current
                consecutive = 1
            if consecutive >= required_stable:
                return current
        if len(matches) > 1:
            raise RuntimeError(f"duplicate matrix windows for {case_id}: {state!r}")
        if process.poll() is not None:
            raise RuntimeError(f"geometry client exited early with {process.returncode}")
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for matrix case {case_id}")


def expected_hint_values(profile: str) -> dict[str, int]:
    values = {
        "flags": 3,
        "min_width": 0,
        "min_height": 0,
        "max_width": 0,
        "max_height": 0,
        "base_width": 0,
        "base_height": 0,
        "width_inc": 0,
        "height_inc": 0,
        "min_aspect_num": 0,
        "min_aspect_den": 0,
        "max_aspect_num": 0,
        "max_aspect_den": 0,
        "gravity": 0,
    }
    if profile == "min-max":
        values.update({
            "flags": 3 | 16 | 32,
            "min_width": 80, "min_height": 60,
            "max_width": 240, "max_height": 180,
        })
    elif profile == "base-increment":
        values.update({
            "flags": 3 | 64 | 256,
            "base_width": 17, "base_height": 11,
            "width_inc": 10, "height_inc": 7,
        })
    elif profile == "aspect":
        values.update({
            "flags": 3 | 128,
            "min_aspect_num": 4, "min_aspect_den": 3,
            "max_aspect_num": 16, "max_aspect_den": 9,
        })
    elif profile == "complete":
        values.update({
            "flags": 3 | 16 | 32 | 64 | 128 | 256,
            "min_width": 73, "min_height": 52,
            "max_width": 263, "max_height": 187,
            "base_width": 13, "base_height": 9,
            "width_inc": 8, "height_inc": 6,
            "min_aspect_num": 4, "min_aspect_den": 3,
            "max_aspect_num": 16, "max_aspect_den": 9,
        })
    elif profile not in {"none", "position-size"}:
        raise ValueError(f"unknown hint profile: {profile}")
    return values


def normalize_window(item: dict[str, object]) -> dict[str, object]:
    x = int(item["x"])
    y = int(item["y"])
    width = int(item["width"])
    height = int(item["height"])
    border = int(item["border_width"])
    title_extent = int(item["title_height"])
    outer_width = int(item["outer_width"])
    outer_height = int(item["outer_height"])
    client_x = int(item["client_x"])
    client_y = int(item["client_y"])
    result: dict[str, object] = {
        "client_inner": {
            "x": client_x, "y": client_y, "width": width, "height": height,
        },
        "extents": {
            "left": client_x - x,
            "top": client_y - y,
            "right": x + outer_width - client_x - width,
            "bottom": y + outer_height - client_y - height,
        },
        "frame_inner": {
            "x": x + border, "y": y + border,
            "width": int(item["frame_width"]),
            "height": int(item["frame_height"]),
        },
        "frame_outer": {
            "x": x, "y": y, "width": outer_width, "height": outer_height,
        },
        "title_outer": None,
    }
    if item["decorated"] is True:
        result["title_outer"] = {
            "x": x, "y": y, "width": outer_width,
            "height": border + title_extent,
        }
    return result


def compare_case(
    case: dict[str, Any], config: dict[str, Any], item: dict[str, object]
) -> dict[str, object]:
    errors: list[str] = []
    case_id = str(case["id"])
    expected_title = bool(case["expected_title"])
    expected_border = (
        int(case["initial_border_width"])
        if config["client_border_width"] is True
        else int(config["border_width"])
    )
    width, height = (int(value) for value in case["size"])
    expected_scalars: dict[str, object] = {
        "x": REQUEST_X,
        "y": REQUEST_Y,
        "width": width,
        "height": height,
        "border_width": expected_border,
        "original_border_width": int(case["initial_border_width"]),
        "decorated": expected_title,
    }
    for key, expected in expected_scalars.items():
        if item.get(key) != expected:
            errors.append(f"{key}: expected {expected!r}, got {item.get(key)!r}")

    title_bar = int(item["title_bar_height"])
    title_extent = int(item["title_height"])
    expected_title_extent = title_bar + expected_border if expected_title else 0
    expected_geometry = {
        "title_bar_height": title_bar if expected_title else 0,
        "title_height": expected_title_extent,
        "frame_width": width,
        "frame_height": height + expected_title_extent,
        "outer_width": width + 2 * expected_border,
        "outer_height": height + expected_title_extent + 2 * expected_border,
        "content_x": expected_border,
        "content_y": expected_border + expected_title_extent,
        "client_x": REQUEST_X + expected_border,
        "client_y": REQUEST_Y + expected_border + expected_title_extent,
    }
    if expected_title and (title_bar <= 0 or title_bar % 2 != 1):
        errors.append(f"title bar height is not a positive odd value: {title_bar}")
    for key, expected in expected_geometry.items():
        if item.get(key) != expected:
            errors.append(f"{key}: expected {expected!r}, got {item.get(key)!r}")

    parent = int(item["parent"])
    if (parent != 0) != (case["kind"] == "transient"):
        errors.append(f"transient parent state is wrong: {parent}")
    expected_hints = expected_hint_values(str(case["hint_profile"]))
    hints = item.get("size_hints")
    if not isinstance(hints, dict):
        errors.append("size_hints is missing")
    else:
        actual_hints = {key: hints.get(key) for key in expected_hints}
        if actual_hints != expected_hints:
            errors.append(
                f"WM_NORMAL_HINTS changed: expected={expected_hints!r} "
                f"actual={actual_hints!r}"
            )

    normalized = normalize_window(item)
    extents = normalized["extents"]
    assert isinstance(extents, dict)
    expected_extents = {
        "left": expected_border,
        "top": expected_border + expected_title_extent,
        "right": expected_border,
        "bottom": expected_border,
    }
    if extents != expected_extents:
        errors.append(
            f"normalized extents differ: expected={expected_extents!r} "
            f"actual={extents!r}"
        )
    if (normalized["title_outer"] is not None) != expected_title:
        errors.append("normalized title presence differs from the case oracle")
    if errors:
        raise RuntimeError(f"matrix case {case_id} failed:\n" + "\n".join(errors))
    return {
        "case_id": case_id,
        "configuration": case["configuration"],
        "expected_title": expected_title,
        "hint_profile": case["hint_profile"],
        "normalized": normalized,
    }


def run_case(
    compositor_binary: Path,
    client_binary: Path,
    source_root: Path,
    case: dict[str, Any],
    config: dict[str, Any],
    run_index: int,
    case_index: int,
    stable_observations: int,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="wtwm-geometry-matrix-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        socket_name = f"wtwm-geometry-{os.getpid()}-{run_index}-{case_index}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor = subprocess.Popen(
            [
                str(compositor_binary),
                "-f", str(source_root / str(case["configuration"])),
                "-s", startup,
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
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, compositor)
            control.command("OUTPUT 640 480")
            display = wait_path(display_marker, compositor)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            width, height = case["size"]
            client = subprocess.Popen(
                [
                    str(client_binary), str(case["id"]), str(case["kind"]),
                    str(case["initial_border_width"]), str(width), str(height),
                    str(case["hint_profile"]),
                ],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            item = wait_window(
                control, str(case["id"]), client, stable_observations
            )
            observation = compare_case(case, config, item)
            assert client.stdin is not None
            client.stdin.write("QUIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                _, client_error = client.communicate()
                raise RuntimeError(f"geometry client failed: {client_error}")
            client = None
            control.command("QUIT")
            compositor.wait(timeout=5)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor returned {compositor.returncode}")
            return observation
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
                try:
                    _, client_error = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    _, client_error = client.communicate()
            raise RuntimeError(
                f"{error}\ncompositor stderr:\n{compositor_error}"
                f"\nclient stderr:\n{client_error}"
            ) from error
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
                compositor.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    matrix_path = source_root / MATRIX_PATH
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    cases = matrix["cases"]
    configurations = {
        config["path"]: config for config in matrix["configurations"]
    }
    clean_runs = int(matrix["capture"]["clean_runs"])
    stable_observations = int(matrix["capture"]["stable_observations_per_case"])
    runs: list[list[dict[str, object]]] = []
    for run_index in range(clean_runs):
        observations = []
        for case_index, case in enumerate(cases):
            observations.append(run_case(
                args.compositor.resolve(), args.client.resolve(), source_root,
                case, configurations[case["configuration"]], run_index, case_index,
                stable_observations,
            ))
        runs.append(observations)
    if any(run != runs[0] for run in runs[1:]):
        raise RuntimeError("wtwm geometry matrix differs across clean runs")
    report = {
        "cases": runs[0],
        "reference_numeric_baseline": False,
        "schema_version": 1,
        "source_matrix": {
            "path": str(MATRIX_PATH),
            "sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        },
    }
    if args.output is not None:
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wtwm geometry matrix valid: {len(runs[0])} cases, {clean_runs} clean runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
