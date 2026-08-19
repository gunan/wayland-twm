#!/usr/bin/env python3
"""Validate the frozen single-seat input-hotplug translation contract."""

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
    "reference/lifecycle/twm-1.0.13.1/input-hotplug-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "607e6fe82619ddcd413c09740e00244a3982d543b7a8884f2a67a0008ed47a8a"
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
SOURCE_PATHS = ("src/wtwm.c",)
EXPECTED_CURRENT_ANCHORS = {
    "runtime.keyboard-record",
    "runtime.keyboard-device",
    "runtime.cursor",
    "runtime.seat",
    "runtime.keyboard-list",
    "runtime.xwayland-seat",
    "runtime.clear-keyboard-focus",
    "runtime.reset-cursor",
    "runtime.finish-interactive",
    "runtime.restoration-pending",
    "runtime.output-refresh",
    "runtime.zero-output-pointer-clear",
    "runtime.restart",
    "runtime.pointer-refresh",
    "runtime.pointer-motion",
    "runtime.keyboard-modifiers",
    "runtime.keyboard-key",
    "runtime.keyboard-destroy",
    "runtime.new-keyboard",
    "runtime.new-input",
    "runtime.cursor-layout",
    "runtime.keyboard-list-init",
    "runtime.seat-create",
    "runtime.backend-input-listener",
}
EXPECTED_REQUIREMENTS = {
    "input.reference-core-boundary",
    "input.single-seat-inventory",
    "input.capability-admission",
    "input.keyboard-aggregate",
    "input.pointer-continuity",
    "input.interaction-cancellation",
    "input.focus-restoration-safety",
    "input.protocol-invariance",
    "input.reload-restart",
    "input.atomic-resource-safety",
}
EXPECTED_SCENARIOS = {
    "reference-one-core-stream": "reference-input",
    "reference-global-pointer-state": "reference-input",
    "zero-device-capabilities": "runtime-capability",
    "first-keyboard-add": "runtime-keyboard",
    "additional-keyboard-no-steal": "runtime-keyboard",
    "keyboard-event-activates": "runtime-keyboard",
    "keyboard-removal-fallback": "runtime-keyboard",
    "same-key-two-keyboards": "runtime-key-state",
    "binding-owned-key-drain": "runtime-key-state",
    "logical-aggregate-modifiers": "runtime-modifier",
    "last-keyboard-removal": "runtime-keyboard",
    "keyboard-return-focus": "runtime-focus",
    "first-pointer-add": "runtime-pointer",
    "additional-pointer-no-steal": "runtime-pointer",
    "pointer-event-activates": "runtime-pointer",
    "pointer-removal-fallback": "runtime-pointer",
    "same-button-two-pointers": "runtime-button-state",
    "non-last-pointer-continuity": "runtime-pointer",
    "required-button-loss-aborts": "runtime-interaction",
    "last-pointer-aborts-move-resize": "runtime-interaction",
    "last-pointer-closes-menu": "runtime-interaction",
    "last-pointer-requeues-placement": "runtime-placement",
    "no-pointer-noninteractive-placement": "runtime-placement",
    "zero-output-input-hotplug": "runtime-output",
    "restoration-before-pointer-resume": "runtime-output",
    "native-xwayland-aggregate": "runtime-protocol",
    "unsupported-device-ignored": "runtime-boundary",
    "admission-failure-rollback": "runtime-atomicity",
    "duplicate-unknown-readd": "runtime-control",
    "clear-preserves-ordinal-focus-cursor": "runtime-control",
    "reload-held-disposition": "runtime-lifecycle",
    "restart-input-continuity": "runtime-lifecycle",
    "ordinal-activity-overflow": "runtime-resource",
    "bounded-hotplug-churn": "runtime-resource",
    "single-seat-and-session-boundary": "contract-scope",
}
EXPECTED_COMMANDS = [
    "INPUT CLEAR",
    "INPUT ADD KEYBOARD <name>",
    "INPUT ADD POINTER <name>",
    "INPUT REMOVE <name>",
    "INPUT KEY <keyboard> <code> press|release",
    "INPUT POINTER <pointer> <global-x> <global-y>",
    "INPUT BUTTON <pointer> <code> press|release",
]
EXPECTED_DEFERRED = [
    "multiple logical seats, per-seat focus/clipboard/selection, device-to-seat assignment, and independent cursors",
    "touch, tablet, pad, switch, gesture, pointer constraint, relative-pointer lock, and input-method protocol policy",
    "per-device keymap/layout/repeat/accessibility, pointer acceleration/calibration, remapping, and persistent physical-device identity",
    "session startup, logout, backend failure recovery, state-file lifetime, and cross-process input restoration",
    "security authorization for virtual input devices or remote-control injection beyond the test-only interface",
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
            "seat0",
            "Xwayland",
            "global cursor",
            "new_input",
            "keyboard wrapper",
            "aggregate held state",
            "pointer devices",
            "pressed-button ownership",
            "Focus",
            "output restoration",
        ):
            if term not in text:
                errors.append(f"current surface omits {term}")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {
        "core_connection",
        "core_event_stream",
        "bindings_and_global_interaction",
        "focus_boundary",
    }:
        errors.append("reference_behavior fields differ from schema")
    expected = {
        "core_connection": (
            "one X display connection",
            "fixed X screens",
            "KeyPress",
            "ButtonPress/ButtonRelease",
            "does not enumerate physical",
            "no runtime input-device",
        ),
        "core_event_stream": (
            "global XEvent",
            "core event type",
            "without a physical-device identity",
            "aggregated X core",
        ),
        "bindings_and_global_interaction": (
            "core key press",
            "forwards an unbound",
            "one DragWindow",
            "global ButtonPressed",
            "cancel",
            "one logical pointer",
        ),
        "focus_boundary": (
            "focused TwmWindow",
            "FocusRoot",
            "not as ownership",
            "no physical-device removal rule",
            "logical focus",
        ),
    }
    for section_name, terms in expected.items():
        section = require_object(behavior.get(section_name), section_name, errors)
        if set(section) != {"rule", "evidence"}:
            errors.append(f"{section_name} fields differ from schema")
        require_terms(section.get("rule"), terms, section_name, errors)


