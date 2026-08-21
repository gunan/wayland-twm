#!/usr/bin/env python3
"""Validate the frozen twm X11 resource-hint and wtwm no-op contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/x11-resource-noop-contract.json"
)
RUNTIME_RUNNER_PATH = Path("tests/integration/run_m8_noop_options.py")
EXPECTED_CANONICAL_SHA256 = (
    "3685767d15ed53b1b36a73a915e3ba51888299eede726cdb18aeae700be3f4e9"
)
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/man/twm.man": (
        "a1743a47770bd63a2ff5e63b8c6e86d72ee02ddd126813951833fb33b8a56674"
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
EXPECTED_IDENTITIES = {
    "NoBackingStore": {
        "inventory_id": "keyword.nobackingstore",
        "parser_token": "KEYWORD",
        "parser_value": "kw0_NoBackingStore",
        "evidence": ["manual.nobackingstore", "parse.nobackingstore"],
    },
    "NoSaveUnders": {
        "inventory_id": "keyword.nosaveunders",
        "parser_token": "KEYWORD",
        "parser_value": "kw0_NoSaveUnders",
        "evidence": ["manual.nosaveunders", "parse.nosaveunders"],
    },
    "NoGrabServer": {
        "inventory_id": "keyword.nograbserver",
        "parser_token": "KEYWORD",
        "parser_value": "kw0_NoGrabServer",
        "evidence": ["manual.nograbserver", "parse.nograbserver"],
    },
}
EXPECTED_STATE_OCCURRENCES = {
    "Scr->BackingStore": [
        (
            "twm-1.0.13.1/src/menus.c",
            796,
            "        if (Scr->BackingStore) {",
        ),
        (
            "twm-1.0.13.1/src/parse.c",
            695,
            "        Scr->BackingStore = FALSE;",
        ),
        (
            "twm-1.0.13.1/src/twm.c",
            757,
            "    Scr->BackingStore = TRUE;",
        ),
    ],
    "Scr->SaveUnder": [
        (
            "twm-1.0.13.1/src/menus.c",
            774,
            "            if (Scr->SaveUnder) {",
        ),
        (
            "twm-1.0.13.1/src/menus.c",
            792,
            "        if (Scr->SaveUnder) {",
        ),
        (
            "twm-1.0.13.1/src/parse.c",
            699,
            "        Scr->SaveUnder = FALSE;",
        ),
        (
            "twm-1.0.13.1/src/twm.c",
            758,
            "    Scr->SaveUnder = TRUE;",
        ),
    ],
    "Scr->NoGrabServer": [
        (
            "twm-1.0.13.1/src/events.c",
            1685,
            "    if (!Scr->NoGrabServer)",
        ),
        (
            "twm-1.0.13.1/src/menus.c",
            1462,
            "        if (!Scr->NoGrabServer || !Scr->OpaqueMove) {",
        ),
        (
            "twm-1.0.13.1/src/menus.c",
            1904,
            "        if (!Scr->NoGrabServer) {",
        ),
        (
            "twm-1.0.13.1/src/parse.c",
            667,
            "        Scr->NoGrabServer = TRUE;",
        ),
        (
            "twm-1.0.13.1/src/twm.c",
            744,
            "    Scr->NoGrabServer = FALSE;",
        ),
    ],
}
EXPECTED_BACKING_READS = ["twm-1.0.13.1/src/menus.c:796"]
EXPECTED_SAVE_READS = [
    "twm-1.0.13.1/src/menus.c:774",
    "twm-1.0.13.1/src/menus.c:792",
]
EXPECTED_GRAB_READS = [
    "twm-1.0.13.1/src/events.c:1685",
    "twm-1.0.13.1/src/menus.c:1462",
    "twm-1.0.13.1/src/menus.c:1904",
]
EXPECTED_MOVE_TRUTH_TABLE = [
    {"NoGrabServer": False, "OpaqueMove": False, "XGrabServer": True},
    {"NoGrabServer": False, "OpaqueMove": True, "XGrabServer": True},
    {"NoGrabServer": True, "OpaqueMove": False, "XGrabServer": True},
    {"NoGrabServer": True, "OpaqueMove": True, "XGrabServer": False},
]
EXPECTED_CLASSIFICATIONS = {
    "NoBackingStore": "verified-no-op",
    "NoSaveUnders": "verified-no-op",
    "NoGrabServer": "verified-no-op",
}
EXPECTED_PARSER_STATE = {
    "retention_required": True,
    "explicit_fields": [
        "no_backing_store",
        "no_save_unders",
        "no_grab_server",
    ],
    "directive_value": True,
    "absent_value": False,
    "may_be_discarded_after_parse": False,
    "rule": (
        "Each recognized directive remains explicit in the active parsed "
        "configuration even though runtime behavior is invariant."
    ),
}
EXPECTED_INVARIANTS = [
    "visible pixels",
    "compositor-owned window and menu state",
    "input event sequence and resulting action",
    "native Wayland client behavior and protocol continuity",
    "Xwayland client behavior and protocol continuity",
]
EXPECTED_DIRECTIVE_SUBSETS = [
    [],
    ["NoBackingStore"],
    ["NoSaveUnders"],
    ["NoGrabServer"],
    ["NoBackingStore", "NoSaveUnders"],
    ["NoBackingStore", "NoGrabServer"],
    ["NoSaveUnders", "NoGrabServer"],
    ["NoBackingStore", "NoSaveUnders", "NoGrabServer"],
]
EXPECTED_REQUIREMENT_EVIDENCE = {
    "x11-noop.nobackingstore-scope": [
        "manual.nobackingstore-scope",
        "manual.nobackingstore-effect",
        "state.backingstore-disable",
        "backingstore.menu-condition",
        "backingstore.menu-mask",
        "backingstore.menu-value",
    ],
    "x11-noop.nosaveunders-scope": [
        "manual.nosaveunders-scope",
        "manual.nosaveunders-effect",
        "state.saveunder-disable",
        "saveunder.shadow-condition",
        "saveunder.shadow-mask",
        "saveunder.shadow-value",
        "saveunder.menu-condition",
        "saveunder.menu-mask",
        "saveunder.menu-value",
    ],
    "x11-noop.nograbserver-scope": [
        "manual.nograbserver-scope",
        "manual.nograbserver-effect",
        "state.nograbserver-enable",
        "grab.menu-condition",
        "grab.menu-call",
        "grab.move-condition",
        "grab.move-call",
    ],
    "x11-noop.outlined-move-boundary": [
        "grab.move-condition",
        "grab.move-call",
    ],
    "x11-noop.parser-retention": [
        "parse.nobackingstore",
        "parse.nosaveunders",
        "parse.nograbserver",
    ],
    "x11-noop.runtime-invariance": [
        "manual.nobackingstore-scope",
        "manual.nosaveunders-scope",
        "manual.nograbserver-effect",
    ],
    "x11-noop.no-invented-x-resources": [
        "backingstore.menu-mask",
        "saveunder.shadow-mask",
        "saveunder.menu-mask",
        "grab.menu-call",
        "grab.move-call",
    ],
    "x11-noop.future-effect-gate": [
        "manual.nobackingstore-effect",
        "manual.nosaveunders-effect",
        "manual.nograbserver-effect",
    ],
}
EXPECTED_SCENARIOS = {
    "reference-default-menu-attributes": "reference-positive",
    "reference-nobackingstore": "reference-negative",
    "reference-nosaveunders": "reference-negative",
    "reference-menu-grab": "reference-positive-negative-pair",
    "reference-opaque-move-grab": "reference-negative",
    "reference-outlined-move-grab": "reference-boundary",
    "translation-parser-retention": "translation-positive",
    "translation-menu-invariance": "translation-differential",
    "translation-opaque-move-invariance": "translation-differential",
    "translation-outlined-move-invariance": "translation-differential",
    "translation-native-continuity": "translation-negative",
    "translation-xwayland-continuity": "translation-negative",
    "translation-combined-state-boundary": "translation-differential",
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


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Archive:
    """Read and search exact members of the pinned upstream archive."""

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

    def source_occurrences(self, needle: str) -> list[tuple[str, int, str]]:
        matches: list[tuple[str, int, str]] = []
        with tarfile.open(self.path, "r:xz") as source:
            for member in source.getmembers():
                if not member.isfile() or "/src/" not in member.name:
                    continue
                extracted = source.extractfile(member)
                if extracted is None:
                    continue
                lines = extracted.read().decode("utf-8").splitlines()
                for number, line in enumerate(lines, 1):
                    if needle in line:
                        matches.append((member.name, number, line))
        return sorted(matches)


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


def records_by_name(value: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    records: dict[str, Any] = {}
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            errors.append(f"{location}[{index}] must be an object")
            continue
        name = record.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{location}[{index}].name must be a nonempty string")
            continue
        if name in records:
            errors.append(f"duplicate {location} name {name!r}")
        records[name] = record
    return records


def evidence_references(value: Any, at_root: bool = True) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if at_root and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, str):
                yield child
            elif key == "evidence" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from evidence_references(child, False)
    elif isinstance(value, list):
        for child in value:
            yield from evidence_references(child, False)


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    keywords = inventory.get("keywords") if isinstance(inventory, dict) else None
    if not isinstance(keywords, list):
        errors.append("inventory keywords must be an array")
        return
    by_id = {
        item.get("id"): item
        for item in keywords
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for name, expected in EXPECTED_IDENTITIES.items():
        item = by_id.get(expected["inventory_id"])
        if not isinstance(item, dict):
            errors.append(f"inventory lacks {expected['inventory_id']}")
            continue
        if item.get("spelling") != name.lower():
            errors.append(f"inventory spelling mismatch for {name}")
        if item.get("parser_token") != expected["parser_token"]:
            errors.append(f"inventory parser token mismatch for {name}")
        if item.get("parser_value") != expected["parser_value"]:
            errors.append(f"inventory parser value mismatch for {name}")
        anchor = item.get("evidence")
        contract_anchor_id = expected["evidence"][1]
        expected_anchor = {
            "archive_member": {
                "NoBackingStore": "twm-1.0.13.1/src/parse.c",
                "NoSaveUnders": "twm-1.0.13.1/src/parse.c",
                "NoGrabServer": "twm-1.0.13.1/src/parse.c",
            }[name],
            "line": {
                "NoBackingStore": 533,
                "NoSaveUnders": 545,
                "NoGrabServer": 536,
            }[name],
            "text": {
                "NoBackingStore": (
                    '    { "nobackingstore",         KEYWORD, '
                    "kw0_NoBackingStore },"
                ),
                "NoSaveUnders": (
                    '    { "nosaveunders",           KEYWORD, '
                    "kw0_NoSaveUnders },"
                ),
                "NoGrabServer": (
                    '    { "nograbserver",           KEYWORD, '
                    "kw0_NoGrabServer },"
                ),
            }[name],
        }
        if anchor != expected_anchor:
            errors.append(
                f"inventory evidence mismatch for {name} ({contract_anchor_id})"
            )


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("reference_behavior must be an object")
        return
    if set(value) != {
        "directive_identity",
        "defaults",
        "no_backing_store",
        "no_save_unders",
        "no_grab_server",
    }:
        errors.append("reference_behavior fields differ from schema")
        return
    identities = records_by_name(
        value.get("directive_identity"),
        "reference_behavior.directive_identity",
        errors,
    )
    if set(identities) != set(EXPECTED_IDENTITIES):
        errors.append("directive identity set mismatch")
    for name, expected in EXPECTED_IDENTITIES.items():
        record = identities.get(name, {})
        if record.get("argument_count") != 0:
            errors.append(f"{name} must remain a zero-argument KEYWORD")
        for key, expected_value in expected.items():
            if record.get(key) != expected_value:
                errors.append(f"{name} {key} mismatch")

    defaults = value.get("defaults")
    if defaults != {
        "BackingStore": True,
        "SaveUnder": True,
        "NoGrabServer": False,
        "evidence": [
            "default.backingstore-enabled",
            "default.saveunder-enabled",
            "default.nograbserver-disabled",
        ],
    }:
        errors.append("upstream defaults mismatch")

    backing = value.get("no_backing_store")
    if not isinstance(backing, dict):
        errors.append("no_backing_store must be an object")
    else:
        if backing.get("complete_state_reads") != EXPECTED_BACKING_READS:
            errors.append("BackingStore read scope is not the single menu-window read")
        if backing.get("scope") != "twm menu window only":
            errors.append("NoBackingStore scope must remain the twm menu window")
        if "CWBackingStore" not in str(backing.get("effect")):
            errors.append("NoBackingStore effect must name CWBackingStore")

    save = value.get("no_save_unders")
    if not isinstance(save, dict):
        errors.append("no_save_unders must be an object")
    else:
        if save.get("complete_state_reads") != EXPECTED_SAVE_READS:
            errors.append("SaveUnder read scope must contain menu shadow and menu")
        if save.get("scope") != "twm menu shadow and menu windows only":
            errors.append("NoSaveUnders scope must remain menu shadow and menu")
        if "CWSaveUnder" not in str(save.get("effect")):
            errors.append("NoSaveUnders effect must name CWSaveUnder")

    grab = value.get("no_grab_server")
    if not isinstance(grab, dict):
        errors.append("no_grab_server must be an object")
    else:
        if grab.get("complete_state_reads") != EXPECTED_GRAB_READS:
            errors.append("NoGrabServer read scope mismatch")
        if grab.get("move_grab_truth_table") != EXPECTED_MOVE_TRUTH_TABLE:
            errors.append("NoGrabServer/OpaqueMove grab truth table mismatch")
        if grab.get("scope") != (
            "twm menu grabs and opaque-move grabs; outlined moves still grab"
        ):
            errors.append("NoGrabServer outlined-move boundary mismatch")


def validate_translation(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("wayland_translation must be an object")
        return
    if set(value) != {
        "classification",
        "parser_state",
        "platform_boundary",
        "runtime_invariance",
        "future_visible_effect",
    }:
        errors.append("wayland_translation fields differ from schema")
        return
    classifications = records_by_name(
        value.get("classification"),
        "wayland_translation.classification",
        errors,
    )
    if set(classifications) != set(EXPECTED_CLASSIFICATIONS):
        errors.append("Wayland classification set mismatch")
    for name, expected_status in EXPECTED_CLASSIFICATIONS.items():
        record = classifications.get(name, {})
        if record.get("status") != expected_status:
            errors.append(f"{name} must remain a verified-no-op")
        if not isinstance(record.get("reason"), str) or not record["reason"]:
            errors.append(f"{name} no-op classification requires a reason")

    if value.get("parser_state") != EXPECTED_PARSER_STATE:
        errors.append("explicit retained parser-state contract mismatch")

    boundary = value.get("platform_boundary")
    expected_boundary = {
        "wtwm_creates_x_menu_windows": False,
        "wtwm_creates_x_menu_shadow_windows": False,
        "wayland_has_x_server_grab_primitive": False,
        "wtwm_uses_x_server_grab_for_scene_menu_or_move": False,
        "scene_rendering_and_input_owned_by_compositor": True,
        "xwayland_client_x_protocol_remains_owned_by_xwayland": True,
    }
    if boundary != expected_boundary:
        errors.append("Wayland/Xwayland platform boundary mismatch")

    invariance = value.get("runtime_invariance")
    if not isinstance(invariance, dict):
        errors.append("runtime_invariance must be an object")
    else:
        if invariance.get("directive_subsets") != EXPECTED_DIRECTIVE_SUBSETS:
            errors.append("runtime coverage must name all eight directive subsets")
        if invariance.get("must_remain_identical") != EXPECTED_INVARIANTS:
            errors.append("runtime invariance channels mismatch")
        if invariance.get("state_rule") != (
            "the retained parser booleans are the only state difference"
        ):
            errors.append("runtime state boundary mismatch")
        for rule in ("menu_rule", "move_rule", "client_rule"):
            if not isinstance(invariance.get(rule), str) or not invariance[rule]:
                errors.append(f"runtime_invariance.{rule} must be nonempty")

    future = value.get("future_visible_effect")
    if not isinstance(future, dict):
        errors.append("future_visible_effect must be an object")
    else:
        if future.get("allowed_without_reclassification") is not False:
            errors.append("future visible effects require reclassification")
        if not isinstance(future.get("rule"), str) or not future["rule"]:
            errors.append("future visible-effect gate requires a rule")


def load_wtwm_sources(source_root: Path) -> dict[str, str]:
    """Load the portable config ABI and compositor sources for boundary checks."""

    sources: dict[str, str] = {}
    for directory_name in ("include", "src"):
        directory = source_root / directory_name
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {".c", ".h"}:
                relative = path.relative_to(source_root).as_posix()
                sources[relative] = path.read_text(encoding="utf-8")
    return sources


def validate_wtwm_structure(sources: dict[str, str]) -> list[str]:
    """Prove the flags are retained but have no compositor/X request consumer."""

    errors: list[str] = []
    config_header = sources.get("include/wtwm/config.h")
    config_source = sources.get("src/config.c")
    if config_header is None:
        errors.append("wtwm config header is missing")
        config_header = ""
    if config_source is None:
        errors.append("wtwm portable config source is missing")
        config_source = ""

    fields = {
        "no_backing_store": "NoBackingStore",
        "no_save_unders": "NoSaveUnders",
        "no_grab_server": "NoGrabServer",
    }
    for field, directive in fields.items():
        declaration = re.compile(rf"^\s*bool\s+{field}\s*;\s*$", re.MULTILINE)
        flag = re.compile(
            rf'FLAG\("{directive}"\s*,\s*{field}\s*,\s*true\s*\)'
        )
        dump = re.compile(rf"DUMP_BOOL\(\s*{field}\s*\)")
        if len(declaration.findall(config_header)) != 1:
            errors.append(f"config ABI must contain exactly one bool {field}")
        if len(flag.findall(config_source)) != 1:
            errors.append(f"parser must contain exactly one {directive} flag binding")
        if len(dump.findall(config_source)) != 1:
            errors.append(f"config dump must retain exactly one {field} value")

        allowed = {
            "include/wtwm/config.h": [declaration],
            "src/config.c": [flag, dump],
        }
        if field == "no_grab_server":
            allowed["src/config.c"].append(re.compile(r"config->no_grab_server"))
            if config_source.count("config->no_grab_server") != 1:
                errors.append(
                    "legacy no-grab-server config dump must be its only config-> read"
                )
        for path, text in sources.items():
            for number, line in enumerate(text.splitlines(), 1):
                if field not in line:
                    continue
                patterns = allowed.get(path, [])
                if not any(pattern.search(line) for pattern in patterns):
                    errors.append(
                        f"unexpected runtime consumer of {field}: {path}:{number}"
                    )

    prohibited_requests = re.compile(
        r"\b(?:XGrabServer|XUngrabServer|xcb_grab_server|xcb_ungrab_server)\s*\("
    )
    prohibited_attributes = re.compile(r"\b(?:CWBackingStore|CWSaveUnder)\b")
    for path, source in sources.items():
        request = prohibited_requests.search(source)
        if request is not None:
            number = source.count("\n", 0, request.start()) + 1
            errors.append(f"wtwm issues an X server-grab request at {path}:{number}")
        attribute = prohibited_attributes.search(source)
        if attribute is not None:
            number = source.count("\n", 0, attribute.start()) + 1
            errors.append(
                f"wtwm issues an X backing-store/save-under request at {path}:{number}"
            )
    return errors


def validate_runtime_runner(source: str) -> list[str]:
    required = (
        "OBSERVATION_STABLE_SAMPLES = 3",
        "OBSERVATION_MAX_ATTEMPTS = 24",
        "consecutive >= OBSERVATION_STABLE_SAMPLES",
        "def is_redundant_xwayland_configure_echo(",
        'key is None or key[0] != "x11"',
        "def canonical_trace(",
        "if is_redundant_xwayland_configure_echo(events, index):",
        "del events[index:index + 2]",
        "def self_test_trace_normalization()",
        "self_test_trace_normalization()",
        '"state": normalized(self.control.state())',
        '"trace": canonical_trace(normalized(self.control.trace()))',
    )
    return [
        f"runtime A/B runner lacks bounded quiescence guard {needle!r}"
        for needle in required if needle not in source
    ]


def validate_contract(
    contract: Any,
    inventory: Any,
    source_root: Path,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]
    if set(contract) != EXPECTED_TOP_LEVEL:
        errors.append("contract top-level fields differ from schema")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if canonical_sha256(contract) != EXPECTED_CANONICAL_SHA256:
        errors.append("contract differs from the reviewed canonical contract")
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream provenance differs from the pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes differ from the frozen set")

    archive_path = source_root / EXPECTED_UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append(f"pinned archive is missing: {archive_path}")
        return errors
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != EXPECTED_UPSTREAM[
        "sha256"
    ]:
        errors.append("pinned archive SHA-256 mismatch")
        return errors
    archive = Archive(archive_path)
    for member, expected_digest in EXPECTED_SOURCE_MEMBERS.items():
        try:
            data = archive.read(member)
        except (KeyError, tarfile.TarError) as exc:
            errors.append(str(exc))
            continue
        if hashlib.sha256(data).hexdigest() != expected_digest:
            errors.append(f"source member SHA-256 mismatch: {member}")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) != 33:
        errors.append("evidence must contain the 33 frozen source anchors")
        evidence = {}
    for evidence_id, anchor in evidence.items():
        if not isinstance(anchor, dict) or set(anchor) != {"member", "line", "text"}:
            errors.append(f"evidence.{evidence_id} fields differ from schema")
            continue
        member = anchor.get("member")
        number = anchor.get("line")
        text = anchor.get("text")
        if member not in EXPECTED_SOURCE_MEMBERS:
            errors.append(f"evidence.{evidence_id} uses an unpinned source member")
            continue
        if not isinstance(number, int) or not isinstance(text, str):
            errors.append(f"evidence.{evidence_id} line/text types are invalid")
            continue
        try:
            actual = archive.line(member, number)
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"evidence.{evidence_id} cannot be read: {exc}")
            continue
        if actual != text:
            errors.append(f"evidence.{evidence_id} exact source line mismatch")

    references = list(evidence_references(contract))
    for evidence_id in references:
        if evidence_id not in evidence:
            errors.append(f"unknown evidence reference {evidence_id!r}")
    unused = sorted(set(evidence) - set(references))
    if unused:
        errors.append(f"unused source anchors: {', '.join(unused)}")

    for needle, expected in EXPECTED_STATE_OCCURRENCES.items():
        actual = archive.source_occurrences(needle)
        if actual != expected:
            errors.append(f"complete upstream occurrence proof changed for {needle}")

    validate_inventory(inventory, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)
    errors.extend(validate_wtwm_structure(load_wtwm_sources(source_root)))

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != set(EXPECTED_REQUIREMENT_EVIDENCE):
        errors.append("requirement coverage mismatch")
    for requirement_id, expected_evidence in EXPECTED_REQUIREMENT_EVIDENCE.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "level", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        if record.get("level") != "MUST":
            errors.append(f"{requirement_id} must be a MUST requirement")
        if not isinstance(record.get("rule"), str) or not record["rule"]:
            errors.append(f"{requirement_id} rule must be nonempty")
        if record.get("evidence") != expected_evidence:
            errors.append(f"{requirement_id} evidence mismatch")

    scenarios = records_by_id(
        contract.get("verification_scenarios"),
        "verification_scenarios",
        errors,
    )
    if set(scenarios) != set(EXPECTED_SCENARIOS):
        errors.append("positive/negative scenario coverage mismatch")
    for scenario_id, expected_kind in EXPECTED_SCENARIOS.items():
        record = scenarios.get(scenario_id, {})
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        if record.get("kind") != expected_kind:
            errors.append(f"{scenario_id} kind mismatch")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} oracle must be nonempty")
    return errors


def run_tamper_tests(
    contract: dict[str, Any],
    inventory: Any,
    source_root: Path,
) -> list[str]:
    mutations: list[tuple[str, dict[str, Any]]] = []

    broken_anchor = copy.deepcopy(contract)
    broken_anchor["evidence"]["grab.move-condition"]["text"] += " tampered"
    mutations.append(("exact source anchor", broken_anchor))

    expanded_backing_scope = copy.deepcopy(contract)
    expanded_backing_scope["reference_behavior"]["no_backing_store"]["scope"] = (
        "all X windows"
    )
    mutations.append(("expanded backing-store scope", expanded_backing_scope))

    missing_shadow = copy.deepcopy(contract)
    missing_shadow["reference_behavior"]["no_save_unders"][
        "complete_state_reads"
    ].pop(0)
    mutations.append(("missing save-under shadow read", missing_shadow))

    skipped_outline_grab = copy.deepcopy(contract)
    skipped_outline_grab["reference_behavior"]["no_grab_server"][
        "move_grab_truth_table"
    ][2]["XGrabServer"] = False
    mutations.append(("outlined move grab boundary", skipped_outline_grab))

    visible_classification = copy.deepcopy(contract)
    visible_classification["wayland_translation"]["classification"][0][
        "status"
    ] = "visible-effect"
    mutations.append(("verified no-op classification", visible_classification))

    discarded_parser_state = copy.deepcopy(contract)
    discarded_parser_state["wayland_translation"]["parser_state"][
        "may_be_discarded_after_parse"
    ] = True
    mutations.append(("parser-state retention", discarded_parser_state))

    invented_menu_window = copy.deepcopy(contract)
    invented_menu_window["wayland_translation"]["platform_boundary"][
        "wtwm_creates_x_menu_windows"
    ] = True
    mutations.append(("invented X menu window", invented_menu_window))

    dropped_pixels = copy.deepcopy(contract)
    dropped_pixels["wayland_translation"]["runtime_invariance"][
        "must_remain_identical"
    ].remove("visible pixels")
    mutations.append(("visible-pixel invariance", dropped_pixels))

    dropped_xwayland = copy.deepcopy(contract)
    dropped_xwayland["wayland_translation"]["runtime_invariance"][
        "must_remain_identical"
    ].remove("Xwayland client behavior and protocol continuity")
    mutations.append(("Xwayland continuity", dropped_xwayland))

    ungated_future_effect = copy.deepcopy(contract)
    ungated_future_effect["wayland_translation"]["future_visible_effect"][
        "allowed_without_reclassification"
    ] = True
    mutations.append(("future visible-effect gate", ungated_future_effect))

    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement))

    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("positive/negative scenario coverage", missing_scenario))

    failures: list[str] = []
    for name, mutated in mutations:
        if not validate_contract(mutated, inventory, source_root):
            failures.append(f"tamper self-test was not rejected: {name}")

    sources = load_wtwm_sources(source_root)
    missing_field = copy.deepcopy(sources)
    missing_field["include/wtwm/config.h"] = missing_field[
        "include/wtwm/config.h"
    ].replace("\tbool no_backing_store;\n", "", 1)
    if not validate_wtwm_structure(missing_field):
        failures.append("tamper self-test was not rejected: missing parser boolean")

    invented_grab = copy.deepcopy(sources)
    invented_grab["src/wtwm.c"] += "\nvoid tampered(void) { XGrabServer(dpy); }\n"
    if not validate_wtwm_structure(invented_grab):
        failures.append("tamper self-test was not rejected: invented X server grab")

    runner = (source_root / RUNTIME_RUNNER_PATH).read_text(encoding="utf-8")
    broadened_normalization = runner.replace(
        'key is None or key[0] != "x11"',
        "key is None",
        1,
    )
    if not validate_runtime_runner(broadened_normalization):
        failures.append("tamper self-test was not rejected: broadened trace normalization")
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
        errors = validate_contract(contract, inventory, source_root)
        errors.extend(validate_runtime_runner(
            (source_root / RUNTIME_RUNNER_PATH).read_text(encoding="utf-8")
        ))
        normalization_test = subprocess.run(
            [
                sys.executable,
                "-B",
                str(source_root / RUNTIME_RUNNER_PATH),
                "--self-test-trace-normalization",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if normalization_test.returncode != 0:
            errors.append(
                "runtime trace-normalization self-test failed: "
                + (normalization_test.stderr.strip() or normalization_test.stdout.strip())
            )
        if args.self_test_tamper and isinstance(contract, dict):
            errors.extend(run_tamper_tests(contract, inventory, source_root))
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"X11 resource no-op contract validation failed: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("X11 resource no-op contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        "X11 resource no-op contract valid: 33 exact source anchors, "
        "3 verified no-ops, 8 directive subsets, 8 requirements, "
        "13 scenarios, 14 tamper self-tests"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
