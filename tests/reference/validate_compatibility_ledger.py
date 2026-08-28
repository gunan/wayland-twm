#!/usr/bin/env python3
"""Validate the assessed deterministic twm compatibility ledger."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import re
import sys
from pathlib import Path, PurePosixPath

from assess_current_implementation import build as build_assessment


SCHEMA_VERSION = "1.1"
SCHEMA_PATH = "reference/ledger/schema-1.1.json"
INVENTORY_PATH = "reference/inventory/twm-1.0.13.1.json"
CURRENT_AUDIT_PATH = "reference/audits/current-implementation.json"
CROSSWALK_PATH = "reference/audits/current-to-ledger.json"
INVENTORY_SECTIONS = ("keywords", "grammar", "lexical_forms")
ROOT_FIELDS = [
    "schema_version",
    "schema_path",
    "inventory_path",
    "current_audit_path",
    "crosswalk_path",
    "reference",
    "assessment_policy",
    "entries",
]
POLICY_FIELDS = ["phase", "initial_status", "scope", "next_step"]
ENTRY_FIELDS = [
    "id",
    "inventory_section",
    "upstream",
    "syntax_support",
    "runtime_support",
    "native_wayland_behavior",
    "xwayland_behavior",
    "test_coverage",
    "differences",
]
ASSESSMENT_FIELDS = ["status", "evidence", "notes"]
TEST_COVERAGE_FIELDS = ["status", "evidence", "mappings", "notes"]
TEST_MAPPING_FIELDS = ["test_id", "path", "case", "dimensions", "assertions"]
DIFFERENCES_FIELDS = ["status", "evidence", "visual", "semantic", "notes"]
DIFFERENCE_FIELDS = ["summary", "evidence", "tests"]

SYNTAX_STATUSES = ["unsupported", "partial", "complete"]
BEHAVIOR_STATUSES = [
    "unsupported",
    "parsed-only",
    "partial",
    "behaviorally-equivalent",
    "exact",
    "verified-no-op",
    "not-applicable",
    "unavailable",
]
TEST_STATUSES = ["none", "partial", "complete"]
DIFFERENCE_STATUSES = ["none-known", "known"]
TEST_DIMENSIONS = [
    "syntax",
    "runtime",
    "native-wayland",
    "xwayland",
    "visual",
    "semantic",
]
CATEGORY_ENUM = [
    "directive",
    "color-monochrome-option",
    "window-list-directive",
    "mouse-binding-form",
    "key-binding-form",
    "binding-context",
    "binding-modifier",
    "built-in-action",
    "menu-construct",
    "icon-option",
    "icon-manager-option",
    "cursor-option",
    "pixmap-option",
    "font-option",
    "placement-option",
    "title-button-option",
    "direction-or-justification",
    "lexical-form",
    "grammar-structure",
]
FORBIDDEN_FIELDS = {
    "absolute_path",
    "cwd",
    "generated_at",
    "host",
    "hostname",
    "timestamp",
}
TEST_ID_RE = re.compile(r"test\.[a-z0-9]+(?:[._-][a-z0-9]+)*")


def _canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def _policy() -> dict[str, str]:
    return {
        "phase": "current-implementation-audited",
        "initial_status": "unassessed",
        "scope": (
            "One row for every keyword, grammar alternative, and successful lexer "
            "form in the frozen upstream inventory."
        ),
        "next_step": (
            "Keep every row reconciled with focused parser, runtime, native "
            "Wayland, Xwayland, visual, and semantic evidence."
        ),
    }


def _dict_fields(value: object, expected: list[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    if list(value) != expected:
        errors.append(f"{label} fields/order must be: {', '.join(expected)}")
        return False
    return True


def _fixed_enum(schema: dict[str, object], definition: str) -> object:
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        return None
    item = definitions.get(definition, {})
    if not isinstance(item, dict):
        return None
    properties = item.get("properties", {})
    if not isinstance(properties, dict):
        return None
    status = properties.get("status", {})
    return status.get("enum") if isinstance(status, dict) else None


def validate_schema(schema: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["schema root must be an object"]
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        errors.append("schema draft identifier is not fixed")
    if schema.get("$id") != SCHEMA_PATH:
        errors.append("schema $id is not repository-relative and fixed")
    if schema.get("additionalProperties") is not False:
        errors.append("schema root must reject additional properties")
    if schema.get("required") != ROOT_FIELDS:
        errors.append("schema root required fields/order differ")
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return errors + ["schema $defs must be an object"]
    required_fields = {
        "reference": ["name", "version", "archive", "sha256"],
        "assessment_policy": POLICY_FIELDS,
        "ledger_entry": ENTRY_FIELDS,
        "upstream_keyword": [
            "id",
            "spelling",
            "parser_token",
            "parser_value",
            "categories",
            "evidence",
        ],
        "upstream_grammar": [
            "id",
            "production",
            "ordinal",
            "syntax",
            "categories",
            "evidence",
        ],
        "upstream_lexical_form": ["id", "pattern", "categories", "evidence"],
        "upstream_evidence": ["archive_member", "line", "text"],
        "syntax_assessment": ASSESSMENT_FIELDS,
        "behavior_assessment": ASSESSMENT_FIELDS,
        "test_coverage": TEST_COVERAGE_FIELDS,
        "test_mapping": TEST_MAPPING_FIELDS,
        "differences": DIFFERENCES_FIELDS,
        "difference": DIFFERENCE_FIELDS,
    }
    for name, expected in required_fields.items():
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            errors.append(f"schema definition is missing: {name}")
        else:
            if definition.get("required") != expected:
                errors.append(f"schema {name} required fields/order differ")
            if definition.get("additionalProperties") is not False:
                errors.append(f"schema {name} must reject additional properties")
    for name, expected in (
        ("syntax_assessment", SYNTAX_STATUSES),
        ("behavior_assessment", BEHAVIOR_STATUSES),
        ("test_coverage", TEST_STATUSES),
        ("differences", DIFFERENCE_STATUSES),
    ):
        if _fixed_enum(schema, name) != expected:
            errors.append(f"schema {name} status enum differs from its fixed order")
    test_dimensions = definitions.get("test_mapping", {})
    try:
        dimensions = test_dimensions["properties"]["dimensions"]["items"]["enum"]  # type: ignore[index]
    except (KeyError, TypeError):
        dimensions = None
    if dimensions != TEST_DIMENSIONS:
        errors.append("schema test dimension enum differs from its fixed order")
    try:
        sections = definitions["ledger_entry"]["properties"]["inventory_section"]["enum"]  # type: ignore[index]
        phase = definitions["assessment_policy"]["properties"]["phase"]["const"]  # type: ignore[index]
        categories = definitions["categories"]["items"]["enum"]  # type: ignore[index]
    except (KeyError, TypeError):
        sections = phase = categories = None
    if sections != list(INVENTORY_SECTIONS):
        errors.append("schema inventory section enum differs from its fixed order")
    if phase != "current-implementation-audited":
        errors.append("schema assessment phase is not the audited phase")
    if categories != CATEGORY_ENUM:
        errors.append("schema category enum differs from its fixed order")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append("schema properties must be an object")
    else:
        for name, expected in (
            ("schema_version", SCHEMA_VERSION),
            ("schema_path", SCHEMA_PATH),
            ("inventory_path", INVENTORY_PATH),
            ("current_audit_path", CURRENT_AUDIT_PATH),
            ("crosswalk_path", CROSSWALK_PATH),
        ):
            definition = properties.get(name, {})
            if not isinstance(definition, dict) or definition.get("const") != expected:
                errors.append(f"schema {name} const differs from its fixed value")
    return errors


def _walk_for_nondeterminism(value: object, label: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        bad = FORBIDDEN_FIELDS.intersection(value)
        if bad:
            errors.append(f"{label} contains nondeterministic fields: {', '.join(sorted(bad))}")
        for key, child in value.items():
            _walk_for_nondeterminism(child, f"{label}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_for_nondeterminism(child, f"{label}[{index}]", errors)


def _repository_path(value: object, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value or "//" in value:
        errors.append(f"{label} is not a canonical repository-relative path")
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or str(path) != value:
        errors.append(f"{label} is not a canonical repository-relative path")
        return None
    return Path(*path.parts)


def _sorted_unique_strings(value: object, label: str, errors: list[str]) -> bool:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{label} must be an array of non-empty strings")
        return False
    if value != sorted(set(value)):
        errors.append(f"{label} must be sorted and deduplicated")
        return False
    return True


@lru_cache(maxsize=None)
def _is_file(path: Path) -> bool:
    return path.is_file()


@lru_cache(maxsize=None)
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _line_count(path: Path) -> int:
    return len(_read_text(path).splitlines())


def _location(
    value: object, source_root: Path, label: str, errors: list[str]
) -> None:
    if not isinstance(value, str) or ":" not in value:
        errors.append(f"{label} is not an exact repository path:line location")
        return
    path_text, line_text = value.rsplit(":", 1)
    path = _repository_path(path_text, label, errors)
    if path is None or not re.fullmatch(r"[1-9][0-9]*", line_text):
        errors.append(f"{label} is not an exact repository path:line location")
        return
    full_path = source_root / path
    if not _is_file(full_path):
        errors.append(f"{label} path does not exist: {path_text}")
        return
    try:
        line_count = _line_count(full_path)
    except (OSError, UnicodeDecodeError) as error:
        errors.append(f"{label} cannot be read: {error}")
        return
    if int(line_text) > line_count:
        errors.append(f"{label} line is outside the file: {value}")


def _validate_evidence(
    value: object, source_root: Path, label: str, errors: list[str]
) -> None:
    if not _sorted_unique_strings(value, label, errors):
        return
    assert isinstance(value, list)
    if not value:
        errors.append(f"{label} must contain exact repository evidence")
    for index, location in enumerate(value):
        _location(location, source_root, f"{label}[{index}]", errors)


def _validate_assessment(
    value: object,
    statuses: list[str],
    source_root: Path,
    label: str,
    errors: list[str],
) -> None:
    if not _dict_fields(value, ASSESSMENT_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    if value["status"] not in statuses:
        errors.append(f"{label}.status has invalid enum value {value['status']!r}")
    _validate_evidence(value["evidence"], source_root, f"{label}.evidence", errors)
    _sorted_unique_strings(value["notes"], f"{label}.notes", errors)


def _validate_mapping(
    value: object, source_root: Path, label: str, errors: list[str]
) -> None:
    if not _dict_fields(value, TEST_MAPPING_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    if not isinstance(value["test_id"], str) or not TEST_ID_RE.fullmatch(value["test_id"]):
        errors.append(f"{label}.test_id is not a stable test ID")
    path = _repository_path(value["path"], f"{label}.path", errors)
    if path is not None:
        if not path.parts or path.parts[0] != "tests":
            errors.append(f"{label}.path must be below tests/")
        elif not _is_file(source_root / path):
            errors.append(f"{label}.path does not exist")
    if not isinstance(value["case"], str) or not value["case"].strip():
        errors.append(f"{label}.case must identify the exact test case")
    elif path is not None and path.suffix == ".c" and _is_file(source_root / path):
        source = _read_text(source_root / path)
        case_pattern = re.compile(
            rf"\bstatic\s+void\s+{re.escape(value['case'])}\s*\(\s*void\s*\)"
        )
        if not case_pattern.search(source):
            errors.append(f"{label}.case is not an exact C test function in {value['path']}")
        expected_id = "test.config." + value["case"].replace("_", "-")
        if value["path"] == "tests/config_test.c" and value["test_id"] != expected_id:
            errors.append(f"{label}.test_id does not match its exact config test case")
    dimensions = value["dimensions"]
    if not isinstance(dimensions, list) or not dimensions:
        errors.append(f"{label}.dimensions must be a non-empty array")
    elif any(dimension not in TEST_DIMENSIONS for dimension in dimensions):
        errors.append(f"{label}.dimensions contains an invalid enum value")
    else:
        expected = [item for item in TEST_DIMENSIONS if item in dimensions]
        if dimensions != expected:
            errors.append(f"{label}.dimensions must be deduplicated in enum order")
    if not _sorted_unique_strings(value["assertions"], f"{label}.assertions", errors):
        return
    if not value["assertions"]:
        errors.append(f"{label}.assertions must describe exact coverage")


def _validate_test_coverage(
    value: object, source_root: Path, label: str, errors: list[str]
) -> set[str]:
    if not _dict_fields(value, TEST_COVERAGE_FIELDS, label, errors):
        return set()
    assert isinstance(value, dict)
    status = value["status"]
    if status not in TEST_STATUSES:
        errors.append(f"{label}.status has invalid enum value {status!r}")
    _validate_evidence(value["evidence"], source_root, f"{label}.evidence", errors)
    mappings = value["mappings"]
    if not isinstance(mappings, list):
        errors.append(f"{label}.mappings must be an array")
        mappings = []
    for index, mapping in enumerate(mappings):
        _validate_mapping(mapping, source_root, f"{label}.mappings[{index}]", errors)
    if isinstance(value["mappings"], list):
        ordering = lambda item: (
            item.get("test_id", ""),
            item.get("path", ""),
            item.get("case", ""),
        ) if isinstance(item, dict) else ("", "", "")
        if value["mappings"] != sorted(value["mappings"], key=ordering):
            errors.append(f"{label}.mappings must be deterministically ordered")
        mapping_ids = [
            mapping.get("test_id")
            for mapping in value["mappings"]
            if isinstance(mapping, dict)
        ]
        if len(mapping_ids) != len(set(mapping_ids)):
            errors.append(f"{label}.mappings has duplicate test IDs")
    else:
        mapping_ids = []
    if status == "none" and mappings:
        errors.append(f"{label}.status {status!r} cannot have mappings")
    if status in {"partial", "complete"} and not mappings:
        errors.append(f"{label}.status {status!r} requires exact mappings")
    _sorted_unique_strings(value["notes"], f"{label}.notes", errors)
    return {identifier for identifier in mapping_ids if isinstance(identifier, str)}


def _validate_difference(
    value: object,
    mapping_ids: set[str],
    source_root: Path,
    label: str,
    errors: list[str],
) -> None:
    if not _dict_fields(value, DIFFERENCE_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        errors.append(f"{label}.summary must be non-empty")
    if _sorted_unique_strings(value["evidence"], f"{label}.evidence", errors):
        if not value["evidence"]:
            errors.append(f"{label}.evidence must not be empty")
        for index, location in enumerate(value["evidence"]):
            _location(location, source_root, f"{label}.evidence[{index}]", errors)
    if _sorted_unique_strings(value["tests"], f"{label}.tests", errors):
        for test_id in value["tests"]:
            if not TEST_ID_RE.fullmatch(test_id):
                errors.append(f"{label}.tests contains an invalid test ID")
            elif test_id not in mapping_ids:
                errors.append(f"{label}.tests references an unmapped test ID")


def _validate_differences(
    value: object,
    mapping_ids: set[str],
    source_root: Path,
    label: str,
    errors: list[str],
) -> None:
    if not _dict_fields(value, DIFFERENCES_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    status = value["status"]
    if status not in DIFFERENCE_STATUSES:
        errors.append(f"{label}.status has invalid enum value {status!r}")
    _validate_evidence(value["evidence"], source_root, f"{label}.evidence", errors)
    for kind in ("visual", "semantic"):
        records = value[kind]
        if not isinstance(records, list):
            errors.append(f"{label}.{kind} must be an array")
            continue
        for index, record in enumerate(records):
            _validate_difference(
                record,
                mapping_ids,
                source_root,
                f"{label}.{kind}[{index}]",
                errors,
            )
        ordering = lambda item: item.get("summary", "") if isinstance(item, dict) else ""
        if records != sorted(records, key=ordering):
            errors.append(f"{label}.{kind} must be deterministically ordered")
    visual = value["visual"] if isinstance(value["visual"], list) else []
    semantic = value["semantic"] if isinstance(value["semantic"], list) else []
    if status == "none-known" and (visual or semantic):
        errors.append(f"{label}.status {status!r} cannot have difference records")
    if status == "known" and not (visual or semantic):
        errors.append(f"{label}.status 'known' requires a visual or semantic record")
    _sorted_unique_strings(value["notes"], f"{label}.notes", errors)


def validate_ledger(
    ledger: object,
    inventory: dict[str, object],
    source_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not _dict_fields(ledger, ROOT_FIELDS, "ledger", errors):
        return errors
    assert isinstance(ledger, dict)
    _walk_for_nondeterminism(ledger, "ledger", errors)
    if ledger["schema_version"] != SCHEMA_VERSION:
        errors.append("ledger schema_version differs from the fixed schema")
    if ledger["schema_path"] != SCHEMA_PATH:
        errors.append("ledger schema_path differs from the fixed repository path")
    if ledger["inventory_path"] != INVENTORY_PATH:
        errors.append("ledger inventory_path differs from the fixed repository path")
    if ledger["current_audit_path"] != CURRENT_AUDIT_PATH:
        errors.append("ledger current_audit_path differs from the fixed repository path")
    if ledger["crosswalk_path"] != CROSSWALK_PATH:
        errors.append("ledger crosswalk_path differs from the fixed repository path")
    if _canonical_json(ledger["reference"]) != _canonical_json(inventory.get("upstream")):
        errors.append("ledger reference identity differs from the upstream inventory")
    if not _dict_fields(ledger["assessment_policy"], POLICY_FIELDS, "assessment_policy", errors):
        return errors
    policy = ledger["assessment_policy"]
    assert isinstance(policy, dict)
    if policy["phase"] != "current-implementation-audited":
        errors.append("assessment_policy.phase must be current-implementation-audited")
    if policy["initial_status"] != "unassessed":
        errors.append("assessment_policy.initial_status must remain unassessed")
    canonical_policy = _policy()
    for field in ("scope", "next_step"):
        if policy[field] != canonical_policy[field]:
            errors.append(f"assessment_policy.{field} differs from the fixed policy")

    expected_rows: list[tuple[str, dict[str, object]]] = []
    for section in INVENTORY_SECTIONS:
        rows = inventory.get(section)
        if not isinstance(rows, list):
            errors.append(f"inventory {section} must be an array")
            continue
        for row in rows:
            if isinstance(row, dict):
                expected_rows.append((section, row))
            else:
                errors.append(f"inventory {section} contains a non-object row")
    entries = ledger["entries"]
    if not isinstance(entries, list):
        return errors + ["ledger.entries must be an array"]
    actual_ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
    expected_ids = [row["id"] for _, row in expected_rows]
    missing = [identifier for identifier in expected_ids if identifier not in actual_ids]
    extra = [identifier for identifier in actual_ids if identifier not in expected_ids]
    if missing:
        errors.append(f"ledger rows missing inventory IDs: {', '.join(str(item) for item in missing[:8])}")
    if extra:
        errors.append(f"ledger rows contain extra IDs: {', '.join(str(item) for item in extra[:8])}")
    if not missing and not extra and actual_ids != expected_ids:
        errors.append("ledger rows are reordered relative to the inventory")
    if len(actual_ids) != len(set(actual_ids)):
        errors.append("ledger row IDs are not unique")
    if len(entries) != len(expected_rows):
        errors.append(
            f"ledger has {len(entries)} rows but inventory requires {len(expected_rows)}"
        )

    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not _dict_fields(entry, ENTRY_FIELDS, label, errors):
            continue
        assert isinstance(entry, dict)
        if index < len(expected_rows):
            section, upstream = expected_rows[index]
            if entry["id"] != upstream.get("id"):
                errors.append(f"{label}.id differs from the inventory row")
            if entry["inventory_section"] != section:
                errors.append(f"{label}.inventory_section differs from the inventory")
            if _canonical_json(entry["upstream"]) != _canonical_json(upstream):
                errors.append(f"{label}.upstream differs from the exact inventory row")
        _validate_assessment(
            entry["syntax_support"], SYNTAX_STATUSES, source_root,
            f"{label}.syntax_support", errors
        )
        for field in ("runtime_support", "native_wayland_behavior", "xwayland_behavior"):
            _validate_assessment(
                entry[field], BEHAVIOR_STATUSES, source_root, f"{label}.{field}", errors
            )
        mapping_ids = _validate_test_coverage(
            entry["test_coverage"], source_root, f"{label}.test_coverage", errors
        )
        _validate_differences(
            entry["differences"], mapping_ids, source_root, f"{label}.differences", errors
        )
        syntax = entry["syntax_support"].get("status") if isinstance(entry["syntax_support"], dict) else None
        runtime = entry["runtime_support"].get("status") if isinstance(entry["runtime_support"], dict) else None
        native = entry["native_wayland_behavior"].get("status") if isinstance(entry["native_wayland_behavior"], dict) else None
        xwayland = entry["xwayland_behavior"].get("status") if isinstance(entry["xwayland_behavior"], dict) else None
        if syntax == "unsupported" and runtime in {"partial", "behaviorally-equivalent", "exact"}:
            errors.append(f"{label} cannot claim runtime implementation with unsupported syntax")
        if runtime == "parsed-only" and native not in {"parsed-only", "not-applicable"}:
            errors.append(f"{label} parsed-only runtime is inconsistent with native behavior")
        for field, status in (("runtime_support", runtime), ("native_wayland_behavior", native), ("xwayland_behavior", xwayland)):
            if status in {"exact", "behaviorally-equivalent", "verified-no-op"} and not mapping_ids:
                errors.append(f"{label}.{field} strong equivalence/no-op claim requires exact tests")
        categories = set(entry["upstream"].get("categories", [])) if isinstance(entry["upstream"], dict) else set()
        behavior_relevant = (
            entry["inventory_section"] != "lexical_forms"
            and categories != {"grammar-structure"}
        )
        strong = {"exact", "behaviorally-equivalent", "verified-no-op"}
        dimensions = {
            dimension
            for mapping in entry["test_coverage"].get("mappings", [])
            if isinstance(mapping, dict)
            for dimension in mapping.get("dimensions", [])
            if isinstance(dimension, str)
        } if isinstance(entry["test_coverage"], dict) else set()
        if behavior_relevant:
            for field, status in (
                ("runtime_support", runtime),
                ("native_wayland_behavior", native),
                ("xwayland_behavior", xwayland),
            ):
                if status not in strong:
                    errors.append(f"{label}.{field} remains unresolved: {status!r}")
            for required in ("runtime", "native-wayland", "xwayland", "semantic"):
                if required not in dimensions:
                    errors.append(f"{label} closure lacks {required!r} test evidence")
            if not isinstance(entry["test_coverage"], dict) or entry["test_coverage"].get("status") != "complete":
                errors.append(f"{label} behavior closure requires complete test coverage")
            if not isinstance(entry["differences"], dict) or entry["differences"].get("status") != "known":
                errors.append(f"{label} behavior closure requires an explained difference record")
        else:
            for field, status in (
                ("runtime_support", runtime),
                ("native_wayland_behavior", native),
                ("xwayland_behavior", xwayland),
            ):
                if status != "not-applicable":
                    errors.append(f"{label}.{field} syntax-only row must be not-applicable")
    return errors


def validate_crosswalk(
    crosswalk: object,
    current_audit: dict[str, object],
    ledger: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    fields = [
        "schema_version", "current_audit_path", "ledger_path", "audited_commit",
        "mappings", "unmapped_ledger_ids",
    ]
    if not _dict_fields(crosswalk, fields, "crosswalk", errors):
        return errors
    assert isinstance(crosswalk, dict)
    if crosswalk["schema_version"] != "1.0":
        errors.append("crosswalk schema_version must be 1.0")
    if crosswalk["current_audit_path"] != CURRENT_AUDIT_PATH:
        errors.append("crosswalk current_audit_path differs from the fixed path")
    if crosswalk["ledger_path"] != "reference/ledger/twm-1.0.13.1.json":
        errors.append("crosswalk ledger_path differs from the fixed path")
    if crosswalk["audited_commit"] != current_audit.get("audited_commit"):
        errors.append("crosswalk audited_commit differs from the current audit")
    audit_entries = current_audit.get("entries")
    if not isinstance(audit_entries, list):
        return errors + ["current audit entries must be an array"]
    audit_by_id = {
        entry.get("id"): entry for entry in audit_entries if isinstance(entry, dict)
    }
    audit_ids = [entry.get("id") for entry in audit_entries if isinstance(entry, dict)]
    if len(audit_ids) != len(set(audit_ids)):
        errors.append("current audit IDs are not unique")
    ledger_entries = ledger.get("entries")
    ledger_ids = {
        entry.get("id") for entry in ledger_entries if isinstance(entry, dict)
    } if isinstance(ledger_entries, list) else set()
    mappings = crosswalk["mappings"]
    if not isinstance(mappings, list):
        return errors + ["crosswalk mappings must be an array"]
    mapping_fields = ["current_id", "classification", "ledger_ids", "notes"]
    classifications = {"ledger-mapped", "current-only", "runtime-dispatch", "out-of-upstream-scope"}
    mapping_ids: list[object] = []
    mapped_ledger: set[object] = set()
    for index, mapping in enumerate(mappings):
        label = f"crosswalk.mappings[{index}]"
        if not _dict_fields(mapping, mapping_fields, label, errors):
            continue
        assert isinstance(mapping, dict)
        current_id = mapping["current_id"]
        mapping_ids.append(current_id)
        if current_id not in audit_by_id:
            errors.append(f"{label}.current_id is not in the current audit")
        classification = mapping["classification"]
        if classification not in classifications:
            errors.append(f"{label}.classification is invalid")
        target_ids = mapping["ledger_ids"]
        if not _sorted_unique_strings(target_ids, f"{label}.ledger_ids", errors):
            target_ids = []
        if classification == "ledger-mapped" and not target_ids:
            errors.append(f"{label} ledger-mapped entry requires at least one ledger ID")
        if classification != "ledger-mapped" and target_ids:
            errors.append(f"{label} non-ledger classification cannot contain ledger IDs")
        for target_id in target_ids:
            if target_id not in ledger_ids:
                errors.append(f"{label} references an unknown ledger ID: {target_id}")
            mapped_ledger.add(target_id)
        audit_entry = audit_by_id.get(current_id)
        if classification == "runtime-dispatch" and (
            not isinstance(audit_entry, dict) or audit_entry.get("category") != "runtime_dispatch"
        ):
            errors.append(f"{label} runtime-dispatch classification disagrees with the audit")
        if not isinstance(mapping["notes"], str) or not mapping["notes"].strip():
            errors.append(f"{label}.notes must explain the mapping")
    if mapping_ids != sorted(mapping_ids):
        errors.append("crosswalk mappings are not ordered by current ID")
    if len(mapping_ids) != len(set(mapping_ids)):
        errors.append("crosswalk has duplicate current IDs")
    missing_current = sorted(set(audit_ids) - set(mapping_ids))
    extra_current = sorted(set(mapping_ids) - set(audit_ids))
    if missing_current:
        errors.append(f"crosswalk misses current-audit IDs: {', '.join(str(item) for item in missing_current[:8])}")
    if extra_current:
        errors.append(f"crosswalk has extra current IDs: {', '.join(str(item) for item in extra_current[:8])}")
    unmapped = crosswalk["unmapped_ledger_ids"]
    if _sorted_unique_strings(unmapped, "crosswalk.unmapped_ledger_ids", errors):
        expected_unmapped = sorted(ledger_ids - mapped_ledger)
        if unmapped != expected_unmapped:
            errors.append("crosswalk unmapped_ledger_ids is not the exact ledger complement")
    return errors


def validate_summary(summary: str, ledger: dict[str, object], crosswalk: dict[str, object]) -> list[str]:
    errors: list[str] = []
    entries = ledger.get("entries", [])
    if not isinstance(entries, list):
        return ["cannot validate summary without ledger entries"]
    dimensions = (
        "syntax_support", "runtime_support", "native_wayland_behavior",
        "xwayland_behavior", "test_coverage", "differences",
    )
    for dimension in dimensions:
        counts = {}
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get(dimension), dict):
                status = entry[dimension].get("status")
                counts[status] = counts.get(status, 0) + 1
        for status, count in counts.items():
            marker = f"| `{dimension}` | `{status}` | {count} |"
            if marker not in summary:
                errors.append(f"audit summary is missing count: {marker}")
    mappings = crosswalk.get("mappings", [])
    if isinstance(mappings, list):
        counts = {}
        for mapping in mappings:
            if isinstance(mapping, dict):
                value = mapping.get("classification")
                counts[value] = counts.get(value, 0) + 1
        for classification, count in counts.items():
            marker = f"| `{classification}` | {count} |"
            if marker not in summary:
                errors.append(f"audit summary is missing crosswalk count: {marker}")
    return errors


def _tamper_self_test(
    ledger: dict[str, object],
    inventory: dict[str, object],
    schema: dict[str, object],
    crosswalk: dict[str, object],
    current_audit: dict[str, object],
    source_root: Path,
) -> int:
    mutations: list[tuple[str, dict[str, object]]] = []
    changed = copy.deepcopy(ledger)
    changed["entries"].pop(0)  # type: ignore[union-attr]
    mutations.append(("missing-row", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"].append(copy.deepcopy(changed["entries"][0]))  # type: ignore[union-attr,index]
    mutations.append(("extra-row", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0], changed["entries"][1] = changed["entries"][1], changed["entries"][0]  # type: ignore[index]
    mutations.append(("reordered-rows", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["syntax_support"]["status"] = "invented"  # type: ignore[index]
    mutations.append(("invalid-enum", changed))
    changed = copy.deepcopy(ledger)
    changed["generated_at"] = "today"
    mutations.append(("nondeterministic-field", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["upstream"]["evidence"]["line"] = 1  # type: ignore[index]
    mutations.append(("upstream-tamper", changed))
    changed = copy.deepcopy(ledger)
    coverage = changed["entries"][0]["test_coverage"]  # type: ignore[index]
    coverage["status"] = "partial"
    coverage["mappings"] = [
        {
            "test_id": "malformed id",
            "path": "/tmp/nondeterministic.py",
            "case": "",
            "dimensions": ["not-a-dimension"],
        }
    ]
    mutations.append(("malformed-test-mapping", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["differences"]["status"] = "known"  # type: ignore[index]
    changed["entries"][0]["differences"]["visual"] = [  # type: ignore[index]
        {"summary": "difference", "evidence": ["/tmp/file:1"], "tests": []}
    ]
    mutations.append(("malformed-difference-evidence", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["runtime_support"]["status"] = "unassessed"  # type: ignore[index]
    mutations.append(("remaining-unassessed", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["syntax_support"]["evidence"] = []  # type: ignore[index]
    mutations.append(("missing-assessment-evidence", changed))
    changed = copy.deepcopy(ledger)
    covered = next(
        entry for entry in changed["entries"]  # type: ignore[union-attr]
        if any(
            mapping["path"] == "tests/config_test.c"
            for mapping in entry["test_coverage"]["mappings"]
        )
    )
    exact_c_mapping = next(
        mapping for mapping in covered["test_coverage"]["mappings"]
        if mapping["path"] == "tests/config_test.c"
    )
    exact_c_mapping["case"] = "not_an_existing_test_case"
    mutations.append(("nonexistent-test-case", changed))

    failures = [
        name
        for name, changed in mutations
        if not validate_ledger(changed, inventory, source_root)
    ]
    changed_schema = copy.deepcopy(schema)
    changed_schema["$defs"]["syntax_assessment"]["properties"]["status"]["enum"].append("invented")  # type: ignore[index]
    if not validate_schema(changed_schema):
        failures.append("schema-enum-tamper")
    changed_crosswalk = copy.deepcopy(crosswalk)
    changed_crosswalk["mappings"].pop(0)  # type: ignore[union-attr]
    if not validate_crosswalk(changed_crosswalk, current_audit, ledger):
        failures.append("missing-current-audit-mapping")
    changed = copy.deepcopy(ledger)
    complete = next(
        entry for entry in changed["entries"]  # type: ignore[union-attr]
        if entry["syntax_support"]["status"] == "complete"
    )
    complete["syntax_support"]["status"] = "partial"
    expected_ledger, _, _ = build_assessment(source_root)
    if _canonical_json(changed) == _canonical_json(expected_ledger):
        failures.append("deterministic-assessment-tamper")
    if failures:
        print(f"tamper self-test failed to reject: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"tamper self-test: {len(mutations) + 3} ledger/schema/crosswalk mutations rejected")
    return 0


def _load_object(path: Path, label: str) -> tuple[dict[str, object], str]:
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value, raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    inventory_path = args.inventory or source_root / INVENTORY_PATH
    schema_path = args.schema or source_root / SCHEMA_PATH
    ledger_path = args.ledger or source_root / "reference/ledger/twm-1.0.13.1.json"
    current_audit_path = source_root / CURRENT_AUDIT_PATH
    crosswalk_path = source_root / CROSSWALK_PATH
    summary_path = source_root / "docs/audits/compatibility-ledger.md"
    try:
        inventory, inventory_raw = _load_object(inventory_path, "inventory")
        schema, schema_raw = _load_object(schema_path, "schema")
        schema_errors = validate_schema(schema)
        if inventory_raw != _canonical_json(inventory):
            schema_errors.append("upstream inventory JSON is not canonically formatted")
        if schema_raw != _canonical_json(schema):
            schema_errors.append("compatibility ledger schema JSON is not canonically formatted")
        if schema_errors:
            for error in schema_errors:
                print(f"ledger schema error: {error}", file=sys.stderr)
            return 1
        ledger, ledger_raw = _load_object(ledger_path, "ledger")
        current_audit, _ = _load_object(current_audit_path, "current audit")
        crosswalk, crosswalk_raw = _load_object(crosswalk_path, "crosswalk")
        summary_raw = summary_path.read_text(encoding="utf-8")
        errors = validate_ledger(ledger, inventory, source_root)
        errors.extend(validate_crosswalk(crosswalk, current_audit, ledger))
        errors.extend(validate_summary(summary_raw, ledger, crosswalk))
        expected_ledger, expected_crosswalk, expected_summary = build_assessment(source_root)
        if ledger_raw != _canonical_json(expected_ledger):
            errors.append("compatibility ledger differs from the deterministic current audit assessment")
        if crosswalk_raw != _canonical_json(expected_crosswalk):
            errors.append("current-to-ledger crosswalk differs from the deterministic mapping")
        if summary_raw != expected_summary:
            errors.append("human audit summary differs from the machine-checked assessment counts")
        if ledger_raw != _canonical_json(ledger):
            errors.append("compatibility ledger JSON is not canonically formatted")
        if crosswalk_raw != _canonical_json(crosswalk):
            errors.append("current-to-ledger crosswalk JSON is not canonically formatted")
        if errors:
            for error in errors:
                print(f"ledger error: {error}", file=sys.stderr)
            return 1
        if args.self_test_tamper:
            status = _tamper_self_test(
                ledger, inventory, schema, crosswalk, current_audit, source_root
            )
            if status:
                return status
        counts = {
            section: sum(1 for entry in ledger["entries"] if entry["inventory_section"] == section)
            for section in INVENTORY_SECTIONS
        }
        print(
            "compatibility ledger valid: "
            f"{len(ledger['entries'])} rows "
            f"({counts['keywords']} keywords, {counts['grammar']} grammar alternatives, "
            f"{counts['lexical_forms']} lexical forms); current implementation audited, "
            f"{len(crosswalk['mappings'])} current entries crosswalked"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"compatibility ledger validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
