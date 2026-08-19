#!/usr/bin/env python3
"""Validate the twm restart evidence and wtwm Wayland translation contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path("reference/lifecycle/twm-1.0.13.1/restart-contract.json")
INVENTORY_PATH = Path("reference/inventory/twm-1.0.13.1.json")
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/parse.c": (
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c"
    ),
    "twm-1.0.13.1/src/twm.c": (
        "6a8c95df4df186a970e56ed7da4013f6305823c4a9b99cbebfe08f076f01ab3d"
    ),
}
EXPECTED_EVIDENCE = {
    "parse.f-restart": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 461,
        "text": '    { "f.restart",              FKEYWORD, F_RESTART },',
    },
    "parse.f-twmrc": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 471,
        "text": '    { "f.twmrc",                FKEYWORD, F_RESTART },',
    },
    "startup.argc": {
        "member": "twm-1.0.13.1/src/twm.c",
        "line": 216,
        "text": "    Argc = argc;",
    },
    "startup.argv": {
        "member": "twm-1.0.13.1/src/twm.c",
        "line": 217,
        "text": "    Argv = argv;",
    },
    "restart.dispatch": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1271,
        "text": "    case F_RESTART:",
    },
    "restart.reborder": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1274,
        "text": "        Reborder(eventp->xbutton.time);",
    },
    "restart.exec-original-argv": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1278,
        "text": "        execvp(*Argv, Argv);",
    },
}
EXPECTED_ALIAS_NAMES = ["f.restart", "f.twmrc"]
EXPECTED_SEQUENCE = [
    "synchronize-x-server",
    "reborder-managed-windows",
    "synchronize-x-server",
    "close-session-manager-connection-if-present",
    "exec-original-argv",
]
EXPECTED_PHASES = [
    "parse replacement configuration into isolated candidate state",
    "validate the complete candidate without mutating the active generation",
    "atomically publish the candidate and refresh compositor-owned observable state",
    "on any failure discard the candidate and retain the active generation and session",
]
EXPECTED_PROTOCOLS = ["native-wayland", "xwayland"]
EXPECTED_MANAGED_STATE = [
    "client-and-surface-identity",
    "mapping-and-iconification",
    "geometry",
    "stacking",
    "focus",
]
EXPECTED_REFRESH = [
    "bindings-and-action-resolution",
    "menus-and-named-functions",
    "configuration-derived-policy",
    "decorations-colors-fonts-and-cursors",
    "compositor-owned-icons-and-icon-managers",
]
EXPECTED_PRESERVED_OBSERVABLE_STATE = [
    "managed-client-identity",
    "mapping-and-iconification",
    "geometry",
    "stacking",
    "focus",
]
EXPECTED_REQUIREMENT_EVIDENCE = {
    "restart.action-identity": [
        "parse.f-restart",
        "parse.f-twmrc",
        "restart.dispatch",
    ],
    "restart.in-process-atomic": ["restart.exec-original-argv"],
    "restart.native-continuity": ["restart.exec-original-argv"],
    "restart.xwayland-continuity": [
        "restart.reborder",
        "restart.exec-original-argv",
    ],
    "restart.invalid-retention": ["restart.exec-original-argv"],
    "restart.observable-refresh": ["restart.dispatch"],
}
EXPECTED_SCENARIOS = {
    "alias-equivalence",
    "valid-restart-with-active-clients",
    "invalid-restart-with-active-clients",
    "repeated-valid-invalid-restart",
}


def load_json(path: Path) -> Any:
    """Load JSON while rejecting duplicate object keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


