#!/usr/bin/env python3

"""Normalize one reference-twm capture into stable audit artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


EXPECTED_EFFECTIVE = {
    "border_width": 3,
    "button_indent": 0,
    "frame_padding": 2,
    "highlight": False,
    "move_delta": 3,
    "no_defaults": True,
    "no_grab_server": True,
    "no_icon_managers": True,
    "title_button_border_width": 0,
    "title_focus": False,
    "title_font": "fixed",
    "title_padding": 2,
    "use_p_position": 1,
}
PHASES = ("bravo", "alpha")
ROLES = ("alpha", "bravo")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_effective(log_path: Path) -> dict[str, object]:
    raw: dict[str, str] = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("effective\t"):
            continue
        fields = line.split("\t", 2)
        if len(fields) != 3 or fields[1] in raw:
            raise ValueError(f"malformed or duplicate effective observation: {line!r}")
        raw[fields[1]] = fields[2]

    if set(raw) != set(EXPECTED_EFFECTIVE):
        raise ValueError(
            "effective observation fields differ: "
            f"got {sorted(raw)}, expected {sorted(EXPECTED_EFFECTIVE)}"
        )
    observed: dict[str, object] = {}
    for name, expected in EXPECTED_EFFECTIVE.items():
        value: object
        if isinstance(expected, bool):
            if raw[name] not in {"0", "1"}:
                raise ValueError(f"effective boolean {name} is {raw[name]!r}")
            value = raw[name] == "1"
        elif isinstance(expected, int):
            value = int(raw[name])
        else:
            value = raw[name]
        if value != expected:
            raise ValueError(
                f"effective observation {name} is {value!r}, expected {expected!r}"
            )
        observed[name] = value
    return observed


def geometry(values: list[str]) -> dict[str, object]:
    if len(values) != 6:
        raise ValueError(f"geometry has {len(values)} fields, expected 6")
    if values[5] != "viewable":
        raise ValueError(f"controlled window is not viewable: {values[5]!r}")
    return {
        "border_width": int(values[4]),
        "height": int(values[3]),
        "mapped": True,
        "width": int(values[2]),
        "x": int(values[0]),
        "y": int(values[1]),
    }


def parse_state(path: Path, phase: str) -> dict[str, object]:
    screen: dict[str, int] | None = None
    focus: dict[str, str] | None = None
    stacking: list[str] | None = None
    windows: dict[str, dict[str, object]] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if fields[0] == "screen" and len(fields) == 4 and screen is None:
            screen = {
                "depth": int(fields[3]),
                "height": int(fields[2]),
                "width": int(fields[1]),
            }
        elif fields[0] == "focus" and len(fields) == 3 and focus is None:
            if fields[1] not in {*ROLES, "PointerRoot", "None"}:
                raise ValueError(f"unrecognized input-focus window: {fields[1]!r}")
            if fields[2] not in {"PointerRoot", "Parent", "None"}:
                raise ValueError(f"unrecognized focus revert mode: {fields[2]!r}")
            focus = {"target": fields[1], "revert_to": fields[2]}
        elif fields[0] == "stack" and len(fields) == 3 and stacking is None:
            stacking = fields[1:]
        elif fields[0] == "window" and len(fields) == 16:
            role = fields[1]
            if role not in ROLES or role in windows:
                raise ValueError(f"unknown or duplicate controlled role: {role!r}")
            if fields[2] != "client" or fields[9] != "frame":
                raise ValueError(f"malformed controlled-window record: {line!r}")
            windows[role] = {
                "client": geometry(fields[3:9]),
                "frame": geometry(fields[10:16]),
            }
        else:
            raise ValueError(f"malformed or duplicate state record: {line!r}")

    if screen != {"depth": 24, "height": 180, "width": 260}:
        raise ValueError(f"unexpected screen geometry: {screen!r}")
    if focus is None or focus["target"] != phase:
        raise ValueError(f"phase {phase} has unexpected input focus: {focus!r}")
    expected_stack = [role for role in ROLES if role != phase] + [phase]
    if stacking != expected_stack:
        raise ValueError(
            f"phase {phase} stacking is {stacking!r}, expected {expected_stack!r}"
        )
    if set(windows) != set(ROLES):
        raise ValueError(f"controlled window set is incomplete: {sorted(windows)}")

    return {
        "input_focus": focus,
        "phase": phase,
        "root_stacking_bottom_to_top": stacking,
        "screen": screen,
        "windows": [
            {"role": role, **windows[role]}
            for role in ROLES
        ],
    }


def ppm_dimensions(compressed_path: Path) -> tuple[int, int]:
    data = gzip.decompress(compressed_path.read_bytes())
    position = 0

    def token() -> bytes:
        nonlocal position
        while position < len(data):
            if data[position : position + 1] == b"#":
                newline = data.find(b"\n", position)
                if newline < 0:
                    raise ValueError("unterminated PPM comment")
                position = newline + 1
            elif data[position : position + 1].isspace():
                position += 1
            else:
                break
        start = position
        while position < len(data) and not data[position : position + 1].isspace():
            position += 1
        if start == position:
            raise ValueError("truncated PPM header")
        return data[start:position]

    magic = token()
    width = int(token())
    height = int(token())
    maximum = int(token())
    if position >= len(data) or not data[position : position + 1].isspace():
        raise ValueError("PPM header has no raster separator")
    if data[position : position + 2] == b"\r\n":
        position += 2
    else:
        position += 1
    if magic != b"P6" or maximum != 255:
        raise ValueError("screenshot is not an 8-bit binary PPM")
    if len(data) - position != width * height * 3:
        raise ValueError("screenshot pixel payload has the wrong size")
    return width, height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gdb-log", type=Path, required=True)
    parser.add_argument("--twm-log", type=Path, required=True)
    parser.add_argument("--bravo-state", type=Path, required=True)
    parser.add_argument("--bravo-screenshot", type=Path, required=True)
    parser.add_argument("--alpha-state", type=Path, required=True)
    parser.add_argument("--alpha-screenshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    config_bytes = args.config.read_bytes()
    twm_log = args.twm_log.read_text(encoding="utf-8", errors="replace")
    parse_error_markers = (
        "errors found in twm",
        "unable to open twmrc",
        "syntax error",
    )
    if any(marker in twm_log.lower() for marker in parse_error_markers):
        raise ValueError(f"reference twm emitted parse diagnostics: {twm_log!r}")

    effective = parse_effective(args.gdb_log)
    parser_artifact = {
        "effective_observations": {
            "coverage": "bounded selected ScreenInfo fields",
            "fields": effective,
            "observer": (
                "GDB breakpoint at assign_var_savecolor immediately after "
                "ParseTwmrc; exact binary detached and continued unmodified"
            ),
        },
        "parser_outcome": {
            "configuration": "scenario.twmrc",
            "configuration_sha256": sha256(config_bytes),
            "diagnostics_matching_parse_errors": [],
            "method": (
                "reference twm launched with -f scenario.twmrc, reached the "
                "post-ParseTwmrc observer, detached, and remained running"
            ),
            "status": "accepted",
        },
        "schema_version": 1,
    }
    write_json(args.output_dir / "parser.json", parser_artifact)

    state_paths = {"bravo": args.bravo_state, "alpha": args.alpha_state}
    screenshot_paths = {
        "bravo": args.bravo_screenshot,
        "alpha": args.alpha_screenshot,
    }
    for phase in PHASES:
        state = parse_state(state_paths[phase], phase)
        screenshot_bytes = screenshot_paths[phase].read_bytes()
        width, height = ppm_dimensions(screenshot_paths[phase])
        if (width, height) != (260, 180):
            raise ValueError(
                f"phase {phase} screenshot is {width}x{height}, expected 260x180"
            )
        state["schema_version"] = 1
        state["screenshot"] = {
            "encoding": "gzip -n",
            "file": f"phase-{phase}.ppm.gz",
            "format": "PPM P6",
            "height": height,
            "sha256": sha256(screenshot_bytes),
            "width": width,
        }
        write_json(args.output_dir / f"phase-{phase}.json", state)
        (args.output_dir / f"phase-{phase}.ppm.gz").write_bytes(screenshot_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
