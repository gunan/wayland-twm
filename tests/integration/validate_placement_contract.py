#!/usr/bin/env python3
"""Protect the portable placement model, runtime adapter, and live matrix."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def validate_text(placement: str, config: str, wtwm: str,
                  runner: str, client: str, meson: str) -> list[str]:
    errors: list[str] = []
    for marker in (
        "WTWM_USE_P_POSITION_OFF",
        "WTWM_USE_P_POSITION_ON",
        "WTWM_USE_P_POSITION_NON_ZERO",
        "INT16_MAX - (int64_t)screen_width",
        "state->next_x = 50;",
        "state->next_x + 30",
        "edge_adjust(state->next_x, screen_width, client_width)",
        "WTWM_PLACEMENT_BUTTON_CONFIRM",
        "wtwm_placement_prompt_position",
        "wtwm_placement_fill_size",
        "wtwm_placement_output_for_point",
        "wtwm_placement_output_for_outer",
        "uint128_square",
        "intersection_area",
        "if (*x < area->x) *x = area->x;",
        "if (*x > max_x) *x = max_x;",
    ):
        if marker not in placement:
            errors.append(f"portable placement model lacks {marker!r}")
    for marker in (
        'equal_ci(keyword, "UsePPosition")',
        "wtwm_parse_use_p_position(parser->token.text, &mode)",
        'equal_ci(keyword, "MaxWindowSize")',
        "wtwm_parse_max_window_size(parser->token.text, &width, &height)",
        "max_window_size_set = true",
    ):
        if marker not in config:
            errors.append(f"configuration placement adapter lacks {marker!r}")
    for marker in (
        '#include "wtwm/placement.h"',
        "xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_US_POSITION)",
        "xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_P_POSITION)",
        "toplevel->xwayland->parent != NULL",
        "wtwm_random_placement_next(&toplevel->server->random_placement",
        "clip_initial_toplevel_size(toplevel, &area, &width, &height);",
        "toplevel->placement_kind = WTWM_PLACEMENT_REMAPPED;",
        "toplevel->placement_kind = WTWM_PLACEMENT_INTERACTIVE;",
        "interaction->intent = INTERACTION_INITIAL_CONFIRM;",
        "INTERACTION_INITIAL_RESIZE",
        "INTERACTION_MENU_POSITION",
        "finish_initial_placement(server);",
        "wlr_xdg_surface_get_geometry(toplevel->xdg->base, &geometry);",
        'wtwm_placement_kind_name(toplevel->placement_kind)',
        "output_area_snapshot(server, &snapshot, &areas, &count)",
        "wtwm_placement_output_for_point(areas, count",
        "wtwm_placement_output_for_outer(areas, count",
        "output_local_pointer(toplevel->server, &area, &pointer_x, &pointer_y)",
        "xwayland_initial_area(toplevel, toplevel->width, toplevel->height",
        "position.frame_x,\n\t\tposition.frame_y, area",
        "candidate->placement_area",
        ".output_area = output_area",
        "leaf == &output->background->node",
        "struct hit_result hit = {0};",
        "server.pointer_context = 0;",
        "placement_waiting_output",
        "resume_output_waiting_toplevels(server);",
        "toplevel->placement_order < oldest->placement_order",
    ):
        if marker not in wtwm:
            errors.append(f"compositor placement adapter lacks {marker!r}")
    for stale in (
        "server_placement_area(",
        "wlr_output_layout_get_box(server->output_layout, NULL, &output_box)",
        "wlr_output_layout_get_box(server->output_layout, NULL, &output)",
    ):
        if stale in wtwm:
            errors.append(f"compositor placement adapter retains layout union {stale!r}")
    for marker in (
        'UsePPosition "off"',
        'UsePPosition "on"',
        'UsePPosition "non-zero"',
        '"placement-transient": (77, 88, 90, 60, "requested")',
        '"placement-random-3": (110, 110, 100, 80, "random")',
        '"placement-random-oversized": (0, 0, 200, 180, "random")',
        '"placement-default-max-width": (10, 12, 32127, 16, "requested")',
        '"placement-default-max-height": (10, 12, 16, 32287, "requested")',
        '"placement-confirm", (20, 25), "confirm"',
        '"placement-resize", (50, 55), "resize"',
        '"placement-fill", (40, 45), "fill"',
        'run_native_translation(compositor, native_client)',
        'client.stdin.write("UNMAP\\n")',
        'client.stdin.write("REMAP\\n")',
        'after["placement"] == "remapped"',
        'event["state"]["placement"]',
    ):
        if marker not in runner:
            errors.append(f"live placement matrix lacks {marker!r}")
    if re.search(
        r'wait_xwayland_unmapped\(\s*control,\s*'
        r'int\(before\["xid"\]\),\s*"placement-remap"\s*\)',
        runner,
    ) is None:
        errors.append("live placement matrix does not synchronize Xwayland unmap")
    for marker in (
        '"placement-default-max-width", 10, 12,',
        '32200, 16, HINT_US_POSITION',
        '"placement-default-max-height", 10, 12,',
        '16, 32300, HINT_US_POSITION',
        'strcmp(command, "UNMAP\\n") == 0',
        'strcmp(command, "REMAP\\n") == 0',
    ):
        if marker not in client:
            errors.append(f"safe X11 maximum fixture lacks {marker!r}")
    if "40000" in client:
        errors.append("X11 maximum fixture exceeds the renderer-safe bitmap limit")
    for marker in (
        "'src/placement.c'",
        "test('twm placement policy', placement_test)",
        "files('tests/integration/validate_placement_contract.py')",
        "'tests/integration/xwayland_placement_client.c'",
        "files('tests/integration/run_placement.py')",
        "'initial placement integration'",
    ):
        if marker not in meson:
            errors.append(f"Meson placement wiring lacks {marker!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    values = (
        (root / "src/placement.c").read_text(encoding="utf-8"),
        (root / "src/config.c").read_text(encoding="utf-8"),
        (root / "src/wtwm.c").read_text(encoding="utf-8"),
        (root / "tests/integration/run_placement.py").read_text(encoding="utf-8"),
        (root / "tests/integration/xwayland_placement_client.c").read_text(encoding="utf-8"),
        (root / "meson.build").read_text(encoding="utf-8"),
    )
    errors = validate_text(*values)
    if args.self_test_tamper:
        tampered = list(values)
        tampered[2] = tampered[2].replace(
            "xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_US_POSITION)",
            "false",
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing USPosition runtime policy")
        tampered = list(values)
        tampered[3] = tampered[3].replace(
            'after["placement"] == "remapped"', "false", 1
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing remap assertion")
        tampered = list(values)
        tampered[3] = tampered[3].replace(
            'control, int(before["xid"]), "placement-remap"',
            'control, 0, "placement-remap"',
            1,
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted unsynchronized Xwayland remap")
        tampered = list(values)
        tampered[2] = tampered[2].replace(
            "interaction->intent = INTERACTION_INITIAL_CONFIRM;",
            "interaction->intent = INTERACTION_DRAG;", 1
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing placement confirm intent")
        tampered = list(values)
        tampered[2] = tampered[2].replace(
            "wtwm_placement_output_for_outer(areas, count",
            "wtwm_placement_output_for_point(areas, count", 1,
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing outer-owner selection")
        tampered = list(values)
        tampered[2] = tampered[2].replace(
            "struct hit_result hit = {0};",
            "struct hit_result hit = {.context = WTWM_CONTEXT_ROOT};", 1,
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted synthetic root hit in layout gaps")
    if errors:
        for error in errors:
            print(error)
        return 1
    print("placement runtime contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
