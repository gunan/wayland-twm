#!/usr/bin/env python3
"""Validate the Milestone 10 differential-certification corpus inventory."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_PATH = Path("reference/certification/m10-corpus.json")
EXPECTED_RESULT_POLICY = (
    "Scenario inventory only; inclusion does not assert execution or parity."
)
REQUIRED_CASES = {
    "upstream_sample_configurations": {
        "upstream-sample-jim",
        "upstream-sample-keith",
        "upstream-sample-lemke",
    },
    "exhaustive_generated_configurations": {
        "geometry-cartesian-product",
    },
    "collected_real_world_twmrc": {
        "historical-user-jim",
        "historical-user-keith",
        "historical-user-lemke",
    },
    "legacy_x11_applications": {
        "legacy-xterm",
        "canonical-icccm-xlib-clients",
    },
    "native_wayland_equivalents": {
        "managed-toplevel-pair",
        "temporary-surface-pair",
        "selection-pair",
    },
    "output_and_color_scenarios": {
        "single-output-color",
        "single-output-monochrome",
        "multi-output-color",
        "multi-output-monochrome",
    },
    "interaction_workflows": {
        "keyboard-actions",
        "mouse-move-resize",
        "mixed-differential-trace",
    },
}
REQUIRED_FIELDS = {
    "upstream_sample_configurations": {
        "source_release",
        "archive_member",
    },
    "exhaustive_generated_configurations": {
        "generation_method",
        "configuration_count",
        "scenario_count",
        "axes",
    },
    "collected_real_world_twmrc": {
        "provenance",
        "source_kind",
        "archive_member",
    },
    "legacy_x11_applications": {
        "protocol",
        "client_kind",
        "executable",
        "roles",
    },
    "native_wayland_equivalents": {
        "native_protocol",
        "x11_protocol",
        "equivalence_surface",
    },
    "output_and_color_scenarios": {
        "output_profile",
        "color_profile",
        "palette_mode",
    },
    "interaction_workflows": {
        "modality",
        "event_surface",
    },
}


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


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(nonempty_string(item) for item in value)
    )


def validate_case_paths(
    source_root: Path, category_id: str, case_id: str, value: object
) -> list[str]:
    errors: list[str] = []
    if not nonempty_string_list(value):
        return [f"{category_id}/{case_id}: paths must be a non-empty string list"]

    assert isinstance(value, list)
    if len(set(value)) != len(value):
        errors.append(f"{category_id}/{case_id}: paths must not contain duplicates")
    for path_text in value:
        assert isinstance(path_text, str)
        relative = PurePosixPath(path_text)
        if relative.is_absolute() or ".." in relative.parts or path_text != str(relative):
            errors.append(
                f"{category_id}/{case_id}: path is not a normalized repository-relative path: {path_text!r}"
            )
            continue
        path = source_root / Path(*relative.parts)
        if not path.is_file():
            errors.append(
                f"{category_id}/{case_id}: referenced file does not exist: {path_text}"
            )
    return errors


def validate_case_metadata(
    category_id: str, case_id: str, case: dict[str, object]
) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS[category_id] - set(case))
    if missing:
        errors.append(
            f"{category_id}/{case_id}: missing category metadata: {', '.join(missing)}"
        )
    if not nonempty_string_list(case.get("coverage_claims")):
        errors.append(
            f"{category_id}/{case_id}: coverage_claims must be a non-empty string list"
        )

    for field in REQUIRED_FIELDS[category_id] - {
        "configuration_count",
        "scenario_count",
        "axes",
        "roles",
    }:
        if field in case and not nonempty_string(case[field]):
            errors.append(f"{category_id}/{case_id}: {field} must be a non-empty string")

    if category_id == "exhaustive_generated_configurations":
        for field in ("configuration_count", "scenario_count"):
            value = case.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(f"{category_id}/{case_id}: {field} must be positive")
        if not nonempty_string_list(case.get("axes")):
            errors.append(f"{category_id}/{case_id}: axes must be a non-empty string list")
    if category_id == "legacy_x11_applications":
        if case.get("protocol") != "X11":
            errors.append(f"{category_id}/{case_id}: protocol must be X11")
        if not nonempty_string_list(case.get("roles")):
            errors.append(f"{category_id}/{case_id}: roles must be a non-empty string list")

    return errors


def validate_manifest(source_root: Path, manifest: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("corpus_id") != "wtwm-milestone-10-differential-parity":
        errors.append("corpus_id must identify the Milestone 10 differential corpus")
    if manifest.get("reference") != "X.Org twm 1.0.13.1":
        errors.append("reference must be the pinned X.Org twm 1.0.13.1 release")
    if manifest.get("result_policy") != EXPECTED_RESULT_POLICY:
        errors.append("result_policy must not claim unrecorded execution or parity")

    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        return errors + ["categories must be an object"]
    missing_categories = sorted(set(REQUIRED_CASES) - set(categories))
    if missing_categories:
        errors.append(f"missing required categories: {', '.join(missing_categories)}")
    unexpected_categories = sorted(set(categories) - set(REQUIRED_CASES))
    if unexpected_categories:
        errors.append(f"unexpected categories: {', '.join(unexpected_categories)}")

    output_color_pairs: set[tuple[object, object]] = set()
    modalities: set[object] = set()
    for category_id in sorted(set(REQUIRED_CASES) & set(categories)):
        category = categories[category_id]
        if not isinstance(category, dict):
            errors.append(f"{category_id}: category must be an object")
            continue
        if not nonempty_string(category.get("roadmap_category")):
            errors.append(f"{category_id}: roadmap_category must be a non-empty string")
        cases = category.get("cases")
        if not isinstance(cases, list) or not cases:
            errors.append(f"{category_id}: cases must be a non-empty list")
            continue

        actual_ids: list[str] = []
        for index, case in enumerate(cases):
            fallback_id = f"case[{index}]"
            if not isinstance(case, dict):
                errors.append(f"{category_id}/{fallback_id}: case must be an object")
                continue
            raw_id = case.get("id")
            if not nonempty_string(raw_id):
                errors.append(f"{category_id}/{fallback_id}: id must be a non-empty string")
                case_id = fallback_id
            else:
                assert isinstance(raw_id, str)
                case_id = raw_id
                actual_ids.append(case_id)
            errors.extend(
                validate_case_paths(source_root, category_id, case_id, case.get("paths"))
            )
            errors.extend(validate_case_metadata(category_id, case_id, case))
            if category_id == "output_and_color_scenarios":
                output_color_pairs.add(
                    (case.get("output_profile"), case.get("color_profile"))
                )
            if category_id == "interaction_workflows":
                modalities.add(case.get("modality"))

        duplicate_ids = sorted(
            case_id for case_id in set(actual_ids) if actual_ids.count(case_id) > 1
        )
        if duplicate_ids:
            errors.append(f"{category_id}: duplicate case ids: {', '.join(duplicate_ids)}")
        missing_cases = sorted(REQUIRED_CASES[category_id] - set(actual_ids))
        if missing_cases:
            errors.append(f"{category_id}: missing required cases: {', '.join(missing_cases)}")
        unexpected_cases = sorted(set(actual_ids) - REQUIRED_CASES[category_id])
        if unexpected_cases:
            errors.append(f"{category_id}: unexpected cases: {', '.join(unexpected_cases)}")

    required_output_color_pairs = {
        ("single", "color"),
        ("single", "monochrome"),
        ("multi", "color"),
        ("multi", "monochrome"),
    }
    missing_pairs = required_output_color_pairs - output_color_pairs
    if missing_pairs:
        rendered = ", ".join(
            f"{output}/{color}" for output, color in sorted(missing_pairs)
        )
        errors.append(f"incomplete output/color coverage: {rendered}")
    unexpected_pairs = output_color_pairs - required_output_color_pairs
    if unexpected_pairs:
        errors.append("output/color cases contain unsupported coverage values")

    required_modalities = {"keyboard", "mouse", "mixed"}
    missing_modalities = required_modalities - modalities
    if missing_modalities:
        errors.append(
            "incomplete interaction modality coverage: "
            + ", ".join(sorted(missing_modalities))
        )
    unexpected_modalities = modalities - required_modalities
    if unexpected_modalities:
        errors.append("interaction workflows contain unsupported modality values")
    return errors


def load_manifest(source_root: Path) -> tuple[object | None, list[str]]:
    try:
        return load_json(source_root / MANIFEST_PATH), []
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return None, [f"cannot read {MANIFEST_PATH}: {error}"]


def self_test_tamper(source_root: Path, manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        return ["cannot self-test a non-object manifest"]
    failures: list[str] = []
    tamper_cases: list[tuple[str, Any]] = []

    missing_category = copy.deepcopy(manifest)
    del missing_category["categories"]["upstream_sample_configurations"]
    tamper_cases.append(("required-category-removal", missing_category))

    missing_case = copy.deepcopy(manifest)
    missing_case["categories"]["legacy_x11_applications"]["cases"].pop()
    tamper_cases.append(("required-case-removal", missing_case))

    missing_modality = copy.deepcopy(manifest)
    workflow_cases = missing_modality["categories"]["interaction_workflows"]["cases"]
    workflow_cases[:] = [case for case in workflow_cases if case["modality"] != "mouse"]
    tamper_cases.append(("required-modality-removal", missing_modality))

    broken_path = copy.deepcopy(manifest)
    broken_path["categories"]["upstream_sample_configurations"]["cases"][0][
        "paths"
    ][0] = "reference/certification/does-not-exist.twmrc"
    tamper_cases.append(("nonexistent-path", broken_path))

    for name, tampered in tamper_cases:
        if not validate_manifest(source_root, tampered):
            failures.append(f"tamper {name} unexpectedly passed validation")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--self-test-tamper",
        action="store_true",
        help="prove deterministic manifest damage is rejected",
    )
    arguments = parser.parse_args()
    source_root = arguments.source_root.resolve()
    manifest, load_errors = load_manifest(source_root)
    errors = load_errors or validate_manifest(source_root, manifest)
    if errors:
        for error in errors:
            print(f"m10 corpus error: {error}")
        return 1

    assert manifest is not None
    if arguments.self_test_tamper:
        tamper_errors = self_test_tamper(source_root, manifest)
        if tamper_errors:
            for error in tamper_errors:
                print(f"m10 corpus self-test error: {error}")
            return 1
        print("Milestone 10 corpus tamper self-test passed: 4 mutations rejected")
        return 0

    case_count = sum(
        len(category["cases"])
        for category in manifest["categories"].values()
    )
    print(
        "Milestone 10 certification corpus valid: "
        f"{len(REQUIRED_CASES)} categories, {case_count} cases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
