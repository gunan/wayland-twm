#!/usr/bin/env python3
"""Keep the Milestone 7 portable models and compositor wiring connected."""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED = {
    "src/wtwm.c": (
        "wtwm_icon_layout_region_from_config",
        "wtwm_icon_layout_allocate",
        "should_iconify_by_unmapping",
        "wtwm_render_argb_icon",
        "read_xwayland_wm_hints_icon",
        "manage_bufferless_start_iconified",
        "start_iconified_match",
        "XCB_ATOM_WM_CLASS",
        "initialize_icon_managers",
        "sync_icon_manager_toplevel",
        "move_icon_manager_selection",
        "WTWM_CONTEXT_ICONMGR",
        'test_trace_toplevel_event(toplevel, "animation", "icon")',
    ),
    "src/text.c": ("wtwm_render_argb_icon", "alpha << 24"),
    "src/icon_layout.c": ("wtwm_icon_layout_allocate", "split_entry"),
    "src/icon_manager.c": (
        "wtwm_icon_manager_entry_update",
        "wtwm_icon_manager_move",
        "wtwm_icon_manager_next",
        "wtwm_icon_manager_set_case_sensitive",
    ),
    "tests/integration/run_m7_icons.py": (
        "IconifyByUnmapping",
        "region_allocated",
        "next icon manager",
        "screenshot",
    ),
    "reference/icons/twm-1.0.13.1/icon-contract.json": (
        '"test_scenarios"', '"evidence"', '"sha256"',
    ),
}

FORBIDDEN = {
    "src/wtwm.c": (
        "icon-manager action is inactive until Milestone 7",
        "f.warptoiconmgr is inactive until an icon manager exists",
    ),
}


def validate(files: dict[str, str]) -> list[str]:
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
                errors.append(f"{name} retains inactive path {needle!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    root = arguments.source_root.resolve()
    files = {
        name: (root / name).read_text(encoding="utf-8")
        for name in set(REQUIRED) | set(FORBIDDEN)
    }
    errors = validate(files)
    if arguments.self_test_tamper:
        tampered = dict(files)
        tampered["src/wtwm.c"] = tampered["src/wtwm.c"].replace(
            "wtwm_icon_layout_allocate", "removed_allocator"
        )
        if not validate(tampered):
            errors.append("self-test tamper was accepted")
    if errors:
        for error in errors:
            print(f"m7 icon runtime error: {error}")
        return 1
    print("Milestone 7 icon runtime contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
