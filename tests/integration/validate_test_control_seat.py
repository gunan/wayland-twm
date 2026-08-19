#!/usr/bin/env python3
"""Keep synthetic test-control input aligned with advertised seat resources."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


DEFAULT_INPUTS = re.compile(
    r"test_input_add\(&server\.test_control,\s*"
    r"WTWM_INPUT_DEVICE_KEYBOARD,\s*\"TEST-KEYBOARD-0\"\)\s*\|\|\s*"
    r"!test_input_add\(&server\.test_control,\s*"
    r"WTWM_INPUT_DEVICE_POINTER,\s*\"TEST-POINTER-0\"\)",
    re.DOTALL,
)


def validate(source: str) -> None:
    anchor = source.find("server.test_control.server = &server;")
    if anchor < 0:
        raise ValueError("synthetic test input setup is missing")
    branch_start = source.rfind("#ifdef WTWM_TEST_CONTROL", 0, anchor)
    branch_end = source.find("#else", anchor)
    if branch_start < 0 or branch_end < 0:
        raise ValueError("synthetic input setup escaped the test-control branch")
    branch = source[branch_start:branch_end]
    if DEFAULT_INPUTS.search(branch) is None:
        raise ValueError(
            "test control must install the exact initial keyboard and pointer"
        )
    for fragment in (
        "static const struct wlr_keyboard_impl aggregate_keyboard_impl",
        "wlr_keyboard_init(&server.aggregate_keyboard",
        "wlr_seat_set_keyboard(server.seat, &server.aggregate_keyboard);",
        "wlr_seat_set_capabilities(server.seat, 0);",
        "wtwm_input_hotplug_plan_apply(&server->input, plan)",
        "input_capabilities(plan->capabilities_after)",
    ):
        if fragment not in source:
            raise ValueError(f"dynamic aggregate seat setup lacks {fragment}")
    for fragment in (
        "wlr_cursor_warp_closest(server->cursor, NULL, x, y);",
        "holders == 0 : source_holds && holders == 1;",
        "holders != 0 ? inherited_visible : false;",
        "server->interaction.required_button_valid &&",
        "input_held_count(state, WTWM_INPUT_DEVICE_POINTER,",
    ):
        if fragment not in source:
            raise ValueError(f"physical input aggregation lacks {fragment}")
    for fragment in (
        "sync_xwayland_input_focus(server, toplevel)",
        "wlr_xwayland_surface_activate(toplevel->xwayland, true);",
        "send_take_focus && !xwm_sent_take_focus",
    ):
        if fragment not in source:
            raise ValueError(f"XWM selection focus synchronization lacks {fragment}")


def validate_bridge_handshake(
    wayland_client: str, x11_client: str, runner: str
) -> None:
    for request in (
        "wl_data_device_set_selection(client->data_device",
        "zwp_primary_selection_device_v1_set_selection(client->primary_device",
    ):
        start = wayland_client.find(request)
        if start < 0 or "wl_display_roundtrip(client->display)" not in (
            wayland_client[start:start + 500]
        ):
            raise ValueError(f"Wayland source request lacks a roundtrip: {request}")
    for fragment in (
        "static bool wait_for_input_focus",
        "static bool proxy_owners_ready",
        "static bool wait_for_bridge_ready",
        "xcb_get_input_focus(client->connection)",
        'xcb_atom_t wm_hints = atom(client, "WM_HINTS");',
        "uint32_t hints[9] = {1, 1};",
        'strcmp(command, "WAIT BRIDGE")',
        'strcmp(command, "WAIT FOCUS")',
    ):
        if fragment not in x11_client:
            raise ValueError(f"X11 bridge handshake lacks {fragment}")
    for fragment in (
        "def visible_content_point(",
        'int(item["stack"]) < int(target["stack"])',
        'int(other["outer_width"])',
        'int(other["outer_height"])',
    ):
        if fragment not in runner:
            raise ValueError(f"selection focus targeting lacks {fragment}")
    bridge_start = x11_client.find("static bool wait_for_bridge_ready")
    bridge_end = x11_client.find("static void request_selection", bridge_start)
    bridge = x11_client[bridge_start:bridge_end]
    for fragment in (
        "for (;;)",
        "xcb_connection_has_error(client->connection)",
        "input_focus_is_window(client) && proxy_owners_ready(client)",
        "poll(&descriptor",
    ):
        if fragment not in bridge:
            raise ValueError(f"bridge readiness loop lacks {fragment}")
    command_start = x11_client.find('strcmp(command, "WAIT BRIDGE")')
    command_end = x11_client.find('strcmp(command, "SERVED")', command_start)
    if "wait_for_bridge_ready(client)" not in x11_client[command_start:command_end]:
        raise ValueError("WAIT BRIDGE does not require the full readiness predicate")
    first_x_focus = runner.find('focus_window(control, "wtwm-selection-x11")')
    first_bridge = runner.find('x11, "WAIT BRIDGE"', first_x_focus)
    first_targets = runner.find('x11, "TARGETS CLIPBOARD"', first_bridge)
    if not 0 <= first_x_focus < first_bridge < first_targets:
        raise ValueError("TARGETS request is not gated by the X bridge handshake")
    if runner.count('x11, "WAIT BRIDGE"') < 2:
        raise ValueError("each Wayland-owned selection read needs a bridge handshake")
    x_owned = runner.find('x11, "OWN CLIPBOARD"')
    focus_gate = runner.rfind('x11, "WAIT FOCUS"', 0, x_owned)
    if focus_gate < 0:
        raise ValueError("X-owned selection import lacks an X focus handshake")


def validate_overlay_menu_button(runner: str) -> None:
    if 'Button3 = : all : f.menu "stacking"' not in runner:
        raise ValueError("overlay runner does not bind its compositor menu to Button3")
    for state in ("press", "release"):
        command = f'control.command("BUTTON 273 {state}")'
        if runner.count(command) != 1:
            raise ValueError(
                f"overlay Button3 must inject Linux BTN_RIGHT code 273 on {state}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    source = (arguments.source_root / "src/wtwm.c").read_text(encoding="utf-8")
    validate(source)
    wayland_client = (
        arguments.source_root / "tests/integration/selection_wayland_client.c"
    ).read_text(encoding="utf-8")
    x11_client = (
        arguments.source_root / "tests/integration/selection_x11_client.c"
    ).read_text(encoding="utf-8")
    runner = (
        arguments.source_root / "tests/integration/run_selection_bridge.py"
    ).read_text(encoding="utf-8")
    validate_bridge_handshake(wayland_client, x11_client, runner)
    overlay_runner = (
        arguments.source_root / "tests/integration/run_overlay_stacking.py"
    ).read_text(encoding="utf-8")
    validate_overlay_menu_button(overlay_runner)
    if arguments.self_test_tamper:
        tampered = source.replace(
            "WTWM_INPUT_DEVICE_POINTER,\n\t\t\t\"TEST-POINTER-0\"",
            "WTWM_INPUT_DEVICE_KEYBOARD,\n\t\t\t\"TEST-POINTER-0\"",
            1,
        )
        try:
            validate(tampered)
        except ValueError:
            pass
        else:
            raise ValueError("synthetic seat contract accepted missing pointer")
        tampered = source.replace(
            "wlr_cursor_warp_closest(server->cursor, NULL, x, y);",
            "wlr_cursor_warp_closest(server->cursor, "
            "&device->wlr.pointer.base, x, y);",
            1,
        )
        try:
            validate(tampered)
        except ValueError:
            pass
        else:
            raise ValueError("synthetic seat contract accepted device-local warping")
        tampered = source.replace(
            "holders == 0 : source_holds && holders == 1;",
            "holders == 0 : source_holds;",
            1,
        )
        try:
            validate(tampered)
        except ValueError:
            pass
        else:
            raise ValueError("synthetic seat contract accepted an early shared release")
        tampered_runner = runner.replace('x11, "WAIT BRIDGE"', 'x11, "STATUS"', 1)
        try:
            validate_bridge_handshake(wayland_client, x11_client, tampered_runner)
        except ValueError:
            pass
        else:
            raise ValueError("selection bridge contract accepted ungated TARGETS")
        tampered_x11 = x11_client.replace(
            "input_focus_is_window(client) && proxy_owners_ready(client)",
            "input_focus_is_window(client)",
            1,
        )
        try:
            validate_bridge_handshake(wayland_client, tampered_x11, runner)
        except ValueError:
            pass
        else:
            raise ValueError("bridge contract accepted a focus-only readiness gate")
        tampered_overlay = overlay_runner.replace(
            'control.command("BUTTON 273 press")',
            'control.command("BUTTON 274 press")',
            1,
        )
        try:
            validate_overlay_menu_button(tampered_overlay)
        except ValueError:
            pass
        else:
            raise ValueError("overlay menu contract accepted BTN_MIDDLE for Button3")
        print("synthetic seat, bridge-handshake, and overlay button tampers rejected")
    print("test control synthetic seat contract valid")


if __name__ == "__main__":
    main()
