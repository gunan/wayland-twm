#!/usr/bin/env python3
"""Validate the frozen twm warp-to-screen/history translation contract."""

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
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/warp-screen-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "533b6d57c6e7ace17c61f3ac5b836299a37ff2b70a21b4011667ae6cc68d0582"
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
    "twm-1.0.13.1/src/add_window.c": (
        "c3133cc763d2db086e3417b3c2f3c103dc23685690a59e4116cbd338feb7b888"
    ),
    "twm-1.0.13.1/src/gram.c": (
        "072fe072063f5ff236dfae444bd2b08030262c126664f7493bc6849429c1a331"
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
    "current_surface",
    "reference_behavior",
    "wayland_translation",
    "scope_boundaries",
    "requirements",
    "verification_scenarios",
}
EXPECTED_CURRENT_ANCHORS = {
    "config.argument-validation",
    "config.named-back",
    "action.target-helper",
    "action.next",
    "action.prev",
    "runtime.output-snapshot",
    "runtime.warp-entry",
    "runtime.point-half-open",
    "runtime.pointer-motion",
    "output-order.lookup",
}
EXPECTED_REQUIREMENTS = {
    "warp.reference-dispatch",
    "warp.reference-history",
    "warp.canonical-targets",
    "warp.history-state",
    "warp.pointer-map",
    "warp.gap-zero-one",
    "warp.context-invariance",
    "warp.topology-boundary",
}
EXPECTED_SCENARIOS = {
    "reference-manual-discrepancy": "reference-source",
    "reference-managed-hole-skip": "reference-traversal",
    "reference-history-update": "reference-history",
    "reference-placement-history-write": "reference-history-boundary",
    "next-wrap": "runtime-traversal",
    "prev-wrap": "runtime-traversal",
    "back-toggle": "runtime-history",
    "numeric-history": "runtime-history",
    "same-target-history": "runtime-noop",
    "unset-back": "runtime-noop",
    "relative-equal-size": "runtime-pointer",
    "relative-smaller-target": "runtime-pointer",
    "gap-no-current": "runtime-gap",
    "zero-output": "runtime-zero-output",
    "reload-preserves-history": "runtime-lifecycle",
    "restart-clears-history": "runtime-lifecycle",
    "native-context-invariant": "runtime-native",
    "xwayland-context-invariant": "runtime-xwayland",
    "fixed-topology-boundary": "contract-scope",
}
EXPECTED_DEFERRED = [
    "output add/remove/enable/disable transaction timing and history repair when an identity disappears",
    "output scale, transform, mode, and layout-change transaction mechanics",
    "safe restoration or relocation of windows after an output disappears",
    "input hotplug and multiple keyboards, pointers, seats, or independent seat focus",
    "session startup, logout, failure recovery, and persistent state-file lifecycle",
]
SOURCE_PATHS = (
    "src/config.c",
    "src/actions.c",
    "src/wtwm.c",
    "src/output_order.c",
)


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256_bytes(encoded)


