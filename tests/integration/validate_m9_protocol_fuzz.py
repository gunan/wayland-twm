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
    "released button becomes stale corpus input": "send_serial_fuzz(client);",
    "oversized toplevel geometry": (
        "xdg_surface_set_window_geometry(client->xdg_surface, INT32_MIN, INT32_MIN,"
    ),
    "oversized positioner size": (
        "xdg_positioner_set_size(positioner, INT32_MAX, INT32_MAX);"
    ),
    "oversized positioner anchor rectangle": (
        "xdg_positioner_set_anchor_rect(positioner, INT32_MIN, INT32_MIN,"
    ),
    "separate healthy survivor mode": (
        '[MODE_SURVIVOR] = "m9-protocol-survivor"'
    ),
}

RUNNER_MARKERS = {
    "debug structured logging enabled": '"-d",',
    "separate survivor launched first": (
        'launch(client_binary, "survivor", client_environment)'
    ),
    "survivor retained after geometry": (
        'assert_responsive(control, expected_windows=1)'
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
    "malformed popup isolation": (
        'wait_one_of(positioner, {"SURVIVED", "DISCONNECTED"})'
    ),
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
    "toplevel size evidence": "boundary=xdg_commit outcome=adjusted",
    "popup size evidence": "role=popup boundary=popup_create outcome=rejected",
    "sanitizer evidence rejected": "ERROR: AddressSanitizer",
}


def validate(client: str, runner: str) -> None:
    requirements = {
        **{f"client: {name}": marker in client for name, marker in CLIENT_MARKERS.items()},
        **{f"runner: {name}": marker in runner for name, marker in RUNNER_MARKERS.items()},
    }
    if runner.count('assert_responsive(control, expected_windows=1)') < 4:
        requirements["runner: responsiveness checked between every hostile client"] = False
    if client.count("INT32_MAX") < 8:
        requirements["client: multiple maximum-boundary request fields"] = False
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
