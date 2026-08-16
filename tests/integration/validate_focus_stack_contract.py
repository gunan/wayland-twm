#!/usr/bin/env python3
"""Guard the portable and live focus/context/stacking implementation."""

from __future__ import annotations

import argparse
from pathlib import Path


def require(text: str, fragments: tuple[str, ...], label: str) -> None:
    for fragment in fragments:
        if fragment not in text:
            raise ValueError(f"{label} lacks {fragment!r}")


def validate(root: Path) -> None:
    header = (root / "include/wtwm/focus_stack.h").read_text(encoding="utf-8")
    model = (root / "src/focus_stack.c").read_text(encoding="utf-8")
    compositor = (root / "src/wtwm.c").read_text(encoding="utf-8")
    unit = (root / "tests/focus_stack_test.c").read_text(encoding="utf-8")
    runner = (root / "tests/integration/run_focus_stack.py").read_text(encoding="utf-8")
    client = (root / "tests/integration/focus_stack_x11_client.c").read_text(
        encoding="utf-8"
    )
    meson = (root / "meson.build").read_text(encoding="utf-8")
    docs = (root / "docs/COMPATIBILITY.md").read_text(encoding="utf-8")
    require(header, (
        "WTWM_FOCUS_SURFACE_MENU",
        "global_no_titlebar",
        "wtwm_focus_leave",
        "wtwm_raise_lower_action",
        "wtwm_circle_up_candidate",
        "wtwm_circle_down_candidate",
    ), "focus/stack model API")
    require(model, (
        "case WTWM_FOCUS_SURFACE_MENU: return 0;",
        "input->has_title || input->global_no_titlebar",
        "input->title_focus || input->take_focus",
        "wtwm_stack_is_occluded(top_to_bottom, count, index)",
        "count - 1 - offset",
        "below = index + 1",
    ), "focus/stack model")
    require(unit, (
        "WTWM_FOCUS_SURFACE_TITLE",
        "result.activate && !result.set_input_focus",
        "result.activate && result.set_input_focus && result.send_take_focus",
        "WTWM_FOCUS_POINTER_ROOT",
        "result.deactivate && !result.set_pointer_root",
        "WTWM_STACK_RAISE",
        "WTWM_STACK_LOWER",
    ), "focus/stack unit test")
    require(compositor, (
        "server->focus_root",
        ".global_no_titlebar = server->config.no_title",
        "xwayland_input_hint_true",
        "xwayland_accepts_input",
        "toplevel->server->pointer_toplevel == toplevel",
        ".input_hint = xwayland_input_hint_true(toplevel)",
        "send_xwayland_take_focus(toplevel, server->current_input_time_ms)",
        "Wayland input times aren't guaranteed to share the X server's timestamp",
        "xcb_set_input_focus(connection, XCB_INPUT_FOCUS_POINTER_ROOT, focus,",
        "XCB_CURRENT_TIME);",
        "sync_xwayland_input_focus(server, toplevel)",
        "sync_xwayland_input_focus(server, NULL);",
        "send_take_focus && !xwm_sent_take_focus",
        "set_xwayland_input_focus(server, NULL);",
        "if (type == XCB_FOCUS_IN)",
        "if (entered->auto_raise) raise_toplevel(entered);",
        "raise_lower_toplevel(toplevel);",
        "circulate_toplevels(server, true);",
        "circulate_toplevels(server, false);",
        "wl_list_insert(parent->link.prev, &toplevel->link);",
        'binding_context_name(context)',
        'toplevel->icon_width = 96;',
        '\\"icon_views\\"',
    ), "compositor focus/stack wiring")
    activation_start = compositor.find("static bool sync_xwayland_input_focus(")
    activation_end = compositor.find("\nstatic void suspend_toplevel(", activation_start)
    if (activation_start < 0 or activation_end < activation_start or
            compositor[activation_end:].count(
                "wlr_xwayland_surface_activate") != 0):
        raise ValueError("wlroots XWM activation escaped its bookkeeping helper")
    require(runner, (
        'state["focus_root"] is not False',
        'state["active"] != "focus-a"',
        'assert_stack(state, "focus-b", "focus-a")',
        '{"window", "title", "frame", "icon"}',
        'event["context"] == "menu"',
        'event["state"]["focused"] is False',
        'opposite_point = point(a, "frame")',
        'b_window_exposed = (',
        'status.split()[3] != "a"',
        'status.split()[3] != "root"',
        'state["active"] != "focus-b"',
    ), "headless focus/stack runner")
    require(client, (
        'atom(client, "WM_TAKE_FOCUS")',
        "hints[1] = input ? 1u : 0u;",
        "client->wm_transient_for",
        'strcmp(command, "STATUS") == 0',
        "xcb_get_input_focus(client->connection)",
        'strcmp(command, "CLEAR_HINTS_A") == 0',
    ), "X11 focus/stack fixture")
    require(meson, (
        "test('twm focus contexts and stacking model', focus_stack_test)",
        "'focus contexts and stacking integration'",
        "'tests/integration/run_focus_stack.py'",
    ), "Meson focus/stack registration")
    require(docs, (
        "PointerRoot/sloppy focus",
        "overlap-dependent `f.raiselower`",
        "minimal compositor-owned icon hit target",
    ), "focus/stack compatibility documentation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    validate(arguments.source_root)
    if arguments.self_test_tamper:
        model_path = arguments.source_root / "src/focus_stack.c"
        original = model_path.read_text(encoding="utf-8")
        tampered = original.replace("count - 1 - offset", "offset", 1)
        if tampered == original:
            raise ValueError("focus/stack tamper fixture did not alter the model")
        try:
            require(tampered, ("count - 1 - offset",), "tampered circulation")
        except ValueError:
            pass
        else:
            raise ValueError("focus/stack contract accepted reversed circle-up order")
        print("focus/stack circulation tamper rejected")
    print("focus/context/stacking contract valid")


if __name__ == "__main__":
    main()