def require_object(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def records_by_id(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return {}
    result: dict[str, Any] = {}
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            errors.append(f"{label}[{index}] must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{label}[{index}] needs a nonempty id")
        elif record_id in result:
            errors.append(f"duplicate {label} id: {record_id}")
        else:
            result[record_id] = record
    return result


def evidence_references(value: Any, *, at_root: bool = True) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if at_root and key in {"evidence", "current_surface"}:
                continue
            if key == "evidence" and isinstance(nested, list):
                yield from (item for item in nested if isinstance(item, str))
            else:
                yield from evidence_references(nested, at_root=False)
    elif isinstance(value, list):
        for nested in value:
            yield from evidence_references(nested, at_root=False)


def require_terms(
    value: Any, terms: tuple[str, ...], label: str, errors: list[str]
) -> None:
    if not isinstance(value, str) or not all(term in value for term in terms):
        errors.append(f"{label} semantic text mismatch")


def validate_archive(
    root: Path,
    upstream: Any,
    members: Any,
    evidence: dict[str, Any],
    errors: list[str],
) -> None:
    if upstream != EXPECTED_UPSTREAM or members != EXPECTED_SOURCE_MEMBERS:
        return
    archive_path = root / EXPECTED_UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append(f"missing upstream archive: {archive_path}")
        return
    archive_data = archive_path.read_bytes()
    if sha256_bytes(archive_data) != EXPECTED_UPSTREAM["sha256"]:
        errors.append("upstream archive hash mismatch")
        return
    try:
        with tarfile.open(archive_path, "r:xz") as archive:
            lines_by_member: dict[str, list[str]] = {}
            for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
                extracted = archive.extractfile(member)
                if extracted is None:
                    errors.append(f"missing source member: {member}")
                    continue
                data = extracted.read()
                if sha256_bytes(data) != expected_hash:
                    errors.append(f"source member hash mismatch: {member}")
                lines_by_member[member] = data.decode("utf-8").splitlines()
            for evidence_id, anchor in evidence.items():
                if not isinstance(anchor, dict) or set(anchor) != {
                    "member",
                    "line",
                    "text",
                }:
                    errors.append(f"invalid source anchor shape: {evidence_id}")
                    continue
                member = anchor.get("member")
                line = anchor.get("line")
                text = anchor.get("text")
                if member not in EXPECTED_SOURCE_MEMBERS:
                    errors.append(f"unknown source member in {evidence_id}")
                    continue
                if not isinstance(line, int) or line <= 0 or not isinstance(text, str):
                    errors.append(f"invalid source location: {evidence_id}")
                    continue
                member_lines = lines_by_member.get(member, [])
                actual = member_lines[line - 1] if line <= len(member_lines) else None
                if actual != text:
                    errors.append(f"exact source anchor mismatch: {evidence_id}")
    except (tarfile.TarError, UnicodeDecodeError, OSError) as error:
        errors.append(f"cannot inspect upstream archive: {error}")


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    inventory_obj = require_object(inventory, "inventory", errors)
    expected_inventory_upstream = dict(EXPECTED_UPSTREAM)
    expected_inventory_upstream.pop("inventory")
    if inventory_obj.get("schema_version") != 1:
        errors.append("inventory schema_version mismatch")
    if inventory_obj.get("upstream") != expected_inventory_upstream:
        errors.append("inventory upstream provenance mismatch")
    keywords = inventory_obj.get("keywords")
    if not isinstance(keywords, list):
        errors.append("inventory keywords must be an array")
        return
    matches = [
        record for record in keywords
        if isinstance(record, dict) and record.get("spelling") == "f.warptoscreen"
    ]
    if len(matches) != 1:
        errors.append("inventory must contain exactly one f.warptoscreen keyword")
        return
    expected = {
        "id": "keyword.f.warptoscreen",
        "spelling": "f.warptoscreen",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_WARPTOSCREEN",
        "categories": ["built-in-action"],
        "evidence": {
            "archive_member": "twm-1.0.13.1/src/parse.c",
            "line": 482,
            "text": "    { \"f.warptoscreen\",         FSKEYWORD, F_WARPTOSCREEN },",
        },
    }
    if matches[0] != expected:
        errors.append("inventory f.warptoscreen entry mismatch")


def load_sources(root: Path) -> dict[str, str]:
    return {path: (root / path).read_text(encoding="utf-8") for path in SOURCE_PATHS}


def validate_current_surface(
    value: Any, sources: dict[str, str], errors: list[str]
) -> None:
    surface = require_object(value, "current_surface", errors)
    if set(surface) != {"source_anchors", "observed"}:
        errors.append("current_surface fields differ from schema")
    anchors = require_object(surface.get("source_anchors"), "source_anchors", errors)
    if set(anchors) != EXPECTED_CURRENT_ANCHORS:
        errors.append("current source-anchor coverage mismatch")
    for anchor_id, anchor in anchors.items():
        if not isinstance(anchor, dict) or set(anchor) != {"path", "text"}:
            errors.append(f"invalid current source anchor: {anchor_id}")
            continue
        path = anchor.get("path")
        text = anchor.get("text")
        if path not in SOURCE_PATHS or not isinstance(text, str) or not text:
            errors.append(f"invalid current source location: {anchor_id}")
            continue
        count = sources.get(path, "").count(text)
        if count != 1:
            errors.append(
                f"current source anchor {anchor_id} occurs {count} times in {path}"
            )
    observed = surface.get("observed")
    if not isinstance(observed, list) or len(observed) != 4:
        errors.append("current observed-surface summary mismatch")
    else:
        joined = " ".join(str(item) for item in observed)
        for term in ("parser", "canonical", "half-open", "history", "clamping"):
            if term not in joined:
                errors.append(f"current observed surface omits {term}")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {
        "argument_language",
        "target_selection",
        "history",
        "pointer_mapping",
    }:
        errors.append("reference_behavior fields differ from schema")
    argument = require_object(behavior.get("argument_language"), "argument_language", errors)
    if set(argument) != {"rule", "evidence"}:
        errors.append("argument_language fields differ from schema")
    require_terms(
        argument.get("rule"),
        ("lowercases", "next", "prev", "back", "ASCII-digit", "empty string", "atoi"),
        "reference argument language",
        errors,
    )
    target = require_object(behavior.get("target_selection"), "target_selection", errors)
    if set(target) != {
        "numeric",
        "next",
        "prev",
        "back",
        "manual_code_discrepancy",
        "evidence",
    }:
        errors.append("reference target_selection fields differ from schema")
    require_terms(target.get("numeric"), ("atoi", "wraps", "once"), "numeric", errors)
    require_terms(target.get("next"), ("increasing", "wraps", "skips unmanaged"), "next", errors)
    require_terms(target.get("prev"), ("decreasing", "wraps", "skips unmanaged"), "prev", errors)
    require_terms(target.get("back"), ("PreviousScreen", "without walking", "rings"), "back", errors)
    require_terms(
        target.get("manual_code_discrepancy"),
        ("manual", "opposite", "prev decrements", "back uses PreviousScreen", "Source"),
        "manual/source discrepancy",
        errors,
    )
    history = require_object(behavior.get("history"), "history", errors)
    if set(history) != {
        "initial",
        "successful_different_target",
        "same_target",
        "no_target",
        "interactive_placement",
        "restart",
        "evidence",
    }:
        errors.append("reference history fields differ from schema")
    require_terms(history.get("initial"), ("DefaultScreen", "startup"), "initial history", errors)
    require_terms(
        history.get("successful_different_target"),
        ("before", "source", "Repeated back", "toggle"),
        "successful history",
        errors,
    )
    require_terms(history.get("same_target"), ("before", "unchanged"), "same history", errors)
    require_terms(history.get("no_target"), ("unmanaged", "unchanged"), "no-target history", errors)
    require_terms(
        history.get("interactive_placement"),
        ("first", "AddWindow", "pointer root", "PreviousScreen"),
        "placement history",
        errors,
    )
    require_terms(history.get("restart"), ("execvp", "DefaultScreen", "failed", "intact"), "restart history", errors)
    pointer = require_object(behavior.get("pointer_mapping"), "pointer_mapping", errors)
    if set(pointer) != {"rule", "edge_behavior", "evidence"}:
        errors.append("reference pointer_mapping fields differ from schema")
    require_terms(pointer.get("rule"), ("source root", "same x and y", "does not scale"), "pointer mapping", errors)
    require_terms(pointer.get("edge_behavior"), ("X server", "outside"), "pointer edge behavior", errors)


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    if set(translation) != {
        "classification",
        "active_domain",
        "target_selection",
        "history",
        "pointer_mapping",
        "context_invariance",
        "topology_boundary",
    }:
        errors.append("wayland_translation fields differ from schema")
    require_terms(
        translation.get("classification"),
        ("behaviorally-equivalent", "strict numeric safety difference"),
        "classification",
        errors,
    )
    domain = require_object(translation.get("active_domain"), "active_domain", errors)
    if set(domain) != {"outputs", "current", "identity_index", "single_snapshot"}:
        errors.append("active_domain fields differ from schema")
    require_terms(domain.get("outputs"), ("enabled", "canonical", "Dense", "zero-based"), "output domain", errors)
    require_terms(domain.get("current"), ("half-open", "gap", "no current"), "current output", errors)
    require_terms(
        domain.get("identity_index"),
        ("canonical indices", "immutable output identities", "abstract reference", "index or identity"),
        "identity/index interaction",
        errors,
    )
    require_terms(domain.get("single_snapshot"), ("same snapshot", "index generations"), "snapshot", errors)
    targets = require_object(translation.get("target_selection"), "target_selection", errors)
    if set(targets) != {"numeric", "next", "prev", "back", "no_skip_holes"}:
        errors.append("translation target_selection fields differ from schema")
    require_terms(targets.get("numeric"), ("unsigned ASCII decimal", "fits int", "no target"), "numeric target", errors)
    require_terms(targets.get("next"), ("current + 1", "modulo", "canonical"), "next target", errors)
    require_terms(targets.get("prev"), ("current + count - 1", "modulo", "source"), "prev target", errors)
    require_terms(targets.get("back"), ("previous-output reference", "no target", "toggles"), "back target", errors)
    require_terms(targets.get("no_skip_holes"), ("dense", "disabled outputs", "absent"), "dense traversal", errors)
    history = require_object(translation.get("history"), "translation history", errors)
    if set(history) != {
        "startup",
        "successful_different_target",
        "same_target",
        "no_target",
        "one_output",
        "reload",
        "restart",
        "client_events",
    }:
        errors.append("translation history fields differ from schema")
    history_terms = {
        "startup": ("no previous-output reference", "zero outputs", "Do not synthesize"),
        "successful_different_target": ("completing", "source output"),
        "same_target": ("no-op", "does not change history"),
        "no_target": ("Zero outputs", "gap", "invalid", "no pointer or history mutation"),
        "one_output": ("one enabled output", "all are no-ops", "unchanged"),
        "reload": ("not a screen visit", "preserves", "invalid"),
        "restart": ("f.restart/f.twmrc", "clears", "rejected", "unchanged"),
        "client_events": ("Native", "Xwayland", "do not write", "no Wayland analogue"),
    }
    for key, terms in history_terms.items():
        require_terms(history.get(key), terms, f"translation history {key}", errors)
    pointer = require_object(translation.get("pointer_mapping"), "translation pointer", errors)
    if set(pointer) != {"relative_rule", "target_clamp", "post_warp"}:
        errors.append("translation pointer_mapping fields differ from schema")
    require_terms(pointer.get("relative_rule"), ("dx", "clamp", "width - 1", "Do not scale"), "relative pointer rule", errors)
    require_terms(pointer.get("target_clamp"), ("half-open", "before", "Never", "different output"), "target clamp", errors)
    require_terms(pointer.get("post_warp"), ("process cursor motion once", "immediately"), "post-warp", errors)
    context = require_object(translation.get("context_invariance"), "context_invariance", errors)
    if set(context) != {"rule", "protocols", "gaps"}:
        errors.append("context_invariance fields differ from schema")
    require_terms(context.get("rule"), ("one seat", "pointer", "Root", "does not substitute"), "invocation context", errors)
    require_terms(context.get("protocols"), ("native Wayland", "Xwayland", "do not alter"), "protocol invariance", errors)
    require_terms(context.get("gaps"), ("Root bindings", "gaps", "no current", "no-op"), "gap context", errors)
    topology = require_object(translation.get("topology_boundary"), "topology_boundary", errors)
    if set(topology) != {"fixed_snapshot", "next_task", "non_claim"}:
        errors.append("topology_boundary fields differ from schema")
    require_terms(topology.get("fixed_snapshot"), ("stable", "abstract previous-output reference", "not prescribed"), "fixed topology", errors)
    require_terms(
        topology.get("next_task"),
        ("following output-topology task", "add/remove", "scale", "history representation", "renumbering", "removed"),
        "next topology task",
        errors,
    )
    require_terms(topology.get("non_claim"), ("does not claim", "hotplug", "multiple seats", "persistence"), "topology non-claim", errors)


def validate_scope(value: Any, errors: list[str]) -> None:
    scope = require_object(value, "scope_boundaries", errors)
    if set(scope) != {"this_slice_requires", "explicitly_deferred", "non_claim"}:
        errors.append("scope_boundaries fields differ from schema")
    required = scope.get("this_slice_requires")
    if not isinstance(required, list) or len(required) != 5:
        errors.append("warp slice requirement summary mismatch")
    else:
        joined = " ".join(str(item) for item in required)
        for term in ("next", "prev", "back", "history", "identity", "clamped", "native/Xwayland", "zero-output"):
            if term not in joined:
                errors.append(f"warp slice requirements omit {term}")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred topology scope mismatch")
    require_terms(scope.get("non_claim"), ("only", "topology", "restoration", "input", "session", "exit-criteria"), "scope non-claim", errors)


def validate_contract(
    contract: Any,
    inventory: Any,
    root: Path,
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
        errors.append("upstream provenance differs from pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source-member pins differ from frozen release")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) != 34:
        errors.append("upstream evidence coverage mismatch")
        evidence = evidence if isinstance(evidence, dict) else {}
    if verify_archive:
        validate_archive(
            root,
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
    loaded_sources = sources if sources is not None else load_sources(root)
    validate_current_surface(contract.get("current_surface"), loaded_sources, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)
    validate_scope(contract.get("scope_boundaries"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENTS:
        errors.append("warp requirement coverage mismatch")
    required_terms = {
        "warp.reference-dispatch": ("source", "next", "prev", "back", "atoi", "manual"),
        "warp.reference-history": ("successful", "AddWindow", "PreviousScreen", "same"),
        "warp.canonical-targets": ("current", "numeric", "next", "prev", "previous-output back", "identity-ordered", "snapshot"),
        "warp.history-state": ("source output", "same-target/no-target", "reload", "restart", "toggle"),
        "warp.pointer-map": ("unscaled", "clamp", "target output", "pointer context"),
        "warp.gap-zero-one": ("Zero outputs", "gaps/outside", "one-output", "no pointer or history"),
        "warp.context-invariance": ("seat pointer", "native/Xwayland", "invocation context"),
        "warp.topology-boundary": ("add/remove/scale/mode", "history repair", "restoration", "multiple seats", "session"),
    }
    for requirement_id, terms in required_terms.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        require_terms(record.get("rule"), terms, requirement_id, errors)
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite evidence")

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    actual_scenarios = {key: record.get("kind") for key, record in scenarios.items()}
    if actual_scenarios != EXPECTED_SCENARIOS:
        errors.append("verification scenario ids or kinds mismatch")
    for scenario_id, record in scenarios.items():
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} needs a nonempty oracle")
    return errors


def run_tamper_tests(
    contract: dict[str, Any], inventory: Any, root: Path
) -> list[str]:
    """Prove independent provenance, source, schema, and semantic pins."""

    mutations: list[tuple[str, dict[str, Any], bool]] = []

    def mutate(name: str, path: tuple[Any, ...], value: Any) -> None:
        candidate = copy.deepcopy(contract)
        current: Any = candidate
        for component in path[:-1]:
            current = current[component]
        current[path[-1]] = value
        mutations.append((name, candidate, False))

    mutate("archive pin", ("upstream", "sha256"), "0" * 64)
    mutate("member pin", ("source_members", "twm-1.0.13.1/src/menus.c"), "0" * 64)
    exact_anchor = copy.deepcopy(contract)
    exact_anchor["evidence"]["dispatch.back"]["text"] += " tampered"
    mutations.append(("exact archive anchor", exact_anchor, True))
    mutate(
        "manual discrepancy",
        ("reference_behavior", "target_selection", "manual_code_discrepancy"),
        "The manual is authoritative; back decrements and prev selects history.",
    )
    mutate("reference next", ("reference_behavior", "target_selection", "next"), "next always selects zero.")
    mutate("reference prev", ("reference_behavior", "target_selection", "prev"), "prev means history.")
    mutate("reference back", ("reference_behavior", "target_selection", "back"), "back decrements.")
    mutate("reference same", ("reference_behavior", "history", "same_target"), "Same target clears history.")
    mutate("reference no-target", ("reference_behavior", "history", "no_target"), "Unmanaged targets overwrite history.")
    mutate("reference placement write", ("reference_behavior", "history", "interactive_placement"), "AddWindow never touches history.")
    mutate("reference restart", ("reference_behavior", "history", "restart"), "Restart preserves globals.")
    mutate("reference scale", ("reference_behavior", "pointer_mapping", "rule"), "Scale coordinates proportionally.")
    mutate("classification", ("wayland_translation", "classification"), "literal X root emulation")
    mutate("gap current", ("wayland_translation", "active_domain", "current"), "Gaps select nearest output.")
    mutate("unresolved history", ("wayland_translation", "active_domain", "identity_index"), "Use whichever global list entry has the old integer.")
    mutate("mixed snapshots", ("wayland_translation", "active_domain", "single_snapshot"), "Rebuild a snapshot for every lookup.")
    mutate("numeric wrap", ("wayland_translation", "target_selection", "numeric"), "atoi and wrap to zero.")
    mutate("next order", ("wayland_translation", "target_selection", "next"), "Follow layout x coordinate.")
    mutate("prev meaning", ("wayland_translation", "target_selection", "prev"), "Select history.")
    mutate("back meaning", ("wayland_translation", "target_selection", "back"), "Subtract one index.")
    mutate("disabled holes", ("wayland_translation", "target_selection", "no_skip_holes"), "Keep disabled holes in the snapshot.")
    mutate("startup history", ("wayland_translation", "history", "startup"), "Initialize previous to output zero.")
    mutate("success history timing", ("wayland_translation", "history", "successful_different_target"), "Store target before attempting warp.")
    mutate("same history", ("wayland_translation", "history", "same_target"), "Clear history on same target.")
    mutate("no-target history", ("wayland_translation", "history", "no_target"), "Invalid input stores current.")
    mutate("one-output history", ("wayland_translation", "history", "one_output"), "next advances history on one output.")
    mutate("reload history", ("wayland_translation", "history", "reload"), "Reload clears history.")
    mutate("restart history", ("wayland_translation", "history", "restart"), "Every restart attempt clears history.")
    mutate("client event history", ("wayland_translation", "history", "client_events"), "Focus changes update previous output.")
    mutate("proportional pointer", ("wayland_translation", "pointer_mapping", "relative_rule"), "Scale proportionally.")
    mutate("global pointer clamp", ("wayland_translation", "pointer_mapping", "target_clamp"), "Use nearest point in the layout union.")
    mutate("missing pointer refresh", ("wayland_translation", "pointer_mapping", "post_warp"), "Do not refresh pointer context.")
    mutate("focused owner context", ("wayland_translation", "context_invariance", "rule"), "Use the focused window owner output.")
    mutate("protocol split", ("wayland_translation", "context_invariance", "protocols"), "Maintain independent Xwayland history.")
    mutate("gap invocation", ("wayland_translation", "context_invariance", "gaps"), "A menu action in a gap selects nearest.")
    mutate("topology ownership", ("wayland_translation", "topology_boundary", "next_task"), "This slice completes all topology work.")
    mutate("deferred scope", ("scope_boundaries", "explicitly_deferred"), [])
    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement, False))
    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario, False))
    unknown_evidence = copy.deepcopy(contract)
    unknown_evidence["requirements"][0]["evidence"].append("missing.anchor")
    mutations.append(("evidence closure", unknown_evidence, False))

    baseline_sources = load_sources(root)
    failures: list[str] = []
    for name, candidate, inspect_archive in mutations:
        errors = validate_contract(
            candidate,
            inventory,
            root,
            verify_canonical=False,
            verify_archive=inspect_archive,
            sources=baseline_sources,
        )
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")

    source_mutations = [
        (
            "config named back",
            "src/config.c",
            'strcmp(action->argument, "back") == 0 ||',
            'strcmp(action->argument, "return") == 0 ||',
        ),
        (
            "action next",
            "src/actions.c",
            "return (current + 1) % count;",
            "return current;",
        ),
        (
            "action prev",
            "src/actions.c",
            "return (current + count - 1) % count;",
            "return (current + 1) % count;",
        ),
        (
            "runtime half-open containment",
            "src/wtwm.c",
            "server->cursor->y >= box.y && server->cursor->y < box.y + box.height) {",
            "server->cursor->y >= box.y && server->cursor->y <= box.y + box.height) {",
        ),
        (
            "runtime pointer refresh",
            "src/wtwm.c",
            "process_cursor_motion(server, server->current_input_time_ms);\n\twtwm_output_order_destroy(snapshot);",
            "/* pointer refresh removed */\n\twtwm_output_order_destroy(snapshot);",
        ),
        (
            "canonical output lookup",
            "src/output_order.c",
            "void *wtwm_output_order_at(const struct wtwm_output_order *order, size_t index) {",
            "void *wtwm_output_order_at(const struct wtwm_output_order *order, size_t ordinal) {",
        ),
    ]
    for name, path, old, new in source_mutations:
        source = baseline_sources[path]
        if source.count(old) != 1:
            failures.append(f"source tamper setup mismatch: {name}")
            continue
        changed_sources = dict(baseline_sources)
        changed_sources[path] = source.replace(old, new, 1)
        errors = validate_contract(
            contract,
            inventory,
            root,
            verify_canonical=False,
            verify_archive=False,
            sources=changed_sources,
        )
        if not errors:
            failures.append(f"source tamper self-test was not rejected: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run tamper mutations")
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    try:
        contract = load_json(root / CONTRACT_PATH)
        inventory = load_json(root / EXPECTED_UPSTREAM["inventory"])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"warp-screen contract error: {error}", file=sys.stderr)
        return 1
    errors = validate_contract(contract, inventory, root)
    if arguments.self_test and not errors:
        errors.extend(run_tamper_tests(contract, inventory, root))
    if errors:
        for error in errors:
            print(f"warp-screen contract error: {error}", file=sys.stderr)
        return 1
    suffix = " and tamper suite" if arguments.self_test else ""
    print(
        "warp-screen contract valid: "
        f"{len(contract['evidence'])} source anchors, "
        f"{len(contract['requirements'])} requirements, "
        f"{len(contract['verification_scenarios'])} scenarios{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
