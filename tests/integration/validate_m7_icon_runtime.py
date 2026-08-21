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
        "reserve_icon_manager_toplevel",
        "update_bufferless_xwayland_identity",
        "xwayland_map_requested",
        "start_iconified_match",
        "XCB_MAP_REQUEST",
        "XCB_ATOM_WM_CLASS",
        "initialize_icon_managers",
        "sync_icon_manager_toplevel",
        "wtwm_render_icon_manager_marker",
        "view->width + 2",
        "create_icon_manager_outline(row, 2",
        "(row_height - 11) / 2",
        "int text_x = 22",
        "node->node, text_x, 4",
        "move_icon_manager_selection",
        "WTWM_CONTEXT_ICONMGR",
        'test_trace_toplevel_event(toplevel, "animation", "icon")',
    ),
    "src/text.c": (
        "wtwm_render_argb_icon",
        "alpha << 24",
        "wtwm_render_icon_manager_marker",
        "static const unsigned char rows[11][2]",
        "{0xff, 0x07}, {0x01, 0x04}, {0x0d, 0x05}, {0x9d, 0x05}",
        "{0x85, 0x05}, {0x01, 0x04}, {0xff, 0x07}",
    ),
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
        "ppm_structure",
        'structure["structured"] < 1',
    ),
    "tests/integration/run_m7_lifecycle_churn.py": (
        "INITIAL_ASSOCIATION_TIMEOUT_SECONDS = 360",
        "INITIAL_ASSOCIATION_STALL_SECONDS = 60",
        "initial Xwayland association stalled",
        "CLEANUP_TIMEOUT_SECONDS = 120",
        "CLEANUP_STALL_SECONDS = 30",
        "Xwayland stress cleanup stalled",
        'client_command(client, "QUIT", "OK QUIT")',
        'result["result"] = "passed"',
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
        marker_tampered = dict(files)
        marker_tampered["src/text.c"] = marker_tampered["src/text.c"].replace(
            "{0xff, 0x07}, {0x01, 0x04}",
            "{0x00, 0x00}, {0x01, 0x04}",
            1,
        )
        if not validate(marker_tampered):
            errors.append("siconify bitmap tamper was accepted")
    if errors:
        for error in errors:
            print(f"m7 icon runtime error: {error}")
        return 1
    print("Milestone 7 icon runtime contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