class Archive:
    """Read members and exact lines from the pinned source archive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._members: dict[str, bytes] = {}

    def read(self, member: str) -> bytes:
        if member not in self._members:
            with tarfile.open(self.path, "r:xz") as source:
                extracted = source.extractfile(member)
                if extracted is None:
                    raise KeyError(f"archive member does not exist: {member}")
                self._members[member] = extracted.read()
        return self._members[member]

    def line(self, member: str, number: int) -> str:
        lines = self.read(member).decode("utf-8").splitlines()
        if number < 1 or number > len(lines):
            raise IndexError(f"line {number} is outside {member} (1..{len(lines)})")
        return lines[number - 1]

    def source_occurrences(
        self, pattern: re.Pattern[str]
    ) -> list[tuple[str, int, str]]:
        matches: list[tuple[str, int, str]] = []
        with tarfile.open(self.path, "r:xz") as source:
            names = [
                name
                for name in source.getnames()
                if name.startswith("twm-1.0.13.1/src/")
                and (name.endswith(".c") or name.endswith(".h"))
            ]
        for name in names:
            for number, line in enumerate(
                self.read(name).decode("utf-8").splitlines(), start=1
            ):
                if pattern.search(line):
                    matches.append((name, number, line))
        return matches


def records_by_id(
    value: Any, location: str, errors: list[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(value):
        where = f"{location}[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{where} must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{where}.id must be a nonempty string")
            continue
        if record_id in records:
            errors.append(f"duplicate {location} id {record_id!r}")
        records[record_id] = record
    return records


def referenced_evidence(
    value: Any, location: str = "contract"
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if location == "contract" and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, str):
                yield f"{location}.{key}", child
                continue
            if key == "evidence" and isinstance(child, list):
                for index, evidence_id in enumerate(child):
                    if isinstance(evidence_id, str):
                        yield f"{location}.{key}[{index}]", evidence_id
                continue
            yield from referenced_evidence(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from referenced_evidence(child, f"{location}[{index}]")


def require_nonempty_text(
    record: dict[str, Any], field: str, location: str, errors: list[str]
) -> None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{location}.{field} must be a nonempty string")


def require_exact_fields(
    record: Any,
    expected: dict[str, Any],
    location: str,
    errors: list[str],
    allowed_extra_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(record, dict):
        errors.append(f"{location} must be an object")
        return {}
    expected_fields = set(expected) | set(allowed_extra_fields)
    if set(record) != expected_fields:
        errors.append(
            f"{location} fields differ from schema: got {sorted(record)}, "
            f"expected {sorted(expected_fields)}"
        )
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            errors.append(
                f"{location}.{field} must be {expected_value!r}, "
                f"got {record.get(field)!r}"
            )
    return record


def validate(
    contract: dict[str, Any],
    inventory: dict[str, Any],
    source_root: Path,
) -> list[str]:
    errors: list[str] = []

    expected_top_level = {
        "schema_version",
        "contract",
        "upstream",
        "source_members",
        "evidence",
        "reference_behavior",
        "wayland_translation",
        "requirements",
        "verification_scenarios",
    }
    if set(contract) != expected_top_level:
        errors.append(
            "contract top-level fields differ from schema: "
            f"got {sorted(contract)}"
        )
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    require_nonempty_text(contract, "contract", "contract", errors)

    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append(
            "upstream identity must exactly pin the approved archive and inventory"
        )
    inventory_upstream = inventory.get("upstream")
    expected_inventory_upstream = {
        key: EXPECTED_UPSTREAM[key]
        for key in ("name", "version", "archive", "sha256")
    }
    if inventory_upstream != expected_inventory_upstream:
        errors.append("inventory upstream identity differs from the approved reference")

    archive_path = source_root / EXPECTED_UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append(f"upstream archive is missing: {archive_path}")
        return errors
    actual_archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual_archive_hash != EXPECTED_UPSTREAM["sha256"]:
        errors.append(
            f"archive hash mismatch: expected {EXPECTED_UPSTREAM['sha256']}, "
            f"got {actual_archive_hash}"
        )
        return errors
    archive = Archive(archive_path)

    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source_members must exactly pin parse.c, twm.c, and menus.c")
    for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
        try:
            actual_hash = hashlib.sha256(archive.read(member)).hexdigest()
        except KeyError as exc:
            errors.append(str(exc))
            continue
        if actual_hash != expected_hash:
            errors.append(
                f"source member hash mismatch for {member}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
        evidence = {}
    if evidence != EXPECTED_EVIDENCE:
        errors.append("evidence catalog differs from the frozen exact source anchors")
    for evidence_id, anchor in EXPECTED_EVIDENCE.items():
        try:
            actual_line = archive.line(anchor["member"], anchor["line"])
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"evidence.{evidence_id} cannot be read: {exc}")
            continue
        if actual_line != anchor["text"]:
            errors.append(
                f"evidence.{evidence_id} mismatch at "
                f"{anchor['member']}:{anchor['line']}: "
                f"expected {anchor['text']!r}, got {actual_line!r}"
            )

    inventory_keywords = inventory.get("keywords")
    if not isinstance(inventory_keywords, list):
        errors.append("inventory.keywords must be an array")
        inventory_keywords = []
    keyword_by_spelling = {
        keyword.get("spelling"): keyword
        for keyword in inventory_keywords
        if isinstance(keyword, dict)
        and keyword.get("spelling") in EXPECTED_ALIAS_NAMES
    }

    reference_behavior = contract.get("reference_behavior")
    if not isinstance(reference_behavior, dict) or set(reference_behavior) != {
        "action_identity",
        "process_restart",
    }:
        errors.append(
            "reference_behavior must contain action_identity and process_restart"
        )
        reference_behavior = {}
    action_identity = reference_behavior.get("action_identity")
    if not isinstance(action_identity, dict) or set(action_identity) != {
        "normalized_action",
        "aliases",
        "rule",
    }:
        errors.append("reference_behavior.action_identity has invalid fields")
        action_identity = {}
    if action_identity.get("normalized_action") != "F_RESTART":
        errors.append("reference action identity must be F_RESTART")
    require_nonempty_text(action_identity, "rule", "reference action identity", errors)
    aliases = action_identity.get("aliases")
    if not isinstance(aliases, list):
        errors.append("reference action aliases must be an array")
        aliases = []
    if [alias.get("name") for alias in aliases if isinstance(alias, dict)] != (
        EXPECTED_ALIAS_NAMES
    ):
        errors.append("reference action aliases must be f.restart then f.twmrc")
    for alias in aliases:
        if not isinstance(alias, dict):
            errors.append("reference action alias must be an object")
            continue
        name = alias.get("name")
        inventory_record = keyword_by_spelling.get(name)
        if inventory_record is None:
            errors.append(f"inventory lacks restart alias {name!r}")
            continue
        expected_alias = {
            "name": name,
            "inventory_id": inventory_record.get("id"),
            "parser_token": inventory_record.get("parser_token"),
            "parser_value": inventory_record.get("parser_value"),
            "evidence": "parse.f-restart" if name == "f.restart" else "parse.f-twmrc",
        }
        if alias != expected_alias:
            errors.append(f"reference alias {name!r} differs from inventory")
        if inventory_record.get("parser_value") != "F_RESTART":
            errors.append(f"inventory alias {name!r} does not normalize to F_RESTART")
        expected_inventory_evidence = EXPECTED_EVIDENCE[expected_alias["evidence"]]
        inventory_evidence = inventory_record.get("evidence", {})
        normalized_inventory_evidence = {
            "member": inventory_evidence.get("archive_member"),
            "line": inventory_evidence.get("line"),
            "text": inventory_evidence.get("text"),
        }
        if normalized_inventory_evidence != expected_inventory_evidence:
            errors.append(f"inventory evidence for {name!r} differs from frozen source")

    process_restart = reference_behavior.get("process_restart")
    process_restart = require_exact_fields(
        process_restart,
        {
            "execution_model": "replace-process-image",
            "program": "*Argv",
            "arguments": "Argv",
            "argv_origin": "main-argv",
            "argv_assignment_count": 1,
            "sequence": EXPECTED_SEQUENCE,
            "evidence": [
                "startup.argc",
                "startup.argv",
                "restart.dispatch",
                "restart.reborder",
                "restart.exec-original-argv",
            ],
        },
        "reference_behavior.process_restart",
        errors,
        allowed_extra_fields=("rule",),
    )
    require_nonempty_text(
        process_restart, "rule", "reference_behavior.process_restart", errors
    )
    argv_assignments = archive.source_occurrences(re.compile(r"\bArgv\s*="))
    if argv_assignments != [
        ("twm-1.0.13.1/src/twm.c", 217, "    Argv = argv;")
    ]:
        errors.append(
            "upstream Argv assignment set changed; original-argv proof is invalid: "
            f"{argv_assignments!r}"
        )
    argv_execs = archive.source_occurrences(
        re.compile(r"^\s*execvp\(\*Argv,\s*Argv\);$")
    )
    if argv_execs != [
        (
            "twm-1.0.13.1/src/menus.c",
            1278,
            "        execvp(*Argv, Argv);",
        )
    ]:
        errors.append(f"upstream original-argv exec proof changed: {argv_execs!r}")

    translation = contract.get("wayland_translation")
    if not isinstance(translation, dict) or set(translation) != {
        "action_identity",
        "restart_transaction",
        "client_continuity",
        "invalid_replacement",
        "observable_refresh",
    }:
        errors.append("wayland_translation fields differ from schema")
        translation = {}
    require_exact_fields(
        translation.get("action_identity"),
        {
            "normalized_action": "F_RESTART",
            "aliases": EXPECTED_ALIAS_NAMES,
            "dispatch": "one-shared-handler",
            "alias_specific_behavior": False,
        },
        "wayland_translation.action_identity",
        errors,
    )
    require_exact_fields(
        translation.get("restart_transaction"),
        {
            "execution_model": "in-process",
            "atomicity": "prepare-validate-commit-or-no-change",
            "candidate_config_isolated": True,
            "commit_only_after_full_validation": True,
            "exec_or_exit": False,
            "phases": EXPECTED_PHASES,
        },
        "wayland_translation.restart_transaction",
        errors,
    )
    require_exact_fields(
        translation.get("client_continuity"),
        {
            "required_protocols": EXPECTED_PROTOCOLS,
            "connection_identity_preserved": True,
            "restart_xwayland": False,
            "disconnect_clients": False,
            "preserve_managed_state": EXPECTED_MANAGED_STATE,
        },
        "wayland_translation.client_continuity",
        errors,
    )
    require_exact_fields(
        translation.get("invalid_replacement"),
        {
            "result": "reject-and-retain-active-session",
            "active_config_preserved": True,
            "active_generation_preserved": True,
            "observable_state_unchanged": True,
            "clients_preserved": True,
            "diagnostic_required": True,
        },
        "wayland_translation.invalid_replacement",
        errors,
    )
    require_exact_fields(
        translation.get("observable_refresh"),
        {
            "trigger": "successful-transaction-commit-only",
            "publish_as_one_generation": True,
            "refresh_before_next_input_dispatch": EXPECTED_REFRESH,
            "preserve_unless_new_config_explicitly_changes_presentation": (
                EXPECTED_PRESERVED_OBSERVABLE_STATE
            ),
            "failed_transaction_refresh": "none",
        },
        "wayland_translation.observable_refresh",
        errors,
    )

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != set(EXPECTED_REQUIREMENT_EVIDENCE):
        errors.append(
            "requirement coverage mismatch: "
            f"got {sorted(requirements)}, "
            f"expected {sorted(EXPECTED_REQUIREMENT_EVIDENCE)}"
        )
    for requirement_id, expected_evidence in EXPECTED_REQUIREMENT_EVIDENCE.items():
        requirement = requirements.get(requirement_id, {})
        if set(requirement) != {"id", "level", "rule", "evidence"}:
            errors.append(f"requirement {requirement_id} fields differ from schema")
        if requirement.get("level") != "MUST":
            errors.append(f"requirement {requirement_id} must have level MUST")
        require_nonempty_text(
            requirement, "rule", f"requirement {requirement_id}", errors
        )
        if requirement.get("evidence") != expected_evidence:
            errors.append(
                f"requirement {requirement_id} evidence differs from contract"
            )

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    if set(scenarios) != EXPECTED_SCENARIOS:
        errors.append(
            f"verification scenario coverage mismatch: got {sorted(scenarios)}"
        )
    alias_scenario = scenarios.get("alias-equivalence", {})
    if alias_scenario.get("actions") != EXPECTED_ALIAS_NAMES:
        errors.append("alias-equivalence must exercise both restart spellings")
    for scenario_id, scenario in scenarios.items():
        expected_fields = (
            {"id", "actions", "oracle"}
            if scenario_id == "alias-equivalence"
            else {"id", "protocols", "oracle"}
        )
        if set(scenario) != expected_fields:
            errors.append(f"scenario {scenario_id} fields differ from schema")
        require_nonempty_text(scenario, "oracle", f"scenario {scenario_id}", errors)
        if scenario_id != "alias-equivalence" and scenario.get("protocols") != (
            EXPECTED_PROTOCOLS
        ):
            errors.append(
                f"scenario {scenario_id} must cover native Wayland and Xwayland"
            )

    used_evidence: set[str] = set()
    for location, evidence_id in referenced_evidence(contract):
        used_evidence.add(evidence_id)
        if evidence_id not in EXPECTED_EVIDENCE:
            errors.append(f"{location} references unknown evidence {evidence_id!r}")
    unused_evidence = sorted(set(EXPECTED_EVIDENCE) - used_evidence)
    if unused_evidence:
        errors.append(f"unreferenced evidence anchors: {', '.join(unused_evidence)}")

    return errors


def self_test_tamper(
    contract: dict[str, Any], inventory: dict[str, Any], source_root: Path
) -> list[str]:
    """Prove representative upstream and translation corruption is rejected."""

    mutations: list[tuple[str, dict[str, Any]]] = []

    broken_alias = copy.deepcopy(contract)
    broken_alias["reference_behavior"]["action_identity"]["aliases"][1][
        "parser_value"
    ] = "F_RELOAD"
    mutations.append(("broken upstream alias", broken_alias))

    broken_anchor = copy.deepcopy(contract)
    broken_anchor["evidence"]["restart.exec-original-argv"]["text"] += " tampered"
    mutations.append(("broken exact source anchor", broken_anchor))

    external_restart = copy.deepcopy(contract)
    external_restart["wayland_translation"]["restart_transaction"][
        "execution_model"
    ] = "replace-process-image"
    mutations.append(("external Wayland restart", external_restart))

    dropped_xwayland = copy.deepcopy(contract)
    dropped_xwayland["wayland_translation"]["client_continuity"][
        "required_protocols"
    ] = ["native-wayland"]
    mutations.append(("missing Xwayland continuity", dropped_xwayland))

    destructive_failure = copy.deepcopy(contract)
    destructive_failure["wayland_translation"]["invalid_replacement"][
        "active_config_preserved"
    ] = False
    mutations.append(("invalid config destroys active state", destructive_failure))

    missing_refresh = copy.deepcopy(contract)
    missing_refresh["wayland_translation"]["observable_refresh"][
        "refresh_before_next_input_dispatch"
    ].pop()
    mutations.append(("incomplete observable refresh", missing_refresh))

    failures: list[str] = []
    for label, mutation in mutations:
        if not validate(mutation, inventory, source_root):
            failures.append(f"self-test mutation was not detected: {label}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    contract_path = args.contract or source_root / CONTRACT_PATH
    inventory_path = args.inventory or source_root / INVENTORY_PATH
    try:
        contract = load_json(contract_path)
        inventory = load_json(inventory_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"restart contract validation failed: {exc}", file=sys.stderr)
        return 1
    if not isinstance(contract, dict) or not isinstance(inventory, dict):
        print(
            "restart contract validation failed: contract and inventory must be "
            "objects",
            file=sys.stderr,
        )
        return 1

    try:
        errors = validate(contract, inventory, source_root)
        if args.self_test_tamper and not errors:
            errors.extend(self_test_tamper(contract, inventory, source_root))
    except (OSError, tarfile.TarError) as exc:
        print(f"restart contract validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("restart contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    suffix = " with tamper self-tests" if args.self_test_tamper else ""
    print(
        "restart contract valid: 2 aliases, 6 Wayland requirements, "
        f"4 scenarios, {len(EXPECTED_EVIDENCE)} exact source anchors{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
