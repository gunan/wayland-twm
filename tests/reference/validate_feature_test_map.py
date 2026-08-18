#!/usr/bin/env python3
"""Validate and execute every current-feature test mapping."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from generate_feature_test_map import (
    AUDIT_PATH,
    MAP_PATH,
    MESON_TEST,
    SUMMARY_PATH,
    TEST_PATH,
    INTERACTION_RUNTIME_FEATURES,
    RESTART_RUNTIME_FEATURES,
    build,
    canonical,
)


ROOT_FIELDS = [
    "schema_version", "current_audit_path", "feature_count", "dimension_policy",
    "test_catalog", "entries",
]
ENTRY_FIELDS = ["feature_id", "category", "implementation_status", "tests"]
TEST_FIELDS = [
    "test_id", "path", "meson_test", "case", "dimension", "expected", "assertions",
    "fixture", "checks",
]
CHECK_FIELDS = ["location", "contains"]
DIMENSIONS = ["syntax", "source_contract", "runtime"]


def fields(value: object, expected: list[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    if list(value) != expected:
        errors.append(f"{label} fields/order must be: {', '.join(expected)}")
        return False
    return True


def sorted_strings(value: object, label: str, errors: list[str]) -> bool:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{label} must be an array of non-empty strings")
        return False
    if value != sorted(set(value)):
        errors.append(f"{label} must be sorted and deduplicated")
        return False
    return True


def repository_path(value: object, source_root: Path, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"{label} must be a repository-relative path")
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or str(path) != value:
        errors.append(f"{label} must be a canonical repository-relative path")
        return None
    result = Path(*path.parts)
    if not (source_root / result).is_file():
        errors.append(f"{label} does not exist: {value}")
        return None
    return result


def source_location(value: object, source_root: Path, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        errors.append(f"{label} must be path:line")
        return None
    path_text, line_text = value.rsplit(":", 1)
    path = repository_path(path_text, source_root, label, errors)
    if path is None or not re.fullmatch(r"[1-9][0-9]*", line_text):
        errors.append(f"{label} must be path:line")
        return None
    lines = (source_root / path).read_text(encoding="utf-8").splitlines()
    line = int(line_text)
    if line > len(lines):
        errors.append(f"{label} is outside the source file")
        return None
    return lines[line - 1]


def validate_mapping(
    value: object,
    feature: dict[str, object],
    source_root: Path,
    catalog: dict[str, dict[str, object]],
    label: str,
    errors: list[str],
) -> None:
    if not fields(value, TEST_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    test_id = value["test_id"]
    if test_id not in catalog:
        errors.append(f"{label}.test_id is not in the registered test catalog")
    else:
        registered = catalog[test_id]
        for field in ("path", "meson_test", "dimension"):
            if value[field] != registered[field]:
                errors.append(f"{label}.{field} differs from its registered test")
    path = repository_path(value["path"], source_root, f"{label}.path", errors)
    if value["case"] != feature["id"]:
        errors.append(f"{label}.case must equal its exact feature ID")
    if value["dimension"] not in DIMENSIONS:
        errors.append(f"{label}.dimension is invalid")
    if not sorted_strings(value["assertions"], f"{label}.assertions", errors):
        pass
    elif not any(str(feature["id"]) in assertion for assertion in value["assertions"]):
        errors.append(f"{label}.assertions do not name the mapped feature")
    fixture = value["fixture"]
    checks = value["checks"]
    if value["dimension"] == "syntax":
        if value["expected"] not in {"accept", "reject"}:
            errors.append(f"{label} syntax mapping has an invalid expected result")
        if not isinstance(fixture, str) or not fixture.strip():
            errors.append(f"{label} syntax mapping requires a dedicated fixture")
        if checks != []:
            errors.append(f"{label} syntax mapping cannot contain source checks")
    elif value["dimension"] == "source_contract":
        if value["expected"] != "not-applicable":
            errors.append(f"{label} source contract must not declare a parser result")
        if fixture != "":
            errors.append(f"{label} source contract cannot contain a parser fixture")
        if not isinstance(checks, list) or not checks:
            errors.append(f"{label} source contract requires exact checks")
        else:
            for index, check in enumerate(checks):
                check_label = f"{label}.checks[{index}]"
                if not fields(check, CHECK_FIELDS, check_label, errors):
                    continue
                line = source_location(check["location"], source_root, f"{check_label}.location", errors)
                if not isinstance(check["contains"], str) or not check["contains"].strip():
                    errors.append(f"{check_label}.contains must be non-empty")
                elif line is not None and check["contains"] not in line:
                    errors.append(f"{check_label} does not match its exact source line")
            if checks != sorted(checks, key=lambda item: (item.get("location", ""), item.get("contains", "")) if isinstance(item, dict) else ("", "")):
                errors.append(f"{label}.checks are not deterministically ordered")
    elif value["dimension"] == "runtime":
        if value["expected"] != "pass":
            errors.append(f"{label} runtime mapping must require a pass")
        if fixture != "" or checks != []:
            errors.append(f"{label} runtime mapping cannot contain fixture/source checks")


def validate_feature_map(
    feature_map: object,
    audit: dict[str, object],
    expected: dict[str, object],
    source_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not fields(feature_map, ROOT_FIELDS, "feature_map", errors):
        return errors
    assert isinstance(feature_map, dict)
    if feature_map["schema_version"] != "1.1":
        errors.append("feature_map.schema_version must be 1.1")
    if feature_map["current_audit_path"] != AUDIT_PATH:
        errors.append("feature_map.current_audit_path differs from the immutable audit")
    policy = feature_map["dimension_policy"]
    if not isinstance(policy, dict) or list(policy) != ["enum", "syntax", "source_contract", "runtime"]:
        errors.append("feature_map.dimension_policy fields/order differ")
    elif policy["enum"] != DIMENSIONS:
        errors.append("feature_map.dimension_policy enum differs")
    elif "non-runtime" not in str(policy["source_contract"]):
        errors.append("source_contract policy must explicitly be non-runtime")
    audit_entries = audit.get("entries")
    if not isinstance(audit_entries, list):
        return errors + ["current audit entries must be an array"]
    audit_ids = [entry.get("id") for entry in audit_entries if isinstance(entry, dict)]
    if feature_map["feature_count"] != len(audit_entries):
        errors.append("feature_map.feature_count differs from the immutable audit")
    catalog_values = feature_map["test_catalog"]
    if not isinstance(catalog_values, list) or len(catalog_values) != 4:
        errors.append("feature_map.test_catalog must contain the four registered tests")
        catalog_values = []
    catalog: dict[str, dict[str, object]] = {}
    catalog_fields = ["test_id", "path", "meson_test", "dimension"]
    for index, item in enumerate(catalog_values):
        if not fields(item, catalog_fields, f"feature_map.test_catalog[{index}]", errors):
            continue
        assert isinstance(item, dict)
        catalog[str(item["test_id"])] = item
        repository_path(item["path"], source_root, f"feature_map.test_catalog[{index}].path", errors)
    if [item.get("test_id") for item in catalog_values if isinstance(item, dict)] != sorted(catalog):
        errors.append("feature_map.test_catalog is not ordered by test ID")
    meson_text = (source_root / "meson.build").read_text(encoding="utf-8")
    for registered in catalog_values:
        if not isinstance(registered, dict):
            continue
        if (f"'{registered['meson_test']}'" not in meson_text or
                str(registered["path"]) not in meson_text):
            errors.append(f"registered test is absent from meson.build: {registered!r}")
    entries = feature_map["entries"]
    if not isinstance(entries, list):
        return errors + ["feature_map.entries must be an array"]
    entry_ids = [entry.get("feature_id") for entry in entries if isinstance(entry, dict)]
    if entry_ids != audit_ids:
        missing = [identifier for identifier in audit_ids if identifier not in entry_ids]
        extra = [identifier for identifier in entry_ids if identifier not in audit_ids]
        if missing:
            errors.append(f"feature map misses audit IDs: {', '.join(str(item) for item in missing[:8])}")
        if extra:
            errors.append(f"feature map has extra IDs: {', '.join(str(item) for item in extra[:8])}")
        if not missing and not extra:
            errors.append("feature map entries are reordered relative to the immutable audit")
    if len(entry_ids) != len(set(entry_ids)):
        errors.append("feature map has duplicate feature IDs")
    for index, (item, feature) in enumerate(zip(entries, audit_entries)):
        label = f"feature_map.entries[{index}]"
        if not fields(item, ENTRY_FIELDS, label, errors) or not isinstance(feature, dict):
            continue
        assert isinstance(item, dict)
        if item["feature_id"] != feature.get("id"):
            errors.append(f"{label}.feature_id differs from the immutable audit")
        if item["category"] != feature.get("category"):
            errors.append(f"{label}.category differs from the immutable audit")
        if item["implementation_status"] != feature.get("native_wayland_status"):
            errors.append(f"{label}.implementation_status differs from the immutable audit")
        tests = item["tests"]
        if not isinstance(tests, list) or not tests:
            errors.append(f"{label}.tests must map the feature to at least one automated case")
            continue
        for test_index, mapping in enumerate(tests):
            validate_mapping(mapping, feature, source_root, catalog, f"{label}.tests[{test_index}]", errors)
        dimensions = [mapping.get("dimension") for mapping in tests if isinstance(mapping, dict)]
        expected_dimensions = [] if feature.get("category") == "runtime_dispatch" else ["syntax"]
        if feature.get("native_wayland_status") == "effective":
            expected_dimensions.append("source_contract")
        if feature.get("id") in INTERACTION_RUNTIME_FEATURES:
            expected_dimensions.append("runtime")
        if feature.get("id") in RESTART_RUNTIME_FEATURES:
            expected_dimensions.append("runtime")
        expected_dimensions.sort()
        if dimensions != expected_dimensions:
            errors.append(f"{label}.tests dimensions must be {expected_dimensions}")
        keys = [
            (mapping.get("test_id"), mapping.get("case"), mapping.get("dimension"))
            for mapping in tests if isinstance(mapping, dict)
        ]
        if len(keys) != len(set(keys)):
            errors.append(f"{label}.tests contains duplicate cases")
    syntax_fixtures = [
        mapping.get("fixture")
        for entry in entries if isinstance(entry, dict)
        for mapping in entry.get("tests", []) if isinstance(mapping, dict)
        if mapping.get("dimension") == "syntax"
    ]
    if len(syntax_fixtures) != len(set(syntax_fixtures)):
        errors.append("syntax cases must use one unique dedicated fixture per feature")
    if canonical(feature_map) != canonical(expected):
        errors.append("feature map differs from the deterministic generated mapping")
    return errors


def execute_cases(feature_map: dict[str, object], source_root: Path, config_tool: Path) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="wtwm-feature-cases.") as temporary:
        temp_root = Path(temporary)
        for entry in feature_map["entries"]:  # type: ignore[index]
            for mapping in entry["tests"]:
                if mapping["dimension"] == "syntax":
                    path = temp_root / (str(entry["feature_id"]).replace(".", "-") + ".twmrc")
                    path.write_text(mapping["fixture"], encoding="utf-8")
                    result = subprocess.run(
                        [str(config_tool), str(path)],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    expected_accept = mapping["expected"] == "accept"
                    if (result.returncode == 0) != expected_accept:
                        errors.append(
                            f"{entry['feature_id']} syntax case expected "
                            f"{mapping['expected']}: "
                            f"{result.stderr.strip() or result.stdout.strip()}"
                        )
    return errors


def tamper_self_test(
    feature_map: dict[str, object],
    audit: dict[str, object],
    expected: dict[str, object],
    source_root: Path,
) -> int:
    mutations: list[tuple[str, dict[str, object]]] = []
    changed = copy.deepcopy(feature_map)
    changed["entries"].pop(0)  # type: ignore[union-attr]
    mutations.append(("deleted-feature", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"].append(copy.deepcopy(changed["entries"][0]))  # type: ignore[union-attr,index]
    mutations.append(("duplicate-feature", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0], changed["entries"][1] = changed["entries"][1], changed["entries"][0]  # type: ignore[index]
    mutations.append(("reordered-features", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0]["tests"] = []  # type: ignore[index]
    mutations.append(("missing-mapping", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0]["tests"][0]["case"] = "another.feature"  # type: ignore[index]
    mutations.append(("irrelevant-case", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0]["tests"][0]["dimension"] = "runtime"  # type: ignore[index]
    mutations.append(("invalid-runtime-claim", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0]["tests"][0]["expected"] = "sometimes"  # type: ignore[index]
    mutations.append(("invalid-expected-result", changed))
    changed = copy.deepcopy(feature_map)
    changed["entries"][0]["tests"][0]["fixture"] = "OpaqueMove\n"  # type: ignore[index]
    mutations.append(("stale-fixture", changed))
    changed = copy.deepcopy(feature_map)
    first_fixture = changed["entries"][0]["tests"][0]["fixture"]  # type: ignore[index]
    changed["entries"][1]["tests"][0]["fixture"] = first_fixture  # type: ignore[index]
    mutations.append(("shared-fixture", changed))
    changed = copy.deepcopy(feature_map)
    effective = next(
        entry for entry in changed["entries"]  # type: ignore[union-attr]
        if any(test["dimension"] == "source_contract" for test in entry["tests"])
    )
    source_mapping = next(test for test in effective["tests"] if test["dimension"] == "source_contract")
    source_mapping["checks"][0]["contains"] = "not present in source"
    mutations.append(("invalid-source-contract", changed))
    failures = [
        name for name, changed in mutations
        if not validate_feature_map(changed, audit, expected, source_root)
    ]
    if failures:
        print("feature-map tamper self-test failed to reject: " + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"feature-map tamper self-test: {len(mutations)} omissions/mutations rejected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--config-tool", required=True, type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    config_tool = args.config_tool.resolve()
    try:
        audit = json.loads((source_root / AUDIT_PATH).read_text(encoding="utf-8"))
        path = source_root / MAP_PATH
        raw = path.read_text(encoding="utf-8")
        feature_map = json.loads(raw)
        expected, expected_summary = build(source_root)
        errors = validate_feature_map(feature_map, audit, expected, source_root)
        if raw != canonical(feature_map):
            errors.append("feature-test map JSON is not canonical")
        summary = (source_root / SUMMARY_PATH).read_text(encoding="utf-8")
        if summary != expected_summary:
            errors.append("feature-test summary is stale")
        if not config_tool.is_file():
            errors.append(f"config tool does not exist: {config_tool}")
        if not errors:
            errors.extend(execute_cases(feature_map, source_root, config_tool))
        if errors:
            for error in errors:
                print(f"feature-map error: {error}", file=sys.stderr)
            return 1
        if args.self_test_tamper:
            status = tamper_self_test(feature_map, audit, expected, source_root)
            if status:
                return status
        syntax_count = sum(
            test["dimension"] == "syntax"
            for entry in feature_map["entries"] for test in entry["tests"]
        )
        contract_count = sum(
            test["dimension"] == "source_contract"
            for entry in feature_map["entries"] for test in entry["tests"]
        )
        runtime_count = sum(
            test["dimension"] == "runtime"
            for entry in feature_map["entries"] for test in entry["tests"]
        )
        print(
            f"current feature coverage valid: {len(feature_map['entries'])} features, "
            f"{syntax_count} syntax cases, {contract_count} source-contract cases, "
            f"{runtime_count} runtime claims"
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"feature-map validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
