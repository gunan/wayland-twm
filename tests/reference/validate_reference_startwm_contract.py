#!/usr/bin/env python3
"""Validate the twm f.startwm source and safe Wayland handoff contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path("reference/lifecycle/twm-1.0.13.1/startwm-contract.json")
EXPECTED_CONTRACT_SHA256 = (
    "cda3ad75d885fe0c2014083f1c05758cc34ba4b090b74a0a9f3f30d8e2592d81"
)
EXPECTED_TOP_LEVEL = {
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
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
    "action_contract": "reference/actions/twm-1.0.13.1/action-contract.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/man/twm.man": (
        "a1743a47770bd63a2ff5e63b8c6e86d72ee02ddd126813951833fb33b8a56674"
    ),
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/parse.c": (
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c"
    ),
}
EXPECTED_EVIDENCE = {
    "manual.startwm": {
        "member": "twm-1.0.13.1/man/twm.man",
        "line": 1377,
        "text": '.IP "\\fBf.startwm\\fP \\fIstring\\fP" 8',
    },
    "manual.startwm-effect": {
        "member": "twm-1.0.13.1/man/twm.man",
        "line": 1378,
        "text": "This function kills \\fItwm\\fP and starts another window manager, as",
    },
    "manual.startwm-target": {
        "member": "twm-1.0.13.1/man/twm.man",
        "line": 1379,
        "text": "specified by \\fIstring\\fP.",
    },
    "parse.f-startwm": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 468,
        "text": '    { "f.startwm",              FSKEYWORD, F_STARTWM },',
    },
    "startwm.dispatch": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2184,
        "text": "    case F_STARTWM:",
    },
    "startwm.shell-exec": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2185,
        "text": '        execlp("/bin/sh", "sh", "-c", action, (void *) NULL);',
    },
    "startwm.failure-warning": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2186,
        "text": '        twmWarning("unable to start:  %s", *Argv);',
    },
    "startwm.failure-break": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2187,
        "text": "        break;",
    },
    "startwm.common-return": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2193,
        "text": "    return do_next_action;",
    },
}
EXPECTED_REQUIREMENT_EVIDENCE = {
    "startwm.reference-shell-command": [
        "parse.f-startwm",
        "startwm.dispatch",
        "startwm.shell-exec",
        "startwm.failure-warning",
        "startwm.common-return",
    ],
    "startwm.preflight-before-mutation": ["startwm.shell-exec"],
    "startwm.unsupported-retention": ["startwm.shell-exec"],
    "startwm.failure-continuity": [
        "startwm.failure-warning",
        "startwm.common-return",
    ],
    "startwm.success-continuity": [
        "manual.startwm",
        "manual.startwm-effect",
        "manual.startwm-target",
        "startwm.shell-exec",
    ],
    "startwm.no-generic-wayland-takeover": ["startwm.shell-exec"],
}
EXPECTED_SCENARIOS = {
    "upstream-shell-success": "reference-valid",
    "upstream-shell-exec-failure": "reference-invalid",
    "generic-wayland-command": "translation-unsupported",
    "supported-target-preflight-failure": "translation-invalid",
    "registered-in-process-success": "translation-valid",
    "cooperative-successor-success": "translation-valid-when-adapter-exists",
}
EXPECTED_PRESERVED = [
    "compositor process and event loop",
    "Wayland display and listening socket",
    "native Wayland clients and resources",
    "Xwayland server and X11 clients",
    "mapping, geometry, iconification, and stacking",
    "keyboard and pointer focus",
    "clipboard, primary selection, and window-manager selections",
    "session-manager identity and lifecycle ownership",
]
EXPECTED_BOUNDARIES = [
    "Wayland display and listening socket",
    "all native Wayland client connections, objects, and roles",
    "Xwayland server and all X11 client connections",
    "outputs, input devices, seats, and active grabs",
    "managed geometry, mapping, iconification, and stacking",
    "keyboard focus and pointer focus",
    "clipboard, primary selection, and window-manager selections",
    "session-manager identity and lifecycle ownership",
]


def load_json(path: Path) -> Any:
    """Load JSON and reject duplicate object keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Archive:
    """Read exact source members from the pinned release archive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.members: dict[str, bytes] = {}

    def read(self, member: str) -> bytes:
        if member not in self.members:
            with tarfile.open(self.path, "r:xz") as source:
                extracted = source.extractfile(member)
                if extracted is None:
                    raise KeyError(f"archive member does not exist: {member}")
                self.members[member] = extracted.read()
        return self.members[member]

    def line(self, member: str, number: int) -> str:
        lines = self.read(member).decode("utf-8").splitlines()
        if not 1 <= number <= len(lines):
            raise IndexError(f"line {number} is outside {member}")
        return lines[number - 1]


def records_by_id(value: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    records: dict[str, Any] = {}
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            errors.append(f"{location}[{index}] must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{location}[{index}].id must be a nonempty string")
            continue
        if record_id in records:
            errors.append(f"duplicate {location} id {record_id!r}")
        records[record_id] = record
    return records


def evidence_references(value: Any, location: str = "contract") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if location == "contract" and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, str):
                yield child
            elif key == "evidence" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from evidence_references(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from evidence_references(child, f"{location}[{index}]")


def validate_contract(
    contract: Any,
    archive: Archive,
    inventory: Any,
    action_contract: Any,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]
    if set(contract) != EXPECTED_TOP_LEVEL:
        errors.append("contract top-level keys differ from the frozen schema")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        errors.append("contract content differs from the reviewed canonical contract")
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream provenance differs from the pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes differ from the pinned members")
    if contract.get("evidence") != EXPECTED_EVIDENCE:
        errors.append("source evidence differs from the frozen exact lines")

    archive_digest = hashlib.sha256(archive.path.read_bytes()).hexdigest()
    if archive_digest != EXPECTED_UPSTREAM["sha256"]:
        errors.append("pinned upstream archive SHA-256 mismatch")
    for member, expected_digest in EXPECTED_SOURCE_MEMBERS.items():
        try:
            data = archive.read(member)
        except (KeyError, tarfile.TarError) as exc:
            errors.append(str(exc))
            continue
        if hashlib.sha256(data).hexdigest() != expected_digest:
            errors.append(f"source member SHA-256 mismatch: {member}")
    for evidence_id, record in EXPECTED_EVIDENCE.items():
        try:
            actual = archive.line(record["member"], record["line"])
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"{evidence_id}: {exc}")
            continue
        if actual != record["text"]:
            errors.append(f"{evidence_id}: pinned source line mismatch")

    evidence = contract.get("evidence")
    evidence_ids = set(evidence) if isinstance(evidence, dict) else set()
    for evidence_id in evidence_references(contract):
        if evidence_id not in evidence_ids:
            errors.append(f"unknown evidence reference {evidence_id!r}")

    keywords = inventory.get("keywords") if isinstance(inventory, dict) else None
    keyword_matches = [
        item
        for item in keywords or []
        if isinstance(item, dict) and item.get("id") == "keyword.f.startwm"
    ]
    expected_keyword = {
        "spelling": "f.startwm",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_STARTWM",
        "evidence": {
            "archive_member": "twm-1.0.13.1/src/parse.c",
            "line": 468,
            "text": EXPECTED_EVIDENCE["parse.f-startwm"]["text"],
        },
    }
    if len(keyword_matches) != 1:
        errors.append("inventory must contain exactly one keyword.f.startwm")
    else:
        for key, expected in expected_keyword.items():
            if keyword_matches[0].get(key) != expected:
                errors.append(f"inventory keyword.f.startwm {key} mismatch")

    behaviors = action_contract.get("behaviors") if isinstance(action_contract, dict) else None
    behavior = behaviors.get("F_STARTWM") if isinstance(behaviors, dict) else None
    if not isinstance(behavior, dict):
        errors.append("action contract lacks F_STARTWM behavior")
    else:
        if behavior.get("aliases") != ["f.startwm"]:
            errors.append("action contract F_STARTWM aliases mismatch")
        if behavior.get("evidence") != {
            "member": "twm-1.0.13.1/src/menus.c",
            "line": 2184,
            "text": "    case F_STARTWM:",
        }:
            errors.append("action contract F_STARTWM evidence mismatch")
        effect = behavior.get("effect")
        if not isinstance(effect, str) or "execlp('/bin/sh', 'sh', '-c', argument)" not in effect:
            errors.append("action contract F_STARTWM shell execution mismatch")
        failure = behavior.get("no_op_when")
        if not isinstance(failure, str) or "exec fails" not in failure:
            errors.append("action contract F_STARTWM failure behavior mismatch")

    reference = contract.get("reference_behavior")
    if not isinstance(reference, dict):
        errors.append("reference_behavior must be an object")
    else:
        identity = reference.get("action_identity", {})
        if identity.get("parser_token") != "FSKEYWORD":
            errors.append("f.startwm must retain FSKEYWORD argument parsing")
        if identity.get("normalized_action") != "F_STARTWM":
            errors.append("f.startwm must normalize to F_STARTWM")
        command = reference.get("command_execution", {})
        if command.get("argv") != ["sh", "-c", "action"]:
            errors.append("reference command argv must be sh -c action")
        if command.get("program") != "/bin/sh" or command.get("path_lookup") != "execlp":
            errors.append("reference command must use execlp /bin/sh")
        if command.get("preflight") is not False or command.get("returns_on_success") is not False:
            errors.append("reference exec preflight/return semantics mismatch")
        failure = reference.get("exec_failure", {})
        if failure.get("result") != "warn-and-continue-current-twm":
            errors.append("reference exec failure must warn and continue")
        if failure.get("warning_argument") != "original Argv[0], not the attempted action string":
            errors.append("reference warning argument mismatch")

    translation = contract.get("wayland_translation")
    if not isinstance(translation, dict):
        errors.append("wayland_translation must be an object")
    else:
        strategies = records_by_id(
            translation.get("strategy_classification"),
            "wayland_translation.strategy_classification",
            errors,
        )
        if set(strategies) != {
            "registered-in-process-successor",
            "explicit-cooperative-successor",
            "generic-shell-command",
        }:
            errors.append("strategy classification set mismatch")
        generic = strategies.get("generic-shell-command", {})
        if generic.get("support") != "unsupported" or generic.get("connection_fd_transfer") is not False:
            errors.append("generic shell commands must not be accepted as handoff")
        preflight = translation.get("preflight", {})
        if preflight.get("runs_before_session_mutation") is not True:
            errors.append("handoff preflight must precede session mutation")
        if preflight.get("generic_wayland_takeover_available") is not False:
            errors.append("generic Wayland takeover must remain unavailable")
        transaction = translation.get("handoff_transaction", {})
        if transaction.get("ownership_boundaries") != EXPECTED_BOUNDARIES:
            errors.append("handoff ownership boundaries mismatch")
        if transaction.get("generic_wayland_fd_takeover_claimed") is not False:
            errors.append("contract must not claim generic Wayland fd takeover")
        phases = transaction.get("phases")
        if not isinstance(phases, list) or len(phases) != 4 or "retire" not in phases[-1]:
            errors.append("handoff phases must retain-before-ready and retire last")
        failed = translation.get("unsupported_or_failed", {})
        if failed.get("outcome") != "report-and-retain-current-session":
            errors.append("unsupported/failed handoff must retain the session")
        if failed.get("execute_configured_shell_command") is not False:
            errors.append("unsupported/failed handoff must not execute the command")
        if failed.get("preserve") != EXPECTED_PRESERVED:
            errors.append("unsupported/failed handoff preservation set mismatch")

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != set(EXPECTED_REQUIREMENT_EVIDENCE):
        errors.append("requirement id set mismatch")
    for requirement_id, expected_evidence in EXPECTED_REQUIREMENT_EVIDENCE.items():
        record = requirements.get(requirement_id, {})
        if record.get("level") != "MUST":
            errors.append(f"{requirement_id} must be a MUST requirement")
        if record.get("evidence") != expected_evidence:
            errors.append(f"{requirement_id} evidence mismatch")
        if not isinstance(record.get("rule"), str) or not record["rule"]:
            errors.append(f"{requirement_id} must have a rule")

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    if set(scenarios) != set(EXPECTED_SCENARIOS):
        errors.append("verification scenario id set mismatch")
    for scenario_id, expected_class in EXPECTED_SCENARIOS.items():
        record = scenarios.get(scenario_id, {})
        if record.get("class") != expected_class:
            errors.append(f"{scenario_id} class mismatch")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} must have an oracle")
        if scenario_id.startswith(("generic-", "supported-", "registered-", "cooperative-")):
            if record.get("protocols") != ["native-wayland", "xwayland"]:
                errors.append(f"{scenario_id} must cover native Wayland and Xwayland")

    return errors


def run_tamper_tests(
    contract: dict[str, Any],
    archive: Archive,
    inventory: Any,
    action_contract: Any,
) -> list[str]:
    mutations: list[tuple[str, dict[str, Any]]] = []

    broken_anchor = copy.deepcopy(contract)
    broken_anchor["evidence"]["startwm.shell-exec"]["text"] += " tampered"
    mutations.append(("source anchor", broken_anchor))

    broken_parser = copy.deepcopy(contract)
    broken_parser["reference_behavior"]["action_identity"]["parser_token"] = "FKEYWORD"
    mutations.append(("argument parser", broken_parser))

    broken_command = copy.deepcopy(contract)
    broken_command["reference_behavior"]["command_execution"]["argv"] = ["action"]
    mutations.append(("shell command", broken_command))

    accepted_generic = copy.deepcopy(contract)
    accepted_generic["wayland_translation"]["strategy_classification"][2]["support"] = "supported"
    mutations.append(("generic takeover", accepted_generic))

    dropped_client = copy.deepcopy(contract)
    dropped_client["wayland_translation"]["unsupported_or_failed"]["preserve"].remove(
        "native Wayland clients and resources"
    )
    mutations.append(("failure continuity", dropped_client))

    claimed_fd_takeover = copy.deepcopy(contract)
    claimed_fd_takeover["wayland_translation"]["handoff_transaction"][
        "generic_wayland_fd_takeover_claimed"
    ] = True
    mutations.append(("fd takeover claim", claimed_fd_takeover))

    reordered_phases = copy.deepcopy(contract)
    reordered_phases["wayland_translation"]["handoff_transaction"]["phases"].reverse()
    mutations.append(("handoff order", reordered_phases))

    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario))

    failures: list[str] = []
    for name, mutated in mutations:
        if not validate_contract(mutated, archive, inventory, action_contract):
            failures.append(f"tamper self-test was not rejected: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()

    try:
        contract = load_json(source_root / CONTRACT_PATH)
        inventory = load_json(source_root / EXPECTED_UPSTREAM["inventory"])
        action_contract = load_json(source_root / EXPECTED_UPSTREAM["action_contract"])
        archive = Archive(source_root / EXPECTED_UPSTREAM["archive"])
        errors = validate_contract(contract, archive, inventory, action_contract)
        if args.self_test_tamper and isinstance(contract, dict):
            errors.extend(run_tamper_tests(contract, archive, inventory, action_contract))
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"startwm contract validation failed: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("startwm contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        "startwm contract valid: 9 exact source anchors, 3 handoff strategies, "
        "6 requirements, 6 scenarios, 8 tamper self-tests"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