TRANSLATION_SCHEMA = {
    "logical_seat_inventory": {"seat", "supported", "identity", "activity", "active"},
    "admission_and_capabilities": {
        "prepare",
        "failure",
        "exact_capabilities",
        "ordering",
        "test_devices",
    },
    "keyboard_state_and_delivery": {
        "per_device",
        "binding",
        "client_refcount",
        "removal_release",
        "common_map",
    },
    "active_keyboard_and_modifiers": {
        "activation",
        "aggregate_adapter",
        "aggregate",
        "updates",
        "fallback",
        "last_keyboard",
    },
    "pointer_state_and_cursor": {
        "global_cursor",
        "per_device_buttons",
        "motion_focus",
        "active_fallback",
        "first_pointer",
    },
    "removal_and_interactions": {
        "button_drain",
        "required_button",
        "last_pointer",
        "initial_placement",
        "resume",
    },
    "focus_output_restoration": {
        "logical_keyboard_focus",
        "keyboard_return",
        "zero_outputs",
        "restore_order",
        "output_change",
    },
    "protocol_invariance": {"common_policy", "native", "xwayland", "boundary"},
    "configuration_restart": {"reload", "restart", "rejected", "session_boundary"},
    "atomicity_and_resources": {
        "removal",
        "batch_clear",
        "bounded",
        "churn",
        "unknown_duplicate",
    },
    "verification_interface": {
        "initial",
        "commands",
        "device_record",
        "seat_record",
        "errors",
    },
}

