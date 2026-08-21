#!/usr/bin/env python3
"""Validate compositor boundary hardening and bounded diagnostics wiring."""

from __future__ import annotations

import argparse
from pathlib import Path


def validate_sources(
    wtwm: str,
    protocol: str,
    hardening: str,
    header: str,
    readme: str,
    compatibility: str,
) -> None:
    requirements = {
        "xdg move/resize grab serial validation": (
            "wlr_seat_validate_pointer_grab_serial" in wtwm
            and "wlr_seat_validate_touch_grab_serial" in wtwm
            and "event->seat, event->serial, \"move\"" in wtwm
            and "event->seat, event->serial, \"resize\"" in wtwm
            and "event->seat, event->serial, \"show_window_menu\"" in wtwm
        ),
        "xdg request seat and client ownership validation": (
            "seat_client != NULL && seat_client->seat == server->seat" in wtwm
            and "seat_client->client == toplevel->xdg->base->client->client"
            in wtwm
        ),
        "xdg pointer origin-surface validation": (
            "server->seat->pointer_state.focused_client == seat_client" in wtwm
            and "wlr_surface_get_root_surface(pointer_surface) ==" in wtwm
        ),
        "xdg touch origin and client validation": (
            "touch_point->client == seat_client" in wtwm
            and "wlr_surface_get_root_surface(touch_point->surface) ==" in wtwm
        ),
        "cursor event serial validation": (
            "wlr_seat_client_validate_event_serial" in wtwm
        ),
        "selection zero-serial rejection": (
            wtwm.count("event == NULL || event->serial == 0") >= 2
        ),
        "data drag serial and origin validation": all(
            marker in wtwm
            for marker in (
                "request_start_drag",
                "wlr_seat_validate_pointer_grab_serial(server->seat, event->origin",
                "wlr_seat_validate_touch_grab_serial(server->seat, event->origin",
                "touch_point->client == drag->seat_client",
                "wlr_seat_start_pointer_drag",
                "wlr_seat_start_touch_drag",
                "destroy_rejected_drag",
            )
        ),
        "bounded native and Xwayland size ingestion": all(
            marker in wtwm
            for marker in (
                '"xdg_map"',
                '"xdg_commit"',
                '"xwayland_create"',
                '"xwayland_commit"',
                '"xwayland_geometry"',
            )
        ),
        "bounded complete popup positioner": (
            "popup_positioner_valid" in wtwm
            and "wtwm_client_positioner_validate" in wtwm
            and all(
                marker in wtwm
                for marker in (
                    "rules->size.width",
                    "rules->anchor_rect.width",
                    "rules->parent_size.width",
                    "rules->offset.x",
                    "geometry->width",
                )
            )
        ),
        "portable size ceiling and fallback policy": (
            "#define WTWM_CLIENT_SIZE_MAX 65535" in header
            and "sanitize_fallback" in hardening
            and "WTWM_POSITIONER_INVALID_GEOMETRY" in header
            and "wtwm_client_positioner_validate" in hardening
        ),
        "explicit public wlroots request boundary": all(
            marker in compatibility
            for marker in (
                "authorization/grab serial",
                "xdg_popup.grab",
                "wl_data_offer.accept",
                "set_parent_configure",
                "reposition token",
                "core-surface",
            )
        ),
        "README hardening gate completed": (
            "- [x] **Shared:** Validate every Wayland request serial and "
            "client-supplied size." in readme
        ),
        "scene geometry is normalized before wlroots listeners": (
            "wtwm_client_geometry_in_bounds" in hardening
            and "normalize_xdg_surface_geometry" in wtwm
            and wtwm.find("wl_signal_add(&xdg->base->surface->events.commit")
            < wtwm.find("wlr_scene_xdg_surface_create(toplevel->tree")
        ),
        "bounded SIGUSR2 diagnostic dump": all(
            marker in wtwm
            for marker in (
                "--diagnostic-dump",
                "SIGUSR2",
                "DIAGNOSTIC_MAX_OUTPUTS = 64",
                "DIAGNOSTIC_MAX_WINDOWS = 256",
                '"event=diagnostic_dump',
            )
        ),
        "bounded test-control dump": (
            'strcmp(verb, "DUMP") == 0' in protocol
            and "parse_int(limit, 1, 256" in protocol
            and "WTWM_TEST_COMMAND_DUMP" in wtwm
        ),
        "structured rejection logging": (
            '"event=client_request protocol=xdg_shell' in wtwm
            and '"event=client_size protocol=%s' in wtwm
        ),
    }
    failed = [name for name, present in requirements.items() if not present]
    if failed:
        raise AssertionError("missing hardening contract: " + ", ".join(failed))


