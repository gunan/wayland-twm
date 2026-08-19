#!/usr/bin/env python3
"""Validate the frozen twm output-aware placement/root translation contract."""

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
    "reference/lifecycle/twm-1.0.13.1/output-placement-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "165a32c778c9a9dba131cf2c4441f45c076d8d88f39920d2cd34148dcd90e12a"
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
    "twm-1.0.13.1/src/events.c": (
        "4fe7f9746d569abe64c7301a1b31197a299eede117d54456929b6e82726366e3"
    ),
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/resize.c": (
        "086966fc1ef0ba0cc7975623aaed52273b9b03f40f6a08e0a3d6f49698f25f67"
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
EXPECTED_REQUIREMENT_IDS = {
    "placement.reference-root",
    "placement.output-selection",
    "placement.xwayland-requested",
    "placement.native-and-prompt",
    "placement.global-random-state",
    "placement.root-menu-focus",
    "placement.spatial-actions",
    "placement.gap-zero-safety",
    "placement.scope-boundary",
}
EXPECTED_SCENARIOS = {
    "reference-global-random-cascade": "reference-state",
    "reference-requested-position-bypasses-clamp": "reference-requested",
    "reference-root-confined-prompt": "reference-root",
    "native-pointer-output": "runtime-native",
    "native-parent-output": "runtime-native",
    "xwayland-request-inside": "runtime-xwayland-requested",
    "xwayland-request-gap": "runtime-xwayland-requested",
    "xwayland-request-outside": "runtime-xwayland-requested",
    "xwayland-transient-parent": "runtime-xwayland-requested",
    "xwayland-prompt-pointer-output": "runtime-xwayland-interactive",
    "global-random-across-outputs": "runtime-state",
    "output-local-random-edge-reset": "runtime-state",
    "menu-output-clamp": "runtime-root",
    "root-gap-no-binding": "runtime-gap",
    "background-gap-unpainted": "runtime-gap",
    "move-pinned-output": "runtime-move",
    "force-move-cross-output": "runtime-move",
    "zoom-owner-output": "runtime-zoom",
    "interactive-fill-output": "runtime-placement",
    "selected-output-max-window-default": "runtime-placement",
    "zero-output-deferred": "runtime-zero-output",
    "zero-output-state-stable": "runtime-zero-output",
    "override-redirect-unmanaged": "runtime-xwayland-boundary",
    "icon-manager-boundary": "contract-scope",
    "deferred-topology-boundary": "contract-scope",
}
EXPECTED_DEFERRED = [
    "f.warptoscreen next/prev/back history and topology-sensitive history repair",
    "output addition/removal/scale/mode transaction mechanics and operation repair during those changes",
    "safe window restoration or relocation after an output disappears",
    "persistent session-state reassociation across changed output topology",
    "input hotplug and multiple keyboards, pointers, seats, or independent seat focus",
    "session startup, logout, failure recovery, and persistent state-file lifecycle",
    "persistent physical-output identity across sessions when backend identity strings collide",
]
SOURCE_PATHS = (
    "include/wtwm/placement.h",
    "src/placement.c",
    "src/wtwm.c",
)


def load_json(path: Path) -> Any:
    """Load JSON and reject duplicate keys."""

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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
            errors.append(f"{label}[{index}] has no nonempty id")
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
                    errors.append(f"{evidence_id} source anchor fields differ")
                    continue
                member = anchor.get("member")
                line = anchor.get("line")
                text = anchor.get("text")
                if member not in member_lines:
                    errors.append(f"{evidence_id} cites unknown member")
                    continue
                if not isinstance(line, int) or line < 1 or line > len(
                    member_lines[member]
                ):
                    errors.append(f"{evidence_id} line is out of range")
                    continue
                if member_lines[member][line - 1] != text:
                    errors.append(f"{evidence_id} exact source text mismatch")
    except (OSError, tarfile.TarError, UnicodeDecodeError) as exc:
        errors.append(f"unable to inspect upstream archive: {exc}")


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    if not isinstance(inventory, dict):
        errors.append("inventory must be an object")
        return
    if inventory.get("schema_version") != 1:
        errors.append("inventory schema_version mismatch")
    if inventory.get("upstream") != {
        key: EXPECTED_UPSTREAM[key]
        for key in ("name", "version", "archive", "sha256")
    }:
        errors.append("inventory does not pin the same upstream release")


