#!/usr/bin/env python3
"""Generate and validate the deterministic twm compatibility ledger."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = "1.0"
SCHEMA_PATH = "reference/ledger/schema-1.0.json"
INVENTORY_PATH = "reference/inventory/twm-1.0.13.1.json"
INVENTORY_SECTIONS = ("keywords", "grammar", "lexical_forms")
ROOT_FIELDS = [
    "schema_version",
    "schema_path",
    "inventory_path",
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
ASSESSMENT_FIELDS = ["status", "notes"]
TEST_COVERAGE_FIELDS = ["status", "mappings", "notes"]
TEST_MAPPING_FIELDS = ["test_id", "path", "case", "dimensions", "assertions"]
DIFFERENCES_FIELDS = ["status", "visual", "semantic", "notes"]
DIFFERENCE_FIELDS = ["summary", "evidence", "tests"]

SYNTAX_STATUSES = ["unassessed", "unsupported", "partial", "complete"]
BEHAVIOR_STATUSES = [
    "unassessed",
    "unsupported",
    "parsed-only",
    "partial",
    "behaviorally-equivalent",
    "exact",
    "verified-no-op",
    "not-applicable",
]
TEST_STATUSES = ["unassessed", "none", "partial", "complete"]
DIFFERENCE_STATUSES = ["unassessed", "none-known", "known"]
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
        "phase": "inventory-initialized",
        "initial_status": "unassessed",
        "scope": (
            "One row for every keyword, grammar alternative, and successful lexer "
            "form in the frozen upstream inventory."
        ),
        "next_step": (
            "Milestone 0 implementation item 4 audits the current wtwm "
            "implementation and replaces unassessed values with evidence-backed "
            "assessments."
        ),
    }


def _assessment() -> dict[str, object]:
    return {"status": "unassessed", "notes": []}


def _ledger_entry(section: str, upstream: dict[str, object]) -> dict[str, object]:
    return {
        "id": upstream["id"],
        "inventory_section": section,
        "upstream": copy.deepcopy(upstream),
        "syntax_support": _assessment(),
        "runtime_support": _assessment(),
        "native_wayland_behavior": _assessment(),
        "xwayland_behavior": _assessment(),
        "test_coverage": {"status": "unassessed", "mappings": [], "notes": []},
        "differences": {
            "status": "unassessed",
            "visual": [],
            "semantic": [],
            "notes": [],
        },
    }


def build_ledger(inventory: dict[str, object]) -> dict[str, object]:
    entries = []
    for section in INVENTORY_SECTIONS:
        section_entries = inventory.get(section)
        if not isinstance(section_entries, list):
            raise ValueError(f"inventory {section} must be an array")
        for upstream in section_entries:
            if not isinstance(upstream, dict):
                raise ValueError(f"inventory {section} contains a non-object row")
            entries.append(_ledger_entry(section, upstream))
    reference = inventory.get("upstream")
    if not isinstance(reference, dict):
        raise ValueError("inventory upstream identity must be an object")
    return {
        "schema_version": SCHEMA_VERSION,
        "schema_path": SCHEMA_PATH,
        "inventory_path": INVENTORY_PATH,
        "reference": copy.deepcopy(reference),
        "assessment_policy": _policy(),
        "entries": entries,
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
        phases = definitions["assessment_policy"]["properties"]["phase"]["enum"]  # type: ignore[index]
        categories = definitions["categories"]["items"]["enum"]  # type: ignore[index]
    except (KeyError, TypeError):
        sections = phases = categories = None
    if sections != list(INVENTORY_SECTIONS):
        errors.append("schema inventory section enum differs from its fixed order")
    if phases != ["inventory-initialized", "current-implementation-audited"]:
        errors.append("schema assessment phase enum differs from its fixed order")
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
    if not full_path.is_file():
        errors.append(f"{label} path does not exist: {path_text}")
        return
    try:
        line_count = len(full_path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError) as error:
        errors.append(f"{label} cannot be read: {error}")
        return
    if int(line_text) > line_count:
        errors.append(f"{label} line is outside the file: {value}")


def _validate_assessment(
    value: object,
    statuses: list[str],
    label: str,
    errors: list[str],
) -> None:
    if not _dict_fields(value, ASSESSMENT_FIELDS, label, errors):
        return
    assert isinstance(value, dict)
    if value["status"] not in statuses:
        errors.append(f"{label}.status has invalid enum value {value['status']!r}")
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
        elif not (source_root / path).is_file():
            errors.append(f"{label}.path does not exist")
    if not isinstance(value["case"], str) or not value["case"].strip():
        errors.append(f"{label}.case must identify the exact test case")
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
    if status in {"unassessed", "none"} and mappings:
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
    if status in {"unassessed", "none-known"} and (visual or semantic):
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
    if _canonical_json(ledger["reference"]) != _canonical_json(inventory.get("upstream")):
        errors.append("ledger reference identity differs from the upstream inventory")
    if not _dict_fields(ledger["assessment_policy"], POLICY_FIELDS, "assessment_policy", errors):
        return errors
    policy = ledger["assessment_policy"]
    assert isinstance(policy, dict)
    if policy["phase"] not in {"inventory-initialized", "current-implementation-audited"}:
        errors.append("assessment_policy.phase has an invalid enum value")
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
            entry["syntax_support"], SYNTAX_STATUSES, f"{label}.syntax_support", errors
        )
        for field in ("runtime_support", "native_wayland_behavior", "xwayland_behavior"):
            _validate_assessment(entry[field], BEHAVIOR_STATUSES, f"{label}.{field}", errors)
        mapping_ids = _validate_test_coverage(
            entry["test_coverage"], source_root, f"{label}.test_coverage", errors
        )
        _validate_differences(
            entry["differences"], mapping_ids, source_root, f"{label}.differences", errors
        )
        if policy["phase"] == "inventory-initialized":
            assessment_statuses = [
                entry[field].get("status") if isinstance(entry[field], dict) else None
                for field in (
                    "syntax_support",
                    "runtime_support",
                    "native_wayland_behavior",
                    "xwayland_behavior",
                    "test_coverage",
                    "differences",
                )
            ]
            if any(status != "unassessed" for status in assessment_statuses):
                errors.append(f"{label} makes a status claim during inventory initialization")
            for field in (
                "syntax_support",
                "runtime_support",
                "native_wayland_behavior",
                "xwayland_behavior",
            ):
                value = entry[field]
                if isinstance(value, dict) and value.get("notes"):
                    errors.append(f"{label}.{field} has notes before implementation audit")
            coverage = entry["test_coverage"]
            if isinstance(coverage, dict) and (coverage.get("mappings") or coverage.get("notes")):
                errors.append(f"{label}.test_coverage contains pre-audit claims")
            differences = entry["differences"]
            if isinstance(differences, dict) and any(
                differences.get(field) for field in ("visual", "semantic", "notes")
            ):
                errors.append(f"{label}.differences contains pre-audit claims")
    return errors


def _tamper_self_test(
    ledger: dict[str, object],
    inventory: dict[str, object],
    schema: dict[str, object],
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
    changed["assessment_policy"]["phase"] = "current-implementation-audited"  # type: ignore[index]
    mutations.append(("malformed-test-mapping", changed))
    changed = copy.deepcopy(ledger)
    changed["entries"][0]["differences"]["status"] = "known"  # type: ignore[index]
    changed["entries"][0]["differences"]["visual"] = [  # type: ignore[index]
        {"summary": "difference", "evidence": ["/tmp/file:1"], "tests": []}
    ]
    changed["assessment_policy"]["phase"] = "current-implementation-audited"  # type: ignore[index]
    mutations.append(("malformed-difference-evidence", changed))

    failures = [
        name
        for name, changed in mutations
        if not validate_ledger(changed, inventory, source_root)
    ]
    changed_schema = copy.deepcopy(schema)
    changed_schema["$defs"]["syntax_assessment"]["properties"]["status"]["enum"].append("invented")  # type: ignore[index]
    if not validate_schema(changed_schema):
        failures.append("schema-enum-tamper")
    if failures:
        print(f"tamper self-test failed to reject: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"tamper self-test: {len(mutations) + 1} ledger/schema mutations rejected")
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
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    inventory_path = args.inventory or source_root / INVENTORY_PATH
    schema_path = args.schema or source_root / SCHEMA_PATH
    ledger_path = args.ledger or source_root / "reference/ledger/twm-1.0.13.1.json"
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
        if args.write:
            ledger = build_ledger(inventory)
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(_canonical_json(ledger), encoding="utf-8")
            print(f"wrote {ledger_path}")
            return 0
        ledger, ledger_raw = _load_object(ledger_path, "ledger")
        errors = validate_ledger(ledger, inventory, source_root)
        if ledger_raw != _canonical_json(ledger):
            errors.append("compatibility ledger JSON is not canonically formatted")
        if errors:
            for error in errors:
                print(f"ledger error: {error}", file=sys.stderr)
            return 1
        if args.self_test_tamper:
            status = _tamper_self_test(ledger, inventory, schema, source_root)
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
            f"{counts['lexical_forms']} lexical forms); assessments unassessed"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"compatibility ledger validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