def read_sources(source_root: Path) -> tuple[str, str, str, str, str, str]:
    return (
        (source_root / "src" / "wtwm.c").read_text(encoding="utf-8"),
        (source_root / "src" / "test_control.c").read_text(encoding="utf-8"),
        (source_root / "src" / "hardening.c").read_text(encoding="utf-8"),
        (source_root / "src" / "hardening.h").read_text(encoding="utf-8"),
        (source_root / "README.md").read_text(encoding="utf-8"),
        (source_root / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8"),
    )


def self_test_tamper(sources: tuple[str, str, str, str, str, str]) -> None:
    wtwm, protocol, hardening, header, readme, compatibility = sources
    wtwm_gates = (
        "wlr_seat_validate_pointer_grab_serial",
        "wlr_seat_validate_touch_grab_serial",
        "seat_client != NULL && seat_client->seat == server->seat",
        "seat_client->client == toplevel->xdg->base->client->client",
        "server->seat->pointer_state.focused_client == seat_client",
        "wlr_surface_get_root_surface(pointer_surface) ==",
        "touch_point->client == seat_client",
        "wlr_surface_get_root_surface(touch_point->surface) ==",
        "wlr_seat_client_validate_event_serial",
        'event->seat, event->serial, "move"',
        'event->seat, event->serial, "resize"',
        'event->seat, event->serial, "show_window_menu"',
        "event == NULL || event->serial == 0",
        "request_start_drag",
        "wlr_seat_validate_pointer_grab_serial(server->seat, event->origin",
        "wlr_seat_validate_touch_grab_serial(server->seat, event->origin",
        "touch_point->client == drag->seat_client",
        "destroy_rejected_drag",
        '"xdg_map"',
        '"xdg_commit"',
        '"xwayland_create"',
        '"xwayland_commit"',
        '"xwayland_geometry"',
        "popup_positioner_valid",
        "rules->anchor_rect.width",
        "rules->parent_size.width",
        "rules->offset.x",
        "geometry->width",
        "normalize_xdg_surface_geometry",
        "DIAGNOSTIC_MAX_WINDOWS = 256",
    )
    for gate in wtwm_gates:
        tampered = wtwm.replace(gate, "removed")
        if tampered == wtwm:
            raise AssertionError(f"self-test could not locate gate: {gate}")
        try:
            validate_sources(
                tampered, protocol, hardening, header, readme, compatibility
            )
        except AssertionError:
            pass
        else:
            raise AssertionError(f"contract accepted missing gate: {gate}")

    tampered_protocol = protocol.replace("parse_int(limit, 1, 256", "removed")
    try:
        validate_sources(
            wtwm, tampered_protocol, hardening, header, readme, compatibility
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("contract accepted an unbounded DUMP command")

    for gate in ("authorization/grab serial", "xdg_popup.grab", "core-surface"):
        tampered = compatibility.replace(gate, "removed")
        try:
            validate_sources(wtwm, protocol, hardening, header, readme, tampered)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"contract accepted missing boundary: {gate}")

    tampered_readme = readme.replace(
        "- [x] **Shared:** Validate every Wayland request serial and "
        "client-supplied size.",
        "- [ ] **Shared:** Validate every Wayland request serial and "
        "client-supplied size.",
    )
    try:
        validate_sources(
            wtwm, protocol, hardening, header, tampered_readme, compatibility
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("contract accepted an unchecked hardening gate")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    sources = read_sources(args.source_root)
    validate_sources(*sources)
    if args.self_test_tamper:
        self_test_tamper(sources)


if __name__ == "__main__":
    main()
