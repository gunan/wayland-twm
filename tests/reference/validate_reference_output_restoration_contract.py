#!/usr/bin/env python3
"""Validate the frozen disappeared-output window-restoration contract."""

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
    "reference/lifecycle/twm-1.0.13.1/output-restoration-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "4fcdb298db649e5e5628c29b12d022db29e7ec62c63e3158de20a61f74cd0fa7"
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
    "twm-1.0.13.1/src/icons.c": (
        "d97413dc1abb5a8811ee54056d3a949dbbe6a8ef08c147198a2ae30cff4e558b"
    ),
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/resize.c": (
        "086966fc1ef0ba0cc7975623aaed52273b9b03f40f6a08e0a3d6f49698f25f67"
    ),
    "twm-1.0.13.1/src/twm.h": (
        "c9688764f567e781acaf6ed8f7590ddf94b45ce09bd306dd8db55524a88b46e1"
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
SOURCE_PATHS = (
    "include/wtwm/actions.h",
    "src/actions.c",
    "src/placement.c",
    "src/wtwm.c",
)
EXPECTED_CURRENT_ANCHORS = {
    "runtime.toplevel-state",
    "runtime.frame-position",
    "runtime.output-reference",
    "runtime.icon-state",
    "runtime.zoom-state",
    "runtime.outer-selection",
    "placement.outer-selector",
    "placement.intersection-priority",
    "placement.nearest-center",
    "placement.reference-clamp",
    "runtime.topology-refresh",
    "runtime.topology-zero",
    "runtime.topology-destroy",
    "runtime.waiter-resume",
    "runtime.session-save-icon",
    "runtime.session-save-zoom",
    "runtime.session-restore-geometry",
    "runtime.session-restore-icon",
    "runtime.xwayland-transient",
    "actions.zoom-record",
    "actions.zoom-save",
    "actions.zoom-output",
}
EXPECTED_REQUIREMENTS = {
    "restoration.reference-boundary",
    "restoration.affected-selection",
    "restoration.destination-clamp",
    "restoration.transient-family",
    "restoration.iconified-icons",
    "restoration.zoom-saved",
    "restoration.zero-output",
    "restoration.focus-protocol",
    "restoration.atomic-churn",
    "restoration.lifecycle-boundary",
}
EXPECTED_SCENARIOS = {
    "reference-randr-no-restoration": "reference-topology",
    "reference-oversize-clamp-difference": "reference-translation",
    "visible-frame-byte-exact": "runtime-frame",
    "stranded-frame-relative-restore": "runtime-frame",
    "surviving-owner-moved": "runtime-destination",
    "missing-owner-canonical-tie": "runtime-destination",
    "oversized-frame-near-edge": "runtime-clamp",
    "disable-destroy-equivalent": "runtime-topology",
    "shrink-move-stranded-only": "runtime-topology",
    "no-automatic-repatriation": "runtime-churn",
    "native-managed-frame": "runtime-native",
    "xwayland-managed-frame": "runtime-xwayland",
    "transient-root-family": "runtime-family",
    "transient-child-only": "runtime-family",
    "override-redirect-excluded": "runtime-boundary",
    "iconified-frame-and-manual-icon": "runtime-icon",
    "automatic-icon-region": "runtime-icon",
    "iconify-by-unmapping": "runtime-icon",
    "zoom-owner-changed": "runtime-zoom",
    "zoom-owner-unchanged": "runtime-zoom",
    "zoom-preserves-mode-stack-focus": "runtime-zoom",
    "focus-and-stack-invariant": "runtime-state",
    "zero-output-hide-existing": "runtime-zero-output",
    "zero-output-new-map-separated": "runtime-zero-output",
    "zero-output-resume-order": "runtime-zero-output",
    "zero-output-same-vs-new-identity": "runtime-zero-output",
    "reversible-failure-rollback": "runtime-atomicity",
    "destroy-failure-pending": "runtime-atomicity",
    "repeated-topology-churn": "runtime-churn",
    "save-after-restoration": "runtime-session",
    "restart-preserves-restoration": "runtime-session",
    "previous-state-current-topology": "runtime-session",
    "reload-no-restoration-side-effect": "runtime-lifecycle",
    "input-and-session-boundary": "contract-scope",
}
EXPECTED_DEFERRED = [
    "input hotplug and multiple keyboards, pointers, seats, or independent seat focus",
    "session startup, logout, failure recovery, state-file lifetime, and persistent physical-output identity or reassociation",
    "new per-output workspace ownership, automatic repatriation policy, or user-configurable restoration destinations",
    "relocation of unmanaged Xwayland override-redirect surfaces, layer-shell surfaces, popups, drag icons, or client-owned subsurfaces",
]


def load_json(path: Path) -> Any:
    """Load JSON while rejecting duplicate keys."""

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
    source_members: Any,
    evidence: dict[str, Any],
    errors: list[str],
) -> None:
    if upstream != EXPECTED_UPSTREAM or source_members != EXPECTED_SOURCE_MEMBERS:
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
            member_lines: dict[str, list[str]] = {}
            for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
                extracted = archive.extractfile(member)
                if extracted is None:
                    errors.append(f"missing archive member: {member}")
                    continue
                data = extracted.read()
                if sha256_bytes(data) != expected_hash:
                    errors.append(f"archive member hash mismatch: {member}")
                member_lines[member] = data.decode("utf-8").splitlines()
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
                lines = member_lines.get(member, [])
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
    categories = value.get("category_order")
    if not isinstance(categories, list) or "built-in-action" not in categories:
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
            "greatest positive",
            "nearest-center",
            "native and Xwayland",
            "iconified",
            "transient",
            "zoom",
            "topology",
            "zero-output",
            "Session",
            "physical-output identity",
        ):
            if term not in text:
                errors.append(f"current surface omits {term}")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {
        "topology_limit",
        "move_and_icon_bounds",
        "families_icons_zoom",
    }:
        errors.append("reference_behavior fields differ from schema")
    topology = require_object(behavior.get("topology_limit"), "topology_limit", errors)
    if set(topology) != {"rule", "evidence"}:
        errors.append("topology_limit fields differ from schema")
    require_terms(
        topology.get("rule"),
        ("fixed startup", "width and height", "no output disappearance", "rollback"),
        "reference topology limit",
        errors,
    )
    bounds = require_object(
        behavior.get("move_and_icon_bounds"), "move_and_icon_bounds", errors
    )
    if set(bounds) != {"rule", "oversize_discrepancy", "evidence"}:
        errors.append("move_and_icon_bounds fields differ from schema")
    require_terms(
        bounds.get("rule"),
        ("DontMoveOff", "near edge", "far edge", "IconPositionHint", "PlaceIcon", "not topology restoration"),
        "reference move/icon bounds",
        errors,
    )
    require_terms(
        bounds.get("oversize_discrepancy"),
        ("negative", "stronger safety translation", "preserve", "pin", "not permanently hidden"),
        "reference oversize discrepancy",
        errors,
    )
    families = require_object(
        behavior.get("families_icons_zoom"), "families_icons_zoom", errors
    )
    if set(families) != {"rule", "restoration_difference", "evidence"}:
        errors.append("families_icons_zoom fields differ from schema")
    require_terms(
        families.get("rule"),
        ("transient parentage", "iconifies/deiconifies", "manual icon", "saved unzoomed", "screen dimensions", "raises"),
        "reference family/icon/zoom",
        errors,
    )
    require_terms(
        families.get("restoration_difference"),
        ("no disappearing-screen", "must not synthesize", "focus", "raise", "stacking"),
        "reference restoration difference",
        errors,
    )


