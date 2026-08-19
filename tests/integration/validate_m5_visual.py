#!/usr/bin/env python3
"""Guard Milestone 5 visual implementation and differential-test wiring."""

from __future__ import annotations

import argparse
from pathlib import Path


def require(text: str, fragments: tuple[str, ...], label: str) -> None:
    for fragment in fragments:
        if fragment not in text:
            raise ValueError(f"{label} lacks {fragment!r}")


def validate(root: Path) -> None:
    compositor = (root / "src/wtwm.c").read_text(encoding="utf-8")
    text = (root / "src/text.c").read_text(encoding="utf-8")
    visual = (root / "src/visual.c").read_text(encoding="utf-8")
    visual_test = (root / "tests/visual_test.c").read_text(encoding="utf-8")
    color = (root / "src/color.c").read_text(encoding="utf-8")
    color_test = (root / "tests/color_test.c").read_text(encoding="utf-8")
    font = (root / "src/font.c").read_text(encoding="utf-8")
    xbm = (root / "src/xbm.c").read_text(encoding="utf-8")
    client = (root / "tests/integration/m5_visual_client.c").read_text(
        encoding="utf-8"
    )
    differential = (
        root / "tests/integration/run_m5_visual_differential.py"
    ).read_text(encoding="utf-8")
    states = (root / "tests/integration/run_m5_visual_states.py").read_text(
        encoding="utf-8"
    )
    workflow = (root / ".github/workflows/build.yml").read_text(encoding="utf-8")
    meson = (root / "meson.build").read_text(encoding="utf-8")
    compatibility = (root / "docs/COMPATIBILITY.md").read_text(encoding="utf-8")
    tasks = (root / "README.md").read_text(encoding="utf-8")

    require(visual, (
        "wtwm_title_layout_compute",
        "wtwm_title_button_box",
        "wtwm_title_squeeze_x",
        "wtwm_menu_layout_compute",
        "wtwm_visual_scale_box",
    ), "portable visual layout")
    require(visual_test, (
        "test_default_title_layout",
        "test_title_squeezing_and_justification",
        "test_default_menu_layout",
        "test_fractional_scale_projection",
    ), "visual layout unit tests")
    require(color, (
        "wtwm_color_parse_literal",
        "wtwm_color_interpolate",
        "wtwm_color_grayscale",
        "wtwm_color_monochrome",
    ), "color conversion")
    require(color_test, (
        'expect("#abc012def"',
        'expect("rgb:f/80/0000"',
        "wtwm_color_grayscale",
        "wtwm_color_monochrome",
    ), "color unit tests")
    require(font, ("wtwm_pango_font_description", "parse_xlfd",),
            "XLFD mapping")
    require(xbm, ("WTWM_XBM_MAX_FILE_BYTES", "parse_source",), "XBM loader")
    require(text, (
        "render_core_text",
        "wtwm_render_xbm_cursor",
        "wtwm_render_xbm_title",
        "wtwm_render_builtin_title",
    ), "bitmap-compatible renderer")
    require(compositor, (
        "wlr_scene_buffer_set_source_box",
        "configured_icon_bitmap(toplevel)",
        "set_cursor_role(server, \"Menu\")",
        "menu_palettes(server, menu, palettes)",
        "wtwm_config_squeeze_rule",
        "layout.focus_highlight_visible",
    ), "compositor visual wiring")
    require(client, (
        'strcmp(line, "PHASE")',
        'strcmp(line, "TITLE")',
        'strcmp(line, "RAPID")',
        'puts("READY")',
    ), "visual X11 client")
    require(differential, (
        'for phase in ("bravo", "alpha")',
        '"mismatch_pixels": mismatch',
        '"geometry_mask_mismatch_pixels": structural',
        '"font_mask_mismatch_pixels": font',
        'results["exact"] = not failures',
    ), "reference pixel differential")
    require(states, (
        'for mode in ("color", "grayscale", "monochrome")',
        '"masks": []',
        "MAX_STABILITY_CAPTURES = 12",
        "for _ in range(MAX_STABILITY_CAPTURES - 1):",
        "if data == repeat_data:",
        "repeat.replace(first)",
        "did not converge after {MAX_STABILITY_CAPTURES} captures",
        "sha256={stability_hashes!r}",
        'images["button-pressed"]',
        '("title-long", "L" * 180)',
        '("title-empty", "")',
        '("title-nonascii", "Grüße 中")',
        'images["title-rapid"]',
        'images["menu-highlight"]',
        'images["submenu"]',
        'images["icon"]',
    ), "visual state capture")
    require(workflow, (
        "Compare canonical Milestone 5 pixels with reference twm",
        "Capture every Milestone 5 visual state and color mode",
        "Upload Milestone 5 visual differential",
        "Upload Milestone 5 visual state captures",
    ), "Milestone 5 CI")
    require(meson, ("'Milestone 5 visual contract'",), "Meson registration")
    require(compatibility, (
        "zero masks and zero mismatched pixels",
        "Compositor-owned configured-XBM",
        "normal/hover/pressed",
        "an A/B reviewer has",
    ), "Milestone 5 compatibility documentation")
    require(tasks, (
        "## Tasks",
        "Capture paired stable screenshots after every significant",
        "Review every golden image",
    ), "README visual certification tasks")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    validate(arguments.source_root)
    if arguments.self_test_tamper:
        runner_path = arguments.source_root / (
            "tests/integration/run_m5_visual_differential.py"
        )
        original = runner_path.read_text(encoding="utf-8")
        tampered = original.replace('results["exact"] = not failures',
                                    'results["exact"] = True', 1)
        if tampered == original:
            raise ValueError("visual differential tamper did not alter runner")
        try:
            require(tampered, ('results["exact"] = not failures',),
                    "tampered exact comparison")
        except ValueError:
            pass
        else:
            raise ValueError("visual contract accepted an unconditional pass")
        states_path = arguments.source_root / (
            "tests/integration/run_m5_visual_states.py"
        )
        original_states = states_path.read_text(encoding="utf-8")
        tampered_states = original_states.replace(
            "        repeat.replace(first)\n", "        break\n", 1
        )
        if tampered_states == original_states:
            raise ValueError("visual stability tamper did not alter runner")
        try:
            require(tampered_states, ("repeat.replace(first)",),
                    "tampered visual stability convergence")
        except ValueError:
            pass
        else:
            raise ValueError("visual contract accepted a one-shot stability check")
        print("Milestone 5 visual tamper rejected")
    print("Milestone 5 visual contract valid")


if __name__ == "__main__":
    main()