def load_sources(root: Path) -> dict[str, str]:
    return {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in SOURCE_PATHS
    }


def validate_current_surface(
    value: Any, sources: dict[str, str], errors: list[str]
) -> None:
    surface = require_object(value, "current_surface", errors)
    if set(surface) != {"source_anchors", "observed"}:
        errors.append("current_surface fields differ from schema")
        return
    anchors = surface.get("source_anchors")
    if not isinstance(anchors, dict) or len(anchors) != 16:
        errors.append("current source-anchor coverage mismatch")
        return
    for anchor_id, anchor in anchors.items():
        if not isinstance(anchor, dict) or set(anchor) != {"path", "text"}:
            errors.append(f"{anchor_id} current anchor fields differ")
            continue
        path = anchor.get("path")
        text = anchor.get("text")
        if path not in sources:
            errors.append(f"{anchor_id} cites an uninspected source")
        elif not isinstance(text, str) or text not in sources[path]:
            errors.append(f"{anchor_id} current source text missing")
    observed = surface.get("observed")
    if not isinstance(observed, list) or len(observed) != 5 or not all(
        isinstance(item, str) and item for item in observed
    ):
        errors.append("current observed-surface record mismatch")

    placement = sources.get("src/placement.c", "")
    required_placement = (
        "state->next_x = 50;",
        "state->next_y = 50;",
        "state->next_x = saturate_int((int64_t)state->next_x + 30);",
        "*x = pointer_x;",
        "*y = pointer_y;",
        "if (*x < area->x) *x = area->x;",
        "if (*x > max_x) *x = max_x;",
        "bool wtwm_placement_output_for_point(",
        "bool wtwm_placement_output_for_outer(",
        "uint128_square",
        "intersection_area",
    )
    for snippet in required_placement:
        if snippet not in placement:
            errors.append(f"portable placement behavior missing: {snippet}")
    pointer_start = placement.find("void wtwm_pointer_placement(")
    pointer_end = placement.find("\n}", pointer_start)
    pointer_body = placement[pointer_start:pointer_end]
    if "*x = pointer_x;" not in pointer_body or "*y = pointer_y;" not in pointer_body:
        errors.append("pointer placement must preserve the selected pointer origin")
    runtime = sources.get("src/wtwm.c", "")
    required_runtime = (
        "wlr_output_layout_get_box(server->output_layout, wlr_output, &box);",
        "output->background = wlr_scene_rect_create(&server->scene->tree,",
        "struct hit_result hit = {0};",
        "server.pointer_context = 0;",
        "leaf == &output->background->node",
        "static bool place_native_toplevel(struct toplevel *toplevel) {",
        "static bool initial_xwayland_frame(struct toplevel *toplevel,",
        "wtwm_placement_output_for_point(areas, count",
        "wtwm_placement_output_for_outer(areas, count",
        "placement_waiting_output",
        "toplevel->placement_order < oldest->placement_order",
    )
    for snippet in required_runtime:
        if snippet not in runtime:
            errors.append(f"current compositor surface missing: {snippet}")
    for stale in (
        "server_placement_area(",
        "wlr_output_layout_get_box(server->output_layout, NULL, &output_box)",
        "wlr_output_layout_get_box(server->output_layout, NULL, &output)",
    ):
        if stale in runtime:
            errors.append(f"current compositor retains layout-union adapter: {stale}")


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {
        "screen_root_namespace",
        "initial_placement",
        "placement_state",
        "root_spatial_actions",
    }:
        errors.append("reference behavior sections differ")
        return
    root = require_object(
        behavior.get("screen_root_namespace"), "screen_root_namespace", errors
    )
    if not all(
        term in str(root.get("rule"))
        for term in ("distinct RootWindow", "ScreenInfo", "event", "width", "height")
    ):
        errors.append("reference per-screen root namespace mismatch")
    if not all(
        term in str(root.get("spatial_effect"))
        for term in ("Placement", "menus", "moves", "fills", "zooms", "between")
    ):
        errors.append("reference per-root spatial boundary mismatch")

    initial = require_object(
        behavior.get("initial_placement"), "initial_placement", errors
    )
    requested = str(initial.get("requested_rule"))
    if not all(
        term in requested
        for term in ("Transient", "USPosition", "PPosition", "not passed through DontMoveOff")
    ):
        errors.append("reference requested-position rule mismatch")
    prompt = str(initial.get("prompt_rule"))
    if not all(
        term in prompt
        for term in ("selected X root", "upper-left", "Button2", "Button3")
    ):
        errors.append("reference interactive placement rule mismatch")
    random = str(initial.get("random_rule"))
    if not all(
        term in random
        for term in ("PlaceX/PlaceY", "current Scr", "advances", "30")
    ):
        errors.append("reference RandomPlacement rule mismatch")

    state = require_object(behavior.get("placement_state"), "placement_state", errors)
    random_scope = str(state.get("random_scope"))
    if not all(
        term in random_scope
        for term in (
            "file-scope static",
            "not ScreenInfo members",
            "shares the cascade",
            "current Scr dimensions",
        )
    ):
        errors.append("reference global random-state scope mismatch")
    pointer = str(state.get("pointer_state"))
    if not all(
        term in pointer
        for term in ("no PointerPlacement directive", "no per-screen", "diagnostic")
    ):
        errors.append("reference pointer-state non-claim mismatch")

    actions = require_object(
        behavior.get("root_spatial_actions"), "root_spatial_actions", errors
    )
    if "current Scr root" not in str(actions.get("menu")):
        errors.append("reference menu root mismatch")
    if not all(
        term in str(actions.get("dont_move_off"))
        for term in ("window and icon", "near-edge", "far-edge", "f.forcemove")
    ):
        errors.append("reference DontMoveOff rule mismatch")
    if "selected Scr dimensions" not in str(actions.get("fill")):
        errors.append("reference fill root mismatch")
    if not all(
        term in str(actions.get("zoom"))
        for term in ("selected window", "current Scr root", "saved pre-zoom")
    ):
        errors.append("reference zoom root mismatch")


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    if set(translation) != {
        "classification",
        "output_root_model",
        "output_selection",
        "client_paths",
        "placement_state",
        "root_spatial_actions",
    }:
        errors.append("Wayland translation sections differ")
        return
    if translation.get("classification") != (
        "behaviorally-equivalent per-output root-geometry translation with "
        "documented unified-layout output selection and preserved process-global "
        "random state"
    ):
        errors.append("translation classification mismatch")

    model = require_object(translation.get("output_root_model"), "output_root_model", errors)
    if not all(
        term in str(model.get("root_box"))
        for term in ("enabled", "logical layout box", "X-root-equivalent", "origin")
    ):
        errors.append("output root-box mapping mismatch")
    no_union = str(model.get("no_union"))
    if not all(
        term in no_union
        for term in ("never a root box", "Empty gaps", "outside", "DontMoveOff")
    ):
        errors.append("layout-union rejection mismatch")
    if not all(
        term in str(model.get("root_bindings"))
        for term in ("same global configuration", "actual output", "gap", "no root")
    ):
        errors.append("root binding target mismatch")
    if not all(
        term in str(model.get("background"))
        for term in ("Every enabled output", "exactly covering", "no synthetic")
    ):
        errors.append("per-output background rule mismatch")
    if not all(
        term in str(model.get("focus"))
        for term in ("one seat", "compositor-global", "clears", "independent")
    ):
        errors.append("global FocusRoot translation mismatch")

    selection = require_object(
        translation.get("output_selection"), "output_selection", errors
    )
    if not all(
        term in str(selection.get("point_containment"))
        for term in ("half-open", "enabled output", "canonical")
    ):
        errors.append("point containment selection mismatch")
    nearest = str(selection.get("nearest_fallback"))
    if not all(
        term in nearest
        for term in (
            "layout gap",
            "outside every output",
            "smallest squared Euclidean distance",
            "canonical",
            "never makes the gap",
        )
    ):
        errors.append("gap/outside nearest-output rule mismatch")
    owner = str(selection.get("window_owner"))
    if not all(
        term in owner
        for term in ("greatest positive intersection area", "canonical", "nearest", "center")
    ):
        errors.append("window owner selection mismatch")
    pinning = str(selection.get("operation_pinning"))
    if not all(
        term in pinning
        for term in ("capture", "whole operation", "never changes", "recomputes")
    ):
        errors.append("operation-long output pinning mismatch")
    zero = str(selection.get("zero_outputs"))
    if not all(
        term in zero
        for term in ("no output", "deferred", "unexposed", "no synthetic 1x1", "neither random")
    ):
        errors.append("zero-output placement safety mismatch")

    paths = require_object(translation.get("client_paths"), "client_paths", errors)
    if not all(
        term in str(paths.get("native_top_level"))
        for term in ("no client-supplied global position", "pointer", "parent", "selected output")
    ):
        errors.append("native output-selection rule mismatch")
    if not all(
        term in str(paths.get("xwayland_prompt_or_random"))
        for term in ("ask the user", "pointer output", "pins", "process-global")
    ):
        errors.append("Xwayland prompt/random selection mismatch")
    accepted = str(paths.get("xwayland_accepted_request"))
    if not all(
        term in accepted
        for term in (
            "gravity-adjusted outer-frame origin",
            "inside an output",
            "layout gap",
            "outside all outputs",
            "nearest-output",
            "Preserve",
            "does not clamp",
            "DontMoveOff does not apply",
        )
    ):
        errors.append("accepted Xwayland request selection mismatch")
    transient = str(paths.get("xwayland_transient"))
    if not all(
        term in transient
        for term in ("managed parent", "parent's current owner", "preserving", "Without")
    ):
        errors.append("Xwayland transient selection mismatch")
    if not all(
        term in str(paths.get("xwayland_override_redirect"))
        for term in ("unmanaged", "global coordinates", "do not consume")
    ):
        errors.append("override-redirect scope mismatch")

    state = require_object(translation.get("placement_state"), "placement_state", errors)
    global_random = str(state.get("random_scope"))
    if not all(
        term in global_random
        for term in (
            "one compositor-global",
            "file-scope PlaceX/PlaceY",
            "Do not reset or isolate",
            "output-local coordinates",
            "global origin",
        )
    ):
        errors.append("global RandomPlacement translation mismatch")
    pointer = str(state.get("pointer_scope"))
    if not all(
        term in pointer
        for term in ("no per-output reference sequence", "remains global", "does not alter coordinates")
    ):
        errors.append("pointer placement state translation mismatch")
    if not all(
        term in str(state.get("deliberate_non_divergence"))
        for term in ("Per-output random cursors", "contradict", "rejects")
    ):
        errors.append("per-output random-state rejection missing")

    actions = require_object(
        translation.get("root_spatial_actions"), "root_spatial_actions", errors
    )
    if not all(
        term in str(actions.get("menu"))
        for term in ("invocation output", "owner output", "submenu", "pinned")
    ):
        errors.append("output-pinned menu rule mismatch")
    dont_move = str(actions.get("dont_move_off"))
    if not all(
        term in dont_move
        for term in (
            "window or icon owner",
            "pin",
            "near-edge",
            "far-edge",
            "f.forcemove",
            "never switches",
        )
    ):
        errors.append("output-pinned DontMoveOff mismatch")
    if not all(
        term in str(actions.get("interactive_initial"))
        for term in ("Button2", "Button3", "initially selected output", "right and bottom")
    ):
        errors.append("output-pinned interactive fill mismatch")
    if not all(
        term in str(actions.get("zoom"))
        for term in ("owner output", "global origin", "does not switch")
    ):
        errors.append("output-pinned zoom mismatch")
    if "selected output's logical width and height" not in str(
        actions.get("max_window_default")
    ):
        errors.append("selected-output maximum-size rule mismatch")
    if not all(
        term in str(actions.get("accepted_request_exception"))
        for term in ("do not alter", "accepted", "reference twm")
    ):
        errors.append("accepted-request clamp exception mismatch")