SEMANTIC_TERMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("logical_seat_inventory", "seat"): ("exactly one", "seat0", "native Wayland", "Xwayland", "Every admitted", "never create"),
    ("logical_seat_inventory", "supported"): ("zero-to-N", "KEYBOARD", "POINTER", "Ignore other", "independent-seat"),
    ("logical_seat_inventory", "identity"): ("admission attempt", "uint64", "shared", "never reused", "gap", "new ordinal", "exhaustion rejects"),
    ("logical_seat_inventory", "activity"): ("unique nonzero", "never-active", "UINT64_MAX", "dense 1..K", "oldest to newest", "K+1", "never rejected forever"),
    ("logical_seat_inventory", "active"): ("first admitted", "does not steal", "greatest last-activity", "lowest announcement", "no active"),
    ("admission_and_capabilities", "prepare"): ("Before publication", "wrapper", "pressed-state", "keymap/repeat", "listeners", "global cursor", "all fallible"),
    ("admission_and_capabilities", "failure"): ("byte-for-byte", "staged resources", "ordinal already reserved", "consumed"),
    ("admission_and_capabilities", "exact_capabilities"): ("if and only if", "at least one admitted keyboard", "at least one admitted pointer", "neither", "never advertise touch"),
    ("admission_and_capabilities", "ordering"): ("first-device add", "before adding", "restore protocol focus", "last-device removal", "drain", "before removing", "do not flap"),
    ("admission_and_capabilities", "test_devices"): ("ordinary admitted synthetic", "inventory/count/capability/state", "not an exception"),
    ("keyboard_state_and_delivery", "per_device"): ("independently per keyboard", "up/down", "compositor-owned or client-owned", "duplicate press", "unmatched release", "without underflow"),
    ("keyboard_state_and_delivery", "binding"): ("active", "physical ownership", "logical aggregate xkb", "before this press", "binding once", "never changes", "consumed"),
    ("keyboard_state_and_delivery", "client_refcount"): ("client-visible reference count", "aggregate xkb", "zero-to-one", "one-to-zero", "double-toggle", "remain stuck"),
    ("keyboard_state_and_delivery", "removal_release"): ("client-owned holders", "synthetic protocol release", "final", "Consume compositor-owned", "never evaluates", "emergency exit"),
    ("keyboard_state_and_delivery", "common_map"): ("same compositor keymap", "repeat", "Per-device", "explicitly deferred"),
    ("active_keyboard_and_modifiers", "activation"): ("key or modifier", "active keyboard", "before", "never changes logical focus", "cursor"),
    ("active_keyboard_and_modifiers", "aggregate_adapter"): ("one logical aggregate", "distinct from physical", "permanently selected", "conforming", "not the only representation", "arbitrary physical", "not conforming"),
    ("active_keyboard_and_modifiers", "aggregate"): ("only by client-owned", "zero-to-one", "one-to-zero", "aggregate xkb", "Raw per-device", "never bitwise-ORed", "seat group"),
    ("active_keyboard_and_modifiers", "updates"): ("aggregate xkb transition", "depressed", "latched", "locked", "group", "exclusive aggregate key holders", "active-keyboard changes alone"),
    ("active_keyboard_and_modifiers", "fallback"): ("deterministic activity/ordinal", "without replacing", "preserve protocol keyboard focus", "without leave/enter", "modifier rewrite"),
    ("active_keyboard_and_modifiers", "last_keyboard"): ("final eligible aggregate key releases", "reset", "initial zero", "clear native Wayland", "remove keyboard capability", "Preserve compositor logical"),
    ("pointer_state_and_cursor", "global_cursor"): ("one compositor global cursor", "one logical pointer focus/grab", "Relative", "absolute", "exact global", "another cursor"),
    ("pointer_state_and_cursor", "per_device_buttons"): ("independently per pointer", "compositor-owned or client-owned", "reference count", "zero-to-one/one-to-zero", "invalid duplicate"),
    ("pointer_state_and_cursor", "motion_focus"): ("valid pointer event", "activates", "global position once", "non-last", "exact cursor", "protocol pointer focus/grab", "draining"),
    ("pointer_state_and_cursor", "active_fallback"): ("greatest-activity/lowest-ordinal", "never moves", "never synthesizes", "focus-follows-mouse", "AutoRaise", "binding"),
    ("pointer_state_and_cursor", "first_pointer"): ("publishes pointer capability", "preserved global cursor", "minimum protocol enter/motion", "not treat", "focus change", "warp", "action"),
    ("removal_and_interactions", "button_drain"): ("client-owned button holders", "final aggregate holder", "existing seat grab/focus", "Compositor-owned", "no drain dispatches", "title button"),
    ("removal_and_interactions", "required_button"): ("final aggregate holder", "required", "abort", "rather than routing", "another holder", "continue"),
    ("removal_and_interactions", "last_pointer"): ("last pointer capability", "abort ordinary move/resize/forcemove", "pre-operation", "close every compositor menu", "clear deferred", "clear pointer focus/grab", "without changing"),
    ("removal_and_interactions", "initial_placement"): ("native or Xwayland", "interaction UI", "hidden and input-waiting", "no placement/random", "pointer count is zero", "noninteractive"),
    ("removal_and_interactions", "resume"): ("first pointer returns", "pointer hit first", "oldest-first", "active output", "restoration is complete", "Client popups", "not dismissed"),
    ("focus_output_restoration", "logical_keyboard_focus"): ("independent of physical keyboard", "pointer count", "output count", "never chooses another"),
    ("focus_output_restoration", "keyboard_return"): ("zero-to-one", "reassert native Wayland", "stored logical focus", "focus-root", "Do not emit", "stacking"),
    ("focus_output_restoration", "zero_outputs"): ("zero active outputs", "restoration-pending", "cursor coordinates", "logical keyboard focus", "pointer focus clear", "Keyboard events continue", "cannot create"),
    ("focus_output_restoration", "restore_order"): ("complete window restoration", "before pointer-coordinate", "global placement order", "never alter restoration"),
    ("focus_output_restoration", "output_change"): ("repair global cursor", "independent", "does not activate", "keyboard aggregate", "input activity"),
    ("protocol_invariance", "common_policy"): ("identical", "native Wayland", "managed Xwayland", "aggregate", "interaction cancellation", "teardown"),
    ("protocol_invariance", "native"): ("wl_seat capability", "wl_keyboard/wl_pointer focus", "aggregate modifier/key/button", "not exposed as separate"),
    ("protocol_invariance", "xwayland"): ("seat0", "single X core", "never disconnects", "X input focus", "final releases", "stuck"),
    ("protocol_invariance", "boundary"): ("input-result", "not identical device-enumeration", "override-redirect", "pointer constraints", "input methods", "outside"),
    ("configuration_restart", "reload"): ("Successful or rejected", "preserves live device", "held", "capabilities", "Accepted binding changes", "original", "through release"),
    ("configuration_restart", "restart"): ("in-place", "does not detach", "reannounce", "renumber", "drain", "preserves", "cancellation", "once"),
    ("configuration_restart", "rejected"): ("changes no input", "sends no capability", "modifier", "motion", "enter/leave", "focus event"),
    ("configuration_restart", "session_boundary"): ("process-local", "not written", "f.saveyourself", "RestartPreviousState", "following session-lifecycle"),
    ("atomicity_and_resources", "removal"): ("irreversible", "no allocation", "stop accepting", "drain", "fallback", "exact capabilities", "detach", "exactly once", "order"),
    ("atomicity_and_resources", "batch_clear"): ("INPUT CLEAR", "deterministic batch", "without actions", "cancels pointer UI once", "zero capabilities", "logical focus/cursor", "ordinal or activity"),
    ("atomicity_and_resources", "bounded"): ("overflow-checked", "proportional", "fixed protocol-code limits", "no recursive retry", "unbounded allocation"),
    ("atomicity_and_resources", "churn"): ("Repeated", "leak no", "stale callback", "double release", "double free", "use after free"),
    ("atomicity_and_resources", "unknown_duplicate"): ("unique by object lifetime", "duplicate live name", "atomically", "unknown removal/injection", "new ordinal"),
    ("verification_interface", "initial"): ("TEST-KEYBOARD-0", "TEST-POINTER-0", "Legacy", "route", "fail without state change"),
    ("verification_interface", "device_record"): ("ordinal order", "exactly", "name,type,ordinal,active,pressed,modifiers", "sorted physical", "raw diagnostic", "depressed,latched,locked,group", "zero masks"),
    ("verification_interface", "seat_record"): ("seat_capabilities", "sorted subset array", "keyboard", "pointer", "logical aggregate seat_modifiers", "exactly {depressed,latched,locked,group}", "aggregate xkb adapter", "active_keyboard", "active_pointer", "live name or null", "cursor", "logical focus", "protocol", "restoration/output"),
    ("verification_interface", "errors"): ("Duplicate live ADD", "unknown REMOVE", "unknown-device injection", "malformed", "invalid transition", "exhausted ordinal", "prior STATE byte-for-byte", "diagnostic counters"),
}


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    expected_sections = {"classification", *TRANSLATION_SCHEMA}
    if set(translation) != expected_sections:
        errors.append("wayland_translation fields differ from schema")
    require_terms(
        translation.get("classification"),
        ("behaviorally-equivalent", "single-logical-seat", "X core", "Dynamic device identity", "stronger", "resource-safety"),
        "translation classification",
        errors,
    )
    for section_name, expected_fields in TRANSLATION_SCHEMA.items():
        section = require_object(translation.get(section_name), section_name, errors)
        if set(section) != expected_fields:
            errors.append(f"{section_name} fields differ from schema")
        for field in expected_fields - {"commands"}:
            require_terms(
                section.get(field),
                SEMANTIC_TERMS[(section_name, field)],
                f"{section_name}.{field}",
                errors,
            )
    verification = require_object(
        translation.get("verification_interface"), "verification_interface", errors
    )
    if verification.get("commands") != EXPECTED_COMMANDS:
        errors.append("verification command surface mismatch")


