#!/usr/bin/env python3
"""Capture normalized frame geometry from the frozen reference twm."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any


PARSE_ERROR_MARKERS = (
    "errors found in twm",
    "unable to open twmrc",
    "syntax error",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


def stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def wait_for_x11(display: str, xvfb: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ["xdpyinfo", "-display", display],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            return
        if xvfb.poll() is not None:
            stdout, stderr = xvfb.communicate()
            raise RuntimeError(f"Xvfb exited during startup:\n{stdout}\n{stderr}")
        time.sleep(0.01)
    raise RuntimeError(f"Xvfb did not become ready on {display}")


def parse_bool(value: str, field: str) -> bool:
    if value not in {"0", "1"}:
        raise ValueError(f"{field} is not a normalized boolean: {value!r}")
    return value == "1"


def parse_geometry(fields: list[str], label: str) -> dict[str, object]:
    if len(fields) != 7 or fields[0] != label or fields[6] != "viewable":
        raise ValueError(f"malformed {label} geometry: {fields!r}")
    x, y, width, height, border = (int(value) for value in fields[1:6])
    if width <= 0 or height <= 0 or border < 0:
        raise ValueError(f"invalid {label} dimensions: {fields!r}")
    inner = {"height": height, "width": width, "x": x, "y": y}
    outer = {
        "height": height + 2 * border,
        "width": width + 2 * border,
        "x": x - border,
        "y": y - border,
    }
    return {
        "border_width": border,
        "inner": inner,
        "mapped": True,
        "outer": outer,
    }


def optional_size(enabled: bool, width: int, height: int) -> object:
    return {"height": height, "width": width} if enabled else None


def parse_hints(fields: list[str]) -> dict[str, object]:
    if len(fields) != 21 or fields[0] != "hints":
        raise ValueError(f"malformed WM_NORMAL_HINTS record: {fields!r}")
    values = [int(value) for value in fields[1:]]
    has_min = parse_bool(fields[3], "minimum-size presence")
    has_max = parse_bool(fields[6], "maximum-size presence")
    has_base = parse_bool(fields[9], "base-size presence")
    has_increment = parse_bool(fields[12], "resize-increment presence")
    has_aspect = parse_bool(fields[15], "aspect-ratio presence")
    aspect: object = None
    if has_aspect:
        aspect = {
            "maximum": {"denominator": values[18], "numerator": values[17]},
            "minimum": {"denominator": values[16], "numerator": values[15]},
        }
    return {
        "aspect_ratio": aspect,
        "base_size": optional_size(has_base, values[9], values[10]),
        "maximum_size": optional_size(has_max, values[6], values[7]),
        "minimum_size": optional_size(has_min, values[3], values[4]),
        "resize_increment": optional_size(has_increment, values[12], values[13]),
        "user_position": parse_bool(fields[1], "user-position presence"),
        "user_size": parse_bool(fields[2], "user-size presence"),
        "window_gravity": parse_bool(fields[20], "window-gravity presence"),
    }


def parse_client_output(text: str, expected_case: str) -> dict[str, object]:
    records: dict[str, list[str]] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if not fields or fields[0] in records:
            raise ValueError(f"duplicate or empty observer record: {line!r}")
        records[fields[0]] = fields
    if set(records) != {
        "screen", "case", "kind", "request", "transient",
        "client", "frame", "title", "hints",
    }:
        raise ValueError(f"observer record set is incomplete: {sorted(records)}")
    if records["case"] != ["case", expected_case]:
        raise ValueError(f"observer returned the wrong case: {records['case']!r}")
    screen_fields = records["screen"]
    if len(screen_fields) != 4:
        raise ValueError(f"malformed screen record: {screen_fields!r}")
    screen = {
        "depth": int(screen_fields[3]),
        "height": int(screen_fields[2]),
        "width": int(screen_fields[1]),
    }
    kind_fields = records["kind"]
    transient_fields = records["transient"]
    request_fields = records["request"]
    if len(kind_fields) != 2 or kind_fields[1] not in {"normal", "transient"}:
        raise ValueError(f"malformed client-kind record: {kind_fields!r}")
    if transient_fields not in (["transient", "false"], ["transient", "true"]):
        raise ValueError(f"malformed transient record: {transient_fields!r}")
    if len(request_fields) != 6:
        raise ValueError(f"malformed request record: {request_fields!r}")
    client = parse_geometry(records["client"], "client")
    frame = parse_geometry(records["frame"], "frame")
    title_fields = records["title"]
    title = None
    if title_fields != ["title", "absent"]:
        title = parse_geometry(title_fields, "title")

    client_inner = client["inner"]
    frame_outer = frame["outer"]
    assert isinstance(client_inner, dict) and isinstance(frame_outer, dict)
    extents = {
        "bottom": (
            int(frame_outer["y"]) + int(frame_outer["height"])
            - int(client_inner["y"]) - int(client_inner["height"])
        ),
        "left": int(client_inner["x"]) - int(frame_outer["x"]),
        "right": (
            int(frame_outer["x"]) + int(frame_outer["width"])
            - int(client_inner["x"]) - int(client_inner["width"])
        ),
        "top": int(client_inner["y"]) - int(frame_outer["y"]),
    }
    return {
        "client": client,
        "extents": extents,
        "frame": frame,
        "kind": kind_fields[1],
        "normal_hints": parse_hints(records["hints"]),
        "request": {
            "border_width": int(request_fields[5]),
            "height": int(request_fields[4]),
            "width": int(request_fields[3]),
            "x": int(request_fields[1]),
            "y": int(request_fields[2]),
        },
        "screen": screen,
        "title": title,
        "transient_for_owner": transient_fields[1] == "true",
    }


def capture_case(
    reference_twm: Path,
    client: Path,
    source_root: Path,
    case: dict[str, Any],
    display_number: int,
    expected_screen: dict[str, object],
) -> dict[str, object]:
    display = f":{display_number}"
    environment = os.environ.copy()
    environment["DISPLAY"] = display
    width = int(expected_screen["width"])
    height = int(expected_screen["height"])
    depth = int(expected_screen["depth"])

    with tempfile.TemporaryDirectory(prefix="wtwm-geometry-case-"):
        xvfb = subprocess.Popen(
            [
                "Xvfb", display, "-screen", "0", f"{width}x{height}x{depth}",
                "-nolisten", "tcp",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        twm: subprocess.Popen[str] | None = None
        try:
            wait_for_x11(display, xvfb)
            config = source_root / str(case["configuration"])
            twm = subprocess.Popen(
                [
                    str(reference_twm), "-display", display, "-single",
                    "-f", str(config), "-quiet",
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            size = case["size"]
            assert isinstance(size, list)
            title_mode = "title" if case["expected_title"] else "no-title"
            completed = subprocess.run(
                [
                    str(client), str(case["id"]), str(case["kind"]),
                    str(case["initial_border_width"]), str(size[0]), str(size[1]),
                    str(case["hint_profile"]), title_mode,
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"case {case['id']} observer failed ({completed.returncode}):\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
            observation = parse_client_output(completed.stdout, str(case["id"]))
            if observation["screen"] != expected_screen:
                raise RuntimeError(
                    f"case {case['id']} screen differs: {observation['screen']!r}"
                )
            if twm.poll() is not None:
                twm_stdout, twm_stderr = twm.communicate()
                raise RuntimeError(
                    f"reference twm exited during case {case['id']}:\n"
                    f"stdout:\n{twm_stdout}\nstderr:\n{twm_stderr}"
                )
            return observation
        finally:
            twm_stdout = ""
            twm_stderr = ""
            if twm is not None:
                twm_stdout, twm_stderr = stop_process(twm)
            stop_process(xvfb)
            diagnostics = (twm_stdout + "\n" + twm_stderr).lower()
            if any(marker in diagnostics for marker in PARSE_ERROR_MARKERS):
                raise RuntimeError(
                    f"reference twm emitted parse diagnostics for {case['id']}:\n"
                    f"{twm_stdout}\n{twm_stderr}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-twm", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--display-base", type=int, required=True)
    args = parser.parse_args()

    matrix_path = args.source_root / "reference/geometry/twm-1.0.13.1/matrix.json"
    matrix = load_json(matrix_path)
    if not isinstance(matrix, dict):
        raise ValueError("geometry matrix root must be an object")
    cases = matrix.get("cases")
    configurations = matrix.get("configurations")
    expected_screen = matrix.get("screen")
    if not isinstance(cases, list) or not isinstance(configurations, list):
        raise ValueError("geometry matrix cases or configurations are missing")
    if not isinstance(expected_screen, dict):
        raise ValueError("geometry matrix screen is missing")
    config_by_path = {
        str(config["path"]): config
        for config in configurations
        if isinstance(config, dict) and "path" in config
    }
    observations: list[dict[str, object]] = []
    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, dict):
            raise ValueError("geometry matrix case must be an object")
        case: dict[str, Any] = raw_case
        config_path = str(case["configuration"])
        if config_path not in config_by_path:
            raise ValueError(f"case references unknown configuration: {config_path}")
        observation = capture_case(
            args.reference_twm,
            args.client,
            args.source_root,
            case,
            args.display_base + index,
            expected_screen,
        )
        observations.append(
            {
                "case_id": case["id"],
                "configuration": config_by_path[config_path],
                "expected_title": case["expected_title"],
                "hint_profile": case["hint_profile"],
                "observation": observation,
            }
        )

    output = {
        "cases": observations,
        "environment": matrix["environment"],
        "reference": matrix["reference"],
        "schema_version": 1,
        "screen": expected_screen,
        "source_matrix": {
            "path": "reference/geometry/twm-1.0.13.1/matrix.json",
            "sha256": sha256(matrix_path.read_bytes()),
        },
    }
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
