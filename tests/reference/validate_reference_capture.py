#!/usr/bin/env python3

"""Validate committed reference-twm capture provenance and baselines."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path


CAPTURE_DIR = Path("reference/captures/twm-1.0.13.1")
MANIFEST_PATH = CAPTURE_DIR / "manifest.json"
BASELINE_DIR = CAPTURE_DIR / "baseline"
EXPECTED_MANIFEST_SHA256 = (
    "cdb280c96b0f429fce01ae84ed62a9ea2e0a71fa4bc41e660505d754215d2086"
)
EXPECTED_SOURCE_HASHES = {
    "reference/captures/twm-1.0.13.1/scenario.twmrc": (
        "cb71a8b832729a0455b55b286da7289ab8b09ab86b74e503c0ed3e6e2f611976"
    ),
    "reference/environment/debian-trixie-x11.json": (
        "ece237f52847ee3489050c941cc877454fd55fdcac8af5c4915c61b52d8a6c1c"
    ),
    "reference/environment/debian-trixie-x11-packages.txt": (
        "641758add2407062e248456c54ec536d2827a330b96cfc3df25ebb8f8620616e"
    ),
    "tests/reference/build_reference_twm.sh": (
        "7bd05b6f7eb902b753b19a0c32de326d4ceefec75ba2f1d0c704c4709f15713d"
    ),
    "tests/reference/capture_reference_twm.sh": (
        "678c63f70527831c04806842013cb4897e9546b0e967af72308043bddde80d63"
    ),
    "tests/reference/normalize_reference_capture.py": (
        "35284846b031f1b5e6b10e32d2f7b8cea47b02573ae2de9e9a9129a30bf25954"
    ),
    "tests/reference/reference_capture_client.c": (
        "02cb8e55ab3dd9414ee3c7d3f591f5f45247d962670be9e58a682d5dd6440471"
    ),
}
EXPECTED_ARTIFACT_HASHES = {
    "parser.json": "bc1e12ed4f8fc2c71af5e951d17578eb57945554b15f5b927211aab636ec440a",
    "phase-alpha.json": (
        "f70a39cb321ccffcdef0a43b1ecd8ba1e95085bbf4dd37784545476f70313cda"
    ),
    "phase-alpha.ppm.gz": (
        "798c10c1b831388c34850829c22dd9c5ca59665ffbe428ddc93e6309eede15a5"
    ),
    "phase-bravo.json": (
        "3a24158eec8ad7e2b1bfde918172520609c9fe2e736984dd8de1d76e620191d3"
    ),
    "phase-bravo.ppm.gz": (
        "75bd1214027efc8a9631f0ec995356410f8b5ff3329cf7c655a9b4ac5d8a9dd2"
    ),
}
EXPECTED_UNCOMPRESSED_HASHES = {
    "phase-alpha.ppm.gz": (
        "02c7bcd13f8e53dc07f9aa46a38c1341dcde66931668ec0f3270d0cc28e477e5"
    ),
    "phase-bravo.ppm.gz": (
        "1976780154cf605e478569cddda35e14ac3b5c9b126a23db09ec7da2750a06cc"
    ),
}
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
EXPECTED_WINDOWS = [
    {
        "client": {
            "border_width": 0,
            "height": 65,
            "mapped": True,
            "width": 100,
            "x": 33,
            "y": 51,
        },
        "frame": {
            "border_width": 3,
            "height": 85,
            "mapped": True,
            "width": 100,
            "x": 33,
            "y": 31,
        },
        "role": "alpha",
    },
    {
        "client": {
            "border_width": 0,
            "height": 70,
            "mapped": True,
            "width": 110,
            "x": 91,
            "y": 81,
        },
        "frame": {
            "border_width": 3,
            "height": 90,
            "mapped": True,
            "width": 110,
            "x": 91,
            "y": 61,
        },
        "role": "bravo",
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicate_keys)


def validate_parser(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["parser baseline root must be an object"]
    errors: list[str] = []
    outcome = value.get("parser_outcome")
    observations = value.get("effective_observations")
    if value.get("schema_version") != 1:
        errors.append("parser baseline schema_version must be 1")
    if not isinstance(outcome, dict):
        errors.append("parser_outcome must be an object")
    else:
        if outcome.get("status") != "accepted":
            errors.append("parser outcome must be accepted")
        if outcome.get("configuration") != "scenario.twmrc":
            errors.append("parser outcome configuration has drifted")
        expected_config_hash = EXPECTED_SOURCE_HASHES[
            "reference/captures/twm-1.0.13.1/scenario.twmrc"
        ]
        if outcome.get("configuration_sha256") != expected_config_hash:
            errors.append("parser outcome configuration hash has drifted")
        if outcome.get("diagnostics_matching_parse_errors") != []:
            errors.append("parser outcome contains parse diagnostics")
    if not isinstance(observations, dict):
        errors.append("effective_observations must be an object")
    else:
        if observations.get("coverage") != "bounded selected ScreenInfo fields":
            errors.append("effective observation scope must remain explicitly bounded")
        if observations.get("fields") != EXPECTED_EFFECTIVE:
            errors.append("bounded effective configuration observations have drifted")
        observer = observations.get("observer")
        if not isinstance(observer, str) or "detached" not in observer:
            errors.append("effective observer must record debugger detachment")
    return errors


def validate_phase(value: object, phase: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"phase {phase} baseline root must be an object"]
    errors: list[str] = []
    expected_stack = [role for role in ("alpha", "bravo") if role != phase] + [phase]
    expected_focus = {"revert_to": "PointerRoot", "target": phase}
    if value.get("schema_version") != 1:
        errors.append(f"phase {phase} schema_version must be 1")
    if value.get("phase") != phase:
        errors.append(f"phase {phase} identity has drifted")
    if value.get("screen") != {"depth": 24, "height": 180, "width": 260}:
        errors.append(f"phase {phase} screen has drifted")
    if value.get("input_focus") != expected_focus:
        errors.append(f"phase {phase} input focus has drifted")
    if value.get("root_stacking_bottom_to_top") != expected_stack:
        errors.append(f"phase {phase} root stacking has drifted")
    if value.get("windows") != EXPECTED_WINDOWS:
        errors.append(f"phase {phase} geometry has drifted")
    screenshot = value.get("screenshot")
    screenshot_name = f"phase-{phase}.ppm.gz"
    if not isinstance(screenshot, dict):
        errors.append(f"phase {phase} screenshot metadata is missing")
    else:
        expected_screenshot = {
            "encoding": "gzip -n",
            "file": screenshot_name,
            "format": "PPM P6",
            "height": 180,
            "sha256": EXPECTED_ARTIFACT_HASHES[screenshot_name],
            "width": 260,
        }
        if screenshot != expected_screenshot:
            errors.append(f"phase {phase} screenshot metadata has drifted")
    return errors


def ppm_dimensions(data: bytes) -> tuple[int, int]:
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
    position += 2 if data[position : position + 2] == b"\r\n" else 1
    if magic != b"P6" or maximum != 255:
        raise ValueError("screenshot is not an 8-bit binary PPM")
    if len(data) - position != width * height * 3:
        raise ValueError("screenshot pixel payload has the wrong size")
    return width, height


def has_volatile_key(value: object) -> bool:
    volatile_keys = {"xid", "pid", "timestamp", "temporary_path", "display_number"}
    if isinstance(value, dict):
        return any(
            key.lower() in volatile_keys or has_volatile_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(has_volatile_key(child) for child in value)
    return False


def validate(source_root: Path) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    loaded: dict[str, object] = {}
    manifest_path = source_root / MANIFEST_PATH
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = load_json(manifest_path)
    except (OSError, UnicodeError, ValueError) as error:
        return [f"cannot read capture manifest: {error}"], loaded
    loaded["manifest"] = manifest
    if sha256(manifest_bytes) != EXPECTED_MANIFEST_SHA256:
        errors.append("capture manifest bytes have drifted")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        errors.append("capture manifest schema_version must be 1")

    for relative_path, expected_hash in EXPECTED_SOURCE_HASHES.items():
        try:
            actual_hash = sha256((source_root / relative_path).read_bytes())
        except OSError as error:
            errors.append(f"cannot read capture source {relative_path}: {error}")
            continue
        if actual_hash != expected_hash:
            errors.append(f"capture source hash has drifted: {relative_path}")

    baseline_dir = source_root / BASELINE_DIR
    try:
        actual_names = sorted(path.name for path in baseline_dir.iterdir() if path.is_file())
    except OSError as error:
        errors.append(f"cannot read capture baseline directory: {error}")
        return errors, loaded
    if actual_names != sorted(EXPECTED_ARTIFACT_HASHES):
        errors.append("capture baseline file set is incomplete or has extras")

    for name, expected_hash in EXPECTED_ARTIFACT_HASHES.items():
        path = baseline_dir / name
        try:
            data = path.read_bytes()
        except OSError as error:
            errors.append(f"cannot read baseline {name}: {error}")
            continue
        if sha256(data) != expected_hash:
            errors.append(f"capture baseline hash has drifted: {name}")
        if name.endswith(".json"):
            try:
                value = load_json(path)
            except (OSError, UnicodeError, ValueError) as error:
                errors.append(f"cannot parse baseline {name}: {error}")
                continue
            loaded[name] = value
            if has_volatile_key(value):
                errors.append(f"baseline contains a volatile key: {name}")
        else:
            if len(data) < 10 or data[:2] != b"\x1f\x8b":
                errors.append(f"baseline is not gzip data: {name}")
                continue
            if data[3] & 0x08 or data[4:8] != b"\x00\x00\x00\x00":
                errors.append(f"baseline gzip header is not gzip -n normalized: {name}")
            try:
                raster = gzip.decompress(data)
                dimensions = ppm_dimensions(raster)
            except (OSError, ValueError) as error:
                errors.append(f"cannot decode baseline screenshot {name}: {error}")
                continue
            if dimensions != (260, 180):
                errors.append(f"baseline screenshot dimensions have drifted: {name}")
            if sha256(raster) != EXPECTED_UNCOMPRESSED_HASHES[name]:
                errors.append(f"uncompressed screenshot hash has drifted: {name}")

    if "parser.json" in loaded:
        errors.extend(validate_parser(loaded["parser.json"]))
    for phase in ("bravo", "alpha"):
        key = f"phase-{phase}.json"
        if key in loaded:
            errors.extend(validate_phase(loaded[key], phase))

    workflow = (source_root / ".github/workflows/build.yml").read_text(encoding="utf-8")
    baseline_marker = (
        '"$GITHUB_WORKSPACE/reference/captures/twm-1.0.13.1/baseline"'
    )
    if baseline_marker not in workflow:
        errors.append("reference workflow does not compare committed capture baselines")
    return errors, loaded


def self_test_tamper(loaded: dict[str, object]) -> list[str]:
    errors: list[str] = []
    parser_value = copy.deepcopy(loaded.get("parser.json"))
    if isinstance(parser_value, dict) and isinstance(
        parser_value.get("parser_outcome"), dict
    ):
        parser_value["parser_outcome"]["status"] = "rejected"
        if not validate_parser(parser_value):
            errors.append("tamper self-test did not reject parser outcome mutation")
    else:
        errors.append("tamper self-test could not load parser baseline")

    phase_value = copy.deepcopy(loaded.get("phase-alpha.json"))
    if isinstance(phase_value, dict):
        phase_value["input_focus"] = {"target": "None", "revert_to": "None"}
        if not validate_phase(phase_value, "alpha"):
            errors.append("tamper self-test did not reject focus mutation")
    else:
        errors.append("tamper self-test could not load alpha baseline")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    try:
        errors, loaded = validate(args.source_root.resolve())
    except (OSError, UnicodeError, ValueError) as error:
        errors = [f"capture validation failed unexpectedly: {error}"]
        loaded = {}
    if not errors and args.self_test_tamper:
        errors.extend(self_test_tamper(loaded))
    if errors:
        for error in errors:
            print(f"reference capture error: {error}")
        return 1
    print("reference capture valid: parser, 2 states, 2 screenshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
