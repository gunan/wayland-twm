#!/usr/bin/env python3
"""Validate the frozen twm cut-buffer and wtwm clipboard translation contract."""

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
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/cut-buffer-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "6d6dd04e43faf7f4b217429ce3cc12b28dee478c3e7a2fb5a32f3a07e140ac01"
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
    "twm-1.0.13.1/src/gram.y": (
        "7b7c66abb6280891ffc265c25c7989b206e16d883008db44a94dd057f39e8a52"
    ),
    "twm-1.0.13.1/src/lex.l": (
        "7602b84882e6a2714295997ccc8e29db99ced98f3607f71cc5b2f422ee46fbc7"
    ),
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/menus.h": (
        "2ac660c04c2df65c7c2ee6fac5fc2e812cf06b518eedba37705aa68c2a13b572"
    ),
    "twm-1.0.13.1/src/parse.c": (
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c"
    ),
    "twm-1.0.13.1/src/util.c": (
        "50f520eff663c8e5b7d735d46bc244e00f79898044a94a031767e97b02265318"
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
EXPECTED_EVIDENCE_IDS = {
    "manual.shorthand",
    "manual.shorthand-equivalence",
    "manual.cut",
    "manual.cut-newline",
    "manual.cut-property",
    "manual.cutfile",
    "manual.cutfile-source",
    "manual.cutfile-replace",
    "manual.file",
    "manual.file-read",
    "manual.file-destination",
    "parse.cut",
    "parse.cutfile",
    "parse.file",
    "lexer.cut-shorthand",
    "parser.string-action",
    "parser.action-copy",
    "limit.max-file-size",
    "dispatch.buffer",
    "dispatch.cut",
    "cut.copy",
    "cut.newline",
    "cut.store",
    "dispatch.cutfile",
    "cutfile.fetch",
    "cutfile.token",
    "cutfile.expand",
    "cutfile.open",
    "cutfile.read",
    "cutfile.nonempty",
    "cutfile.store",
    "cutfile.empty-warning",
    "dispatch.file",
    "file.expand",
    "file.open",
    "file.read",
    "file.nonempty",
    "file.store",
    "file.expand-warning",
    "expand.leading-tilde",
    "expand.plain-copy",
    "expand.allocation",
    "expand.join",
}
EXPECTED_ACTIONS = [
    {
        "name": "f.cut",
        "inventory_id": "keyword.f.cut",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_CUT",
        "argument_count": 1,
        "evidence": ["parse.cut", "parser.string-action", "parser.action-copy"],
    },
    {
        "name": "f.cutfile",
        "inventory_id": "keyword.f.cutfile",
        "parser_token": "FKEYWORD",
        "parser_value": "F_CUTFILE",
        "argument_count": 0,
        "evidence": ["parse.cutfile"],
    },
    {
        "name": "f.file",
        "inventory_id": "keyword.f.file",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_FILE",
        "argument_count": 1,
        "evidence": ["parse.file", "parser.string-action", "parser.action-copy"],
    },
]
EXPECTED_PRESERVE_CONDITIONS = {
    "f_file": [
        "filename expansion failure",
        "open failure",
        "read error",
        "empty file",
    ],
    "f_cutfile": [
        "empty cut buffer",
        "whitespace-only cut buffer",
        "filename expansion failure",
        "open failure",
        "read error",
        "empty file",
    ],
}
EXPECTED_CLASSIFICATIONS = {
    "f.cut": "behaviorally-equivalent",
    "cut-shorthand": "behaviorally-equivalent",
    "f.file": "behaviorally-equivalent",
    "f.cutfile": "behaviorally-equivalent",
}
EXPECTED_MIME_TYPES = ["text/plain;charset=utf-8", "text/plain"]
EXPECTED_PUBLISH_ORDER = [
    "atomically replace the compositor legacy bytes",
    "replace the ordinary Wayland CLIPBOARD selection with a compositor-owned source",
    (
        "mirror the exact bytes to Xwayland root CUT_BUFFER0 type STRING when "
        "Xwayland is ready"
    ),
]
EXPECTED_REQUIREMENT_IDS = {
    "cut.parser-identity",
    "cut.reference-bytes",
    "cut.persistent-buffer",
    "cut.clipboard-publication",
    "cut.xwayland-mirror",
    "cut.cutfile-source",
    "cut.source-io-safety",
    "cut.lifecycle",
}
EXPECTED_SCENARIOS = {
    "parser-three-actions-and-shorthand": "parser-positive-negative-pair",
    "reference-cut-newline": "reference-positive",
    "reference-file-capacity": "reference-boundary",
    "reference-cutfile-token": "reference-boundary",
    "native-before-xwayland": "runtime-readiness",
    "late-xwayland-mirror": "runtime-readiness",
    "dual-publish-xwayland-ready": "runtime-cross-client",
    "native-to-x11-clipboard": "runtime-cross-client",
    "xwayland-to-native-clipboard": "runtime-cross-client",
    "cutfile-external-x-property": "runtime-xwayland",
    "cutfile-internal-fallback": "runtime-native",
    "foreign-clipboard-independence": "runtime-state-machine",
    "primary-invariance": "runtime-negative",
    "empty-and-error-preserve": "runtime-negative",
    "file-exact-capacity": "runtime-boundary",
    "binary-byte-length": "runtime-boundary",
    "successive-source-replacement": "runtime-state-machine",
    "restart-preserves-source": "runtime-lifecycle",
    "send-io-boundaries": "runtime-resource-safety",
    "shutdown-destruction": "runtime-resource-safety",
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
    """Read exact members and lines from the pinned release archive."""

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


def require_object(parent: Any, key: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(parent, dict) or not isinstance(parent.get(key), dict):
        errors.append(f"{key} must be an object")
        return {}
    return parent[key]


def evidence_references(value: Any, at_root: bool = True) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if at_root and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from evidence_references(child, False)
    elif isinstance(value, list):
        for child in value:
            yield from evidence_references(child, False)


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    if not isinstance(inventory, dict):
        errors.append("upstream inventory must be an object")
        return
    keywords = inventory.get("keywords")
    lexical = inventory.get("lexical_forms")
    if not isinstance(keywords, list) or not isinstance(lexical, list):
        errors.append("inventory keyword or lexical arrays are missing")
        return
    all_records = {
        entry.get("id"): entry
        for entry in keywords + lexical
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    expected = {
        "keyword.f.cut": {
            "spelling": "f.cut",
            "parser_token": "FSKEYWORD",
            "parser_value": "F_CUT",
        },
        "keyword.f.cutfile": {
            "spelling": "f.cutfile",
            "parser_token": "FKEYWORD",
            "parser_value": "F_CUTFILE",
        },
        "keyword.f.file": {
            "spelling": "f.file",
            "parser_token": "FSKEYWORD",
            "parser_value": "F_FILE",
        },
        "lexical.cut-shorthand": {"pattern": '"^"'},
    }
    for record_id, fields in expected.items():
        record = all_records.get(record_id)
        if not isinstance(record, dict):
            errors.append(f"inventory lacks {record_id}")
            continue
        for key, expected_value in fields.items():
            if record.get(key) != expected_value:
                errors.append(f"inventory {record_id} {key} mismatch")


def validate_archive(
    root: Path,
    upstream: Any,
    source_members: Any,
    evidence: Any,
    errors: list[str],
) -> None:
    archive_path = root / EXPECTED_UPSTREAM["archive"]
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as exc:
        errors.append(f"cannot read upstream archive: {exc}")
        return
    if hashlib.sha256(archive_bytes).hexdigest() != EXPECTED_UPSTREAM["sha256"]:
        errors.append("pinned upstream archive SHA-256 mismatch")
        return
    if not isinstance(upstream, dict) or upstream.get("sha256") != (
        EXPECTED_UPSTREAM["sha256"]
    ):
        errors.append("contract archive SHA-256 pin mismatch")
    if not isinstance(source_members, dict) or not isinstance(evidence, dict):
        return
    archive = Archive(archive_path)
    for member, expected_digest in EXPECTED_SOURCE_MEMBERS.items():
        try:
            content = archive.read(member)
        except (KeyError, tarfile.TarError) as exc:
            errors.append(str(exc))
            continue
        if hashlib.sha256(content).hexdigest() != expected_digest:
            errors.append(f"source member SHA-256 mismatch: {member}")
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
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            or not isinstance(text, str)
        ):
            errors.append(f"evidence.{evidence_id} line/text types are invalid")
            continue
        try:
            actual = archive.line(member, number)
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"evidence.{evidence_id} cannot be read: {exc}")
            continue
        if actual != text:
            errors.append(f"evidence.{evidence_id} exact source line mismatch")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("reference_behavior must be an object")
        return
    if set(value) != {
        "action_identity",
        "cut_shorthand",
        "storage",
        "f_cut",
        "f_file",
        "f_cutfile",
        "filename_expansion",
    }:
        errors.append("reference_behavior fields differ from schema")
    if value.get("action_identity") != EXPECTED_ACTIONS:
        errors.append("action signatures differ from pinned parser identities")
    shorthand = value.get("cut_shorthand")
    expected_shorthand = {
        "inventory_id": "lexical.cut-shorthand",
        "spelling": "^",
        "equivalent_action": "f.cut",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_CUT",
        "evidence": [
            "manual.shorthand",
            "manual.shorthand-equivalence",
            "lexer.cut-shorthand",
        ],
    }
    if shorthand != expected_shorthand:
        errors.append("caret shorthand equivalence mismatch")

    storage = require_object(value, "storage", errors)
    if storage.get("property_type") != "STRING":
        errors.append("reference cut-buffer property type must be STRING")
    if "CUT_BUFFER0" not in str(storage.get("destination")):
        errors.append("reference storage destination must be CUT_BUFFER0")
    if "replaces" not in str(storage.get("replacement")):
        errors.append("reference XStoreBytes replacement rule mismatch")

    cut = require_object(value, "f_cut", errors)
    if cut.get("output") != (
        "the action string bytes followed by exactly one newline byte"
    ):
        errors.append("f.cut exact one-newline output mismatch")
    if cut.get("empty_argument_output") != "one newline byte":
        errors.append("empty f.cut argument must publish one newline")

    for key in ("f_file", "f_cutfile"):
        action = require_object(value, key, errors)
        if action.get("read_operation") != (
            "one read of at most MAX_FILE_SIZE minus one bytes"
        ):
            errors.append(f"{key} one-read boundary mismatch")
        if action.get("maximum_replacement_bytes") != 4095:
            errors.append(f"{key} maximum replacement must be 4095 bytes")
        if action.get("preserve_conditions") != EXPECTED_PRESERVE_CONDITIONS[key]:
            errors.append(f"{key} preserve-on-error conditions mismatch")
        replacement = str(action.get("replacement_condition"))
        if "more than zero bytes" not in replacement:
            errors.append(f"{key} must replace only after a nonempty read")
    cutfile = require_object(value, "f_cutfile", errors)
    token = str(cutfile.get("filename_decoding"))
    if not all(term in token for term in ("first", "non-whitespace", "ignored")):
        errors.append("f.cutfile percent-s first-token decoding mismatch")

    expansion = require_object(value, "filename_expansion", errors)
    if expansion.get("tilde_user_lookup") is not False:
        errors.append("reference leading tilde must not perform user lookup")
    if expansion.get("examples") != {
        "file": "file",
        "~/file": "HOME//file",
        "~user/file": "HOME/user/file",
    }:
        errors.append("leading-tilde expansion examples mismatch")
    leading = str(expansion.get("leading_tilde"))
    if not all(term in leading for term in ("any leading tilde", "HOME", "remainder")):
        errors.append("leading-tilde concatenation rule mismatch")


def validate_translation(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("wayland_translation must be an object")
        return
    if set(value) != {
        "classification",
        "legacy_buffer",
        "successful_publish",
        "wayland_clipboard",
        "xwayland_cut_buffer",
        "cutfile_source_precedence",
        "action_outputs",
        "lifecycle",
    }:
        errors.append("wayland_translation fields differ from schema")
    if value.get("classification") != EXPECTED_CLASSIFICATIONS:
        errors.append("cut action translation classifications mismatch")

    legacy = require_object(value, "legacy_buffer", errors)
    if legacy.get("owner") != "the compositor":
        errors.append("legacy buffer must be compositor owned")
    representation = str(legacy.get("representation"))
    if not all(term in representation for term in ("byte array", "byte length", "zero")):
        errors.append("legacy buffer must be length-delimited and binary safe")
    if legacy.get("initial_state") != "empty and unpublished":
        errors.append("legacy buffer initial state mismatch")
    if legacy.get("maximum_file_bytes") != 4095:
        errors.append("translated file byte limit must remain 4095")
    persistence = str(legacy.get("persistence_rule"))
    if not all(term in persistence for term in ("foreign clipboard", "restart", "do not mutate")):
        errors.append("legacy-byte ownership independence mismatch")

    publish = require_object(value, "successful_publish", errors)
    if publish.get("order") != EXPECTED_PUBLISH_ORDER:
        errors.append("successful dual-publication order mismatch")
    isolation = str(publish.get("failure_isolation"))
    if not all(term in isolation for term in ("Xwayland", "never rolls back", "CLIPBOARD")):
        errors.append("unavailable Xwayland must not undo native publication")
    primary = str(publish.get("primary_selection"))
    if not all(term in primary for term in ("never", "PRIMARY")):
        errors.append("cut actions must never mutate PRIMARY")

    clipboard = require_object(value, "wayland_clipboard", errors)
    if clipboard.get("seat_channel") != (
        "ordinary CLIPBOARD via wlr_seat_set_selection"
    ):
        errors.append("ordinary Wayland CLIPBOARD channel mismatch")
    if clipboard.get("mime_types") != EXPECTED_MIME_TYPES:
        errors.append("compositor data-source MIME types mismatch")
    if clipboard.get("serial") != (
        "wl_display_next_serial on the compositor display for every compositor-owned publication"
    ):
        errors.append("compositor selection serial rule mismatch")
    send = str(clipboard.get("send"))
    if not all(
        term in send
        for term in ("exact stored byte length", "partial writes", "EINTR", "close", "exactly once")
    ):
        errors.append("data-source send I/O safety rule mismatch")
    cancellation = str(clipboard.get("cancellation"))
    if not all(
        term in cancellation
        for term in ("canceled", "destroyed", "persistent legacy bytes")
    ):
        errors.append("clipboard cancellation independence mismatch")
    destruction = str(clipboard.get("destruction"))
    if not all(term in destruction for term in ("MIME", "payload", "exactly once")):
        errors.append("data-source destruction completeness mismatch")

    xwayland = require_object(value, "xwayland_cut_buffer", errors)
    expected_x_fields = {
        "property": "CUT_BUFFER0 on the Xwayland root window",
        "type": "STRING",
        "format": 8,
        "mode": "replace",
        "payload": "the exact legacy byte array and byte length",
    }
    for key, expected in expected_x_fields.items():
        if xwayland.get(key) != expected:
            errors.append(f"Xwayland CUT_BUFFER0 {key} mismatch")
    readiness = str(xwayland.get("readiness"))
    if not all(term in readiness for term in ("before Xwayland", "atoms", "mirrored")):
        errors.append("late Xwayland readiness mirror mismatch")
    loss = str(xwayland.get("connection_loss"))
    if not all(term in loss for term in ("preserve", "CLIPBOARD", "later")):
        errors.append("Xwayland connection-loss preservation mismatch")

    precedence = require_object(value, "cutfile_source_precedence", errors)
    ready = str(precedence.get("xwayland_ready"))
    unavailable = str(precedence.get("xwayland_unavailable"))
    independent = str(precedence.get("clipboard_independence"))
    if not all(term in ready for term in ("CUT_BUFFER0", "first", "preserves")):
        errors.append("ready-Xwayland f.cutfile source mismatch")
    if not all(term in unavailable for term in ("first", "persistent internal")):
        errors.append("native f.cutfile fallback mismatch")
    if not all(term in independent for term in ("never", "CLIPBOARD")):
        errors.append("f.cutfile must not consume a foreign clipboard owner")

    outputs = require_object(value, "action_outputs", errors)
    if "exactly one newline" not in str(outputs.get("f.cut")):
        errors.append("translated f.cut newline mismatch")
    for key in ("f.file", "f.cutfile"):
        if "4095" not in str(outputs.get(key)) or "nonempty" not in str(outputs.get(key)):
            errors.append(f"translated {key} read output mismatch")

    lifecycle = require_object(value, "lifecycle", errors)
    restart = str(lifecycle.get("restart"))
    shutdown = str(lifecycle.get("shutdown"))
    replacement = str(lifecycle.get("ownership_replacement"))
    if not all(
        term in restart
        for term in ("restart", "legacy bytes", "seat", "clients", "connection")
    ):
        errors.append("restart persistence boundary mismatch")
    if not all(term in shutdown for term in ("destroy", "free", "listeners", "use-after-free")):
        errors.append("shutdown cleanup boundary mismatch")
    if not all(term in replacement for term in ("cancels", "destroys", "new source")):
        errors.append("successive source ownership transition mismatch")


def load_wtwm_sources(root: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for relative in ("include/wtwm/config.h", "src/config.c", "src/wtwm.c"):
        path = root / relative
        try:
            sources[relative] = path.read_text(encoding="utf-8")
        except OSError:
            sources[relative] = ""
    return sources


def validate_wtwm_structure(sources: dict[str, str]) -> list[str]:
    """Check parser and runtime dispatch surfaces without requiring wlroots."""

    errors: list[str] = []
    header = sources.get("include/wtwm/config.h", "")
    config = sources.get("src/config.c", "")
    runtime = sources.get("src/wtwm.c", "")
    if not header:
        errors.append("current config ABI header is missing")
    if not config:
        errors.append("current portable parser source is missing")
    if not runtime:
        errors.append("current compositor source is missing")

    mappings = {
        r'ACT_ARG\("f\.cut",\s*WTWM_ACTION_CUT\)': "f.cut argument mapping",
        r'ACT\("f\.cutfile",\s*WTWM_ACTION_CUTFILE\)': "f.cutfile mapping",
        r'ACT_ARG\("f\.file",\s*WTWM_ACTION_FILE\)': "f.file argument mapping",
        (
            r'else if \(strcmp\(spelling, "\^"\) == 0\) '
            r'named = find_action\("f\.cut"\);'
        ): "caret shorthand mapping",
    }
    for pattern, label in mappings.items():
        if len(re.findall(pattern, config)) != 1:
            errors.append(f"current parser must contain exactly one {label}")
    for enum_name in ("WTWM_ACTION_CUT", "WTWM_ACTION_CUTFILE", "WTWM_ACTION_FILE"):
        if len(re.findall(rf"^\s*{enum_name},\s*$", header, re.MULTILINE)) != 1:
            errors.append(f"current config ABI must contain exactly one {enum_name}")

    runtime_requirements = {
        r"\bxcb_atom_t\s+atom_cut_buffer0\s*;": "CUT_BUFFER0 atom state",
        r'\bxwayland_atom\(connection,\s*"CUT_BUFFER0"\)': "CUT_BUFFER0 atom setup",
        r"\bstatic bool store_cut_buffer\s*\(": "cut-buffer store helper",
        r"\bstatic char \*fetch_cut_buffer\s*\(": "cut-buffer fetch helper",
        r"\bstatic bool file_to_cut_buffer\s*\(": "file-to-buffer helper",
        r"\bstatic void cut_text\s*\(": "f.cut helper",
        r"\bcase WTWM_ACTION_CUT\s*:": "f.cut runtime dispatch",
        r"\bcase WTWM_ACTION_CUTFILE\s*:": "f.cutfile runtime dispatch",
        r"\bcase WTWM_ACTION_FILE\s*:": "f.file runtime dispatch",
        r"\bXCB_ATOM_STRING\b": "STRING property type",
    }
    for pattern, label in runtime_requirements.items():
        if re.search(pattern, runtime) is None:
            errors.append(f"current compositor lacks {label}")
    return errors


def validate_contract(
    contract: Any,
    inventory: Any,
    source_root: Path,
    *,
    verify_canonical: bool = True,
    verify_archive: bool = True,
    sources: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]
    if set(contract) != EXPECTED_TOP_LEVEL:
        errors.append("contract top-level fields differ from schema")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if verify_canonical and canonical_sha256(contract) != EXPECTED_CANONICAL_SHA256:
        errors.append("contract differs from the reviewed canonical contract")
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream provenance differs from the pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes differ from the frozen set")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
        evidence = {}
    elif set(evidence) != EXPECTED_EVIDENCE_IDS:
        errors.append("evidence ids differ from the frozen source-anchor set")
    if verify_archive:
        validate_archive(
            source_root,
            contract.get("upstream"),
            contract.get("source_members"),
            evidence,
            errors,
        )
    referenced = set(evidence_references(contract))
    unknown = sorted(referenced - set(evidence))
    unused = sorted(set(evidence) - referenced)
    if unknown:
        errors.append("unknown evidence references: " + ", ".join(unknown))
    if unused:
        errors.append("unused source anchors: " + ", ".join(unused))

    validate_inventory(inventory, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENT_IDS:
        errors.append("cut-buffer requirement coverage mismatch")
    requirement_terms = {
        "cut.parser-identity": ("f.cut", "f.cutfile", "f.file", "caret"),
        "cut.reference-bytes": ("newline", "tokenization", "4095", "nonempty"),
        "cut.persistent-buffer": ("length-delimited", "failed", "empty"),
        "cut.clipboard-publication": ("CLIPBOARD", "serial", "PRIMARY"),
        "cut.xwayland-mirror": ("CUT_BUFFER0", "STRING", "unavailable"),
        "cut.cutfile-source": ("CUT_BUFFER0", "internal", "clipboard"),
        "cut.source-io-safety": ("partial writes", "EINTR", "closure"),
        "cut.lifecycle": ("restart", "shutdown", "legacy bytes"),
    }
    for requirement_id, terms in requirement_terms.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "level", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        if record.get("level") != "MUST":
            errors.append(f"{requirement_id} must be a MUST requirement")
        rule = record.get("rule")
        if not isinstance(rule, str) or not all(term in rule for term in terms):
            errors.append(f"{requirement_id} semantic rule mismatch")
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite upstream evidence")

    scenarios = records_by_id(
        contract.get("verification_scenarios"),
        "verification_scenarios",
        errors,
    )
    if {key: record.get("kind") for key, record in scenarios.items()} != (
        EXPECTED_SCENARIOS
    ):
        errors.append("verification scenario ids or kinds mismatch")
    for scenario_id, record in scenarios.items():
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} oracle must be nonempty")

    errors.extend(validate_wtwm_structure(sources or load_wtwm_sources(source_root)))
    return errors


def run_tamper_tests(
    contract: dict[str, Any],
    inventory: Any,
    source_root: Path,
) -> list[str]:
    """Prove independent semantic pins reject representative mutations."""

    mutations: list[tuple[str, dict[str, Any], bool]] = []

    def mutate(name: str, path: tuple[Any, ...], value: Any) -> None:
        candidate = copy.deepcopy(contract)
        current: Any = candidate
        for component in path[:-1]:
            current = current[component]
        current[path[-1]] = value
        mutations.append((name, candidate, False))

    mutate("archive pin", ("upstream", "sha256"), "0" * 64)
    mutate(
        "source pin",
        ("source_members", "twm-1.0.13.1/src/menus.c"),
        "0" * 64,
    )
    exact_anchor = copy.deepcopy(contract)
    exact_anchor["evidence"]["cut.newline"]["text"] += " tampered"
    mutations.append(("exact source anchor", exact_anchor, True))
    mutate(
        "parser action signature",
        ("reference_behavior", "action_identity", 1, "argument_count"),
        1,
    )
    mutate(
        "caret equivalence",
        ("reference_behavior", "cut_shorthand", "equivalent_action"),
        "f.file",
    )
    mutate(
        "cut newline",
        ("reference_behavior", "f_cut", "output"),
        "the action string bytes without a newline",
    )
    mutate(
        "file capacity",
        ("reference_behavior", "f_file", "maximum_replacement_bytes"),
        4096,
    )
    mutate(
        "cutfile token",
        ("reference_behavior", "f_cutfile", "filename_decoding"),
        "use the entire buffer",
    )
    mutate(
        "error preservation",
        ("reference_behavior", "f_file", "preserve_conditions"),
        [],
    )
    mutate(
        "tilde user lookup",
        ("reference_behavior", "filename_expansion", "tilde_user_lookup"),
        True,
    )
    mutate(
        "classification",
        ("wayland_translation", "classification", "f.cut"),
        "verified-no-op",
    )
    mutate(
        "binary length",
        ("wayland_translation", "legacy_buffer", "representation"),
        "a zero-terminated string",
    )
    mutate(
        "publish order",
        ("wayland_translation", "successful_publish", "order"),
        list(reversed(EXPECTED_PUBLISH_ORDER)),
    )
    mutate(
        "PRIMARY isolation",
        ("wayland_translation", "successful_publish", "primary_selection"),
        "replace PRIMARY",
    )
    mutate(
        "selection serial",
        ("wayland_translation", "wayland_clipboard", "serial"),
        "reuse the last client serial",
    )
    mutate(
        "partial writes",
        ("wayland_translation", "wayland_clipboard", "send"),
        "call write once",
    )
    mutate(
        "X property type",
        ("wayland_translation", "xwayland_cut_buffer", "type"),
        "UTF8_STRING",
    )
    mutate(
        "late readiness",
        ("wayland_translation", "xwayland_cut_buffer", "readiness"),
        "discard pre-Xwayland actions",
    )
    mutate(
        "cutfile precedence",
        ("wayland_translation", "cutfile_source_precedence", "xwayland_ready"),
        "use ordinary CLIPBOARD",
    )
    mutate(
        "restart persistence",
        ("wayland_translation", "lifecycle", "restart"),
        "clear all state",
    )
    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement, False))
    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario, False))
    unknown_evidence = copy.deepcopy(contract)
    unknown_evidence["requirements"][0]["evidence"].append("missing.anchor")
    mutations.append(("evidence closure", unknown_evidence, False))

    failures: list[str] = []
    baseline_sources = load_wtwm_sources(source_root)
    for name, candidate, archive in mutations:
        errors = validate_contract(
            candidate,
            inventory,
            source_root,
            verify_canonical=False,
            verify_archive=archive,
            sources=baseline_sources,
        )
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")

    source_mutations: list[tuple[str, str, str, str]] = [
        (
            "parser f.cut mapping",
            "src/config.c",
            'ACT_ARG("f.cut", WTWM_ACTION_CUT)',
            'ACT("f.cut", WTWM_ACTION_CUT)',
        ),
        (
            "caret parser mapping",
            "src/config.c",
            'named = find_action("f.cut");',
            'named = find_action("f.file");',
        ),
        (
            "runtime f.cut dispatch",
            "src/wtwm.c",
            "case WTWM_ACTION_CUT:",
            "case WTWM_ACTION_NOP:",
        ),
        (
            "runtime CUT_BUFFER0 atom",
            "src/wtwm.c",
            'xwayland_atom(connection, "CUT_BUFFER0")',
            'xwayland_atom(connection, "CUT_BUFFER1")',
        ),
    ]
    for name, path, before, after in source_mutations:
        changed = copy.deepcopy(baseline_sources)
        if before not in changed[path]:
            failures.append(f"tamper self-test fixture missing: {name}")
            continue
        changed[path] = changed[path].replace(before, after, 1)
        if not validate_wtwm_structure(changed):
            failures.append(f"tamper self-test was not rejected: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        contract = load_json(source_root / CONTRACT_PATH)
        inventory = load_json(source_root / EXPECTED_UPSTREAM["inventory"])
        errors = validate_contract(contract, inventory, source_root)
        if args.self_test_tamper and isinstance(contract, dict):
            errors.extend(run_tamper_tests(contract, inventory, source_root))
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"cut-buffer contract validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("cut-buffer contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    suffix = "; 27 tamper self-tests passed" if args.self_test_tamper else ""
    print(
        "cut-buffer contract valid: "
        f"{len(EXPECTED_EVIDENCE_IDS)} exact source anchors, "
        f"{len(EXPECTED_REQUIREMENT_IDS)} requirements, "
        f"{len(EXPECTED_SCENARIOS)} scenarios{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