TRANSLATION_SCHEMA = {
    "snapshot_and_affected": {"snapshot", "normal_frame", "stranded", "no_op"},
    "owner_destination": {
        "source_owner",
        "surviving_owner",
        "missing_owner",
        "no_outputs",
        "no_repatriation",
    },
    "coordinate_and_clamp": {
        "relative_candidate",
        "fitting_axis",
        "oversize_axis",
        "dimensions",
    },
    "transient_families": {"membership", "root_stranded", "root_visible", "ordering"},
    "icons_and_iconified": {
        "hidden_frame",
        "visible_icon",
        "automatic_icon",
        "unmapping",
    },
    "zoom_and_saved_geometry": {"affected", "target", "displayed", "side_effects"},
    "zero_output_lifecycle": {
        "hide_existing",
        "focus_stack",
        "new_maps",
        "resume",
        "pending_identity",
    },
    "focus_stack_protocol": {"focus_and_stack", "native", "xwayland", "invariance"},
    "atomicity_and_churn": {"prepare", "reversible_failure", "destroy_failure", "repeat"},
    "configuration_session_restart": {"reload", "save", "restart", "previous_state"},
}

SEMANTIC_TERMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("snapshot_and_affected", "snapshot"): ("immutable pre-transaction", "post-transaction canonical", "one pair"),
    ("snapshot_and_affected", "normal_frame"): ("positive-area intersection", "byte-for-byte", "canonical indices"),
    ("snapshot_and_affected", "stranded"): ("zero positive-area", "Disable and destroy", "shrink", "scale", "mode"),
    ("snapshot_and_affected", "no_op"): ("rolled-back", "move nothing", "partial visibility", "output return"),
    ("owner_destination", "source_owner"): ("wtwm_placement_output_for_outer", "greatest positive intersection", "first canonical", "nearest-center"),
    ("owner_destination", "surviving_owner"): ("exact source identity", "destination", "moved or shrank"),
    ("owner_destination", "missing_owner"): ("nearest", "old outer-box center", "overflow-safe", "dense-index", "protocol"),
    ("owner_destination", "no_outputs"): ("no destination", "bounded in-memory", "synthetic"),
    ("owner_destination", "no_repatriation"): ("future pre-state", "does not return", "byte-exact"),
    ("coordinate_and_clamp", "relative_candidate"): ("destination origin", "unscaled logical offset", "checked wide", "old global"),
    ("coordinate_and_clamp", "fitting_axis"): ("no larger", "inclusive range", "whole outer box"),
    ("coordinate_and_clamp", "oversize_axis"): ("exceeds", "preserve size", "near edge", "far edge", "Never shrink"),
    ("coordinate_and_clamp", "dimensions"): ("complete compositor outer", "decorations", "half-open", "client/frame size"),
    ("transient_families", "membership"): ("recursive family", "xdg parent", "Xwayland transient-for", "override-redirect", "stacking order"),
    ("transient_families", "root_stranded"): ("one root destination", "safety-clamp the root", "actual root delta", "planned root top-left minus old root top-left", "actual post-clamp delta", "every managed descendant", "independently safety-clamp"),
    ("transient_families", "root_visible"): ("positively visible", "byte-for-byte", "only a stranded descendant", "delta zero", "visible siblings"),
    ("transient_families", "ordering"): ("parent links", "focus", "exact pre-state stacking", "never raises"),
    ("icons_and_iconified", "hidden_frame"): ("hidden underlying frame", "iconified", "deiconify", "stranded"),
    ("icons_and_iconified", "visible_icon"): ("independent", "Manual/IconPositionHint", "relative candidate", "iconified state"),
    ("icons_and_iconified", "automatic_icon"): ("remains automatic", "deterministic allocator", "byte-for-byte", "fall back", "Never convert"),
    ("icons_and_iconified", "unmapping"): ("IconifyByUnmapping", "no visible icon", "only the hidden frame", "Do not create"),
    ("zoom_and_saved_geometry", "affected"): ("zoom-owner", "identity disappears", "logical box changes", "still intersects", "byte-exact"),
    ("zoom_and_saved_geometry", "target"): ("surviving owner identity", "canonical-nearest", "saved unzoomed", "origin delta", "preserving"),
    ("zoom_and_saved_geometry", "displayed"): ("exact zoom mode", "recompute displayed", "wtwm_action_zoom", "Do not treat", "saved box"),
    ("zoom_and_saved_geometry", "side_effects"): ("does not raise", "focus", "unzoom", "zero outputs", "pending"),
    ("zero_output_lifecycle", "hide_existing"): ("protocol-mapped", "connected", "disable their compositor scene", "pending", "synthetic unmap", "configure-to-zero"),
    ("zero_output_lifecycle", "focus_stack"): ("focus bookkeeping", "exact stacking", "Clear only invalid pointer", "no hidden client"),
    ("zero_output_lifecycle", "new_maps"): ("placement-waiting", "scene-hidden", "not mixed"),
    ("zero_output_lifecycle", "resume"): ("first successful", "stable pre-existing stacking", "scene visibility", "before resuming", "oldest-first", "failed"),
    ("zero_output_lifecycle", "pending_identity"): ("only in memory", "same managed identity", "new identity", "canonical-nearest"),
    ("focus_stack_protocol", "focus_and_stack"): ("exact focus", "stacking order", "iconified", "no focus", "user-action trace"),
    ("focus_stack_protocol", "native"): ("native Wayland", "frame/scene position", "only when", "normal restoration"),
    ("focus_stack_protocol", "xwayland"): ("managed Xwayland", "frame/client coordinates", "without withdrawing", "transient-for"),
    ("focus_stack_protocol", "invariance"): ("identical", "native", "managed Xwayland", "WM_NAME/WM_CLASS", "mapping order"),
    ("atomicity_and_churn", "prepare"): ("complete restoration plan", "before publishing", "reversible", "input/render/client-visible"),
    ("atomicity_and_churn", "reversible_failure"): ("allocation", "backend", "rolls back", "byte-for-byte"),
    ("atomicity_and_churn", "destroy_failure"): ("irreversible", "dead output reference", "hidden", "bounded restoration-pending", "never expose"),
    ("atomicity_and_churn", "repeat"): ("next transaction", "drift-free", "bounded", "no leak", "double restore", "use after free"),
    ("configuration_session_restart", "reload"): ("does not undo", "repatriate", "automatic icon regions", "rejection"),
    ("configuration_session_restart", "save"): ("f.saveyourself", "relocated current frame", "manual icon", "zoom mode", "pending"),
    ("configuration_session_restart", "restart"): ("in-place", "preserves", "never repatriates", "warp-history", "do not alter"),
    ("configuration_session_restart", "previous_state"): ("RestartPreviousState", "no physical-output identity", "current canonical", "safety clamp", "zoom display", "Ambiguous"),
}


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    expected = {"classification", *TRANSLATION_SCHEMA}
    if set(translation) != expected:
        errors.append("wayland_translation fields differ from schema")
    require_terms(
        translation.get("classification"),
        ("behaviorally-equivalent", "fixed-screen", "deterministic visibility", "atomicity", "resource-safety"),
        "translation classification",
        errors,
    )
    for section_name, expected_fields in TRANSLATION_SCHEMA.items():
        section = require_object(
            translation.get(section_name), section_name, errors
        )
        if set(section) != expected_fields:
            errors.append(f"{section_name} fields differ from schema")
        for field in expected_fields:
            require_terms(
                section.get(field),
                SEMANTIC_TERMS[(section_name, field)],
                f"{section_name}.{field}",
                errors,
            )


