#!/usr/bin/env python3
"""Protect wtwm's portable and live Xwayland geometry-matrix adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_TITLE = {
    "normal-default-decoration": True,
    "normal-client-border-ignored": True,
    "normal-client-border-preserved-on-frame": True,
    "normal-no-title": False,
    "make-title": True,
    "transient-default-no-title": False,
    "transient-decorated": True,
    "compact-fixed-font": True,
    "spacious-9x15-font": True,
    "hints-min-max": True,
    "hints-base-increment": True,
    "hints-complete-aspect": True,
}


def function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    opening = source.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return ""


def validate_text(
    wtwm: str, geometry: str, geometry_test: str,
    client: str, runner: str, meson: str,
) -> list[str]:
    errors: list[str] = []
    title_model = function_body(geometry, "bool wtwm_window_has_title(")
    ordered_markers = (
        "if (make_title_match) has_title = true;",
        "if (no_title_match) has_title = false;",
        "if (transient && !decorate_transients) has_title = false;",
    )
    positions = [title_model.find(marker) for marker in ordered_markers]
    if not title_model or any(position < 0 for position in positions):
        errors.append("portable title model lacks MakeTitle/NoTitle/transient precedence")
    elif positions != sorted(positions):
        errors.append("portable title model applies reference precedence out of order")

    decorate = function_body(wtwm, "static bool should_decorate(")
    for marker in (
        "toplevel->xwayland->parent != NULL",
        "wtwm_window_has_title(toplevel->server->config.no_title,",
        "toplevel->server->config.decorate_transients",
    ):
        if marker not in decorate:
            errors.append(f"runtime title adapter lacks {marker!r}")
    set_parent = function_body(wtwm, "static void xwayland_set_parent(")
    if "update_toplevel_metadata(toplevel, false);" not in set_parent:
        errors.append("live WM_TRANSIENT_FOR changes do not recompute decoration")

    set_geometry = function_body(wtwm, "static void xwayland_set_geometry(")
    if set_geometry.count("x -= toplevel_content_x(toplevel);") != 1:
        errors.append("Xwayland geometry callback must translate content_x exactly once")
    if set_geometry.count("y -= toplevel_content_y(toplevel);") != 1:
        errors.append("Xwayland geometry callback must translate content_y exactly once")
    if '\\"original_border_width\\":%d' not in wtwm:
        errors.append("test state omits the original X11 client border")

    for marker in (
        "test_title_rule_order",
        "Reference transient suppression is last",
        "test_initial_gravity_matrix",
        "gravity_y = -1; gravity_y <= 1",
        "gravity_x = -1; gravity_x <= 1",
    ):
        if marker not in geometry_test:
            errors.append(f"portable geometry tests lack {marker!r}")

    for marker in (
        "xcb_create_window(client->connection, XCB_COPY_FROM_PARENT",
        "WM_TRANSIENT_FOR",
        "P_MIN_SIZE | P_MAX_SIZE | P_BASE_SIZE",
        "P_RESIZE_INC | P_ASPECT",
        'set_class(client.connection, client.window, case_id);',
    ):
        if marker not in client:
            errors.append(f"Xwayland matrix client lacks {marker!r}")

    for marker in (
        'MATRIX_PATH = Path("reference/geometry/twm-1.0.13.1/matrix.json")',
        'clean_runs = int(matrix["capture"]["clean_runs"])',
        'stable_observations = int(matrix["capture"]["stable_observations_per_case"])',
        "for case_index, case in enumerate(cases):",
        "compare_case(case, config, item)",
        '"client_inner"',
        '"frame_outer"',
        '"title_outer"',
        '"reference_numeric_baseline": False',
        '"original_border_width"',
    ):
        if marker not in runner:
            errors.append(f"Xwayland matrix runner lacks {marker!r}")

    for marker in (
        "'wtwm Xwayland geometry matrix contract'",
        "tests/integration/validate_wtwm_geometry_matrix.py",
        "'--self-test-tamper'",
        "'wtwm-xwayland-geometry-matrix-client'",
        "tests/integration/xwayland_geometry_matrix_client.c",
        "'wtwm Xwayland geometry matrix integration'",
        "tests/integration/run_xwayland_geometry_matrix.py",
        "'--source-root', meson.project_source_root()",
    ):
        if marker not in meson:
            errors.append(f"Meson Xwayland geometry matrix wiring lacks {marker!r}")
    return errors


def validate_matrix(matrix: object) -> list[str]:
    if not isinstance(matrix, dict):
        return ["reference geometry matrix root is not an object"]
    errors: list[str] = []
    capture = matrix.get("capture")
    if not isinstance(capture, dict) or capture.get("committed_baseline") is not True:
        errors.append("wtwm adapter requires the reviewed numeric baseline")
    elif not isinstance(capture.get("baseline"), dict):
        errors.append("wtwm adapter requires baseline provenance")
    cases = matrix.get("cases")
    if not isinstance(cases, list):
        return errors + ["reference geometry cases are missing"]
    actual = {
        case.get("id"): case.get("expected_title")
        for case in cases if isinstance(case, dict)
    }
    if actual != EXPECTED_TITLE:
        errors.append("wtwm adapter case/title oracle has drifted")
    if len(cases) != len(EXPECTED_TITLE):
        errors.append("wtwm adapter does not have exactly one record per matrix case")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    paths = {
        "wtwm": root / "src/wtwm.c",
        "geometry": root / "src/geometry.c",
        "geometry_test": root / "tests/geometry_test.c",
        "client": root / "tests/integration/xwayland_geometry_matrix_client.c",
        "runner": root / "tests/integration/run_xwayland_geometry_matrix.py",
        "meson": root / "meson.build",
        "matrix": root / "reference/geometry/twm-1.0.13.1/matrix.json",
    }
    text = {
        key: path.read_text(encoding="utf-8")
        for key, path in paths.items() if key != "matrix"
    }
    matrix = json.loads(paths["matrix"].read_text(encoding="utf-8"))
    errors = validate_text(
        text["wtwm"], text["geometry"], text["geometry_test"],
        text["client"], text["runner"], text["meson"],
    )
    errors += validate_matrix(matrix)
    if args.self_test_tamper:
        tampered_wtwm = text["wtwm"].replace(
            "y -= toplevel_content_y(toplevel);", "", 1
        )
        if not validate_text(
            tampered_wtwm, text["geometry"], text["geometry_test"],
            text["client"], text["runner"], text["meson"],
        ):
            errors.append("self-test missed a broken vertical geometry translation")
        tampered_runner = text["runner"].replace(
            '"reference_numeric_baseline": False',
            '"reference_numeric_baseline": True', 1,
        )
        if not validate_text(
            text["wtwm"], text["geometry"], text["geometry_test"],
            text["client"], tampered_runner, text["meson"],
        ):
            errors.append("self-test missed inventing a numeric-baseline claim")
        tampered_matrix = json.loads(json.dumps(matrix))
        tampered_matrix["cases"][5]["expected_title"] = True
        if not validate_matrix(tampered_matrix):
            errors.append("self-test missed transient-title oracle drift")
    if errors:
        for error in errors:
            print(error)
        return 1
    print("wtwm Xwayland geometry matrix contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
