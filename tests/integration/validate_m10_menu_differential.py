#!/usr/bin/env python3
"""Keep the live Milestone 10 menu differential fail-closed and wired."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tarfile


REQUIRED = {
    "tests/integration/run_m10_menu_differential.py": (
        'PHASES = ("normal", "title", "highlight", "pull-right", "child")',
        '"name": "cert-root"',
        '"name": "cert-child"',
        '"parent": "cert-root"',
        '"depth": 2',
        '"selected": 3',
        '"pull_right": True',
        '"submenu_open": True',
        '"break PopUpMenu\\n"',
        '"break PaintEntry\\n"',
        '"WTWM_MENU_POP',
        '"WTWM_MENU_PAINT',
        'capture_reference_stable',
        'capture_wtwm_stable',
        '"mismatch_pixels": mismatch',
        '"exact": mismatch == 0',
        '"unexplained_pixel_differences": 0',
        'compare_states(reference["states"], wtwm["states"])',
        'right["pull-right"]["pull_right"] = False',
        'value["exposure"] is False',
        'require_reference_pointer(',
        'captures["title"] != captures["normal"]',
    ),
    "tests/integration/m10_menu_differential.twmrc": (
        'Button3 = : root : f.menu "cert-root"',
        'Menu "cert-root"',
        'Menu "cert-child"',
        '"Menu states" f.title',
        '"Pull right" f.menu "cert-child"',
        'NoMenuShadows',
        'MenuFont "fixed"',
    ),
    "include/wtwm/visual.h": ("wtwm_menu_popup_origin",),
    "src/visual.c": (
        "bool wtwm_menu_popup_origin",
        "origin_x -= layout->content.width / 2;",
        "origin_y -= layout->row_height / 2;",
    ),
    "tests/visual_test.c": (
        "wtwm_menu_popup_origin(&layout, false, 130, 90, &x, &y)",
        "assert(x == 85);",
        "assert(y == 82);",
    ),
    "src/wtwm.c": (
        "wtwm_menu_popup_origin(&layout, submenu, anchor_x, anchor_y",
        "server->menu.x + content_width / 2",
        "server->menu.y + selected * server->menu.row_height",
        "parent->selected = -1;",
        r'\"parent\":',
        r'\"pull_right\":%s,\"submenu_open\":%s',
    ),
    ".github/workflows/build.yml": (
        "Compare live menu state and rendered pixels with reference twm",
        "python3 -B tests/integration/run_m10_menu_differential.py",
        "--reference-twm /tmp/reference-build/twm",
        "--input-driver /tmp/m4-trace-input",
        "--observer /tmp/m7-icon-observer",
        "m10-menu-differential-evidence",
        "Upload Milestone 10 live menu differential",
    ),
    "meson.build": (
        "Milestone 10 live menu differential contract",
        "tests/integration/validate_m10_menu_differential.py",
        "Milestone 10 live menu differential model",
        "tests/integration/run_m10_menu_differential.py",
        "--self-test",
    ),
    "README.md": (
        "- [x] **Agent:** Add a live reference/`wtwm` menu differential",
    ),
    "tests/integration/README.md": (
        "run_m10_menu_differential.py",
        "Normal, title, highlighted, pull-right, and child-submenu phases",
        "with no tolerance or",
        "mask.",
    ),
    "docs/COMPATIBILITY.md": (
        "a live five-phase menu differential compares name, parent, depth",
        "records nine as live reference differentials",
    ),
    "tests/certification/validate_m10_differential_contract.py": (
        '"menu-state": "live-reference-differential"',
        "live menu differential coverage underclaim was accepted",
    ),
}

FORBIDDEN = {
    "tests/integration/run_m10_menu_differential.py": (
        "pixel_tolerance", "ignored_pixels", "allowed_difference",
    ),
}

REFERENCE_SNIPPETS = (
    "ActiveMenu = menu;",
    "MenuDepth++;",
    "x -= (menu->width / 2);",
    "y -= (Scr->EntryHeight / 2);",
    "ActiveItem = mi;",
    "ActiveItem->func == F_MENU",
    "PopUpMenu(ActiveItem->sub,",
)


def validate_contract(text: str) -> list[str]:
    errors: list[str] = []
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return [f"differential contract is invalid JSON: {error}"]
    dimensions = value.get("dimensions", []) if isinstance(value, dict) else []
    matches = [
        item for item in dimensions
        if isinstance(item, dict) and item.get("id") == "menu-state"
    ]
    if len(matches) != 1:
        return ["differential contract must contain exactly one menu-state dimension"]
    menu = matches[0]
    if menu.get("coverage_status") != "live-reference-differential":
        errors.append("menu-state is not a live reference differential")
    mappings = menu.get("mappings", {})
    if "tests/integration/run_m10_menu_differential.py" not in mappings.get(
            "runners", []):
        errors.append("menu-state lacks the live runner mapping")
    if "tests/integration/validate_m10_menu_differential.py" not in mappings.get(
            "validators", []):
        errors.append("menu-state lacks the fail-closed validator mapping")
    return errors


def validate(files: dict[str, str], reference_source: str) -> list[str]:
    errors: list[str] = []
    for name, needles in REQUIRED.items():
        text = files.get(name, "")
        for needle in needles:
            if needle not in text:
                errors.append(f"{name} lacks {needle!r}")
    for name, needles in FORBIDDEN.items():
        text = files.get(name, "")
        for needle in needles:
            if needle in text:
                errors.append(f"{name} contains forbidden relaxation {needle!r}")
    for snippet in REFERENCE_SNIPPETS:
        if snippet not in reference_source:
            errors.append(f"frozen reference menus.c lacks {snippet!r}")
    if "PaintEntry(MenuRoot *mr, MenuItem *mi, int exposure)" not in reference_source:
        errors.append("frozen PaintEntry observation boundary drifted")
    errors.extend(validate_contract(files.get(
        "reference/certification/m10-differential-contract.json", ""
    )))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    root = arguments.source_root.resolve()
    names = set(REQUIRED) | set(FORBIDDEN) | {
        "reference/certification/m10-differential-contract.json",
    }
    files = {
        name: (root / name).read_text(encoding="utf-8") for name in names
    }
    archive = root / "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz"
    with tarfile.open(archive, "r:xz") as bundle:
        member = bundle.extractfile("twm-1.0.13.1/src/menus.c")
        if member is None:
            reference_source = ""
        else:
            reference_source = member.read().decode("utf-8")
    errors = validate(files, reference_source)
    if arguments.self_test_tamper and not errors:
        tampered = copy.deepcopy(files)
        tampered["tests/integration/run_m10_menu_differential.py"] = tampered[
            "tests/integration/run_m10_menu_differential.py"
        ].replace('"exact": mismatch == 0', '"exact": True', 1)
        if not validate(tampered, reference_source):
            errors.append("exact-pixel tamper was accepted")
        tampered = copy.deepcopy(files)
        contract = json.loads(tampered[
            "reference/certification/m10-differential-contract.json"
        ])
        contract["dimensions"][6]["coverage_status"] = (
            "partial-existing-infrastructure"
        )
        tampered["reference/certification/m10-differential-contract.json"] = (
            json.dumps(contract)
        )
        if not validate(tampered, reference_source):
            errors.append("menu coverage-status tamper was accepted")
    if errors:
        for error in errors:
            print(f"m10 menu differential error: {error}")
        return 1
    print("Milestone 10 live menu differential contract verified")
    if arguments.self_test_tamper:
        print("Milestone 10 live menu differential tamper checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
