#!/usr/bin/env python3
"""Validate the Milestone 10 differential-certification coverage contract."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import sys


CONTRACT_PATH = Path("reference/certification/m10-differential-contract.json")
EXPECTED_DIMENSIONS = (
    ("parsed-configuration", "Parsed configuration."),
    ("window-position-and-dimensions", "Window position and dimensions."),
    ("frame-extents", "Frame extents."),
    ("focus-owner", "Focus owner."),
    ("stacking-order", "Stacking order."),
    ("pointer-location", "Pointer location."),
    ("menu-state", "Menu state."),
    ("icons-and-icon-managers", "Icon and icon-manager state."),
    ("commands-launched", "Commands launched."),
    ("client-close-and-destruction", "Client close and destruction behavior."),
    (
        "screenshots-after-significant-actions",
        "Screenshots after every significant action.",
    ),
)
MAPPING_RULES = {
    "runners": ("tests", {".py", ".sh"}),
    "validators": ("tests", {".py"}),
    "committed_evidence": ("reference", {".json"}),
}
ALLOWED_COVERAGE = {
    "live-reference-differential",
    "partial-existing-infrastructure",
}
EXPECTED_COVERAGE = {
    "parsed-configuration": "live-reference-differential",
    "window-position-and-dimensions": "live-reference-differential",
    "frame-extents": "live-reference-differential",
    "focus-owner": "live-reference-differential",
    "stacking-order": "live-reference-differential",
    "pointer-location": "live-reference-differential",
    "menu-state": "partial-existing-infrastructure",
    "icons-and-icon-managers": "live-reference-differential",
    "commands-launched": "partial-existing-infrastructure",
    "client-close-and-destruction": "partial-existing-infrastructure",
    "screenshots-after-significant-actions": "partial-existing-infrastructure",
}


def duplicate_rejecting_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys instead of silently accepting the final value."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_contract(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=duplicate_rejecting_pairs,
    )


def validate_repository_path(
    value: object,
    source_root: Path,
    dimension_id: str,
    mapping_kind: str,
) -> list[str]:
    if not isinstance(value, str) or not value:
        return [f"{dimension_id}: {mapping_kind} mapping must be a nonempty path"]
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        return [
            f"{dimension_id}: {mapping_kind} mapping is not a normalized "
            f"repository-relative path: {value!r}"
        ]
    required_root, allowed_suffixes = MAPPING_RULES[mapping_kind]
    if not relative.parts or relative.parts[0] != required_root:
        return [
            f"{dimension_id}: {mapping_kind} mapping must be beneath "
            f"{required_root}/: {value!r}"
        ]
    if relative.suffix not in allowed_suffixes:
        return [
            f"{dimension_id}: {mapping_kind} mapping has an unsupported suffix: "
            f"{value!r}"
        ]
    candidate = source_root / Path(*relative.parts)
    if not candidate.is_file():
        return [
            f"{dimension_id}: {mapping_kind} mapping does not exist: {value!r}"
        ]
    try:
        candidate.resolve().relative_to(source_root.resolve())
    except ValueError:
        return [
            f"{dimension_id}: {mapping_kind} mapping escapes the source tree: {value!r}"
        ]
    if mapping_kind == "validators" and not candidate.name.startswith("validate_"):
        return [
            f"{dimension_id}: validator mapping is not a validator entry point: {value!r}"
        ]
    return []


def validate_result(value: object, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    if value.get("status") != "not-recorded":
        errors.append(
            f"{label} must remain not-recorded until an actual certification "
            "artifact is committed and validated"
        )
    if value.get("artifact", "missing") is not None:
        errors.append(f"{label} must not name an artifact while it is not-recorded")
    return errors


def validate_dimension(
    value: object,
    expected_id: str,
    expected_text: str,
    source_root: Path,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{expected_id}: dimension entry must be an object"]
    errors: list[str] = []
    dimension_id = value.get("id")
    if dimension_id != expected_id:
        errors.append(
            f"dimension order/identity mismatch: expected {expected_id!r}, "
            f"found {dimension_id!r}"
        )
    if value.get("roadmap_text") != expected_text:
        errors.append(f"{expected_id}: Roadmap comparison text has drifted")
    coverage = value.get("coverage_status")
    if coverage not in ALLOWED_COVERAGE:
        errors.append(f"{expected_id}: unknown coverage_status {coverage!r}")
    elif coverage != EXPECTED_COVERAGE[expected_id]:
        errors.append(
            f"{expected_id}: coverage_status must be "
            f"{EXPECTED_COVERAGE[expected_id]!r}, found {coverage!r}"
        )
    if coverage == "partial-existing-infrastructure":
        note = value.get("coverage_note")
        if not isinstance(note, str) or not note.strip():
            errors.append(f"{expected_id}: partial coverage lacks an explanatory note")
    semantics = value.get("comparison_semantics")
    if (
        not isinstance(semantics, list)
        or not semantics
        or any(not isinstance(item, str) or not item.strip() for item in semantics)
    ):
        errors.append(f"{expected_id}: comparison_semantics must be nonempty strings")
    elif len(semantics) != len(set(semantics)):
        errors.append(f"{expected_id}: comparison_semantics contains duplicates")

    mappings = value.get("mappings")
    if not isinstance(mappings, dict):
        errors.append(f"{expected_id}: mappings must be an object")
    else:
        if set(mappings) != set(MAPPING_RULES):
            errors.append(
                f"{expected_id}: mappings must contain exactly "
                + ", ".join(MAPPING_RULES)
            )
        for mapping_kind in MAPPING_RULES:
            paths = mappings.get(mapping_kind)
            if not isinstance(paths, list) or not paths:
                errors.append(f"{expected_id}: {mapping_kind} mapping is empty or missing")
                continue
            string_paths = [path for path in paths if isinstance(path, str)]
            if len(string_paths) != len(paths):
                errors.append(f"{expected_id}: {mapping_kind} mappings must be strings")
            if len(string_paths) != len(set(string_paths)):
                errors.append(f"{expected_id}: {mapping_kind} mappings contain duplicates")
            for path in paths:
                errors.extend(
                    validate_repository_path(path, source_root, expected_id, mapping_kind)
                )

    errors.extend(
        validate_result(
            value.get("actual_pass_evidence"),
            f"{expected_id}: actual_pass_evidence",
        )
    )
    return errors


def validate_contract(value: object, source_root: Path) -> list[str]:
    if not isinstance(value, dict):
        return ["Milestone 10 differential contract root must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != 1:
        errors.append("Milestone 10 differential contract schema_version must be 1")
    if value.get("contract_id") != "milestone-10-differential-parity":
        errors.append("Milestone 10 differential contract_id has drifted")
    if value.get("reference") != {"implementation": "twm", "version": "1.0.13.1"}:
        errors.append("Milestone 10 differential contract must pin twm 1.0.13.1")
    scope = value.get("scope")
    if (
        not isinstance(scope, str)
        or "coverage mapping is not evidence" not in scope.lower()
    ):
        errors.append("contract scope does not distinguish coverage from pass evidence")
    errors.extend(validate_result(value.get("certification_result"), "certification_result"))
    result = value.get("certification_result")
    if not isinstance(result, dict) or not isinstance(result.get("note"), str):
        errors.append("certification_result must explain why no result is recorded")

    dimensions = value.get("dimensions")
    if not isinstance(dimensions, list):
        errors.append("dimensions must be an array")
        return errors
    if len(dimensions) != len(EXPECTED_DIMENSIONS):
        errors.append(
            f"dimensions must cover all {len(EXPECTED_DIMENSIONS)} Roadmap entries; "
            f"found {len(dimensions)}"
        )
    identifiers = [
        dimension.get("id")
        for dimension in dimensions
        if isinstance(dimension, dict)
    ]
    if len(identifiers) != len(set(identifiers)):
        errors.append("dimension identifiers must be unique")
    for index, (expected_id, expected_text) in enumerate(EXPECTED_DIMENSIONS):
        if index >= len(dimensions):
            errors.append(f"missing required dimension {expected_id!r}")
            continue
        errors.extend(
            validate_dimension(
                dimensions[index], expected_id, expected_text, source_root
            )
        )
    return errors


def self_test_tamper(contract: object, source_root: Path) -> list[str]:
    if not isinstance(contract, dict) or not isinstance(contract.get("dimensions"), list):
        return ["cannot tamper-test an invalid contract structure"]
    failures: list[str] = []

    missing_dimension = copy.deepcopy(contract)
    missing_dimension["dimensions"].pop(0)
    if not validate_contract(missing_dimension, source_root):
        failures.append("required-dimension removal was accepted")

    missing_mapping = copy.deepcopy(contract)
    missing_mapping["dimensions"][0]["mappings"]["runners"] = []
    if not validate_contract(missing_mapping, source_root):
        failures.append("required-mapping removal was accepted")

    nonexistent_mapping = copy.deepcopy(contract)
    nonexistent_mapping["dimensions"][0]["mappings"]["validators"][0] = (
        "tests/certification/does-not-exist.py"
    )
    if not validate_contract(nonexistent_mapping, source_root):
        failures.append("nonexistent mapping was accepted")

    underclaimed_pointer = copy.deepcopy(contract)
    underclaimed_pointer["dimensions"][5]["coverage_status"] = (
        "partial-existing-infrastructure"
    )
    if not validate_contract(underclaimed_pointer, source_root):
        failures.append("exact pointer-coordinate coverage underclaim was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    source_root = arguments.source_root.resolve()
    path = source_root / CONTRACT_PATH
    try:
        contract = load_contract(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Milestone 10 differential contract error: {error}", file=sys.stderr)
        return 1

    errors = validate_contract(contract, source_root)
    if arguments.self_test_tamper and not errors:
        errors.extend(self_test_tamper(contract, source_root))
    if errors:
        for error in errors:
            print(f"Milestone 10 differential contract error: {error}", file=sys.stderr)
        return 1
    print(
        "Milestone 10 differential coverage contract valid: "
        f"{len(EXPECTED_DIMENSIONS)} dimensions; certification result not recorded"
    )
    if arguments.self_test_tamper:
        print("Milestone 10 differential contract tamper checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
