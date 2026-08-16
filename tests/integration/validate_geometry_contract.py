#!/usr/bin/env python3
"""Protect the portable twm geometry model and compositor adapter wiring."""

from __future__ import annotations

import argparse
from pathlib import Path


def function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    opening = source.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return ""


def validate_text(wtwm: str, geometry: str, meson: str) -> list[str]:
    errors: list[str] = []
    required_wtwm = (
        '#include "wtwm/geometry.h"',
        "wtwm_frame_geometry(toplevel->width, toplevel->height,",
        "wtwm_initial_window_position(toplevel->xwayland->x,",
        "wtwm_configure_request_position(toplevel->tree->node.x,",
        "wlr_scene_node_set_enabled(&toplevel->frame->node, toplevel_has_frame(toplevel));",
        "geometry.content_x, geometry.content_y);",
        "constraints.flags |= WTWM_SIZE_HINT_ASPECT;",
        "toplevel->xdg->current.min_width",
        '"\\\"outer_width\\\":%d,\\\"outer_height\\\":%d,"',
    )
    for marker in required_wtwm:
        if marker not in wtwm:
            errors.append(f"compositor geometry adapter lacks {marker!r}")

    configure = function_body(wtwm, "static void xwayland_request_configure(")
    interactive = function_body(wtwm, "static void set_toplevel_box(")
    hint_sync = function_body(wtwm, "static void xwayland_deferred_sync(")
    if not configure:
        errors.append("Xwayland ConfigureRequest adapter is missing")
    elif "constrain_toplevel_size(" in configure:
        errors.append("ordinary Xwayland ConfigureRequest incorrectly applies user-resize constraints")
    if "constrain_toplevel_size(toplevel, &width, &height);" not in interactive:
        errors.append("interactive resize does not apply the portable constraint model")
    if not hint_sync:
        errors.append("Xwayland hint synchronization is missing")
    elif "constrain_toplevel_size(" in hint_sync or "configure_xwayland_frame(" in hint_sync:
        errors.append("a WM_NORMAL_HINTS property change incorrectly resizes the client")

    required_geometry = (
        "height += (int64_t)2 * clamp_nonnegative(frame_padding);",
        "if ((height & 1) == 0) ++height;",
        "title_bar_height + border_width",
        "if (constrained_width < min_width)",
        "if (constrained_width > max_width)",
        "multiple_toward_zero((int64_t)constrained_width - base_width",
        "hints->min_aspect_x * constrained_height",
        "hints->max_aspect_x * constrained_height",
    )
    for marker in required_geometry:
        if marker not in geometry:
            errors.append(f"portable geometry model lacks {marker!r}")

    required_meson = (
        "'src/geometry.c'",
        "test('twm geometry and size constraints', geometry_test)",
        "config_dep, geometry_dep, interaction_dep, wlroots",
        "files('tests/integration/validate_geometry_contract.py')",
    )
    for marker in required_meson:
        if marker not in meson:
            errors.append(f"Meson geometry wiring lacks {marker!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    wtwm = (root / "src/wtwm.c").read_text(encoding="utf-8")
    geometry = (root / "src/geometry.c").read_text(encoding="utf-8")
    meson = (root / "meson.build").read_text(encoding="utf-8")
    errors = validate_text(wtwm, geometry, meson)
    if args.self_test_tamper:
        tampered = wtwm.replace(
            "constrain_toplevel_size(toplevel, &width, &height);", "", 1
        )
        if not validate_text(tampered, geometry, meson):
            errors.append("self-test failed to detect missing interactive constraints")
    if errors:
        for error in errors:
            print(error)
        return 1
    print("geometry runtime contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
