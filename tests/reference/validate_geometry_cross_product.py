#!/usr/bin/env python3
"""Validate the generated M4 geometry cross-product and exact live wiring."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from geometry_cross_product import (
    MANIFEST_PATH, generate_cases, generate_configurations, generated_hashes,
    load_manifest,
)


RUNNER_PATH = Path("tests/integration/run_m4_geometry_differential.py")
REFERENCE_CLIENT_PATH = Path("tests/reference/geometry_matrix_client.c")
WTWM_CLIENT_PATH = Path("tests/integration/xwayland_geometry_matrix_client.c")
GENERATOR_PATH = Path("tests/reference/geometry_cross_product.py")
WORKFLOW_PATH = Path(".github/workflows/build.yml")
MESON_PATH = Path("meson.build")
SOURCE_PATHS = [
    GENERATOR_PATH,
    RUNNER_PATH,
    REFERENCE_CLIENT_PATH,
    WTWM_CLIENT_PATH,
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_manifest(manifest: object, source_root: Path) -> list[str]:
    if not isinstance(manifest, dict):
        return ["geometry cross-product manifest must be an object"]
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("geometry cross-product schema_version must be 1")
    base = manifest.get("base_matrix")
    expected_matrix = "reference/geometry/twm-1.0.13.1/matrix.json"
    if not isinstance(base, dict) or base.get("path") != expected_matrix:
        errors.append("cross-product does not reuse the pinned reference matrix")
    else:
        if base.get("sha256") != sha256(source_root / expected_matrix):
            errors.append("cross-product base matrix hash is stale")
        matrix = json.loads((source_root / expected_matrix).read_text(encoding="utf-8"))
        if matrix.get("capture", {}).get("clean_runs") != 2:
            errors.append("cross-product base must require two clean runs")
        if matrix.get("capture", {}).get("stable_observations_per_case") != 3:
            errors.append("cross-product base must require three stable observations")

    expected_axes = {
        "title_policy": ["titled", "untitled"],
        "border_policy": ["frame-border", "client-border"],
        "transient_policy": [
            "normal", "transient-suppressed", "transient-decorated"
        ],
        "hint_profile": ["none", "min-max", "base-increment", "aspect"],
    }
    if manifest.get("axes") != expected_axes:
        errors.append("geometry axes or deterministic order have drifted")
    expected_profiles = [
        {"id": "none", "size": [137, 91]},
        {"id": "min-max", "size": [137, 91]},
        {"id": "base-increment", "size": [137, 88]},
        {"id": "aspect", "size": [144, 96]},
    ]
    if manifest.get("hint_profiles") != expected_profiles:
        errors.append("semantic geometry hint profiles have drifted")

    try:
        cases = generate_cases(manifest)
        configurations = generate_configurations(manifest)
        hashes = generated_hashes(manifest)
    except (KeyError, TypeError, ValueError) as error:
        return errors + [f"geometry cross-product generation failed: {error}"]
    expected_tuples = list(itertools.product(
        expected_axes["title_policy"], expected_axes["border_policy"],
        expected_axes["transient_policy"], expected_axes["hint_profile"],
    ))
    actual_tuples = [(
        case["axes"]["title_policy"], case["axes"]["border_policy"],
        case["axes"]["transient_policy"], case["axes"]["hint_profile"],
    ) for case in cases]
    if actual_tuples != expected_tuples:
        errors.append("generated cases are not the complete ordered Cartesian product")
    if len(cases) != 48 or len(set(actual_tuples)) != 48:
        errors.append("generated geometry cross-product must contain 48 unique cases")
    if len(configurations) != 12:
        errors.append("geometry cross-product must contain 12 generated configurations")
    for case in cases:
        axes = case["axes"]
        expected_title = (
            axes["title_policy"] == "titled"
            and axes["transient_policy"] != "transient-suppressed"
        )
        expected_kind = "normal" if axes["transient_policy"] == "normal" else "transient"
        if case["expected_title"] is not expected_title:
            errors.append(f"generated title oracle is wrong for {case['id']}")
        if case["kind"] != expected_kind:
            errors.append(f"generated transient state is wrong for {case['id']}")
    generated = manifest.get("generated")
    if not isinstance(generated, dict):
        errors.append("generated cardinality/hash ledger is missing")
    else:
        if generated.get("case_count") != 48 or generated.get("configuration_count") != 12:
            errors.append("generated geometry cardinality ledger has drifted")
        if generated.get("cases_sha256") != hashes["cases_sha256"]:
            errors.append("generated geometry case hash is stale")
        if generated.get("configurations_sha256") != hashes["configurations_sha256"]:
            errors.append("generated geometry configuration hash is stale")

    sources = manifest.get("sources")
    expected_source_names = [path.as_posix() for path in SOURCE_PATHS]
    if not isinstance(sources, list):
        errors.append("geometry cross-product source hashes are missing")
    else:
        actual_names = [entry.get("path") for entry in sources if isinstance(entry, dict)]
        if actual_names != expected_source_names:
            errors.append("geometry cross-product source hash set/order has drifted")
        for entry in sources:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                errors.append("geometry cross-product source hash entry is malformed")
                continue
            path = source_root / entry["path"]
            if entry.get("sha256") != sha256(path):
                errors.append(f"geometry cross-product source hash is stale: {entry['path']}")
    return errors


def validate_wiring(runner: str, reference_client: str, wtwm_client: str,
                    workflow: str, meson: str) -> list[str]:
    errors: list[str] = []
    try:
        ast.parse(runner)
    except SyntaxError as error:
        errors.append(f"geometry differential runner is invalid Python: {error}")
    for marker in (
        "generate_cases(manifest)",
        "generate_configurations(manifest)",
        'clean_runs = int(matrix["capture"]["clean_runs"])',
        'stable_observations = int(matrix["capture"]["stable_observations_per_case"])',
        "reference_normalized = normalize_reference(reference_observation)",
        'wtwm_normalized = wtwm_observation["normalized"]',
        "if reference_normalized != wtwm_normalized:",
        '"client_inner", "frame_outer", "title_outer", "extents"',
        '"result": "exactly-equivalent"',
        '"result": "failed"',
        'args.evidence_dir / "runner-error.log"',
    ):
        if marker not in runner:
            errors.append(f"exact geometry differential runner lacks {marker!r}")
    for forbidden in (
        "excluded_case", "excluded_field", "allowed_difference", "tolerance",
        "continue-on-error", "SystemExit(77)",
        "if False and reference_normalized != wtwm_normalized:",
    ):
        if forbidden in runner:
            errors.append(f"geometry differential contains forbidden escape {forbidden!r}")
    for source, name in (
        (reference_client, "reference"), (wtwm_client, "wtwm/Xwayland"),
    ):
        for marker in (
            'strcmp(', '"none"', '"min-max"', '"base-increment"', '"aspect"',
            "PAspect" if name == "reference" else "P_ASPECT",
        ):
            if marker not in source:
                errors.append(f"{name} geometry client lacks {marker!r}")

    job_start = workflow.find("  x11-differential:\n")
    job = workflow[job_start:] if job_start >= 0 else ""
    for marker in (
        "tests/reference/geometry_matrix_client.c",
        "-o /tmp/reference-geometry-matrix-client",
        "tests/integration/run_m4_geometry_differential.py",
        "--reference-twm /tmp/reference-build/twm",
        '--wtwm-client "$GITHUB_WORKSPACE/build-differential/wtwm-xwayland-geometry-matrix-client"',
        "--output /tmp/m4-geometry-differential.json",
        "--evidence-dir /tmp/m4-geometry-differential-evidence",
        "name: m4-geometry-differential",
        "/tmp/m4-geometry-differential.json",
        "/tmp/m4-geometry-differential-evidence",
        "if: always()",
        "if-no-files-found: error",
    ):
        if marker not in job:
            errors.append(f"X11 differential CI job lacks geometry marker {marker!r}")
    if "continue-on-error" in job or "|| true" in job:
        errors.append("live geometry differential must fail CI on an exact mismatch")
    for marker in (
        "Milestone 4 geometry cross-product contract",
        "tests/reference/validate_geometry_cross_product.py",
        "--self-test-tamper",
    ):
        if marker not in meson:
            errors.append(f"Meson geometry cross-product test lacks {marker!r}")
    if "run_m4_geometry_differential.py" in meson:
        errors.append("live geometry differential must run only in controlled Linux CI")
    return errors


def read_sources(source_root: Path) -> tuple[str, str, str, str, str]:
    return tuple((source_root / path).read_text(encoding="utf-8") for path in (
        RUNNER_PATH, REFERENCE_CLIENT_PATH, WTWM_CLIENT_PATH, WORKFLOW_PATH, MESON_PATH,
    ))  # type: ignore[return-value]


def validate(source_root: Path, manifest: object | None = None,
             sources: tuple[str, str, str, str, str] | None = None) -> list[str]:
    value = load_manifest(source_root) if manifest is None else manifest
    texts = read_sources(source_root) if sources is None else sources
    return validate_manifest(value, source_root) + validate_wiring(*texts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    try:
        manifest = load_manifest(root)
        sources = read_sources(root)
        errors = validate(root, manifest, sources)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        errors = [f"could not load geometry cross-product contract: {error}"]
        manifest = {}
        sources = ("", "", "", "", "")
    if args.self_test_tamper and not errors:
        tampered_axes: dict[str, Any] = copy.deepcopy(manifest)
        tampered_axes["axes"]["hint_profile"].pop()
        if not validate(root, tampered_axes, sources):
            errors.append("self-test missed an incomplete hint-profile axis")
        tampered_hash: dict[str, Any] = copy.deepcopy(manifest)
        tampered_hash["generated"]["cases_sha256"] = "0" * 64
        if not validate(root, tampered_hash, sources):
            errors.append("self-test missed generated case hash drift")
        runner, *other_sources = sources
        tampered_runner = runner.replace(
            "if reference_normalized != wtwm_normalized:",
            "if False and reference_normalized != wtwm_normalized:", 1,
        )
        if not validate(root, manifest, (tampered_runner, *other_sources)):
            errors.append("self-test missed disabling the exact comparison")
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Milestone 4 geometry cross-product contract valid: 48 exact cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
