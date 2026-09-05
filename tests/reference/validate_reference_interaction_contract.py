#!/usr/bin/env python3
"""Validate source-derived twm 1.0.13.1 interaction contracts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("reference/interactions/twm-1.0.13.1/source-contract.json")
ARCHIVE_HASH = "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5"
EXPECTED_GROUPS = [
    "move-threshold",
    "constrained-move",
    "move-bounds",
    "move-functions",
    "move-rendering",
    "resize-origin",
    "resize-rendering",
    "focus-context",
    "focus-policy",
    "stacking",
    "placement",
]
EXPECTED_CASE_IDS = [
    "move-delta-below-both",
    "move-delta-equality-starts",
    "move-delta-zero-starts",
    "constrained-time-zero-disabled",
    "constrained-strictly-inside-window",
    "constrained-equality-is-too-late",
    "constrained-middle-third-no-axis",
    "constrained-horizontal-grid-exit",
    "constrained-both-exits-vertical-wins",
    "dont-move-off-left-top",
    "dont-move-off-right-bottom",
    "dont-move-off-oversize-prefers-far-edge",
    "force-move-bypasses-bounds",
    "delta-stop-before-threshold",
    "delta-stop-after-threshold",
    "outline-move-preview",
    "opaque-move-preview",
    "resize-is-always-outline",
    "resize-outline-titled-nine-lines",
    "resize-outline-titleless-eight-lines",
    "resize-outline-tiny-thirds-collapse",
    "abort-outline-move-keeps-original-geometry",
    "abort-opaque-move-restores-original-geometry",
    "abort-resize-keeps-original-geometry",
    "auto-relative-top-left",
    "auto-relative-bottom-right",
    "auto-relative-center-waits",
    "auto-relative-titlebar-disabled",
    "event-context-map",
    "pointer-root-default",
    "frame-enter-title-focus",
    "frame-enter-no-title-focus",
    "frame-enter-take-focus-protocol",
    "client-enter-only-installs-colormap",
    "icon-enter-does-not-activate-client",
    "icon-manager-enter-activates-client",
    "frame-leave-pointer-root-clears-focus",
    "frame-leave-no-title-focus-clears-model-only",
    "frame-leave-click-focus-is-ignored",
    "click-focus-locks",
    "click-focus-toggle-restores-sloppy",
    "focus-on-icon-is-no-op",
    "unfocus-restores-pointer-root",
    "raise-frame",
    "lower-icon",
    "raise-lower-opposite",
    "raise-lower-suppressed-after-move",
    "circle-up-delegates-to-x",
    "circle-down-delegates-to-x",
    "us-position-always-honored",
    "p-position-off-prompts",
    "p-position-on-honored",
    "p-position-nonzero-origin-prompts",
    "p-position-nonzero-honored",
    "transient-position-always-honored",
    "random-placement-sequence",
    "random-placement-edge-reset",
    "max-window-initial-clip",
    "max-window-default-derived-from-screen",
    "interactive-placement-pointer-is-upper-left",
    "interactive-placement-dont-move-off",
    "interactive-placement-button1-confirms",
    "interactive-placement-button2-resizes",
    "interactive-placement-button3-fills",
    "window-menu-move-commits-on-press",
    "ordinary-move-second-press-aborts",
]


def load_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


def c_div(numerator: int, denominator: int) -> int:
    return int(numerator / denominator)


def evaluate(operation: str, values: dict[str, Any]) -> dict[str, Any]:
    if operation == "move-threshold":
        starts = not (
            abs(values["dx"]) < values["delta"]
            and abs(values["dy"]) < values["delta"]
        )
        return {"movement_starts": starts}

    if operation == "constrained-entry":
        configured = values["configured_ms"]
        return {"constrained": configured != 0 and values["elapsed_ms"] < configured}

    if operation == "constrained-axis":
        width_third = values["width"] // 3
        height_third = values["height"] // 3
        axis = "none"
        if values["pointer_x"] < width_third or values["pointer_x"] > 2 * width_third:
            axis = "horizontal"
        if values["pointer_y"] < height_third or values["pointer_y"] > 2 * height_third:
            axis = "vertical"
        return {"axis": axis}

    if operation == "move-clamp":
        x, y = values["position"]
        width, height = values["outer_size"]
        screen_width, screen_height = values["screen"]
        if not values["force"]:
            right = x + width
            bottom = y + height
            if x < 0:
                x = 0
            if right > screen_width:
                x = screen_width - width
            if y < 0:
                y = 0
            if bottom > screen_height:
                y = screen_height - height
        return {"position": [x, y]}

    if operation == "delta-stop":
        return {"continue_function": not values["window_moved"]}

    if operation == "render-path":
        if values["action"] == "move":
            if values["opaque_move"]:
                return {"during_motion": "window", "commit": "motion"}
            return {"during_motion": "outline", "commit": "release"}
        if values["action"] == "resize":
            return {
                "during_motion": "outline",
                "commit": "release",
                "opaque_resize_directive": False,
            }

    if operation == "outline-layout":
        width, height = values["outer_size"]
        border = values["border_width"]
        title = values["title_height"]
        left, right = 0, width - 1
        top, bottom = 0, height - 1
        inner_left, inner_right = left + border, right - border
        inner_top, inner_bottom = top + title + border, bottom - border
        width_third = c_div(inner_right - inner_left, 3)
        height_third = c_div(inner_bottom - inner_top, 3)
        segments = [
            [left, top, right, top],
            [left, bottom, right, bottom],
            [left, top, left, bottom],
            [right, top, right, bottom],
            [inner_left + width_third, inner_top,
             inner_left + width_third, inner_bottom],
            [inner_left + 2 * width_third, inner_top,
             inner_left + 2 * width_third, inner_bottom],
            [inner_left, inner_top + height_third,
             inner_right, inner_top + height_third],
            [inner_left, inner_top + 2 * height_third,
             inner_right, inner_top + 2 * height_third],
        ]
        if title != 0:
            segments.append([left, top + title, right, top + title])
        return {"segments": segments}

    if operation == "abort-path":
        return {"geometry": "original", "preview_cleared": True}

    if operation == "auto-resize-origin":
        if values["from_titlebar"]:
            return {"horizontal": "none", "vertical": "none"}
        width, height = values["size"]
        pointer_x, pointer_y = values["pointer"]
        horizontal_third = width // 3 if width >= 3 else 1
        vertical_third = height // 3 if height >= 3 else 1
        h = c_div(pointer_x, horizontal_third)
        v = c_div(pointer_y - values["title_height"], vertical_third)
        horizontal = "left" if h <= 0 else "right" if h >= 2 else "none"
        vertical = "top" if v <= 0 else "bottom" if v >= 2 else "none"
        return {"horizontal": horizontal, "vertical": vertical}

    if operation == "context-map":
        return {
            "root": "root",
            "title": "title",
            "client": "window",
            "icon": "icon",
            "frame": "frame",
            "icon_manager_entry": "iconmgr",
            "menu": "no-binding-context",
        }

    if operation == "focus-default":
        return {
            "focus_root": True,
            "title_focus": True,
            "x_focus_when_unfocused": "PointerRoot",
        }

    if operation == "focus-enter":
        active_surface = values["surface"] in {"frame", "iconmgr"}
        activate = values["focus_root"] and active_surface
        set_input = (
            activate
            and values["title_focus"]
            and values["input_hint"]
            and (values["has_title"] or values["surface"] == "iconmgr")
        )
        return {
            "activate": activate,
            "set_input_focus": set_input,
            "send_take_focus": activate and values["take_focus"],
        }

    if operation == "focus-leave":
        deactivate = (
            values["focus_root"]
            and not values["detail_inferior"]
            and (
                values["surface"] == "iconmgr"
                or (values["surface"] == "frame" and not values["queued_match"])
            )
        )
        return {
            "deactivate": deactivate,
            "set_pointer_root": deactivate
            and (values["title_focus"] or values["take_focus"]),
        }

    if operation == "focus-toggle":
        if values["iconified"]:
            return {"result": "unchanged", "focus_root": values["focus_root"]}
        if not values["focus_root"] and values["selected_is_current"]:
            return {"result": "pointer-root", "focus_root": True}
        return {"result": "click-focus", "focus_root": False}

    if operation == "unfocus":
        return {"focus_root": True, "focused_window": None, "x_focus": "PointerRoot"}

    if operation == "stack-action":
        action = values["action"]
        target = values["target"]
        if action == "raise":
            return {"x_request": f"XRaiseWindow({target})"}
        if action == "lower":
            return {"x_request": f"XLowerWindow({target})"}
        if action == "raiselower":
            if values["window_moved"]:
                return {"x_request": "none"}
            return {
                "x_request": "XConfigureWindow(Opposite)",
                "visible_result": "raise-if-occluded-otherwise-lower",
            }
        if action == "circleup":
            return {
                "x_request": "XCirculateSubwindowsUp(root)",
                "visible_result": "raise-bottommost-occluded",
            }
        if action == "circledown":
            return {
                "x_request": "XCirculateSubwindowsDown(root)",
                "visible_result": "lower-topmost-occluding",
            }

    if operation == "placement-prompt":
        x, y = values["position"]
        use_p = values["use_p_position"]
        honor_p = (
            values["p_position"]
            and use_p != "off"
            and (use_p == "on" or x != 0 or y != 0)
        )
        ask_user = not (values["transient"] or values["us_position"] or honor_p)
        return {"ask_user": ask_user}

    if operation == "random-placement":
        place_x = place_y = 50
        screen_width, screen_height = values["screen"]
        positions: list[list[int]] = []
        for width, height in values["sizes"]:
            if place_x + width > screen_width:
                place_x = max(0, min(50, screen_width - width))
            if place_y + height > screen_height:
                place_y = max(0, min(50, screen_height - height))
            positions.append([place_x, place_y])
            place_x += 30
            place_y += 30
        return {"positions": positions, "next": [place_x, place_y]}

    if operation == "max-window-clip":
        return {
            "size": [
                min(values["size"][0], values["maximum"][0]),
                min(values["size"][1], values["maximum"][1]),
            ]
        }

    if operation == "max-window-default":
        return {
            "maximum": [32767 - values["screen"][0], 32767 - values["screen"][1]]
        }

    if operation == "placement-position":
        x, y = values["pointer"]
        width, height = values["outer_size"]
        screen_width, screen_height = values["screen"]
        if values["dont_move_off"]:
            right = x + width
            bottom = y + height
            if x < 0:
                x = 0
            if right > screen_width:
                x = screen_width - width
            if y < 0:
                y = 0
            if bottom > screen_height:
                y = screen_height - height
        return {"frame_origin": [x, y]}

    if operation == "placement-button":
        button = values["button"]
        if button == 1:
            return {"phase": "confirm", "commit_event": "release"}
        if button == 2:
            return {"phase": "resize", "commit_event": "release"}
        if button == 3:
            return {"phase": "fill", "commit_event": "press"}
        return {"phase": "ignore", "commit_event": "none"}

    if operation == "move-logical-release":
        if values["menu_from_window"]:
            return {"commit_event": "press", "second_press_aborts": False}
        return {"commit_event": "release", "second_press_aborts": True}

    raise ValueError(f"unknown operation {operation!r}")


def validate_sources(
    sources: object, archive: tarfile.TarFile
) -> tuple[list[str], set[str]]:
    if not isinstance(sources, list):
        return ["sources must be an array"], set()
    errors: list[str] = []
    ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            errors.append("source citation is malformed")
            continue
        source_id = source["id"]
        if source_id in ids:
            errors.append(f"duplicate source citation id: {source_id}")
        ids.add(source_id)
        if "absent" in source:
            members = source.get("members")
            token = source.get("absent")
            if not isinstance(members, list) or not isinstance(token, str):
                errors.append(f"absence citation {source_id} is malformed")
                continue
            for member in members:
                try:
                    handle = archive.extractfile(member)
                    text = handle.read().decode("utf-8") if handle else ""
                except (KeyError, OSError, UnicodeError) as error:
                    errors.append(f"cannot read source citation {source_id}: {error}")
                    continue
                if token in text:
                    errors.append(f"absence citation {source_id} found forbidden token in {member}")
            continue

        member = source.get("member")
        lines = source.get("lines")
        anchors = source.get("anchors")
        if (
            not isinstance(member, str)
            or not isinstance(lines, list)
            or len(lines) != 2
            or not all(isinstance(value, int) and value > 0 for value in lines)
            or lines[0] > lines[1]
            or not isinstance(anchors, list)
            or not anchors
            or not all(isinstance(anchor, str) and anchor for anchor in anchors)
        ):
            errors.append(f"source citation {source_id} is malformed")
            continue
        try:
            handle = archive.extractfile(member)
            text = handle.read().decode("utf-8") if handle else ""
        except (KeyError, OSError, UnicodeError) as error:
            errors.append(f"cannot read source citation {source_id}: {error}")
            continue
        source_lines = text.splitlines()
        if lines[1] > len(source_lines):
            errors.append(f"source citation {source_id} line range is outside its member")
            continue
        excerpt = "\n".join(source_lines[lines[0] - 1 : lines[1]])
        for anchor in anchors:
            if anchor not in excerpt:
                errors.append(f"source citation {source_id} lacks anchor {anchor!r}")
    return errors, ids


def validate_contract(contract: object, source_root: Path) -> list[str]:
    if not isinstance(contract, dict):
        return ["interaction contract root must be an object"]
    errors: list[str] = []
    if contract.get("schema_version") != 1:
        errors.append("interaction contract schema_version must be 1")
    reference = contract.get("reference")
    expected_reference = {
        "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
        "archive_sha256": ARCHIVE_HASH,
        "name": "X.Org twm",
        "version": "1.0.13.1",
    }
    if reference != expected_reference:
        errors.append("interaction contract does not pin frozen twm 1.0.13.1")
        return errors
    archive_path = source_root / expected_reference["archive"]
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as error:
        errors.append(f"cannot read pinned twm archive: {error}")
        return errors
    if hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_HASH:
        errors.append("pinned twm archive hash has drifted")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("interaction evidence policy is missing")
    else:
        if evidence.get("kind") != "source-derived-contract":
            errors.append("interaction evidence must identify itself as source-derived")
        if evidence.get("committed_live_baseline") is not False:
            errors.append("interaction evidence must not claim an unrecorded live baseline")
        if evidence.get("live_capture_run") is not False:
            errors.append("interaction evidence must not claim an unrun live capture")
        if not isinstance(evidence.get("reason"), str) or not evidence["reason"]:
            errors.append("interaction evidence lacks its live-capture limitation")

    if contract.get("coverage_groups") != EXPECTED_GROUPS:
        errors.append("interaction coverage groups or order have drifted")

    try:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            source_errors, source_ids = validate_sources(contract.get("sources"), archive)
    except (tarfile.TarError, OSError) as error:
        errors.append(f"cannot open pinned twm archive: {error}")
        source_errors, source_ids = [], set()
    errors.extend(source_errors)

    raw_cases = contract.get("cases")
    if not isinstance(raw_cases, list):
        errors.append("interaction cases must be an array")
        return errors
    case_ids: list[object] = []
    covered_groups: set[object] = set()
    for case in raw_cases:
        if not isinstance(case, dict):
            errors.append("interaction case is malformed")
            continue
        case_id = case.get("id")
        case_ids.append(case_id)
        group = case.get("group")
        covered_groups.add(group)
        if group not in EXPECTED_GROUPS:
            errors.append(f"case {case_id} uses unknown coverage group {group!r}")
        citations = case.get("sources")
        if not isinstance(citations, list) or not citations:
            errors.append(f"case {case_id} lacks source citations")
        elif any(source_id not in source_ids for source_id in citations):
            errors.append(f"case {case_id} cites an unknown source")
        values = case.get("input")
        expected = case.get("expected")
        if not isinstance(values, dict) or not isinstance(expected, dict):
            errors.append(f"case {case_id} has malformed input or expected output")
            continue
        try:
            actual = evaluate(str(case.get("operation")), values)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            errors.append(f"case {case_id} cannot be evaluated: {error}")
            continue
        if actual != expected:
            errors.append(f"case {case_id} expectation differs: expected {expected}, derived {actual}")
    if case_ids != EXPECTED_CASE_IDS:
        errors.append("interaction case identities or order have drifted")
    if covered_groups != set(EXPECTED_GROUPS):
        errors.append("interaction cases do not cover every required group")

    try:
        meson = (source_root / "meson.build").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"cannot read Meson wiring: {error}")
    else:
        for marker in (
            "'reference interaction source contract'",
            "tests/reference/validate_reference_interaction_contract.py",
            "'--self-test-tamper'",
        ):
            if marker not in meson:
                errors.append(f"Meson interaction contract test lacks {marker!r}")
    return errors


def run_tamper_checks(contract: dict[str, Any], source_root: Path) -> list[str]:
    failures: list[str] = []
    checks: list[tuple[str, dict[str, Any]]] = []

    changed_expectation = copy.deepcopy(contract)
    changed_expectation["cases"][1]["expected"]["movement_starts"] = False
    checks.append(("case expectation", changed_expectation))

    changed_anchor = copy.deepcopy(contract)
    changed_anchor["sources"][0]["anchors"][0] = "invented upstream source line"
    checks.append(("source citation", changed_anchor))

    changed_live_claim = copy.deepcopy(contract)
    changed_live_claim["evidence"]["live_capture_run"] = True
    checks.append(("live evidence claim", changed_live_claim))

    for label, tampered in checks:
        if not validate_contract(tampered, source_root):
            failures.append(f"tamper self-test failed to reject changed {label}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        contract = load_json(source_root / CONTRACT_PATH)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"reference interaction contract validation failed: {error}")
        return 1
    errors = validate_contract(contract, source_root)
    if args.self_test_tamper and isinstance(contract, dict):
        errors.extend(run_tamper_checks(contract, source_root))
    if errors:
        print("reference interaction contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "reference interaction source contract valid: "
        f"{len(contract['cases'])} cases across {len(contract['coverage_groups'])} groups"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
