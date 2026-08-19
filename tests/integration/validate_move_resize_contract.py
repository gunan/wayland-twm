#!/usr/bin/env python3
"""Keep portable interaction semantics and wlroots wiring inseparable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_CASES = {
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
    "abort-outline-move-keeps-original-geometry",
    "abort-opaque-move-restores-original-geometry",
    "abort-resize-keeps-original-geometry",
    "auto-relative-top-left",
    "auto-relative-bottom-right",
    "auto-relative-center-waits",
    "auto-relative-titlebar-disabled",
}

SOURCE_FRAGMENTS = (
    '#include "wtwm/interaction.h"',
    "bool constrained_move;",
    "wtwm_interaction_threshold_reached(",
    "wtwm_constrained_move_entry(",
    "wtwm_constrained_move_axis(",
    "wtwm_clamp_move(",
    "wtwm_auto_relative_resize_edges(",
    "wtwm_anchor_constrained_resize(",
    'test_trace_toplevel_event_at(toplevel, "outline",',
    'test_trace_toplevel_event_at(toplevel, "abort",',
    'test_trace_toplevel_event_at(toplevel, "commit",',
    "event->state == WL_POINTER_BUTTON_STATE_PRESSED",
    "if (!server->config.no_raise_on_move)",
    "if (!server->config.no_raise_on_resize)",
    "wtwm_delta_stop_continues(server->last_interaction_moved)",
    "resume_action_continuation(server);",
)

RUNNER_FRAGMENTS = (
    "arguments.compositor.resolve()",
    "MoveDelta below-threshold motion started",
    "MoveDelta equality did not start",
    "outline preview geometry is wrong",
    "second-button press did not abort outline move",
    "does not synthesize release of the original holder",
    'control.command("BUTTON 274 release")\n    release(control, 273)',
    "DontMoveOff did not clamp outer frame",
    "f.forcemove was incorrectly clamped",
    "rapid second move was not constrained",
    "constrained horizontal motion drifted",
    "resize increments were not applied",
    "resize aspect constraints were not applied",
    "left/top constrained anchoring drifted",
    "AutoRelativeResize did not select top-left",
    "AutoRelativeResize did not select bottom-right",
    "OpaqueMove did not select the live-window path",
    "NoRaiseOnMove did not preserve stacking",
    "NoRaiseOnResize did not preserve stacking",
    "f.deltastop stopped a below-threshold function",
    "f.deltastop did not stop after threshold movement",
)


def require_fragments(text: str, fragments: tuple[str, ...], label: str) -> None:
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise ValueError(f"{label} is missing contract fragments: {missing!r}")


def validate(source_root: Path, *, wtwm_override: str | None = None) -> None:
    contract = json.loads((source_root /
        "reference/interactions/twm-1.0.13.1/source-contract.json").read_text(
            encoding="utf-8"))
    case_ids = {case["id"] for case in contract["cases"]}
    if not REQUIRED_CASES.issubset(case_ids):
        raise ValueError(f"reference interaction cases disappeared: {sorted(REQUIRED_CASES - case_ids)!r}")

    wtwm = wtwm_override if wtwm_override is not None else (
        source_root / "src/wtwm.c").read_text(encoding="utf-8")
    require_fragments(wtwm, SOURCE_FRAGMENTS, "compositor interaction wiring")
    unit = (source_root / "tests/interaction_test.c").read_text(encoding="utf-8")
    for function in (
        "wtwm_interaction_threshold_reached",
        "wtwm_constrained_move_entry",
        "wtwm_constrained_move_axis",
        "wtwm_clamp_move",
        "wtwm_auto_relative_resize_edges",
        "wtwm_anchor_constrained_resize",
        "wtwm_delta_stop_continues",
        "wtwm_interaction_render_path",
        "wtwm_interaction_window_box",
    ):
        if function not in unit:
            raise ValueError(f"portable interaction test omits {function}")
    runner = (source_root / "tests/integration/run_move_resize.py").read_text(
        encoding="utf-8")
    require_fragments(runner, RUNNER_FRAGMENTS, "headless interaction runner")
    meson = (source_root / "meson.build").read_text(encoding="utf-8")
    for fragment in (
        "'src/interaction.c'",
        "'twm move and resize interaction model'",
        "'move and resize interaction integration'",
        "'tests/integration/run_move_resize.py'",
    ):
        if fragment not in meson:
            raise ValueError(f"Meson omits interaction contract {fragment!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    validate(arguments.source_root)
    if arguments.self_test_tamper:
        source = (arguments.source_root / "src/wtwm.c").read_text(encoding="utf-8")
        tampered = source.replace("wtwm_clamp_move(", "removed_move_clamp(", 1)
        try:
            validate(arguments.source_root, wtwm_override=tampered)
        except ValueError:
            pass
        else:
            raise ValueError("move/resize contract accepted missing DontMoveOff wiring")
        print("move/resize wiring tamper rejected")
    print("move/resize interaction contract valid")


if __name__ == "__main__":
    main()