REQUIREMENT_TERMS = {
    "restoration.reference-boundary": ("fixed screens", "dimensions-only", "move/icon/zoom/transient", "stronger Wayland"),
    "restoration.affected-selection": ("positive-intersection", "byte-exact", "zero-intersection", "zoom-owner"),
    "restoration.destination-clamp": ("greatest intersection/canonical-nearest", "surviving identity", "relative", "oversized near edges", "without resizing"),
    "restoration.transient-family": ("managed native/Xwayland family", "root delta", "visible members", "stranded descendants", "stack"),
    "restoration.iconified-icons": ("hidden iconified frames", "visible", "manual/automatic", "IconifyByUnmapping", "icon-manager"),
    "restoration.zoom-saved": ("zoom-owner", "preserve zoom mode", "saved unzoom", "recompute displayed", "no raise/focus/toggle"),
    "restoration.zero-output": ("mapped/connected", "scene-hidden", "pending", "before new placement waiters", "configure-to-zero"),
    "restoration.focus-protocol": ("exact focus/root-focus", "stacking", "native", "managed Xwayland", "override-redirect"),
    "restoration.atomic-churn": ("topology transaction", "reversible failure", "byte-exact", "irreversible destroy", "dead references", "drift-free", "bounded"),
    "restoration.lifecycle-boundary": ("save/restart", "without repatriation", "RestartPreviousState", "input hotplug", "physical-output"),
}