REQUIREMENT_TERMS = {
    "input.reference-core-boundary": ("one X core", "global interaction", "screen focus", "does not claim physical-device"),
    "input.single-seat-inventory": ("one seat0", "zero-to-N", "never-reused ordinals", "activity ranks", "deterministic active/fallback", "no implicit second"),
    "input.capability-admission": ("atomically", "if and only if", "positive", "first-add/last-remove", "rollback"),
    "input.keyboard-aggregate": ("per-keyboard", "same-code", "consume handled", "one aggregate xkb", "without stuck", "actions"),
    "input.pointer-continuity": ("per-pointer", "one global cursor", "exact coordinates", "non-last", "active fallback", "first-pointer", "crossing"),
    "input.interaction-cancellation": ("final required-button", "last-pointer", "abort move/resize", "close menus", "requeue", "hidden", "never interpret"),
    "input.focus-restoration-safety": ("logical focus/activation/stack", "device and output counts", "protocol focus", "output restoration", "pointer hit", "placement"),
    "input.protocol-invariance": ("native Wayland", "Xwayland", "wl_seat capability", "X core", "clients connected"),
    "input.reload-restart": ("inventory", "active devices", "ordinals", "held disposition", "capabilities", "in-place restart", "without drain"),
    "input.atomic-resource-safety": ("rollback exact", "allocation-free", "detach every", "one free", "ordinal/activity", "duplicate/unknown/churn"),
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
        errors.append("input slice requirement summary mismatch")
    else:
        text = " ".join(str(item) for item in required)
        for term in (
            "seat0",
            "zero-to-N",
            "capabilities",
            "aggregate same-code",
            "aggregate xkb",
            "shared cursor",
            "last-pointer",
            "output-independent",
            "native/Xwayland",
            "rollback",
            "test-control",
        ):
            if term not in text:
                errors.append(f"input slice requirements omit {term}")
    owned = scope.get("already_owned")
    if not isinstance(owned, list) or len(owned) != 3:
        errors.append("adjacent contract ownership mismatch")
    else:
        text = " ".join(str(item) for item in owned)
        for contract in (
            "output-topology-contract.json",
            "output-restoration-contract.json",
            "output-placement-contract.json",
            "warp-screen-contract.json",
        ):
            if contract not in text:
                errors.append(f"adjacent ownership omits {contract}")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred input scope mismatch")
    require_terms(
        scope.get("next_handoff"),
        ("immediately following Roadmap", "session-lifecycle", "rediscover physical", "rather than serialize", "single-seat focus/capability"),
        "next handoff",
        errors,
    )
    require_terms(
        scope.get("non_claim"),
        ("only live keyboard/pointer hotplug", "one logical seat", "does not complete multi-seat", "session lifecycle", "exit criteria"),
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
    if not isinstance(evidence, dict) or len(evidence) != 38:
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
        errors.append("input requirement coverage mismatch")
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
        if not isinstance(oracle, str) or len(oracle) < 90:
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
    mutate("upstream version", ("upstream", "version"), "1.0.13")
    first_member = next(iter(EXPECTED_SOURCE_MEMBERS))
    mutate("member hash", ("source_members", first_member), "0" * 64)
    mutate(
        "archive line",
        ("evidence", "events.button-pressed", "line"),
        114,
        inspect_archive=True,
    )
    mutate(
        "archive text",
        ("evidence", "startup.root-key-mask", "text"),
        "tampered",
        inspect_archive=True,
    )
    mutate(
        "current anchor",
        ("current_surface", "source_anchors", "runtime.seat-create", "text"),
        "server.seat = NULL;",
    )
    mutate(
        "classification",
        ("wayland_translation", "classification"),
        "Expose one seat per device.",
    )
    for section_name, field in SEMANTIC_TERMS:
        mutate(
            f"semantic {section_name}.{field}",
            ("wayland_translation", section_name, field),
            "Tampered policy.",
        )
    mutate(
        "commands",
        ("wayland_translation", "verification_interface", "commands"),
        ["INPUT ADD EVERYTHING"],
    )
    mutate("required summary", ("scope_boundaries", "this_slice_requires"), [])
    mutate("owned boundaries", ("scope_boundaries", "already_owned"), [])
    mutate("deferred boundaries", ("scope_boundaries", "explicitly_deferred"), [])
    mutate("next handoff", ("scope_boundaries", "next_handoff"), "Serialize keys.")
    mutate("non claim", ("scope_boundaries", "non_claim"), "Full input parity.")

    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement, False))
    changed_requirement = copy.deepcopy(contract)
    changed_requirement["requirements"][3]["rule"] = "OR raw device masks."
    mutations.append(("aggregate requirement", changed_requirement, False))
    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario, False))
    changed_scenario = copy.deepcopy(contract)
    changed_scenario["verification_scenarios"][9]["kind"] = "runtime"
    mutations.append(("scenario kind", changed_scenario, False))
    vague_oracle = copy.deepcopy(contract)
    vague_oracle["verification_scenarios"][18]["oracle"] = "It works."
    mutations.append(("scenario oracle", vague_oracle, False))
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
            "keyboard record",
            "struct keyboard {",
            "struct ignored_keyboard {",
        ),
        (
            "global cursor",
            "struct wlr_cursor *cursor;",
            "struct wlr_cursor *ignored_cursor;",
        ),
        (
            "Xwayland seat",
            "wlr_xwayland_set_seat(server->xwayland, server->seat);",
            "wlr_xwayland_set_seat(server->xwayland, NULL);",
        ),
        (
            "interaction abort",
            "static void finish_interactive(struct server *server, bool aborted) {",
            "static void ignored_interactive(struct server *server, bool aborted) {",
        ),
        (
            "restoration pending",
            "static void mark_toplevel_restoration_pending(struct toplevel *toplevel) {",
            "static void ignored_restoration_pending(struct toplevel *toplevel) {",
        ),
        (
            "zero output pointer clear",
            "server->pointer_toplevel = NULL;\n"
            "\t\tserver->pointer_context = 0;\n"
            "\t\tif (server->seat != NULL) wlr_seat_pointer_clear_focus(server->seat);",
            "server->pointer_toplevel = NULL;\n"
            "\t\tserver->pointer_context = 0;\n"
            "\t\tif (false) wlr_seat_pointer_clear_focus(server->seat);",
        ),
        (
            "keyboard key",
            "static void keyboard_key(struct wl_listener *listener, void *data) {",
            "static void ignored_keyboard_key(struct wl_listener *listener, void *data) {",
        ),
        (
            "keyboard destroy",
            "static void keyboard_destroy(struct wl_listener *listener, void *data) {",
            "static void ignored_keyboard_destroy(struct wl_listener *listener, void *data) {",
        ),
        (
            "new input",
            "static void new_input(struct wl_listener *listener, void *data) {",
            "static void ignored_new_input(struct wl_listener *listener, void *data) {",
        ),
        (
            "seat create",
            "server.seat = wlr_seat_create(server.display, \"seat0\");",
            "server.seat = wlr_seat_create(server.display, \"seat1\");",
        ),
        (
            "backend listener",
            "wl_signal_add(&server.backend->events.new_input, &server.new_input);",
            "wl_signal_add(&server.backend->events.destroy, &server.new_input);",
        ),
    ]
    source = baseline_sources["src/wtwm.c"]
    for name, old, new in source_mutations:
        if source.count(old) != 1:
            failures.append(f"source tamper setup mismatch: {name}")
            continue
        changed = dict(baseline_sources)
        changed["src/wtwm.c"] = source.replace(old, new, 1)
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
        print(f"input-hotplug contract error: {error}", file=sys.stderr)
        return 1
    errors = validate_contract(contract, inventory, root)
    if arguments.self_test and not errors:
        errors.extend(run_tamper_tests(contract, inventory, root))
    if errors:
        for error in errors:
            print(f"input-hotplug contract error: {error}", file=sys.stderr)
        return 1
    suffix = " and tamper suite" if arguments.self_test else ""
    print(
        "input-hotplug contract valid: "
        f"{len(contract['evidence'])} archive anchors, "
        f"{len(contract['requirements'])} requirements, "
        f"{len(contract['verification_scenarios'])} scenarios{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
