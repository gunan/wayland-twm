#!/usr/bin/env python3
"""Validate the twm saved-state evidence and wtwm persistence contract."""

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
CONTRACT_PATH = Path("reference/lifecycle/twm-1.0.13.1/state-contract.json")
INVENTORY_PATH = Path("reference/inventory/twm-1.0.13.1.json")
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/src/add_window.c": (
        "c3133cc763d2db086e3417b3c2f3c103dc23685690a59e4116cbd338feb7b888"
    ),
    "twm-1.0.13.1/src/events.c": (
        "4fe7f9746d569abe64c7301a1b31197a299eede117d54456929b6e82726366e3"
    ),
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
    "parse.f-saveyourself": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 464,
        "text": '    { "f.saveyourself",         FKEYWORD, F_SAVEYOURSELF },',
    },
    "protocol.detect-saveyourself": {
        "member": "twm-1.0.13.1/src/add_window.c",
        "line": 1383,
        "text": "            if (*ap == _XA_WM_SAVE_YOURSELF)",
    },
    "protocol.record-saveyourself": {
        "member": "twm-1.0.13.1/src/add_window.c",
        "line": 1384,
        "text": "                flags |= DoesWmSaveYourself;",
    },
    "saveyourself.dispatch": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1884,
        "text": "    case F_SAVEYOURSELF:",
    },
    "saveyourself.defer-selection": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1885,
        "text": "        if (DeferExecution(context, func, Scr->SelectCursor))",
    },
    "saveyourself.require-advertisement": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1888,
        "text": "        if (tmp_win->protocols & DoesWmSaveYourself)",
    },
    "saveyourself.send": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1889,
        "text": "            SendSaveYourselfMessage(tmp_win, LastTimestamp());",
    },
    "saveyourself.unsupported-bell": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 1891,
        "text": "            Bell(XkbBI_MinorError, 0, tmp_win->w);",
    },
    "saveyourself.client-message": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2883,
        "text": "    send_clientmessage(tmp->w, _XA_WM_SAVE_YOURSELF, timestamp);",
    },
    "restartpreviousstate.default-disabled": {
        "member": "twm-1.0.13.1/src/twm.c",
        "line": 144,
        "text": (
            "Bool RestartPreviousState = False;      "
            "/* try to restart in previous state */"
        ),
    },
    "parse.restartpreviousstate": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 560,
        "text": (
            '    { "restartpreviousstate",   KEYWORD, '
            "kw0_RestartPreviousState },"
        ),
    },
    "restartpreviousstate.enable": {
        "member": "twm-1.0.13.1/src/parse.c",
        "line": 703,
        "text": "        RestartPreviousState = True;",
    },
    "restartpreviousstate.not-already-iconified": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1326,
        "text": "    if ((!Tmp_win->icon) &&",
    },
    "restartpreviousstate.require-state-hint": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1327,
        "text": (
            "        Tmp_win->wmhints && "
            "(Tmp_win->wmhints->flags & StateHint)) {"
        ),
    },
    "restartpreviousstate.read-wm-state": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1333,
        "text": (
            "        if (!(RestartPreviousState && "
            "GetWMState(Tmp_win->w, &state, &icon) &&"
        ),
    },
    "restartpreviousstate.accept-states": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1334,
        "text": "              (state == NormalState || state == IconicState)))",
    },
    "restartpreviousstate.fallback": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1335,
        "text": "            state = Tmp_win->wmhints->initial_state;",
    },
    "restartpreviousstate.normal-map": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1343,
        "text": "            XMapWindow(dpy, Tmp_win->frame);",
    },
    "restartpreviousstate.normal-property": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1344,
        "text": "            SetMapStateProp(Tmp_win, NormalState);",
    },
    "restartpreviousstate.iconic": {
        "member": "twm-1.0.13.1/src/events.c",
        "line": 1351,
        "text": "            Iconify(Tmp_win, 0, 0);",
    },
    "wm-state.write": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2607,
        "text": (
            "    XChangeProperty(dpy, tmp_win->w, _XA_WM_STATE, "
            "_XA_WM_STATE, 32,"
        ),
    },
    "wm-state.read": {
        "member": "twm-1.0.13.1/src/menus.c",
        "line": 2620,
        "text": (
            "    if (XGetWindowProperty(dpy, w, _XA_WM_STATE, 0L, 2L, "
            "False, _XA_WM_STATE,"
        ),
    },
}
EXPECTED_SAVE_TRANSACTION = {
    "trigger": "f.saveyourself",
    "scope": "all-current-compositor-owned-restorable-state",
    "format": "wtwm-compositor-state",
    "schema_version": 1,
    "atomicity": "write-complete-temporary-file-fsync-and-atomic-rename",
    "publish_only_after_complete_validation": True,
    "partial_snapshot_allowed": False,
    "failure_result": "retain-prior-snapshot-and-running-session-with-diagnostic",
}
EXPECTED_XWAYLAND_PROTOCOL = {
    "target": "selected-xwayland-client",
    "advertised_result": (
        "send WM_SAVE_YOURSELF ClientMessage and atomically save "
        "compositor-owned state"
    ),
    "unadvertised_result": (
        "ring the compatibility bell and still atomically save "
        "compositor-owned state"
    ),
    "message_requires_advertisement": True,
    "claim_client_saved_process_state": False,
}
EXPECTED_NATIVE_PROTOCOL = {
    "equivalent_client-save-protocol": "none",
    "result": "atomically save compositor-owned state only",
    "claim_client_saved_process_state": False,
}
EXPECTED_NATIVE_KEYS = ["protocol-native-wayland", "app-id", "title"]
EXPECTED_XWAYLAND_KEYS = [
    "protocol-xwayland",
    "same-xwayland-generation-xid-or-wm-class-instance-and-class",
    "wm-window-role",
    "sm-client-id-when-present",
    "title",
]
EXPECTED_IDENTITY = {
    "match_cardinality": "exactly-one-live-client-to-exactly-one-saved-record",
    "native_wayland_keys": EXPECTED_NATIVE_KEYS,
    "xwayland_keys": EXPECTED_XWAYLAND_KEYS,
    "missing_identity_result": "skip-record-with-diagnostic",
    "ambiguous_identity_result": (
        "skip-all-conflicting-records-with-diagnostic"
    ),
    "positional_or-arrival-order_fallback": False,
}
EXPECTED_RESTORABLE_FIELDS = [
    "geometry",
    "iconic-state",
    "relative-stack",
    "focus",
    "manual-icon-position",
    "auto-raise",
    "zoom-restore-data",
]
EXPECTED_RESTORABLE_RULES = {
    "fields": EXPECTED_RESTORABLE_FIELDS,
    "geometry_rule": (
        "restore position and size, then clamp the complete visible frame to "
        "current output bounds"
    ),
    "iconic_rule": (
        "restore only mapped normal or iconic compositor presentation, never "
        "client process state"
    ),
    "relative_stack_rule": (
        "reconstruct order only among uniquely matched clients while preserving "
        "current layer constraints"
    ),
    "focus_rule": (
        "restore only to a uniquely matched client that is mapped, non-iconic, "
        "and currently focusable"
    ),
    "manual_icon_position_rule": (
        "restore compositor-owned manual icon coordinates and clamp them to "
        "current output bounds"
    ),
    "auto_raise_rule": (
        "restore the compositor-owned per-client auto-raise policy bit"
    ),
    "zoom_restore_rule": (
        "restore the compositor-owned pre-zoom geometry and active zoom mode "
        "only when valid on current outputs"
    ),
}
EXPECTED_EXCLUDED = [
    "client-process-lifetime",
    "client-owned-document-or-application-state",
    "client-private-protocol-state",
    "unadvertised-WM_SAVE_YOURSELF-completion",
    "relaunching-clients",
]
EXPECTED_RESTORE_PHASES = [
    "read the complete candidate snapshot without mutating the session",
    "validate format version structure values and record uniqueness",
    "match records only to unique native Wayland or Xwayland identities",
    "derive clamped geometry stack focus icon and zoom state for current outputs",
    "publish the valid matched restoration as one compositor generation",
]
EXPECTED_RESTORE_TRANSACTION = {
    "enabled_by": "RestartPreviousState",
    "accepted_format": "wtwm-compositor-state",
    "accepted_schema_versions": [1],
    "phases": EXPECTED_RESTORE_PHASES,
    "malformed_result": (
        "reject-whole-snapshot-retain-running-session-and-report-diagnostic"
    ),
    "unsupported_version_result": (
        "reject-whole-snapshot-retain-running-session-and-report-diagnostic"
    ),
    "ambiguous_records_result": (
        "skip-conflicting-records-and-restore-other-valid-unique-records"
    ),
    "no_partial_publish_on_validation_failure": True,
}
EXPECTED_REQUIREMENT_EVIDENCE = {
    "state.upstream-saveyourself-protocol": [
        "protocol.detect-saveyourself",
        "saveyourself.require-advertisement",
        "saveyourself.client-message",
    ],
    "state.atomic-versioned-snapshot": ["saveyourself.dispatch"],
    "state.unique-protocol-identities": ["wm-state.read"],
    "state.safe-field-set": [
        "restartpreviousstate.accept-states",
        "restartpreviousstate.normal-property",
        "restartpreviousstate.iconic",
    ],
    "state.output-safe-restoration": ["restartpreviousstate.normal-map"],
    "state.focus-eligibility": ["restartpreviousstate.accept-states"],
    "state.invalid-snapshot-retention": ["restartpreviousstate.fallback"],
    "state.no-client-owned-claims": ["saveyourself.client-message"],
}
EXPECTED_SCENARIO_KINDS = {
    "advertised-xwayland-save": "valid",
    "mixed-protocol-valid-restore": "valid",
    "changed-output-topology": "valid",
    "iconic-client-saved-focus": "valid",
    "ambiguous-native-or-xwayland-identity": "invalid-record",
    "malformed-snapshot": "invalid-snapshot",
    "unsupported-schema-version": "unsupported-snapshot",
    "unadvertised-xwayland-and-native-save": "unsupported-client-protocol",
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
    """Read exact members and source lines from the pinned archive."""

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
            raise IndexError(f"line {number} outside {member} (1..{len(lines)})")
        return lines[number - 1]

    def occurrences(self, pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
        matches: list[tuple[str, int, str]] = []
        for member in EXPECTED_SOURCE_MEMBERS:
            for number, line in enumerate(
                self.read(member).decode("utf-8").splitlines(), start=1
            ):
                if pattern.search(line):
                    matches.append((member, number, line))
        return matches


def records_by_id(
    value: Any, location: str, errors: list[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    records: dict[str, dict[str, Any]] = {}
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


def require_nonempty(
    record: dict[str, Any], field: str, location: str, errors: list[str]
) -> None:
    if not isinstance(record.get(field), str) or not record[field].strip():
        errors.append(f"{location}.{field} must be a nonempty string")


def referenced_evidence(
    value: Any, location: str = "contract"
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if location == "contract" and key == "evidence":
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


def validate_inventory(
    inventory: dict[str, Any], errors: list[str]
) -> None:
    keywords = inventory.get("keywords")
    if not isinstance(keywords, list):
        errors.append("inventory.keywords must be an array")
        return
    by_spelling = {
        record.get("spelling"): record
        for record in keywords
        if isinstance(record, dict)
    }
    expected = {
        "f.saveyourself": (
            "keyword.f.saveyourself",
            "FKEYWORD",
            "F_SAVEYOURSELF",
            "parse.f-saveyourself",
        ),
        "restartpreviousstate": (
            "keyword.restartpreviousstate",
            "KEYWORD",
            "kw0_RestartPreviousState",
            "parse.restartpreviousstate",
        ),
    }
    for spelling, (record_id, token, value, evidence_id) in expected.items():
        record = by_spelling.get(spelling)
        if not isinstance(record, dict):
            errors.append(f"inventory lacks keyword {spelling!r}")
            continue
        if (
            record.get("id"),
            record.get("parser_token"),
            record.get("parser_value"),
        ) != (record_id, token, value):
            errors.append(f"inventory identity differs for {spelling!r}")
        inventory_evidence = record.get("evidence", {})
        normalized = {
            "member": inventory_evidence.get("archive_member"),
            "line": inventory_evidence.get("line"),
            "text": inventory_evidence.get("text"),
        }
        if normalized != EXPECTED_EVIDENCE[evidence_id]:
            errors.append(f"inventory evidence differs for {spelling!r}")


def validate_reference_behavior(
    value: Any, errors: list[str]
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "saveyourself_action",
        "restart_previous_state",
    }:
        errors.append("reference_behavior fields differ from schema")
        return
    save = value.get("saveyourself_action")
    expected_save = {
        "spelling": "f.saveyourself",
        "inventory_id": "keyword.f.saveyourself",
        "parser_token": "FKEYWORD",
        "parser_value": "F_SAVEYOURSELF",
        "target": "selected-managed-client",
        "advertisement": "WM_PROTOCOLS contains WM_SAVE_YOURSELF",
        "advertised_result": (
            "send WM_SAVE_YOURSELF ClientMessage with the last X timestamp"
        ),
        "unadvertised_result": (
            "ring the minor-error bell without sending a message"
        ),
        "evidence": [
            "parse.f-saveyourself",
            "protocol.detect-saveyourself",
            "protocol.record-saveyourself",
            "saveyourself.dispatch",
            "saveyourself.defer-selection",
            "saveyourself.require-advertisement",
            "saveyourself.send",
            "saveyourself.unsupported-bell",
            "saveyourself.client-message",
        ],
    }
    if save != expected_save:
        errors.append("reference saveyourself behavior differs from frozen contract")
    restart = value.get("restart_previous_state")
    expected_restart = {
        "spelling": "restartpreviousstate",
        "inventory_id": "keyword.restartpreviousstate",
        "parser_token": "KEYWORD",
        "parser_value": "kw0_RestartPreviousState",
        "default_enabled": False,
        "enabled_by_directive": True,
        "eligibility": (
            "client is not already iconified and WM_HINTS supplies StateHint"
        ),
        "wm_state_candidates": ["NormalState", "IconicState"],
        "invalid_or_unavailable_fallback": "WM_HINTS.initial_state",
        "normal_result": (
            "map the client and frame, publish NormalState, and raise"
        ),
        "iconic_result": "iconify without zoom animation",
        "evidence": [
            "restartpreviousstate.default-disabled",
            "parse.restartpreviousstate",
            "restartpreviousstate.enable",
            "restartpreviousstate.not-already-iconified",
            "restartpreviousstate.require-state-hint",
            "restartpreviousstate.read-wm-state",
            "restartpreviousstate.accept-states",
            "restartpreviousstate.fallback",
            "restartpreviousstate.normal-map",
            "restartpreviousstate.normal-property",
            "restartpreviousstate.iconic",
            "wm-state.write",
            "wm-state.read",
        ],
    }
    if restart != expected_restart:
        errors.append(
            "reference RestartPreviousState behavior differs from frozen contract"
        )


def validate_translation(value: Any, errors: list[str]) -> None:
    expected_fields = {
        "save_transaction",
        "xwayland_client_protocol",
        "native_client_protocol",
        "identity_matching",
        "restorable_state",
        "excluded_state",
        "restore_transaction",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        errors.append("wayland_translation fields differ from schema")
        return
    exact = {
        "save_transaction": EXPECTED_SAVE_TRANSACTION,
        "xwayland_client_protocol": EXPECTED_XWAYLAND_PROTOCOL,
        "native_client_protocol": EXPECTED_NATIVE_PROTOCOL,
        "identity_matching": EXPECTED_IDENTITY,
        "restorable_state": EXPECTED_RESTORABLE_RULES,
        "restore_transaction": EXPECTED_RESTORE_TRANSACTION,
    }
    for field, expected in exact.items():
        if value.get(field) != expected:
            errors.append(f"wayland_translation.{field} differs from contract")
    excluded = value.get("excluded_state")
    if not isinstance(excluded, dict) or set(excluded) != {"never_claimed", "rule"}:
        errors.append("wayland_translation.excluded_state fields differ from schema")
    else:
        if excluded.get("never_claimed") != EXPECTED_EXCLUDED:
            errors.append("excluded client-owned state set differs from contract")
        require_nonempty(
            excluded,
            "rule",
            "wayland_translation.excluded_state",
            errors,
        )


def validate(
    contract: dict[str, Any], inventory: dict[str, Any], source_root: Path
) -> list[str]:
    errors: list[str] = []
    expected_top = {
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
    if set(contract) != expected_top:
        errors.append(f"contract top-level fields differ: got {sorted(contract)}")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    require_nonempty(contract, "contract", "contract", errors)
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream identity differs from the approved source archive")
    inventory_upstream = inventory.get("upstream")
    expected_inventory_upstream = {
        key: EXPECTED_UPSTREAM[key]
        for key in ("name", "version", "archive", "sha256")
    }
    if inventory_upstream != expected_inventory_upstream:
        errors.append("inventory upstream identity differs from approved reference")

    archive_path = source_root / EXPECTED_UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append(f"upstream archive is missing: {archive_path}")
        return errors
    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_UPSTREAM["sha256"]:
        errors.append(f"upstream archive hash mismatch: got {actual_hash}")
        return errors
    archive = Archive(archive_path)
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source_members differ from the frozen source member set")
    for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
        try:
            member_hash = hashlib.sha256(archive.read(member)).hexdigest()
        except KeyError as exc:
            errors.append(str(exc))
            continue
        if member_hash != expected_hash:
            errors.append(f"source member hash mismatch for {member}")

    evidence = contract.get("evidence")
    if evidence != EXPECTED_EVIDENCE:
        errors.append("evidence differs from the frozen exact source anchors")
    for evidence_id, anchor in EXPECTED_EVIDENCE.items():
        try:
            actual_line = archive.line(anchor["member"], anchor["line"])
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"evidence.{evidence_id} cannot be read: {exc}")
            continue
        if actual_line != anchor["text"]:
            errors.append(
                f"evidence.{evidence_id} mismatch at "
                f"{anchor['member']}:{anchor['line']}"
            )

    save_sends = archive.occurrences(
        re.compile(r"^\s*send_clientmessage\(tmp->w, _XA_WM_SAVE_YOURSELF,")
    )
    if save_sends != [
        (
            "twm-1.0.13.1/src/menus.c",
            2883,
            "    send_clientmessage(tmp->w, _XA_WM_SAVE_YOURSELF, timestamp);",
        )
    ]:
        errors.append(f"WM_SAVE_YOURSELF send proof changed: {save_sends!r}")
    state_reads = archive.occurrences(
        re.compile(r"RestartPreviousState && GetWMState\(")
    )
    if state_reads != [
        (
            "twm-1.0.13.1/src/events.c",
            1333,
            EXPECTED_EVIDENCE["restartpreviousstate.read-wm-state"]["text"],
        )
    ]:
        errors.append(f"RestartPreviousState read proof changed: {state_reads!r}")

    validate_inventory(inventory, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != set(EXPECTED_REQUIREMENT_EVIDENCE):
        errors.append(f"requirement coverage differs: got {sorted(requirements)}")
    for requirement_id, expected_evidence in EXPECTED_REQUIREMENT_EVIDENCE.items():
        requirement = requirements.get(requirement_id, {})
        if set(requirement) != {"id", "level", "rule", "evidence"}:
            errors.append(f"requirement {requirement_id} fields differ from schema")
        if requirement.get("level") != "MUST":
            errors.append(f"requirement {requirement_id} level must be MUST")
        require_nonempty(requirement, "rule", f"requirement {requirement_id}", errors)
        if requirement.get("evidence") != expected_evidence:
            errors.append(f"requirement {requirement_id} evidence differs")

    scenarios = records_by_id(
        contract.get("verification_scenarios"),
        "verification_scenarios",
        errors,
    )
    if set(scenarios) != set(EXPECTED_SCENARIO_KINDS):
        errors.append(f"verification scenario coverage differs: got {sorted(scenarios)}")
    for scenario_id, expected_kind in EXPECTED_SCENARIO_KINDS.items():
        scenario = scenarios.get(scenario_id, {})
        if set(scenario) != {"id", "kind", "oracle"}:
            errors.append(f"scenario {scenario_id} fields differ from schema")
        if scenario.get("kind") != expected_kind:
            errors.append(f"scenario {scenario_id} kind differs from contract")
        require_nonempty(scenario, "oracle", f"scenario {scenario_id}", errors)

    used: set[str] = set()
    for location, evidence_id in referenced_evidence(contract):
        used.add(evidence_id)
        if evidence_id not in EXPECTED_EVIDENCE:
            errors.append(f"{location} references unknown evidence {evidence_id!r}")
    unused = sorted(set(EXPECTED_EVIDENCE) - used)
    if unused:
        errors.append(f"unreferenced evidence anchors: {', '.join(unused)}")
    return errors


def self_test_tamper(
    contract: dict[str, Any], inventory: dict[str, Any], source_root: Path
) -> list[str]:
    """Prove upstream, safety, identity, and failure-boundary drift is rejected."""

    mutations: list[tuple[str, dict[str, Any]]] = []

    broken_anchor = copy.deepcopy(contract)
    broken_anchor["evidence"]["saveyourself.client-message"]["text"] += " tamper"
    mutations.append(("exact upstream anchor", broken_anchor))

    broken_reference = copy.deepcopy(contract)
    broken_reference["reference_behavior"]["restart_previous_state"][
        "wm_state_candidates"
    ].append("WithdrawnState")
    mutations.append(("invalid upstream WM_STATE candidate", broken_reference))

    non_atomic = copy.deepcopy(contract)
    non_atomic["wayland_translation"]["save_transaction"]["atomicity"] = "direct-write"
    mutations.append(("non-atomic snapshot", non_atomic))

    unversioned = copy.deepcopy(contract)
    unversioned["wayland_translation"]["save_transaction"]["schema_version"] = 0
    mutations.append(("unversioned snapshot", unversioned))

    fabricated_message = copy.deepcopy(contract)
    fabricated_message["wayland_translation"]["xwayland_client_protocol"][
        "message_requires_advertisement"
    ] = False
    mutations.append(("unadvertised X11 protocol message", fabricated_message))

    process_claim = copy.deepcopy(contract)
    process_claim["wayland_translation"]["native_client_protocol"][
        "claim_client_saved_process_state"
    ] = True
    mutations.append(("native client process claim", process_claim))

    weak_identity = copy.deepcopy(contract)
    weak_identity["wayland_translation"]["identity_matching"][
        "positional_or-arrival-order_fallback"
    ] = True
    mutations.append(("positional identity fallback", weak_identity))

    missing_xwayland_identity = copy.deepcopy(contract)
    missing_xwayland_identity["wayland_translation"]["identity_matching"][
        "xwayland_keys"
    ].clear()
    mutations.append(("missing Xwayland identity", missing_xwayland_identity))

    missing_safe_field = copy.deepcopy(contract)
    missing_safe_field["wayland_translation"]["restorable_state"]["fields"].pop()
    mutations.append(("incomplete safe field set", missing_safe_field))

    unsafe_focus = copy.deepcopy(contract)
    unsafe_focus["wayland_translation"]["restorable_state"]["focus_rule"] = (
        "restore even to iconic clients"
    )
    mutations.append(("unsafe focus restoration", unsafe_focus))

    destructive_malformed = copy.deepcopy(contract)
    destructive_malformed["wayland_translation"]["restore_transaction"][
        "malformed_result"
    ] = "partially-apply"
    mutations.append(("destructive malformed snapshot", destructive_malformed))

    unsupported_accepted = copy.deepcopy(contract)
    unsupported_accepted["wayland_translation"]["restore_transaction"][
        "accepted_schema_versions"
    ].append(99)
    mutations.append(("unsupported version accepted", unsupported_accepted))

    dropped_scenario = copy.deepcopy(contract)
    dropped_scenario["verification_scenarios"].pop()
    mutations.append(("missing unsupported scenario", dropped_scenario))

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
        print(f"state contract validation failed: {exc}", file=sys.stderr)
        return 1
    if not isinstance(contract, dict) or not isinstance(inventory, dict):
        print(
            "state contract validation failed: contract and inventory must be objects",
            file=sys.stderr,
        )
        return 1
    try:
        errors = validate(contract, inventory, source_root)
        if args.self_test_tamper and not errors:
            errors.extend(self_test_tamper(contract, inventory, source_root))
    except (OSError, tarfile.TarError) as exc:
        print(f"state contract validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("state contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    suffix = " with 13 tamper self-tests" if args.self_test_tamper else ""
    print(
        "saved-state contract valid: 2 upstream mechanisms, 8 Wayland "
        f"requirements, 8 scenarios, {len(EXPECTED_EVIDENCE)} exact source "
        f"anchors{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
