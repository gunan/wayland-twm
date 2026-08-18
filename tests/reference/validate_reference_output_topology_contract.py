#!/usr/bin/env python3
"""Validate the frozen output-topology transaction contract."""

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
    "reference/lifecycle/twm-1.0.13.1/output-topology-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "db2d8475300fb074b04ea9e35182ba5dee8bc4606aad6ae00fcb2b822fb361a7"
)
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/src/events.c": (
        "4fe7f9746d569abe64c7301a1b31197a299eede117d54456929b6e82726366e3"
    ),
    "twm-1.0.13.1/src/screen.h": (
        "f238b482ee38fd1d75f410574d36b47e2dafec50808518b7ca374924785e48b0"
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
    "runtime.output-record",
    "runtime.state-listener",
    "runtime.ordinal-counter",
    "runtime.state-entry",
    "runtime.destroy-entry",
    "runtime.ordinal-entry",
    "runtime.ordinal-exhaustion",
    "runtime.add-entry",
    "runtime.identity-copy",
    "runtime.render-init",
    "runtime.preferred-mode",
    "runtime.layout-add",
    "runtime.background-create",
    "runtime.resume-waiters",
    "runtime.icon-layout",
    "runtime.enabled-snapshot",
    "runtime.warp-state",
    "order.identity-compare",
    "order.ordinal-tie",
}
EXPECTED_REQUIREMENTS = {
    "topology.reference-boundary",
    "topology.atomic-transaction",
    "topology.canonical-order",
    "topology.spatial-refresh",
    "topology.pointer-repair",
    "topology.operation-barrier",
    "topology.warp-history",
    "topology.lifecycle-invariance",
    "topology.resource-safety",
    "topology.restoration-boundary",
}
EXPECTED_SCENARIOS = {
    "reference-fixed-membership": "reference-membership",
    "reference-randr-dimensions-only": "reference-geometry",
    "add-success": "runtime-add",
    "add-failure-rollback": "runtime-rollback",
    "ordinal-continuity-exhaustion": "runtime-ordering",
    "disable-enable-identity": "runtime-enable",
    "mode-change": "runtime-geometry",
    "scale-transform-change": "runtime-geometry",
    "layout-rearrangement": "runtime-layout",
    "state-commit-failure": "runtime-rollback",
    "destroy-active-output": "runtime-destroy",
    "zero-output-transition": "runtime-zero-output",
    "zero-to-active-resume": "runtime-zero-output",
    "pointer-preserve": "runtime-pointer",
    "pointer-canonical-repair": "runtime-pointer",
    "unaffected-operation-continues": "runtime-operation",
    "affected-move-resize-cancel": "runtime-operation",
    "affected-menu-close": "runtime-operation",
    "affected-placement-requeue": "runtime-placement",
    "warp-history-renumber": "runtime-history",
    "warp-history-disappears": "runtime-history",
    "reload-restart-topology": "runtime-lifecycle",
    "native-xwayland-invariant": "runtime-protocol",
    "bounded-churn": "runtime-resource",
    "restoration-deferred": "contract-scope",
}
EXPECTED_DEFERRED = [
    "relocation or restoration of managed windows, icons, and transients stranded by a disappeared or shrunken output",
    "persistent session-record geometry reassociation after output identity/topology changes",
    "input hotplug and multiple keyboards, pointers, seats, or independent seat focus",
    "session startup, logout, failure recovery, and persistent state-file lifecycle",
]
SOURCE_PATHS = ("src/wtwm.c", "src/output_order.c")


def load_json(path: Path) -> Any:
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
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256_bytes(data)