def validate_scope(value: Any, errors: list[str]) -> None:
    scope = require_object(value, "scope_boundaries", errors)
    if set(scope) != {
        "this_slice_requires",
        "already_owned",
        "explicitly_deferred",
        "next_handoff",
        "non_claim",
    }:
        errors.append("scope_boundaries fields differ from schema")
    required = scope.get("this_slice_requires")
    if not isinstance(required, list) or len(required) != 5:
        errors.append("restoration slice requirement summary mismatch")
    else:
        text = " ".join(str(item) for item in required)
        for term in (
            "destination",
            "clamping",
            "native/Xwayland",
            "transient",
            "icon",
            "zoom",
            "zero-output",
            "rollback",
            "restart/session",
            "repatriates",
        ):
            if term not in text:
                errors.append(f"restoration slice requirements omit {term}")
    owned = scope.get("already_owned")
    if not isinstance(owned, list) or len(owned) != 3:
        errors.append("adjacent contract ownership mismatch")
    else:
        text = " ".join(str(item) for item in owned)
        for contract in (
            "output-topology-contract.json",
            "screen-output-contract.json",
            "output-placement-contract.json",
            "warp-screen-contract.json",
        ):
            if contract not in text:
                errors.append(f"adjacent ownership omits {contract}")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred restoration scope mismatch")
    require_terms(
        scope.get("next_handoff"),
        ("immediately following Roadmap", "input hotplug", "output-independent focus", "must not reinterpret", "zero-output"),
        "next handoff",
        errors,
    )
    require_terms(
        scope.get("non_claim"),
        ("only managed-window restoration", "does not complete", "input hotplug", "session lifecycle", "exit criteria"),
        "scope non-claim",
        errors,
    )


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
    if not isinstance(evidence, dict) or len(evidence) != 32:
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
        errors.append("restoration requirement coverage mismatch")
    for requirement_id, terms in REQUIREMENT_TERMS.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        require_terms(record.get("rule"), terms, requirement_id, errors)
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite upstream evidence")

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    actual = {
        scenario_id: record.get("kind") for scenario_id, record in scenarios.items()
    }
    if actual != EXPECTED_SCENARIOS:
        errors.append("verification scenario ids or kinds mismatch")
    for scenario_id, record in scenarios.items():
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        oracle = record.get("oracle")
        if not isinstance(oracle, str) or len(oracle) < 80:
            errors.append(f"{scenario_id} needs a specific oracle")
    return errors