def validate_scope(value: Any, errors: list[str]) -> None:
    scope = require_object(value, "scope_boundaries", errors)
    if set(scope) != {
        "this_slice_requires",
        "icon_and_manager_boundary",
        "non_spatial_root_boundary",
        "explicitly_deferred",
        "non_claim",
    }:
        errors.append("scope boundary fields differ")
        return
    required = scope.get("this_slice_requires")
    if not isinstance(required, list) or len(required) != 5:
        errors.append("slice requirement summary mismatch")
    icon_boundary = str(scope.get("icon_and_manager_boundary"))
    if not all(
        term in icon_boundary
        for term in (
            "Milestone 7",
            "global Wayland output layout",
            "does not duplicate",
            "DontMoveOff",
            "moved icon",
        )
    ):
        errors.append("icon/icon-manager scope boundary mismatch")
    non_spatial = str(scope.get("non_spatial_root_boundary"))
    if not all(
        term in non_spatial
        for term in ("not duplicated per output", "observable spatial/root-hit", "output-scoped")
    ):
        errors.append("non-spatial root-state boundary mismatch")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred Milestone 8 scope mismatch")
    if not all(
        term in str(scope.get("non_claim"))
        for term in ("do not complete", "topology", "restoration", "input", "session")
    ):
        errors.append("Roadmap non-claim missing")


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
        errors.append("upstream provenance differs from pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes differ from frozen set")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) < 45:
        errors.append("upstream source-anchor coverage mismatch")
        evidence = evidence if isinstance(evidence, dict) else {}
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
    loaded_sources = sources or load_sources(source_root)
    validate_current_surface(contract.get("current_surface"), loaded_sources, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)
    validate_scope(contract.get("scope_boundaries"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENT_IDS:
        errors.append("output-placement requirement coverage mismatch")
    required_terms = {
        "placement.reference-root": ("ScreenInfo", "root", "dimensions", "event"),
        "placement.output-selection": ("enabled output", "nearest", "intersection", "pinning"),
        "placement.xwayland-requested": ("gravity-adjusted", "gap", "outside", "preserving"),
        "placement.native-and-prompt": ("native", "Xwayland", "pointer", "parent", "pin"),
        "placement.global-random-state": ("process-global", "selected output", "not", "per-output"),
        "placement.root-menu-focus": ("root hits", "backgrounds", "menu", "global", "FocusRoot"),
        "placement.spatial-actions": ("pinned output", "fill", "zoom", "window/icon", "f.forcemove"),
        "placement.gap-zero-safety": ("gaps", "zero-output", "root geometry", "placement state"),
        "placement.scope-boundary": ("Milestone 7", "warp", "topology", "restoration", "session"),
    }
    for requirement_id, terms in required_terms.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        rule = record.get("rule")
        if not isinstance(rule, str) or not all(term in rule for term in terms):
            errors.append(f"{requirement_id} semantic rule mismatch")
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite upstream evidence")

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    if {key: record.get("kind") for key, record in scenarios.items()} != EXPECTED_SCENARIOS:
        errors.append("verification scenario ids or kinds mismatch")
    for scenario_id, record in scenarios.items():
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} oracle must be nonempty")
    return errors


def run_tamper_tests(
    contract: dict[str, Any], inventory: Any, source_root: Path
) -> list[str]:
    """Prove independent schema/source/semantic pins reject mutations."""

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
        "source pin", ("source_members", "twm-1.0.13.1/src/add_window.c"), "0" * 64
    )
    exact_anchor = copy.deepcopy(contract)
    exact_anchor["evidence"]["placement.seed-x"]["text"] += " tampered"
    mutations.append(("exact source anchor", exact_anchor, True))
    mutate(
        "reference root",
        ("reference_behavior", "screen_root_namespace", "rule"),
        "Use one root for all screens.",
    )
    mutate(
        "reference requested clamp",
        ("reference_behavior", "initial_placement", "requested_rule"),
        "Clamp every requested position.",
    )
    mutate(
        "reference random scope",
        ("reference_behavior", "placement_state", "random_scope"),
        "Each ScreenInfo owns PlaceX.",
    )
    mutate(
        "reference pointer state",
        ("reference_behavior", "placement_state", "pointer_state"),
        "PointerPlacement is a per-screen directive.",
    )
    mutate(
        "classification",
        ("wayland_translation", "classification"),
        "literal multi-root emulation",
    )
    mutate(
        "layout union",
        ("wayland_translation", "output_root_model", "no_union"),
        "Use the full layout bounding box as root.",
    )
    mutate(
        "root gap binding",
        ("wayland_translation", "output_root_model", "root_bindings"),
        "Dispatch root bindings in gaps.",
    )
    mutate(
        "per-output focus",
        ("wayland_translation", "output_root_model", "focus"),
        "Track independent keyboard focus per output.",
    )
    mutate(
        "nearest gap",
        ("wayland_translation", "output_selection", "nearest_fallback"),
        "Always choose output zero.",
    )
    mutate(
        "owner selection",
        ("wayland_translation", "output_selection", "window_owner"),
        "Use list order.",
    )
    mutate(
        "operation switching",
        ("wayland_translation", "output_selection", "operation_pinning"),
        "Switch bounds whenever the pointer crosses.",
    )
    mutate(
        "zero output",
        ("wayland_translation", "output_selection", "zero_outputs"),
        "Use a synthetic 1x1 root and advance state.",
    )
    mutate(
        "requested inside-gap-outside",
        ("wayland_translation", "client_paths", "xwayland_accepted_request"),
        "Clamp every request to output zero.",
    )
    mutate(
        "transient parent",
        ("wayland_translation", "client_paths", "xwayland_transient"),
        "Ignore the managed parent.",
    )
    mutate(
        "per-output random divergence",
        ("wayland_translation", "placement_state", "random_scope"),
        "Give every output an independent random cursor.",
    )
    mutate(
        "pointer coordinate state",
        ("wayland_translation", "placement_state", "pointer_scope"),
        "Per-output counters offset placement coordinates.",
    )
    mutate(
        "menu pinning",
        ("wayland_translation", "root_spatial_actions", "menu"),
        "Clamp menus to the layout union.",
    )
    mutate(
        "move switching",
        ("wayland_translation", "root_spatial_actions", "dont_move_off"),
        "Switch output while dragging.",
    )
    mutate(
        "zoom union",
        ("wayland_translation", "root_spatial_actions", "zoom"),
        "Zoom to the layout union.",
    )
    mutate(
        "accepted request clamp",
        ("wayland_translation", "root_spatial_actions", "accepted_request_exception"),
        "Clamp accepted requests with DontMoveOff.",
    )
    mutate(
        "icon manager scope",
        ("scope_boundaries", "icon_and_manager_boundary"),
        "Duplicate every icon manager per output.",
    )
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

    failures: list[str] = []
    baseline_sources = load_sources(source_root)
    for name, candidate, inspect_archive in mutations:
        errors = validate_contract(
            candidate,
            inventory,
            source_root,
            verify_canonical=False,
            verify_archive=inspect_archive,
            sources=baseline_sources,
        )
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")

    source_mutations = [
        (
            "random seed",
            "src/placement.c",
            "state->next_x = 50;",
            "state->next_x = 51;",
        ),
        (
            "random advance",
            "src/placement.c",
            "state->next_x = saturate_int((int64_t)state->next_x + 30);",
            "state->next_x = saturate_int((int64_t)state->next_x + 31);",
        ),
        (
            "pointer origin",
            "src/placement.c",
            "(void)index;\n\t*x = pointer_x;",
            "(void)index;\n\t*x = pointer_x + 1;",
        ),
        (
            "near-edge then far-edge clamp",
            "src/placement.c",
            "if (*x > max_x) *x = max_x;",
            "if (*x > max_x) *x = area->x;",
        ),
        (
            "per-output background box",
            "src/wtwm.c",
            "wlr_output_layout_get_box(server->output_layout, wlr_output, &box);",
            "wlr_output_layout_get_box(server->output_layout, NULL, &box);",
        ),
        (
            "root hit default",
            "src/wtwm.c",
            "struct hit_result hit = {0};",
            "struct hit_result hit = {.context = WTWM_CONTEXT_ROOT};",
        ),
        (
            "outer owner selection",
            "src/wtwm.c",
            "wtwm_placement_output_for_outer(areas, count",
            "wtwm_placement_output_for_point(areas, count",
        ),
        (
            "zero-output ordering",
            "src/wtwm.c",
            "toplevel->placement_order < oldest->placement_order",
            "false",
        ),
    ]
    for name, path, before, after in source_mutations:
        changed = copy.deepcopy(baseline_sources)
        if before not in changed[path]:
            failures.append(f"tamper self-test fixture missing: {name}")
            continue
        changed[path] = changed[path].replace(before, after, 1)
        errors: list[str] = []
        validate_current_surface(contract["current_surface"], changed, errors)
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")
    if len(mutations) + len(source_mutations) < 20:
        failures.append("tamper self-test has fewer than 20 independent mutations")
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
        if args.self_test_tamper and not errors:
            errors.extend(run_tamper_tests(contract, inventory, source_root))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"output placement contract: {error}", file=sys.stderr)
        return 1
    if args.self_test_tamper:
        print("output placement contract tamper self-test passed")
    else:
        print("output placement contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