def require_object(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def require_terms(
    value: Any, terms: tuple[str, ...], label: str, errors: list[str]
) -> None:
    if not isinstance(value, str) or not all(term in value for term in terms):
        errors.append(f"{label} semantic text mismatch")


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
                    errors.append(f"missing archive member: {member}")
                    continue
                data = extracted.read()
                if sha256_bytes(data) != expected_hash:
                    errors.append(f"archive member hash mismatch: {member}")
                lines_by_member[member] = data.decode("utf-8").splitlines()
            for evidence_id, anchor in evidence.items():
                if not isinstance(anchor, dict) or set(anchor) != {
                    "member",
                    "line",
                    "text",
                }:
                    errors.append(f"invalid archive anchor shape: {evidence_id}")
                    continue
                member = anchor.get("member")
                line = anchor.get("line")
                text = anchor.get("text")
                if member not in EXPECTED_SOURCE_MEMBERS:
                    errors.append(f"unknown archive member in {evidence_id}")
                    continue
                if not isinstance(line, int) or line <= 0 or not isinstance(text, str):
                    errors.append(f"invalid archive location: {evidence_id}")
                    continue
                lines = lines_by_member.get(member, [])
                actual = lines[line - 1] if line <= len(lines) else None
                if actual != text:
                    errors.append(f"exact archive anchor mismatch: {evidence_id}")
    except (OSError, tarfile.TarError, UnicodeDecodeError) as error:
        errors.append(f"cannot inspect upstream archive: {error}")


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    value = require_object(inventory, "inventory", errors)
    expected_upstream = dict(EXPECTED_UPSTREAM)
    expected_upstream.pop("inventory")
    if value.get("schema_version") != 1:
        errors.append("inventory schema_version mismatch")
    if value.get("upstream") != expected_upstream:
        errors.append("inventory provenance mismatch")
    category_order = value.get("category_order")
    if not isinstance(category_order, list) or "built-in-action" not in category_order:
        errors.append("inventory category catalog mismatch")


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
            errors.append(f"invalid current anchor shape: {anchor_id}")
            continue
        path = anchor.get("path")
        text = anchor.get("text")
        if path not in SOURCE_PATHS or not isinstance(text, str) or not text:
            errors.append(f"invalid current anchor location: {anchor_id}")
            continue
        count = sources.get(path, "").count(text)
        if count != 1:
            errors.append(f"current anchor {anchor_id} occurs {count} times in {path}")
    observed = surface.get("observed")
    if not isinstance(observed, list) or len(observed) != 4:
        errors.append("current surface observation coverage mismatch")
    else:
        text = " ".join(str(item) for item in observed)
        for term in (
            "identity",
            "ordinal",
            "canonical",
            "background",
            "waiters",
            "transaction",
            "rollback",
            "churn-safety",
        ):
            if term not in text:
                errors.append(f"current surface omits {term}")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {"screen_membership", "screen_geometry", "lifecycle_end"}:
        errors.append("reference_behavior fields differ from schema")
    membership = require_object(behavior.get("screen_membership"), "screen_membership", errors)
    if set(membership) != {"rule", "evidence"}:
        errors.append("screen_membership fields differ from schema")
    require_terms(
        membership.get("rule"),
        ("ScreenCount once", "fixed-size ScreenList", "stable numeric slots", "unmanaged null hole", "no runtime"),
        "reference membership",
        errors,
    )
    geometry = require_object(behavior.get("screen_geometry"), "screen_geometry", errors)
    if set(geometry) != {"startup", "randr", "non_actions", "evidence"}:
        errors.append("screen_geometry fields differ from schema")
    require_terms(geometry.get("startup"), ("DisplayWidth", "DisplayHeight", "maximum-window"), "reference startup geometry", errors)
    require_terms(geometry.get("randr"), ("XRandR", "RRScreenChangeNotify", "existing root", "MyDisplayWidth", "MyDisplayHeight"), "reference RandR", errors)
    require_terms(
        geometry.get("non_actions"),
        ("does not create or destroy", "renumber", "PreviousScreen", "relocate", "roll back"),
        "reference RandR non-actions",
        errors,
    )
    lifecycle = require_object(behavior.get("lifecycle_end"), "lifecycle_end", errors)
    if set(lifecycle) != {"rule", "evidence"}:
        errors.append("lifecycle_end fields differ from schema")
    require_terms(lifecycle.get("rule"), ("whole-process shutdown", "restores", "destroys fonts", "closes"), "reference lifecycle end", errors)


def validate_transaction(translation: dict[str, Any], errors: list[str]) -> None:
    model = require_object(translation.get("transaction_model"), "transaction_model", errors)
    if set(model) != {"events", "snapshot", "prepare", "commit_publish", "failure", "destroy_exception"}:
        errors.append("transaction_model fields differ from schema")
    terms = {
        "events": ("announcement", "destroy", "enable", "disable", "mode", "scale", "transform", "layout-position", "serialized"),
        "snapshot": ("active canonical", "logical box", "screen-warp", "pointer", "pinned"),
        "prepare": ("positive", "fallible", "complete post-transaction", "before publishing"),
        "commit_publish": ("commit", "after preparation", "one event-loop critical section", "half-old/half-new"),
        "failure": ("rejects", "releases", "preserves", "exactly", "Log", "unbounded"),
        "destroy_exception": ("irreversible", "cannot roll back", "complete", "before returning"),
    }
    for key, expected in terms.items():
        require_terms(model.get(key), expected, f"transaction {key}", errors)


def validate_events(translation: dict[str, Any], errors: list[str]) -> None:
    events = require_object(translation.get("event_semantics"), "event_semantics", errors)
    if set(events) != {"add", "add_failure", "disable", "enable", "mode_scale_transform", "layout", "destroy"}:
        errors.append("event_semantics fields differ from schema")
    terms = {
        "add": ("immutable identity", "never-reused", "preferred mode", "layout/scene", "background", "waiters"),
        "add_failure": ("never joins", "does not resume", "ordinal", "consumed", "never reused"),
        "disable": ("removes", "active canonical", "background", "retains", "identity", "re-enable"),
        "enable": ("same wrapper", "same", "ordinal", "positive", "recomputes", "consumes no ordinal"),
        "mode_scale_transform": ("logical size", "auto-layout neighbors", "background", "pointer", "pinned"),
        "layout": ("transaction", "preserves identities", "all boxes", "overflowing", "without partial"),
        "destroy": ("active and managed", "listeners", "layout", "scene-output", "history", "exactly once", "retired"),
    }
    for key, expected in terms.items():
        require_terms(events.get(key), expected, f"event {key}", errors)


def validate_order_and_spatial(translation: dict[str, Any], errors: list[str]) -> None:
    order = require_object(translation.get("canonical_order"), "canonical_order", errors)
    if set(order) != {"active_domain", "identity", "ordering", "dense_recompute", "ordinal"}:
        errors.append("canonical_order fields differ from schema")
    terms = {
        "active_domain": ("successfully committed", "enabled", "positive", "dense zero-based"),
        "identity": ("immutable", "announcement ordinal", "disable", "re-enable"),
        "ordering": ("unsigned-byte", "ordinal", "Geometry", "never"),
        "dense_recompute": ("0..count-1", "post-state", "renumber", "rejected"),
        "ordinal": ("without reuse", "UINT64_MAX", "exhaustion", "rejected"),
    }
    for key, expected in terms.items():
        require_terms(order.get(key), expected, f"canonical {key}", errors)
    spatial = require_object(translation.get("spatial_refresh"), "spatial_refresh", errors)
    if set(spatial) != {"backgrounds", "root_hits", "global_ui", "waiters"}:
        errors.append("spatial_refresh fields differ from schema")
    require_terms(spatial.get("backgrounds"), ("each active output", "exactly one", "logical", "Disabled", "no root/background"), "background refresh", errors)
    require_terms(spatial.get("root_hits"), ("post-state", "Gaps", "stale", "cannot"), "root hit refresh", errors)
    require_terms(spatial.get("global_ui"), ("global icon-region", "icon-manager", "once", "Do not duplicate"), "global UI refresh", errors)
    require_terms(spatial.get("waiters"), ("zero active", "oldest-first", "after", "do not consume"), "waiter refresh", errors)


def validate_pointer_and_operations(translation: dict[str, Any], errors: list[str]) -> None:
    pointer = require_object(translation.get("pointer_repair"), "pointer_repair", errors)
    if set(pointer) != {"preserve", "repair", "zero", "ordering"}:
        errors.append("pointer_repair fields differ from schema")
    require_terms(pointer.get("preserve"), ("inside", "half-open", "exact", "no synthetic warp"), "pointer preserve", errors)
    require_terms(pointer.get("repair"), ("at least one", "nearest point", "canonical order", "once", "cursor motion once", "removed"), "pointer repair", errors)
    require_terms(pointer.get("zero"), ("zero active", "do not invent", "Clear", "retaining", "client"), "zero pointer", errors)
    require_terms(pointer.get("ordering"), ("after", "before", "committed geometry"), "pointer ordering", errors)
    operations = require_object(translation.get("operation_barrier"), "operation_barrier", errors)
    if set(operations) != {"pin_identity", "unaffected", "move_resize", "menu", "placement", "warp"}:
        errors.append("operation_barrier fields differ from schema")
    operation_terms = {
        "pin_identity": ("placement", "menu", "move", "resize", "output reference", "logical box"),
        "unaffected": ("survives", "identical", "continues", "does not switch"),
        "move_resize": ("disappears", "box changes", "cancel", "outlines/grabs", "restore", "forcemove"),
        "menu": ("menu chain", "close", "without executing", "unaffected", "exact"),
        "placement": ("cancel only", "pending/hidden", "no placement/random", "requeue", "oldest-first"),
        "warp": ("synchronous", "immutable snapshot", "cannot interleave", "repairs", "does not retroactively cancel"),
    }
    for key, expected in operation_terms.items():
        require_terms(operations.get(key), expected, f"operation {key}", errors)


def validate_history_lifecycle_resources(
    translation: dict[str, Any], errors: list[str]
) -> None:
    history = require_object(translation.get("warp_history"), "warp_history", errors)
    if set(history) != {"surviving_reference", "missing_reference", "pointer_repair", "failure"}:
        errors.append("warp_history fields differ from schema")
    require_terms(history.get("surviving_reference"), ("pre-state", "identity", "active post-state", "new canonical", "without treating"), "surviving history", errors)
    require_terms(history.get("missing_reference"), ("unset", "disabled/destroyed/failed", "clear", "old dense integer", "different output"), "missing history", errors)
    require_terms(history.get("pointer_repair"), ("does not update", "successful", "again"), "history pointer repair", errors)
    require_terms(history.get("failure"), ("rejected/rolled-back", "byte-for-byte", "did not change"), "history rollback", errors)
    lifecycle = require_object(translation.get("configuration_lifecycle"), "configuration_lifecycle", errors)
    if set(lifecycle) != {"global_config", "reload", "restart", "no_disconnect"}:
        errors.append("configuration_lifecycle fields differ from schema")
    require_terms(lifecycle.get("global_config"), ("never", ".twmrc.N", "one active global", "native/Xwayland"), "global config", errors)
    require_terms(lifecycle.get("reload"), ("successful or rejected", "not a topology", "preserves", "history"), "reload", errors)
    require_terms(lifecycle.get("restart"), ("f.restart/f.twmrc", "preserves", "ordinal", "history clear", "rejected"), "restart", errors)
    require_terms(lifecycle.get("no_disconnect"), ("No successful or failed", "Wayland", "Xwayland", "one compatibility X screen"), "client continuity", errors)
    protocols = require_object(translation.get("protocol_invariance"), "protocol_invariance", errors)
    if set(protocols) != {"rule", "client_geometry_boundary"}:
        errors.append("protocol_invariance fields differ from schema")
    require_terms(protocols.get("rule"), ("same", "native Wayland", "Xwayland", "independent"), "protocol invariance", errors)
    require_terms(protocols.get("client_geometry_boundary"), ("alive", "safe", "does not relocate", "disappeared or shrank"), "client geometry boundary", errors)
    resources = require_object(translation.get("resource_safety"), "resource_safety", errors)
    if set(resources) != {"teardown_order", "references", "bounded", "churn"}:
        errors.append("resource_safety fields differ from schema")
    require_terms(resources.get("teardown_order"), ("Detach", "before", "finishing identity", "freeing", "double-remove"), "teardown order", errors)
    require_terms(resources.get("references"), ("Before free", "history", "interactions", "menu", "pointer", "No callback"), "reference cleanup", errors)
    require_terms(resources.get("bounded"), ("bounded", "overflow", "exactly once", "no recursive retry"), "bounded work", errors)
    require_terms(resources.get("churn"), ("Repeated", "must not leak", "double free", "use after free"), "churn safety", errors)


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    if set(translation) != {
        "classification",
        "transaction_model",
        "event_semantics",
        "canonical_order",
        "spatial_refresh",
        "pointer_repair",
        "operation_barrier",
        "warp_history",
        "configuration_lifecycle",
        "protocol_invariance",
        "resource_safety",
    }:
        errors.append("wayland_translation fields differ from schema")
    require_terms(
        translation.get("classification"),
        ("behaviorally-equivalent", "dynamic-output", "stronger atomicity", "resource-safety", "XRandR"),
        "classification",
        errors,
    )
    validate_transaction(translation, errors)
    validate_events(translation, errors)
    validate_order_and_spatial(translation, errors)
    validate_pointer_and_operations(translation, errors)
    validate_history_lifecycle_resources(translation, errors)


def validate_scope(value: Any, errors: list[str]) -> None:
    scope = require_object(value, "scope_boundaries", errors)
    if set(scope) != {"this_slice_requires", "explicitly_deferred", "restoration_handoff", "non_claim"}:
        errors.append("scope_boundaries fields differ from schema")
    required = scope.get("this_slice_requires")
    if not isinstance(required, list) or len(required) != 5:
        errors.append("topology slice requirement summary mismatch")
    else:
        text = " ".join(str(item) for item in required)
        for term in (
            "atomic",
            "rollback",
            "canonical",
            "history repair",
            "backgrounds",
            "pointer",
            "pin-or-cancel",
            "native/Xwayland",
            "leak-free",
        ):
            if term not in text:
                errors.append(f"topology slice requirements omit {term}")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred restoration/input/session scope mismatch")
    require_terms(scope.get("restoration_handoff"), ("coherent post-state", "no dead output", "next Roadmap task", "unchanged", "invisible", "visible safely"), "restoration handoff", errors)
    require_terms(scope.get("non_claim"), ("does not complete", "restoration", "input", "session", "exit criteria"), "scope non-claim", errors)


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
        errors.append("contract differs from reviewed canonical content")
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream provenance differs from pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member pins differ from frozen release")
    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) != 27:
        errors.append("upstream evidence coverage mismatch")
        evidence = evidence if isinstance(evidence, dict) else {}
    if verify_archive:
        validate_archive(root, contract.get("upstream"), contract.get("source_members"), evidence, errors)
    referenced = set(evidence_references(contract))
    unknown = sorted(referenced - set(evidence))
    unused = sorted(set(evidence) - referenced)
    if unknown:
        errors.append("unknown evidence references: " + ", ".join(unknown))
    if unused:
        errors.append("unused archive anchors: " + ", ".join(unused))
    validate_inventory(inventory, errors)
    validate_current_surface(
        contract.get("current_surface"),
        sources if sources is not None else load_sources(root),
        errors,
    )
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)
    validate_scope(contract.get("scope_boundaries"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENTS:
        errors.append("topology requirement coverage mismatch")
    requirement_terms = {
        "topology.reference-boundary": ("twm", "startup", "width/height", "process"),
        "topology.atomic-transaction": ("Prepare", "commit", "atomically", "failure", "rolls back", "destroy"),
        "topology.canonical-order": ("identity/announcement ordinal", "dense canonical", "never reuse", "exhaustion"),
        "topology.spatial-refresh": ("logical output box", "scene", "root/background", "icon", "waiter", "post-state"),
        "topology.pointer-repair": ("still-valid", "once", "canonical-nearest", "zero outputs", "before"),
        "topology.operation-barrier": ("placement/menu/move/resize", "unchanged pinned", "cancel", "stale geometry", "warp"),
        "topology.warp-history": ("surviving output identity", "clear", "pointer repair", "failure"),
        "topology.lifecycle-invariance": ("global config", "native/Xwayland", "zero/add/change/remove", "reload", "restart", "rejection"),
        "topology.resource-safety": ("listener/layout/scene/reference", "exactly-once", "leak", "double free", "use after free"),
        "topology.restoration-boundary": ("dead-reference-free", "relocation/restoration", "stranded", "next Roadmap"),
    }
    for requirement_id, terms in requirement_terms.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        require_terms(record.get("rule"), terms, requirement_id, errors)
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite upstream evidence")

    scenarios = records_by_id(contract.get("verification_scenarios"), "verification_scenarios", errors)
    actual = {scenario_id: record.get("kind") for scenario_id, record in scenarios.items()}
    if actual != EXPECTED_SCENARIOS:
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
    mutations: list[tuple[str, dict[str, Any], bool]] = []

    def mutate(name: str, path: tuple[Any, ...], value: Any) -> None:
        candidate = copy.deepcopy(contract)
        current: Any = candidate
        for component in path[:-1]:
            current = current[component]
        current[path[-1]] = value
        mutations.append((name, candidate, False))

    mutate("archive pin", ("upstream", "sha256"), "0" * 64)
    mutate("member pin", ("source_members", "twm-1.0.13.1/src/events.c"), "0" * 64)
    exact_anchor = copy.deepcopy(contract)
    exact_anchor["evidence"]["randr.update-width"]["text"] += " tampered"
    mutations.append(("exact archive anchor", exact_anchor, True))
    mutate("reference membership", ("reference_behavior", "screen_membership", "rule"), "X screens hotplug dynamically.")
    mutate("reference RandR", ("reference_behavior", "screen_geometry", "randr"), "Rebuild every screen namespace.")
    mutate("reference non-actions", ("reference_behavior", "screen_geometry", "non_actions"), "Relocate all windows and history atomically.")
    mutate("classification", ("wayland_translation", "classification"), "literal static roots")
    mutate("event coverage", ("wayland_translation", "transaction_model", "events"), "Handle only add.")
    mutate("snapshot", ("wayland_translation", "transaction_model", "snapshot"), "Read live lists after mutation.")
    mutate("prepare", ("wayland_translation", "transaction_model", "prepare"), "Allocate after publish.")
    mutate("half publish", ("wayland_translation", "transaction_model", "commit_publish"), "Dispatch clients between steps.")
    mutate("failure rollback", ("wayland_translation", "transaction_model", "failure"), "Keep partial scene changes on commit failure.")
    mutate("destroy rollback", ("wayland_translation", "transaction_model", "destroy_exception"), "Ignore destroyed devices.")
    mutate("add publication", ("wayland_translation", "event_semantics", "add"), "Publish before scene allocation.")
    mutate("add failure ordinal", ("wayland_translation", "event_semantics", "add_failure"), "Reuse candidate ordinals.")
    mutate("disable identity", ("wayland_translation", "event_semantics", "disable"), "Free identity and wrapper.")
    mutate("enable identity", ("wayland_translation", "event_semantics", "enable"), "Allocate a new ordinal.")
    mutate("mode refresh", ("wayland_translation", "event_semantics", "mode_scale_transform"), "Resize hardware only.")
    mutate("layout partial", ("wayland_translation", "event_semantics", "layout"), "Move one background before validation.")
    mutate("destroy ordering", ("wayland_translation", "event_semantics", "destroy"), "Free wrapper before listeners.")
    mutate("active invalid boxes", ("wayland_translation", "canonical_order", "active_domain"), "Include disabled zero-sized outputs.")
    mutate("mutable identity", ("wayland_translation", "canonical_order", "identity"), "Change ordinal on scale.")
    mutate("geometry ordering", ("wayland_translation", "canonical_order", "ordering"), "Sort by x coordinate.")
    mutate("rejected renumber", ("wayland_translation", "canonical_order", "dense_recompute"), "Renumber before commit.")
    mutate("ordinal wrap", ("wayland_translation", "canonical_order", "ordinal"), "Wrap UINT64_MAX to zero.")
    mutate("stale background", ("wayland_translation", "spatial_refresh", "backgrounds"), "Keep old size rectangles.")
    mutate("gap root", ("wayland_translation", "spatial_refresh", "root_hits"), "Treat union gaps as root.")
    mutate("duplicate icon UI", ("wayland_translation", "spatial_refresh", "global_ui"), "Duplicate managers per output.")
    mutate("early waiter", ("wayland_translation", "spatial_refresh", "waiters"), "Resume before publication and consume state.")
    mutate("pointer always warp", ("wayland_translation", "pointer_repair", "preserve"), "Always warp to output zero.")
    mutate("pointer union", ("wayland_translation", "pointer_repair", "repair"), "Leave pointer in gap.")
    mutate("synthetic zero root", ("wayland_translation", "pointer_repair", "zero"), "Create a 1x1 root.")
    mutate("pointer repair order", ("wayland_translation", "pointer_repair", "ordering"), "Repair against old geometry.")
    mutate("operation repin", ("wayland_translation", "operation_barrier", "unaffected"), "Switch every operation to current index.")
    mutate("commit stale move", ("wayland_translation", "operation_barrier", "move_resize"), "Commit preview on removal.")
    mutate("menu action", ("wayland_translation", "operation_barrier", "menu"), "Execute selected row while closing.")
    mutate("placement consume", ("wayland_translation", "operation_barrier", "placement"), "Expose client and advance random state.")
    mutate("interleaved warp", ("wayland_translation", "operation_barrier", "warp"), "Mutate output list during warp plan.")
    mutate("history integer", ("wayland_translation", "warp_history", "surviving_reference"), "Keep old dense integer.")
    mutate("missing history", ("wayland_translation", "warp_history", "missing_reference"), "Let inherited index select another output.")
    mutate("pointer visit", ("wayland_translation", "warp_history", "pointer_repair"), "Record repair as screen visit.")
    mutate("failed history", ("wayland_translation", "warp_history", "failure"), "Clear history on rejection.")
    mutate("per-output config", ("wayland_translation", "configuration_lifecycle", "global_config"), "Read .twmrc.1 on add.")
    mutate("reload renumber", ("wayland_translation", "configuration_lifecycle", "reload"), "Reload rebuilds identity order.")
    mutate("restart output rebuild", ("wayland_translation", "configuration_lifecycle", "restart"), "Restart destroys all outputs.")
    mutate("client disconnect", ("wayland_translation", "configuration_lifecycle", "no_disconnect"), "Restart Xwayland on mode change.")
    mutate("protocol divergence", ("wayland_translation", "protocol_invariance", "rule"), "Use separate native and Xwayland topology.")
    mutate("premature restoration", ("wayland_translation", "protocol_invariance", "client_geometry_boundary"), "Relocate all disappeared-output windows in this slice.")
    mutate("free before detach", ("wayland_translation", "resource_safety", "teardown_order"), "Free then remove listeners.")
    mutate("stale references", ("wayland_translation", "resource_safety", "references"), "Deferred actions retain output pointers.")
    mutate("unbounded retry", ("wayland_translation", "resource_safety", "bounded"), "Retry allocation forever.")
    mutate("churn leak", ("wayland_translation", "resource_safety", "churn"), "Leaks are acceptable under tests.")
    mutate("deferred restoration", ("scope_boundaries", "explicitly_deferred"), [])
    mutate("restoration handoff", ("scope_boundaries", "restoration_handoff"), "Relocate everything here.")
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
            "state listener",
            "src/wtwm.c",
            "struct wl_listener request_state;",
            "struct wl_listener ignored_state;",
        ),
        (
            "ordinal exhaustion",
            "src/wtwm.c",
            "server->output_announcement_ordinal_exhausted = true;",
            "server->output_announcement_ordinal_exhausted = false;",
        ),
        (
            "output destroy entry",
            "src/wtwm.c",
            "static void output_destroy(struct wl_listener *listener, void *data) {",
            "static void ignored_output_destroy(struct wl_listener *listener, void *data) {",
        ),
        (
            "identity copy",
            "src/wtwm.c",
            "if (!wtwm_output_identity_init(&output->identity, wlr_output->name,",
            "if (false && !wtwm_output_identity_init(&output->identity, wlr_output->name,",
        ),
        (
            "enabled snapshot",
            "src/wtwm.c",
            "if (!output->wlr->enabled || !output->in_layout) continue;\n"
            "\t\tif (!wtwm_output_order_set(*snapshot, index, "
            "&output->identity, output)) {",
            "if (false) continue;\n"
            "\t\tif (!wtwm_output_order_set(*snapshot, index, "
            "&output->identity, output)) {",
        ),
        (
            "identity comparison",
            "src/output_order.c",
            "if (result == 0) result = compare_bytes(a->serial, b->serial);",
            "if (result == 0) result = 0;",
        ),
        (
            "ordinal comparison",
            "src/output_order.c",
            "return a->announcement_ordinal < b->announcement_ordinal ? -1 :",
            "return 0 < 1 ? -1 :",
        ),
    ]
    for name, path, old, new in source_mutations:
        source = baseline_sources[path]
        if source.count(old) != 1:
            failures.append(f"source tamper setup mismatch: {name}")
            continue
        changed = dict(baseline_sources)
        changed[path] = source.replace(old, new, 1)
        errors = validate_contract(
            contract,
            inventory,
            root,
            verify_canonical=False,
            verify_archive=False,
            sources=changed,
        )
        if not errors:
            failures.append(f"source tamper self-test was not rejected: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run tamper probes")
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    try:
        contract = load_json(root / CONTRACT_PATH)
        inventory = load_json(root / EXPECTED_UPSTREAM["inventory"])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"output-topology contract error: {error}", file=sys.stderr)
        return 1
    errors = validate_contract(contract, inventory, root)
    if arguments.self_test and not errors:
        errors.extend(run_tamper_tests(contract, inventory, root))
    if errors:
        for error in errors:
            print(f"output-topology contract error: {error}", file=sys.stderr)
        return 1
    suffix = " and tamper suite" if arguments.self_test else ""
    print(
        "output-topology contract valid: "
        f"{len(contract['evidence'])} archive anchors, "
        f"{len(contract['requirements'])} requirements, "
        f"{len(contract['verification_scenarios'])} scenarios{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
