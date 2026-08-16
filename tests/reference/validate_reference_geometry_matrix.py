#!/usr/bin/env python3
"""Validate the offline contract and optional live reference geometry matrix."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


MATRIX_PATH = Path("reference/geometry/twm-1.0.13.1/matrix.json")
EXPECTED_CASE_IDS = [
    "normal-default-decoration",
    "normal-client-border-ignored",
    "normal-client-border-preserved-on-frame",
    "normal-no-title",
    "make-title",
    "transient-default-no-title",
    "transient-decorated",
    "compact-fixed-font",
    "spacious-9x15-font",
    "hints-min-max",
    "hints-base-increment",
    "hints-complete-aspect",
]
EXPECTED_CONFIG_MARKERS = {
    "default-variable.twmrc": ("BorderWidth 2", "FramePadding 2", "TitleFont \"variable\""),
    "client-border.twmrc": ("ClientBorderWidth", "BorderWidth 2"),
    "no-title.twmrc": ("NoTitle", "BorderWidth 2"),
    "make-title.twmrc": ("NoTitle", "MakeTitle { \"make-title\" }"),
    "decorate-transients.twmrc": ("DecorateTransients", "BorderWidth 2"),
    "compact-fixed.twmrc": ("BorderWidth 0", "FramePadding 0", "TitleFont \"fixed\""),
    "spacious-9x15.twmrc": ("BorderWidth 5", "FramePadding 4", "TitleFont \"9x15\""),
}
VOLATILE_KEYS = {"display_number", "pid", "timestamp", "xid"}


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


def has_volatile_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in VOLATILE_KEYS or has_volatile_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(has_volatile_key(child) for child in value)
    return False


def validate_wiring_text(workflow: str, meson: str) -> list[str]:
    errors: list[str] = []
    reference_job_start = workflow.find("  reference-twm:\n")
    next_job_start = workflow.find("\n  x11-differential:\n", reference_job_start)
    reference_job = (
        workflow[reference_job_start:next_job_start]
        if reference_job_start >= 0 and next_job_start > reference_job_start else ""
    )
    for marker in (
        "tests/reference/capture_reference_geometry_matrix.sh",
        '"$GITHUB_WORKSPACE" /tmp/reference-build /tmp/reference-geometry-matrix',
        "name: reference-geometry-matrix",
        "path: /tmp/reference-geometry-matrix",
        "if: always()",
        "if-no-files-found: error",
    ):
        if marker not in reference_job:
            errors.append(f"reference-twm CI job lacks geometry marker {marker!r}")
    for forbidden in ("continue-on-error", "|| true"):
        if forbidden in reference_job:
            errors.append(f"reference geometry CI contains forbidden fallback {forbidden!r}")
    for marker in (
        "'reference geometry matrix contract'",
        "tests/reference/validate_reference_geometry_matrix.py",
        "'--self-test-tamper'",
    ):
        if marker not in meson:
            errors.append(f"Meson geometry contract test lacks {marker!r}")
    return errors


def validate_wiring(source_root: Path) -> list[str]:
    try:
        workflow = (source_root / ".github/workflows/build.yml").read_text(encoding="utf-8")
        meson = (source_root / "meson.build").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"cannot read geometry matrix CI/Meson wiring: {error}"]
    return validate_wiring_text(workflow, meson)


def validate_matrix(matrix: object, source_root: Path) -> list[str]:
    if not isinstance(matrix, dict):
        return ["geometry matrix root must be an object"]
    errors: list[str] = []
    if matrix.get("schema_version") != 1:
        errors.append("geometry matrix schema_version must be 1")
    if matrix.get("reference") != {
        "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
        "archive_sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
        "name": "X.Org twm",
        "version": "1.0.13.1",
    }:
        errors.append("geometry matrix does not pin the frozen twm release")
    if matrix.get("environment") != {
        "contract": "reference/environment/debian-trixie-x11.json",
        "contract_sha256": "c65424ca2533d36780bf59d3c3392d3d967086cecf179cc49d191aae38ef7d29",
        "packages": "reference/environment/debian-trixie-x11-packages.txt",
        "packages_sha256": "3a6ad091fee1752c507e8c593b23d3e700c62710a425c50bbe44faa9187ea7f7",
    }:
        errors.append("geometry matrix does not pin the Debian Trixie X11 environment")
    for path_text, expected_hash in (
        (
            "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
            "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
        ),
        (
            "reference/environment/debian-trixie-x11.json",
            "c65424ca2533d36780bf59d3c3392d3d967086cecf179cc49d191aae38ef7d29",
        ),
        (
            "reference/environment/debian-trixie-x11-packages.txt",
            "3a6ad091fee1752c507e8c593b23d3e700c62710a425c50bbe44faa9187ea7f7",
        ),
    ):
        try:
            actual_hash = sha256((source_root / path_text).read_bytes())
        except OSError as error:
            errors.append(f"cannot read pinned geometry input {path_text}: {error}")
            continue
        if actual_hash != expected_hash:
            errors.append(f"pinned geometry input hash has drifted: {path_text}")
    if matrix.get("screen") != {"depth": 24, "height": 480, "width": 640}:
        errors.append("geometry matrix screen profile has drifted")
    capture = matrix.get("capture")
    if not isinstance(capture, dict):
        errors.append("geometry matrix capture policy is missing")
    else:
        if capture.get("clean_runs") != 2:
            errors.append("geometry matrix must compare two clean live runs")
        if capture.get("stable_observations_per_case") != 3:
            errors.append("each geometry case must converge for three observations")
        if capture.get("committed_baseline") is not False:
            errors.append("unbootstrapped geometry results must not claim a committed baseline")
        if capture.get("live_artifact") != "geometry-matrix.json":
            errors.append("geometry matrix live artifact name has drifted")
        if capture.get("volatile_fields_omitted") != sorted(VOLATILE_KEYS):
            errors.append("geometry matrix volatile-field policy is incomplete")

    raw_configs = matrix.get("configurations")
    configs: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_configs, list):
        errors.append("geometry matrix configurations must be an array")
    else:
        for config in raw_configs:
            if not isinstance(config, dict) or not isinstance(config.get("path"), str):
                errors.append("geometry matrix configuration is malformed")
                continue
            path_text = config["path"]
            if path_text in configs:
                errors.append(f"duplicate geometry configuration: {path_text}")
                continue
            configs[path_text] = config
            path = source_root / path_text
            try:
                data = path.read_bytes()
                text = data.decode("utf-8")
            except (OSError, UnicodeError) as error:
                errors.append(f"cannot read geometry configuration {path_text}: {error}")
                continue
            if config.get("sha256") != sha256(data):
                errors.append(f"geometry configuration hash has drifted: {path_text}")
            markers = EXPECTED_CONFIG_MARKERS.get(path.name)
            if markers is None:
                errors.append(f"unexpected geometry configuration: {path.name}")
            elif any(marker not in text for marker in markers):
                errors.append(f"geometry configuration semantics have drifted: {path.name}")
    if {Path(path).name for path in configs} != set(EXPECTED_CONFIG_MARKERS):
        errors.append("geometry configuration file set is incomplete or has extras")

    raw_cases = matrix.get("cases")
    cases: list[dict[str, Any]] = []
    if not isinstance(raw_cases, list):
        errors.append("geometry matrix cases must be an array")
    else:
        cases = [case for case in raw_cases if isinstance(case, dict)]
        if len(cases) != len(raw_cases):
            errors.append("geometry matrix contains a malformed case")
        ids = [case.get("id") for case in cases]
        if ids != EXPECTED_CASE_IDS:
            errors.append("geometry matrix case identities or order have drifted")
        for case in cases:
            case_id = case.get("id", "<unknown>")
            if case.get("configuration") not in configs:
                errors.append(f"case {case_id} references an unknown configuration")
            if case.get("kind") not in {"normal", "transient"}:
                errors.append(f"case {case_id} has an invalid kind")
            if not isinstance(case.get("expected_title"), bool):
                errors.append(f"case {case_id} lacks an expected title state")
            if case.get("hint_profile") not in {
                "position-size", "min-max", "base-increment", "complete"
            }:
                errors.append(f"case {case_id} has an invalid hint profile")
            border = case.get("initial_border_width")
            size = case.get("size")
            if not isinstance(border, int) or isinstance(border, bool) or border < 0:
                errors.append(f"case {case_id} has an invalid initial border")
            if (
                not isinstance(size, list) or len(size) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
                       for value in size)
            ):
                errors.append(f"case {case_id} has an invalid client size")

    by_id = {str(case.get("id")): case for case in cases}
    coverage_expectations = {
        "normal-default-decoration": ("normal", True, 0),
        "normal-client-border-ignored": ("normal", True, 4),
        "normal-client-border-preserved-on-frame": ("normal", True, 4),
        "normal-no-title": ("normal", False, 0),
        "make-title": ("normal", True, 0),
        "transient-default-no-title": ("transient", False, 0),
        "transient-decorated": ("transient", True, 0),
    }
    for case_id, expected in coverage_expectations.items():
        case = by_id.get(case_id, {})
        actual = (
            case.get("kind"), case.get("expected_title"),
            case.get("initial_border_width"),
        )
        if actual != expected:
            errors.append(f"required geometry coverage case has drifted: {case_id}")
    preserved = by_id.get("normal-client-border-preserved-on-frame", {})
    ignored = by_id.get("normal-client-border-ignored", {})
    preserved_config = configs.get(str(preserved.get("configuration")), {})
    ignored_config = configs.get(str(ignored.get("configuration")), {})
    if preserved_config.get("client_border_width") is not True:
        errors.append("ClientBorderWidth preservation case does not enable the directive")
    if ignored_config.get("client_border_width") is not False:
        errors.append("client-border control case unexpectedly enables ClientBorderWidth")
    transient_plain = by_id.get("transient-default-no-title", {})
    transient_decorated = by_id.get("transient-decorated", {})
    plain_config = configs.get(str(transient_plain.get("configuration")), {})
    decorated_config = configs.get(str(transient_decorated.get("configuration")), {})
    if plain_config.get("decorate_transients") is not False:
        errors.append("default transient case unexpectedly enables DecorateTransients")
    if decorated_config.get("decorate_transients") is not True:
        errors.append("decorated transient case does not enable DecorateTransients")
    geometry_profiles = {
        (
            config.get("border_width"), config.get("frame_padding"),
            config.get("title_padding"), config.get("title_font"),
        )
        for config in configs.values()
    }
    fonts = {config.get("title_font") for config in configs.values()}
    if len(geometry_profiles) < 3 or not {"variable", "fixed", "9x15"} <= fonts:
        errors.append("geometry matrix lacks three distinct padding/border/font profiles")
    hint_profiles = {case.get("hint_profile") for case in cases}
    if hint_profiles != {"position-size", "min-max", "base-increment", "complete"}:
        errors.append("geometry matrix does not cover every declared size-hint profile")

    sources = matrix.get("observer_sources")
    if not isinstance(sources, list):
        errors.append("geometry matrix observer source inventory is missing")
    else:
        expected_sources = {
            "tests/reference/geometry_matrix_client.c",
            "tests/reference/run_reference_geometry_matrix.py",
            "tests/reference/capture_reference_geometry_matrix.sh",
        }
        actual_sources = {
            source.get("path") for source in sources if isinstance(source, dict)
        }
        if actual_sources != expected_sources or len(sources) != len(expected_sources):
            errors.append("geometry matrix observer source inventory has drifted")
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("path"), str):
                continue
            path = source_root / source["path"]
            try:
                actual_hash = sha256(path.read_bytes())
            except OSError as error:
                errors.append(f"cannot read geometry observer source {source['path']}: {error}")
                continue
            if source.get("sha256") != actual_hash:
                errors.append(f"geometry observer source hash has drifted: {source['path']}")
    return errors


def expected_hints(profile: str) -> dict[str, object]:
    result: dict[str, object] = {
        "aspect_ratio": None,
        "base_size": None,
        "maximum_size": None,
        "minimum_size": None,
        "resize_increment": None,
        "user_position": True,
        "user_size": True,
        "window_gravity": False,
    }
    if profile == "min-max":
        result["minimum_size"] = {"height": 60, "width": 80}
        result["maximum_size"] = {"height": 180, "width": 240}
    elif profile == "base-increment":
        result["base_size"] = {"height": 11, "width": 17}
        result["resize_increment"] = {"height": 7, "width": 10}
    elif profile == "complete":
        result["minimum_size"] = {"height": 52, "width": 73}
        result["maximum_size"] = {"height": 187, "width": 263}
        result["base_size"] = {"height": 9, "width": 13}
        result["resize_increment"] = {"height": 6, "width": 8}
        result["aspect_ratio"] = {
            "maximum": {"denominator": 9, "numerator": 16},
            "minimum": {"denominator": 3, "numerator": 4},
        }
    return result


def validate_rectangle(rectangle: object, label: str) -> list[str]:
    if not isinstance(rectangle, dict) or set(rectangle) != {"x", "y", "width", "height"}:
        return [f"{label} rectangle is malformed"]
    if any(not isinstance(rectangle[key], int) or isinstance(rectangle[key], bool)
           for key in rectangle):
        return [f"{label} rectangle has a non-integer coordinate"]
    if rectangle["width"] <= 0 or rectangle["height"] <= 0:
        return [f"{label} rectangle has a non-positive dimension"]
    return []


def validate_geometry(geometry: object, label: str) -> list[str]:
    if not isinstance(geometry, dict) or set(geometry) != {
        "border_width", "inner", "mapped", "outer"
    }:
        return [f"{label} geometry is malformed"]
    errors = validate_rectangle(geometry.get("inner"), f"{label} inner")
    errors += validate_rectangle(geometry.get("outer"), f"{label} outer")
    border = geometry.get("border_width")
    if not isinstance(border, int) or isinstance(border, bool) or border < 0:
        errors.append(f"{label} border width is invalid")
    if geometry.get("mapped") is not True:
        errors.append(f"{label} must be viewable")
    if not errors:
        inner = geometry["inner"]
        outer = geometry["outer"]
        assert isinstance(inner, dict) and isinstance(outer, dict)
        expected_outer = {
            "height": inner["height"] + 2 * border,
            "width": inner["width"] + 2 * border,
            "x": inner["x"] - border,
            "y": inner["y"] - border,
        }
        if outer != expected_outer:
            errors.append(f"{label} inner/outer border arithmetic is inconsistent")
    return errors


def validate_capture(capture: object, matrix: dict[str, Any], matrix_hash: str) -> list[str]:
    if not isinstance(capture, dict):
        return ["live geometry capture root must be an object"]
    errors: list[str] = []
    if capture.get("schema_version") != 1:
        errors.append("live geometry capture schema_version must be 1")
    for key in ("reference", "environment", "screen"):
        if capture.get(key) != matrix.get(key):
            errors.append(f"live geometry capture {key} differs from the contract")
    if capture.get("source_matrix") != {
        "path": str(MATRIX_PATH), "sha256": matrix_hash
    }:
        errors.append("live geometry capture does not identify the exact matrix")
    if has_volatile_key(capture):
        errors.append("live geometry capture contains a volatile key")

    configs = {
        config["path"]: config for config in matrix["configurations"]
        if isinstance(config, dict) and "path" in config
    }
    cases = matrix.get("cases", [])
    captured_cases = capture.get("cases")
    if not isinstance(captured_cases, list):
        return errors + ["live geometry capture cases must be an array"]
    if [item.get("case_id") for item in captured_cases if isinstance(item, dict)] != [
        case.get("id") for case in cases if isinstance(case, dict)
    ] or len(captured_cases) != len(cases):
        errors.append("live geometry capture case identities or order differ")
        return errors

    for case, captured in zip(cases, captured_cases):
        case_id = str(case["id"])
        if not isinstance(captured, dict):
            errors.append(f"capture case {case_id} is malformed")
            continue
        config = configs[case["configuration"]]
        if captured.get("configuration") != config:
            errors.append(f"capture case {case_id} configuration differs")
        if captured.get("expected_title") is not case["expected_title"]:
            errors.append(f"capture case {case_id} expected-title state differs")
        if captured.get("hint_profile") != case["hint_profile"]:
            errors.append(f"capture case {case_id} hint profile differs")
        observation = captured.get("observation")
        if not isinstance(observation, dict):
            errors.append(f"capture case {case_id} observation is missing")
            continue
        if observation.get("screen") != matrix["screen"]:
            errors.append(f"capture case {case_id} screen differs")
        if observation.get("kind") != case["kind"]:
            errors.append(f"capture case {case_id} kind differs")
        expected_transient = case["kind"] == "transient"
        if observation.get("transient_for_owner") is not expected_transient:
            errors.append(f"capture case {case_id} transient relationship differs")
        size = case["size"]
        expected_request = {
            "border_width": case["initial_border_width"],
            "height": size[1], "width": size[0], "x": 160, "y": 120,
        }
        if observation.get("request") != expected_request:
            errors.append(f"capture case {case_id} request differs")
        if observation.get("normal_hints") != expected_hints(case["hint_profile"]):
            errors.append(f"capture case {case_id} WM_NORMAL_HINTS differ")

        client = observation.get("client")
        frame = observation.get("frame")
        title = observation.get("title")
        errors += validate_geometry(client, f"capture case {case_id} client")
        errors += validate_geometry(frame, f"capture case {case_id} frame")
        if not isinstance(client, dict) or not isinstance(frame, dict):
            continue
        if client.get("border_width") != 0:
            errors.append(f"capture case {case_id} client border was not transferred")
        expected_frame_border = (
            case["initial_border_width"]
            if config["client_border_width"] else config["border_width"]
        )
        if frame.get("border_width") != expected_frame_border:
            errors.append(f"capture case {case_id} frame border differs")
        if case["expected_title"]:
            errors += validate_geometry(title, f"capture case {case_id} title")
            if not isinstance(title, dict):
                continue
            if title.get("border_width") != expected_frame_border:
                errors.append(f"capture case {case_id} title border differs")
            title_outer = title.get("outer")
            frame_outer = frame.get("outer")
            if (
                not isinstance(title_outer, dict) or not isinstance(frame_outer, dict)
                or any(title_outer.get(key) != frame_outer.get(key)
                       for key in ("x", "y", "width"))
            ):
                errors.append(f"capture case {case_id} title does not span frame top")
        elif title is not None:
            errors.append(f"capture case {case_id} unexpectedly has a title")

        client_inner = client.get("inner")
        frame_outer = frame.get("outer")
        extents = observation.get("extents")
        if not isinstance(client_inner, dict) or not isinstance(frame_outer, dict):
            continue
        calculated_extents = {
            "bottom": (
                frame_outer["y"] + frame_outer["height"]
                - client_inner["y"] - client_inner["height"]
            ),
            "left": client_inner["x"] - frame_outer["x"],
            "right": (
                frame_outer["x"] + frame_outer["width"]
                - client_inner["x"] - client_inner["width"]
            ),
            "top": client_inner["y"] - frame_outer["y"],
        }
        if extents != calculated_extents:
            errors.append(f"capture case {case_id} extents are not derived from geometry")
        if (
            calculated_extents["left"] != expected_frame_border
            or calculated_extents["right"] != expected_frame_border
            or calculated_extents["bottom"] != expected_frame_border
        ):
            errors.append(f"capture case {case_id} side/bottom extents differ from frame border")
        if case["expected_title"]:
            assert isinstance(title, dict)
            if calculated_extents["top"] != title["outer"]["height"]:
                errors.append(f"capture case {case_id} top extent differs from title height")
        elif calculated_extents["top"] != expected_frame_border:
            errors.append(f"capture case {case_id} titleless top extent differs from border")
    return errors


def make_geometry(outer_x: int, outer_y: int, width: int, height: int,
                  border: int) -> dict[str, object]:
    return {
        "border_width": border,
        "inner": {
            "height": height - 2 * border,
            "width": width - 2 * border,
            "x": outer_x + border,
            "y": outer_y + border,
        },
        "mapped": True,
        "outer": {"height": height, "width": width, "x": outer_x, "y": outer_y},
    }


def synthetic_capture(matrix: dict[str, Any], matrix_hash: str) -> dict[str, object]:
    configs = {config["path"]: config for config in matrix["configurations"]}
    captured_cases: list[dict[str, object]] = []
    for index, case in enumerate(matrix["cases"]):
        config = configs[case["configuration"]]
        border = case["initial_border_width"] if config["client_border_width"] else config["border_width"]
        width, height = case["size"]
        outer_x = 100 + index
        outer_y = 80 + index
        title_inner_height = 13
        title_outer_height = title_inner_height + 2 * border if case["expected_title"] else 0
        frame_outer_width = width + 2 * border
        frame_outer_height = (
            title_outer_height + height + border
            if case["expected_title"] else height + 2 * border
        )
        frame = make_geometry(
            outer_x, outer_y, frame_outer_width, frame_outer_height, border
        )
        client_y = outer_y + (title_outer_height if case["expected_title"] else border)
        client = make_geometry(outer_x + border, client_y, width, height, 0)
        title = None
        if case["expected_title"]:
            title = make_geometry(
                outer_x, outer_y, frame_outer_width, title_outer_height, border
            )
        captured_cases.append({
            "case_id": case["id"],
            "configuration": config,
            "expected_title": case["expected_title"],
            "hint_profile": case["hint_profile"],
            "observation": {
                "client": client,
                "extents": {
                    "bottom": border,
                    "left": border,
                    "right": border,
                    "top": title_outer_height if case["expected_title"] else border,
                },
                "frame": frame,
                "kind": case["kind"],
                "normal_hints": expected_hints(case["hint_profile"]),
                "request": {
                    "border_width": case["initial_border_width"],
                    "height": height, "width": width, "x": 160, "y": 120,
                },
                "screen": matrix["screen"],
                "title": title,
                "transient_for_owner": case["kind"] == "transient",
            },
        })
    return {
        "cases": captured_cases,
        "environment": matrix["environment"],
        "reference": matrix["reference"],
        "schema_version": 1,
        "screen": matrix["screen"],
        "source_matrix": {"path": str(MATRIX_PATH), "sha256": matrix_hash},
    }


def self_test_tamper(matrix: dict[str, Any], source_root: Path,
                     matrix_hash: str) -> list[str]:
    failures: list[str] = []
    missing_case = copy.deepcopy(matrix)
    missing_case["cases"].pop()
    if not validate_matrix(missing_case, source_root):
        failures.append("case-removal tamper was not detected")
    weakened_runs = copy.deepcopy(matrix)
    weakened_runs["capture"]["clean_runs"] = 1
    if not validate_matrix(weakened_runs, source_root):
        failures.append("repeatability tamper was not detected")
    changed_config_hash = copy.deepcopy(matrix)
    changed_config_hash["configurations"][0]["sha256"] = "0" * 64
    if not validate_matrix(changed_config_hash, source_root):
        failures.append("configuration-hash tamper was not detected")

    capture = synthetic_capture(matrix, matrix_hash)
    clean_errors = validate_capture(capture, matrix, matrix_hash)
    if clean_errors:
        failures.append("synthetic valid capture was rejected: " + "; ".join(clean_errors))
        return failures
    bad_extent = copy.deepcopy(capture)
    bad_extent["cases"][0]["observation"]["extents"]["left"] += 1
    if not validate_capture(bad_extent, matrix, matrix_hash):
        failures.append("extent-arithmetic tamper was not detected")
    missing_title = copy.deepcopy(capture)
    missing_title["cases"][0]["observation"]["title"] = None
    if not validate_capture(missing_title, matrix, matrix_hash):
        failures.append("title-presence tamper was not detected")
    volatile = copy.deepcopy(capture)
    volatile["cases"][0]["observation"]["xid"] = 42
    if not validate_capture(volatile, matrix, matrix_hash):
        failures.append("volatile-field tamper was not detected")
    wrong_matrix = copy.deepcopy(capture)
    wrong_matrix["source_matrix"]["sha256"] = "0" * 64
    if not validate_capture(wrong_matrix, matrix, matrix_hash):
        failures.append("source-matrix tamper was not detected")
    try:
        workflow = (source_root / ".github/workflows/build.yml").read_text(encoding="utf-8")
        meson = (source_root / "meson.build").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        failures.append(f"cannot tamper-test CI/Meson wiring: {error}")
    else:
        removed_ci = workflow.replace(
            "tests/reference/capture_reference_geometry_matrix.sh",
            "tests/reference/removed_geometry_capture.sh", 1,
        )
        if not validate_wiring_text(removed_ci, meson):
            failures.append("live-CI wiring tamper was not detected")
        removed_meson = meson.replace(
            "'reference geometry matrix contract'", "'removed geometry contract'", 1
        )
        if not validate_wiring_text(workflow, removed_meson):
            failures.append("Meson wiring tamper was not detected")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    matrix_path = args.source_root / MATRIX_PATH
    try:
        matrix_bytes = matrix_path.read_bytes()
        matrix = load_json(matrix_path)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"reference geometry matrix contract failed: {error}")
        return 1
    errors = validate_matrix(matrix, args.source_root)
    errors += validate_wiring(args.source_root)
    if not isinstance(matrix, dict):
        print("reference geometry matrix contract failed: invalid matrix root")
        return 1
    matrix_hash = sha256(matrix_bytes)
    if args.capture is not None:
        try:
            capture = load_json(args.capture)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"cannot read live geometry capture: {error}")
        else:
            errors += validate_capture(capture, matrix, matrix_hash)
    if args.self_test_tamper:
        errors += self_test_tamper(matrix, args.source_root, matrix_hash)
    if errors:
        for error in errors:
            print(f"reference geometry matrix contract failed: {error}")
        return 1
    print("reference geometry matrix contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
