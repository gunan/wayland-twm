#!/usr/bin/env python3
"""Protect the portable placement model, runtime adapter, and live matrix."""

from __future__ import annotations

import argparse
from pathlib import Path


def validate_text(placement: str, config: str, wtwm: str,
                  runner: str, meson: str) -> list[str]:
    errors: list[str] = []
    for marker in (
        "WTWM_USE_P_POSITION_OFF",
        "WTWM_USE_P_POSITION_ON",
        "WTWM_USE_P_POSITION_NON_ZERO",
        "INT16_MAX - (int64_t)screen_width",
        "state->next_x = 50;",
        "state->next_x + 30",
        "edge_adjust(state->next_x, screen_width, client_width)",
        "pointer_x + (index % 12u) * 24",
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
        "wtwm_clamp_outer_position(area, geometry.outer_width",
        'wtwm_placement_kind_name(toplevel->placement_kind)',
    ):
        if marker not in wtwm:
            errors.append(f"compositor placement adapter lacks {marker!r}")
    for marker in (
        'UsePPosition "off"',
        'UsePPosition "on"',
        'UsePPosition "non-zero"',
        '"placement-transient": (77, 88, 90, 60, "requested")',
        '"placement-random-3": (110, 110, 100, 80, "random")',
        '"placement-random-oversized": (0, 0, 200, 180, "random")',
        '"placement-default-max": (10, 12, 32127, 32287, "requested")',
        'after["placement"] == "remapped"',
        'event["state"]["placement"]',
    ):
        if marker not in runner:
            errors.append(f"live placement matrix lacks {marker!r}")
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
        (root / "meson.build").read_text(encoding="utf-8"),
    )
    errors = validate_text(*values)
    if args.self_test_tamper:
        tampered = list(values)
        tampered[2] = tampered[2].replace(
            "xwayland_position_flag(toplevel, XCB_ICCCM_SIZE_HINT_US_POSITION)",
            "false", 1,
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing USPosition runtime policy")
        tampered = list(values)
        tampered[3] = tampered[3].replace(
            'after["placement"] == "remapped"', "false", 1
        )
        if not validate_text(*tampered):
            errors.append("self-test accepted missing remap assertion")
    if errors:
        for error in errors:
            print(error)
        return 1
    print("placement runtime contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