def set_nested(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> None:
    target: Any = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement


def run_tamper_tests(
    contract: dict[str, Any], inventory: Any, root: Path
) -> list[str]:
    mutations: list[tuple[str, dict[str, Any], bool]] = []

    def mutate(
        name: str,
        path: tuple[str, ...],
        replacement: Any,
        *,
        inspect_archive: bool = False,
    ) -> None:
        candidate = copy.deepcopy(contract)
        set_nested(candidate, path, replacement)
        mutations.append((name, candidate, inspect_archive))

    mutate("schema", ("schema_version",), 2)
    mutate("archive provenance", ("upstream", "version"), "1.0.13")
    first_member = next(iter(EXPECTED_SOURCE_MEMBERS))
    mutate("member hash", ("source_members", first_member), "0" * 64)
    mutate(
        "evidence line",
        ("evidence", "randr.width", "line"),
        2409,
        inspect_archive=True,
    )
    mutate(
        "evidence text",
        ("evidence", "zoom.save-x", "text"),
        "tampered",
        inspect_archive=True,
    )
    mutate(
        "current anchor",
        ("current_surface", "source_anchors", "actions.zoom-save", "text"),
        "state->saved = current;",
    )
    mutate(
        "classification",
        ("wayland_translation", "classification"),
        "Literal X screen removal.",
    )
    for (section, field), terms in SEMANTIC_TERMS.items():
        del terms
        mutate(
            f"semantic {section}.{field}",
            ("wayland_translation", section, field),
            "Tampered policy.",
        )
    mutate("required summary", ("scope_boundaries", "this_slice_requires"), [])
    mutate("owned boundaries", ("scope_boundaries", "already_owned"), [])
    mutate("deferred boundaries", ("scope_boundaries", "explicitly_deferred"), [])
    mutate("next handoff", ("scope_boundaries", "next_handoff"), "Do everything here.")
    mutate("non claim", ("scope_boundaries", "non_claim"), "Full parity complete.")

    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement, False))
    changed_requirement = copy.deepcopy(contract)
    changed_requirement["requirements"][2]["rule"] = "Move to pointer output."
    mutations.append(("destination requirement", changed_requirement, False))
    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario, False))
    changed_scenario = copy.deepcopy(contract)
    changed_scenario["verification_scenarios"][0]["kind"] = "runtime"
    mutations.append(("scenario kind", changed_scenario, False))
    empty_oracle = copy.deepcopy(contract)
    empty_oracle["verification_scenarios"][20]["oracle"] = "vague"
    mutations.append(("scenario oracle", empty_oracle, False))
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
            "frame position state",
            "src/wtwm.c",
            "int frame_x;\n\tint frame_y;\n\tbool frame_positioned;",
            "int frame_x;\n\tint frame_y;\n\tbool ignored_position;",
        ),
        (
            "outer runtime selector",
            "src/wtwm.c",
            "bool found = loaded && wtwm_placement_output_for_outer(areas, count,",
            "bool found = false && wtwm_placement_output_for_outer(areas, count,",
        ),
        (
            "topology zero output",
            "src/wtwm.c",
            "if (enabled_output_count(server) == 0) {\n"
            "\t\tserver->pointer_toplevel = NULL;",
            "if (enabled_output_count(server) < 0) {\n"
            "\t\tserver->pointer_toplevel = NULL;",
        ),
        (
            "output destroy",
            "src/wtwm.c",
            "static void output_destroy(struct wl_listener *listener, void *data) {",
            "static void ignored_output_destroy(struct wl_listener *listener, void *data) {",
        ),
        (
            "session icon",
            "src/wtwm.c",
            ".has_manual_icon_position = toplevel->icon_moved,",
            ".has_manual_icon_position = false,",
        ),
        (
            "session zoom",
            "src/wtwm.c",
            ".zoom_mode = session_zoom_mode(toplevel->zoom.mode),",
            ".zoom_mode = WTWM_SESSION_ZOOM_NONE,",
        ),
        (
            "Xwayland transient",
            "src/wtwm.c",
            "static void position_xwayland_transient(struct toplevel *toplevel) {",
            "static void ignored_xwayland_transient(struct toplevel *toplevel) {",
        ),
        (
            "placement intersection",
            "src/placement.c",
            "if (intersection > best_intersection) {",
            "if (intersection >= best_intersection) {",
        ),
        (
            "placement nearest center",
            "src/placement.c",
            "int64_t center_x = (int64_t)2 * outer_x +",
            "int64_t center_x = outer_x +",
        ),
        (
            "zoom saved geometry",
            "src/actions.c",
            "if (!wtwm_action_is_zoom(state->mode)) state->saved = *current;",
            "if (false) state->saved = *current;",
        ),
        (
            "zoom record",
            "include/wtwm/actions.h",
            "struct wtwm_zoom_state {\n\tenum wtwm_action_type mode;\n\tstruct wtwm_interaction_box saved;\n};",
            "struct wtwm_zoom_state { enum wtwm_action_type mode; };",
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
        print(f"output-restoration contract error: {error}", file=sys.stderr)
        return 1
    errors = validate_contract(contract, inventory, root)
    if arguments.self_test and not errors:
        errors.extend(run_tamper_tests(contract, inventory, root))
    if errors:
        for error in errors:
            print(f"output-restoration contract error: {error}", file=sys.stderr)
        return 1
    suffix = " and tamper suite" if arguments.self_test else ""
    print(
        "output-restoration contract valid: "
        f"{len(contract['evidence'])} archive anchors, "
        f"{len(contract['requirements'])} requirements, "
        f"{len(contract['verification_scenarios'])} scenarios{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
