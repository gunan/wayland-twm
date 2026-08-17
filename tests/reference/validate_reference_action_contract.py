#!/usr/bin/env python3
"""Validate the frozen twm 1.0.13.1 Milestone 6 action contract."""

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
DEFAULT_CONTRACT = ROOT / "reference/actions/twm-1.0.13.1/action-contract.json"
DEFAULT_INVENTORY = ROOT / "reference/inventory/twm-1.0.13.1.json"
EXPECTED_ACTION_COUNT = 66
EXPECTED_BEHAVIOR_COUNT = 59
REQUIRED_CONTEXTS = {
    "window",
    "title",
    "icon",
    "root",
    "frame",
    "iconmgr",
    "name",
    "all",
}
REQUIRED_MODIFIERS = {
    "shift",
    "control",
    "lock",
    "meta",
    "meta-number",
    "none",
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


def builtin_inventory(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        keyword
        for keyword in inventory.get("keywords", [])
        if "built-in-action" in keyword.get("categories", [])
    ]


def inventory_spellings(inventory: dict[str, Any], category: str) -> set[str]:
    return {
        keyword["spelling"]
        for keyword in inventory.get("keywords", [])
        if category in keyword.get("categories", [])
    }


class ArchiveLines:
    """Read and cache pinned archive members as source lines."""

    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self._members: dict[str, list[str]] = {}

    def line(self, member: str, number: int) -> str:
        if member not in self._members:
            with tarfile.open(self.archive, "r:xz") as source:
                extracted = source.extractfile(member)
                if extracted is None:
                    raise KeyError(f"archive member does not exist: {member}")
                text = extracted.read().decode("utf-8")
            self._members[member] = text.splitlines()
        lines = self._members[member]
        if number < 1 or number > len(lines):
            raise IndexError(
                f"line {number} is outside {member} (1..{len(lines)})"
            )
        return lines[number - 1]


def walk_evidence(value: Any, location: str = "contract") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if set(value) == {"member", "line", "text"}:
            yield location, value
            return
        for key, child in value.items():
            yield from walk_evidence(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_evidence(child, f"{location}[{index}]")


def validate(
    contract: dict[str, Any],
    inventory: dict[str, Any],
    archive_path: Path,
) -> list[str]:
    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(message)

    if contract.get("schema_version") != 1:
        error("contract.schema_version must be 1")

    upstream = contract.get("upstream")
    if not isinstance(upstream, dict):
        error("contract.upstream must be an object")
        upstream = {}
    expected_hash = upstream.get("sha256")
    inventory_upstream = inventory.get("upstream", {})
    if expected_hash != inventory_upstream.get("sha256"):
        error("contract and inventory archive hashes differ")
    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if expected_hash != actual_hash:
        error(f"archive hash mismatch: expected {expected_hash}, got {actual_hash}")

    expected_actions = builtin_inventory(inventory)
    if len(expected_actions) != EXPECTED_ACTION_COUNT:
        error(
            f"inventory has {len(expected_actions)} built-in actions; "
            f"expected {EXPECTED_ACTION_COUNT}"
        )
    expected_by_name = {action["spelling"]: action for action in expected_actions}
    if len(expected_by_name) != len(expected_actions):
        error("inventory contains duplicate built-in action spellings")

    actions = contract.get("actions")
    if not isinstance(actions, list):
        error("contract.actions must be an array")
        actions = []
    action_by_name: dict[str, dict[str, Any]] = {}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            error(f"actions[{index}] must be an object")
            continue
        name = action.get("name")
        if not isinstance(name, str):
            error(f"actions[{index}].name must be a string")
            continue
        if name in action_by_name:
            error(f"duplicate contract action {name}")
        action_by_name[name] = action

    missing = sorted(set(expected_by_name) - set(action_by_name))
    extra = sorted(set(action_by_name) - set(expected_by_name))
    if missing:
        error(f"contract is missing inventory actions: {', '.join(missing)}")
    if extra:
        error(f"contract has actions absent from inventory: {', '.join(extra)}")

    action_member = contract.get("action_table_member")
    if action_member != "twm-1.0.13.1/src/parse.c":
        error("action_table_member must pin twm-1.0.13.1/src/parse.c")

    archive = ArchiveLines(archive_path)
    for name in sorted(set(expected_by_name) & set(action_by_name)):
        expected = expected_by_name[name]
        actual = action_by_name[name]
        evidence = expected.get("evidence", {})
        for field, expected_value in (
            ("parser_token", expected.get("parser_token")),
            ("behavior", expected.get("parser_value")),
            ("line", evidence.get("line")),
        ):
            if actual.get(field) != expected_value:
                error(
                    f"{name}.{field} is {actual.get(field)!r}; "
                    f"inventory requires {expected_value!r}"
                )
        if evidence.get("archive_member") != action_member:
            error(f"inventory source member for {name} differs from action table")
        line_number = actual.get("line")
        if not isinstance(line_number, int):
            continue
        try:
            source_line = archive.line(str(action_member), line_number)
        except (KeyError, IndexError) as exc:
            error(f"{name} source anchor is invalid: {exc}")
            continue
        pattern = re.compile(
            r'^\s*\{\s*"'
            + re.escape(name)
            + r'"\s*,\s*'
            + re.escape(str(actual.get("parser_token")))
            + r'\s*,\s*'
            + re.escape(str(actual.get("behavior")))
            + r'\s*\},'
        )
        if not pattern.search(source_line):
            error(
                f"{name} action anchor does not contain the contracted parser row: "
                f"{action_member}:{line_number}: {source_line!r}"
            )

    behaviors = contract.get("behaviors")
    if not isinstance(behaviors, dict):
        error("contract.behaviors must be an object")
        behaviors = {}
    expected_behaviors = {action["parser_value"] for action in expected_actions}
    if len(expected_behaviors) != EXPECTED_BEHAVIOR_COUNT:
        error(
            f"inventory has {len(expected_behaviors)} distinct action behaviors; "
            f"expected {EXPECTED_BEHAVIOR_COUNT}"
        )
    if set(behaviors) != expected_behaviors:
        missing_behaviors = sorted(expected_behaviors - set(behaviors))
        extra_behaviors = sorted(set(behaviors) - expected_behaviors)
        if missing_behaviors:
            error(f"missing behavior records: {', '.join(missing_behaviors)}")
        if extra_behaviors:
            error(f"unexpected behavior records: {', '.join(extra_behaviors)}")

    expected_aliases: dict[str, list[str]] = {}
    for action in expected_actions:
        expected_aliases.setdefault(action["parser_value"], []).append(action["spelling"])
    for behavior_name, behavior in behaviors.items():
        if not isinstance(behavior, dict):
            error(f"behavior {behavior_name} must be an object")
            continue
        aliases = behavior.get("aliases")
        if aliases != expected_aliases.get(behavior_name):
            error(
                f"{behavior_name}.aliases is {aliases!r}; expected exact parser "
                f"alias order {expected_aliases.get(behavior_name)!r}"
            )
        for field in ("effect", "no_op_when"):
            value = behavior.get(field)
            if not isinstance(value, str) or not value.strip():
                error(f"{behavior_name}.{field} must be a nonempty string")
        evidence = behavior.get("evidence")
        if not (
            isinstance(evidence, dict)
            and set(evidence) == {"member", "line", "text"}
        ):
            error(f"{behavior_name}.evidence must be one exact source anchor")

    binding = contract.get("binding_contract")
    if not isinstance(binding, dict):
        error("binding_contract must be an object")
        binding = {}
    contexts = binding.get("contexts", [])
    if not isinstance(contexts, list):
        error("binding_contract.contexts must be an array")
        contexts = []
    context_names = {
        entry.get("name") for entry in contexts if isinstance(entry, dict)
    }
    if context_names != REQUIRED_CONTEXTS:
        error(f"binding contexts are incomplete: got {sorted(context_names)}")
    context_aliases = {
        alias
        for entry in contexts
        if isinstance(entry, dict)
        for alias in entry.get("aliases", [])
        if alias != "quoted-string"
    }
    expected_context_aliases = inventory_spellings(inventory, "binding-context")
    if context_aliases != expected_context_aliases:
        error(
            "binding context aliases differ from inventory: "
            f"got {sorted(context_aliases)}, expected {sorted(expected_context_aliases)}"
        )
    all_context = next(
        (entry for entry in contexts if isinstance(entry, dict) and entry.get("name") == "all"),
        {},
    )
    if all_context.get("expands_to") != [
        "window",
        "title",
        "icon",
        "root",
        "frame",
        "iconmgr",
    ]:
        error("all context must expand in upstream context-bit order")

    modifiers = binding.get("modifiers", [])
    if not isinstance(modifiers, list):
        error("binding_contract.modifiers must be an array")
        modifiers = []
    modifier_names = {
        entry.get("name") for entry in modifiers if isinstance(entry, dict)
    }
    if modifier_names != REQUIRED_MODIFIERS:
        error(f"binding modifiers are incomplete: got {sorted(modifier_names)}")
    keyword_modifier_aliases = {
        alias
        for entry in modifiers
        if isinstance(entry, dict)
        and entry.get("name") in {"shift", "control", "lock", "meta"}
        for alias in entry.get("aliases", [])
    }
    expected_modifier_aliases = inventory_spellings(inventory, "binding-modifier")
    if keyword_modifier_aliases != expected_modifier_aliases:
        error(
            "binding modifier aliases differ from inventory: "
            f"got {sorted(keyword_modifier_aliases)}, "
            f"expected {sorted(expected_modifier_aliases)}"
        )
    matching = binding.get("matching")
    if not isinstance(matching, list) or len(matching) < 6:
        error("binding_contract.matching must preserve all matching rules")

    fallback = contract.get("fallback_contract")
    if not isinstance(fallback, dict):
        error("fallback_contract must be an object")
    else:
        for field in ("default_function", "window_function"):
            if not isinstance(fallback.get(field), str) or not fallback[field].strip():
                error(f"fallback_contract.{field} must be a nonempty string")

    ordering = contract.get("ordering_and_interruption")
    if not isinstance(ordering, dict):
        error("ordering_and_interruption must be an object")
    else:
        if len(ordering.get("named_functions", [])) < 6:
            error("named-function ordering/interruption rules are incomplete")
        if len(ordering.get("menus", [])) < 4:
            error("nested-menu ordering/interruption rules are incomplete")

    command = contract.get("command_execution")
    required_command_fields = {
        "configuration_decoding",
        "f_exec",
        "bang_alias",
        "f_startwm",
        "f_restart_and_twmrc",
        "evidence",
    }
    if not isinstance(command, dict) or set(command) != required_command_fields:
        error("command_execution fields are incomplete or unexpected")
    elif not all(
        isinstance(command[field], str) and command[field].strip()
        for field in required_command_fields - {"evidence"}
    ):
        error("every command-execution rule must be a nonempty string")

    evidence_count = 0
    for location, anchor in walk_evidence(contract):
        evidence_count += 1
        member = anchor.get("member")
        number = anchor.get("line")
        text = anchor.get("text")
        if not isinstance(member, str) or not isinstance(number, int) or not isinstance(text, str):
            error(f"{location} has malformed source anchor fields")
            continue
        try:
            actual_line = archive.line(member, number)
        except (KeyError, IndexError) as exc:
            error(f"{location} has invalid source anchor: {exc}")
            continue
        if actual_line != text:
            error(
                f"{location} source mismatch at {member}:{number}: "
                f"contracted {text!r}, archive has {actual_line!r}"
            )
    if evidence_count < EXPECTED_BEHAVIOR_COUNT + 30:
        error(f"only {evidence_count} exact source anchors were found")

    return errors


def self_test_tamper(
    contract: dict[str, Any], inventory: dict[str, Any], archive: Path
) -> list[str]:
    """Prove that representative contract corruption is rejected."""

    failures: list[str] = []
    mutations: list[tuple[str, Any]] = []

    missing_action = copy.deepcopy(contract)
    missing_action["actions"] = missing_action["actions"][1:]
    mutations.append(("missing action", missing_action))

    wrong_alias = copy.deepcopy(contract)
    wrong_alias["behaviors"]["F_RESTART"]["aliases"] = ["f.restart"]
    mutations.append(("broken alias", wrong_alias))

    wrong_anchor = copy.deepcopy(contract)
    wrong_anchor["command_execution"]["evidence"][0]["text"] += " tampered"
    mutations.append(("broken source anchor", wrong_anchor))

    missing_rule = copy.deepcopy(contract)
    missing_rule["binding_contract"]["matching"] = []
    mutations.append(("missing binding rules", missing_rule))

    for label, mutation in mutations:
        if not validate(mutation, inventory, archive):
            failures.append(f"self-test mutation was not detected: {label}")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--archive",
        type=Path,
        help="override the archive path recorded by the contract",
    )
    parser.add_argument(
        "--self-test-tamper",
        action="store_true",
        help="also verify that representative contract tampering is rejected",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        contract = load_json(args.contract)
        inventory = load_json(args.inventory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not isinstance(contract, dict) or not isinstance(inventory, dict):
        print("error: contract and inventory roots must be JSON objects", file=sys.stderr)
        return 1

    archive = args.archive
    if archive is None:
        recorded = contract.get("upstream", {}).get("archive")
        if not isinstance(recorded, str):
            print("error: contract does not record an archive path", file=sys.stderr)
            return 1
        archive = ROOT / recorded

    try:
        errors = validate(contract, inventory, archive)
        if args.self_test_tamper and not errors:
            errors.extend(self_test_tamper(contract, inventory, archive))
    except (OSError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        return 1

    suffix = " with tamper self-test" if args.self_test_tamper else ""
    print(
        f"validated {len(contract['actions'])} actions, "
        f"{len(contract['behaviors'])} behaviors, and all source anchors{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
