#!/usr/bin/env python3
"""Portable contract for the Milestone 9 hostile Wayland integration test."""

from __future__ import annotations

import argparse
from pathlib import Path


CLIENT_MARKERS = {
    "zero, released-button, and impossible serial corpus": (
        "const uint32_t serials[] = {0, stale, invalid};"
    ),
    "xdg move request": "xdg_toplevel_move(client->toplevel",
    "xdg resize request": "xdg_toplevel_resize(client->toplevel",
    "xdg show-window-menu request": "xdg_toplevel_show_window_menu(client->toplevel",
    "wl_pointer cursor request": "wl_pointer_set_cursor(client->pointer",
    "dedicated cursor surface": "client->cursor_surface, INT32_MIN, INT32_MAX",
    "cursor corpus excludes released-button serial": "if (serials[i] != stale)",
    "released button becomes stale corpus input": "send_serial_fuzz(client);",
    "invalid drag serial corpus": "send_invalid_drag_fuzz(client, stale);",
    "valid held-button drag request": (
        "wl_data_device_start_drag(client->data_device, source, client->surface,"
    ),
    "valid drag request mode": '[MODE_DRAG] = "m9-protocol-drag"',
    "oversized toplevel geometry": (
        "xdg_surface_set_window_geometry(client->xdg_surface, INT32_MIN, INT32_MIN,"
    ),
    "independent positioner size mode": "MODE_POSITIONER_SIZE",
    "independent positioner anchor mode": "MODE_POSITIONER_ANCHOR",
    "independent positioner parent mode": "MODE_POSITIONER_PARENT",
    "independent positioner offset mode": "MODE_POSITIONER_OFFSET",
    "independent effective geometry mode": "MODE_POSITIONER_GEOMETRY",
    "oversized parent dimensions": (
        "xdg_positioner_set_parent_size(positioner, INT32_MAX, INT32_MAX);"
    ),
    "oversized offset coordinates": (
        "xdg_positioner_set_offset(positioner, INT32_MIN, INT32_MAX);"
    ),
    "separate healthy survivor mode": (
        '[MODE_SURVIVOR] = "m9-protocol-survivor"'
    ),
    "client display cleanup": "wl_display_disconnect(client->display);",
    "client toplevel proxy cleanup": "xdg_toplevel_destroy(client->toplevel);",
    "client popup proxy cleanup": "xdg_popup_destroy(client->popup);",
}

RUNNER_MARKERS = {
    "debug structured logging enabled": '"-d",',
    "persistent raw stdout buffering": (
        "STDOUT_BUFFERS.setdefault(process, bytearray())"
    ),
    "raw pipe reads avoid text-wrapper prefetch races": (
        "os.read(process.stdout.fileno(), 4096)"
    ),
    "separate survivor launched first": (
        'launch(client_binary, "survivor", client_environment)'
    ),
    "survivor retained after geometry": (
        'assert_responsive(control, expected_windows=1)'
    ),
    "valid pointer drag started": (
        'wait_state(control, lambda state: state["data_drag"],'
    ),
    "valid pointer drag finished": (
        'wait_state(control, lambda state: not state["data_drag"],'
    ),
    "pointer enter event observed": (
        'wait_line(serials, "POINTER_ENTER ", prefix=True)'
    ),
    "button press and release generated": (
        'control.command("BUTTON 272 press")'
    ),
    "serial fuzz completed on live connection": (
        'wait_line(serials, "FUZZ_SENT stale=", prefix=True)'
    ),
    "malformed popup isolation": 'wait_one_of(positioner, {"SURVIVED", "DISCONNECTED"})',
    "all popup positioner fields exercised": "for mode, sent, field in positioner_cases:",
    "control responsiveness oracle": (
        'control.command("PING") != "OK WTWM_TEST_CONTROL 1"'
    ),
    "interaction state unchanged": (
        'state["interactive"] or state["menu"] is not None'
    ),
    "move rejection evidence": (
        "event=client_request protocol=xdg_shell action=move outcome=rejected"
    ),
    "resize rejection evidence": (
        "event=client_request protocol=xdg_shell action=resize outcome=rejected"
    ),
    "menu rejection evidence": (
        "event=client_request protocol=xdg_shell action=show_window_menu outcome=rejected"
    ),
    "cursor rejection evidence": (
        "event=client_request protocol=wl_pointer action=set_cursor outcome=rejected"
    ),
    "drag acceptance evidence": (
        "event=client_request protocol=wl_data_device action=start_drag outcome=accepted"
    ),
    "drag rejection evidence": (
        "event=client_request protocol=wl_data_device action=start_drag outcome=rejected"
    ),
    "toplevel size evidence": "boundary=xdg_commit outcome=adjusted",
    "popup field evidence": 'for field in ("size", "anchor_rect", "parent_size", "offset", "geometry")',
    "sanitizer evidence rejected": "ERROR: AddressSanitizer",
    "Meson executable paths resolved": (
        "run(args.compositor.resolve(), args.client.resolve())"
    ),
}


def validate(client: str, runner: str) -> None:
    requirements = {
        **{f"client: {name}": marker in client for name, marker in CLIENT_MARKERS.items()},
        **{f"runner: {name}": marker in runner for name, marker in RUNNER_MARKERS.items()},
    }
    if runner.count('assert_responsive(control, expected_windows=1)') < 5:
        requirements["runner: responsiveness checked between every hostile client"] = False
    if client.count("INT32_MAX") < 10:
        requirements["client: multiple maximum-boundary request fields"] = False
    main_setup = client[client.find("int main("):client.find("if (!create_toplevel")]
    if main_setup.count("wl_display_roundtrip(client.display)") < 2:
        requirements["client: seat capabilities synchronized after registry globals"] = False
    failed = [name for name, present in requirements.items() if not present]
    if failed:
        raise AssertionError("missing protocol-fuzz contract: " + ", ".join(failed))


def self_test_tamper(client: str, runner: str) -> None:
    for name, marker in CLIENT_MARKERS.items():
        tampered = client.replace(marker, "REMOVED")
        if tampered == client:
            raise AssertionError(f"could not tamper client marker: {name}")
        try:
            validate(tampered, runner)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"contract accepted missing client marker: {name}")
    for name, marker in RUNNER_MARKERS.items():
        tampered = runner.replace(marker, "REMOVED")
        if tampered == runner:
            raise AssertionError(f"could not tamper runner marker: {name}")
        try:
            validate(client, tampered)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"contract accepted missing runner marker: {name}")
    barrier = "wl_display_roundtrip(client.display)"
    first = client.find(barrier, client.find("int main("))
    second = client.find(barrier, first + len(barrier))
    if first < 0 or second < 0:
        raise AssertionError("could not locate two setup round trips")
    tampered = client[:second] + "REMOVED" + client[second + len(barrier):]
    try:
        validate(tampered, runner)
    except AssertionError:
        pass
    else:
        raise AssertionError("contract accepted missing seat-capability round trip")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    client = args.client.read_text(encoding="utf-8")
    runner = args.runner.read_text(encoding="utf-8")
    validate(client, runner)
    if args.self_test_tamper:
        self_test_tamper(client, runner)


if __name__ == "__main__":
    main()
