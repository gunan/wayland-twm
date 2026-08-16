#!/usr/bin/env python3
"""Protect the native-Wayland/Xwayland mixed-session integration scenario."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


PATHS = (
    Path("tests/integration/run_mixed_clients.py"),
    Path("tests/integration/mixed_wayland_client.c"),
    Path("tests/integration/mixed_x11_client.c"),
    Path("meson.build"),
    Path("docs/COMPATIBILITY.md"),
    Path("tests/integration/README.md"),
)


def validate_text(
    runner: str,
    wayland_client: str,
    x11_client: str,
    meson: str,
    compatibility: str,
    integration_readme: str,
) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(runner)
    except SyntaxError as error:
        return [f"mixed-session runner is invalid Python: {error}"]

    sleeps = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "time"
        and call.func.attr == "sleep"
    ]
    if any(
        not call.args
        or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, (int, float))
        or call.args[0].value > 0.01
        for call in sleeps
    ):
        errors.append("mixed-session runner uses an arbitrary success sleep")

    runner_markers = (
        '"native-a": {',
        '"native-b": {',
        '"x11-a": {',
        '"x11-b": {',
        '("native-a", "x11-a", "native-b", "x11-b")',
        'control.command("KEY 30 press")',
        'control.command("KEY 30 release")',
        "target.wait_for_key_pair(token, role)",
        'f"OK REPORT {token} x11-a=0 x11-b=0 focus=none"',
        'f"OK REPORT {token} native-a=0 native-b=0 focus=none "',
        'not entry["associated"] or not entry["mapped"] or not entry["has_buffer"]',
        'window_by_role(item, role)["stack"] == 0',
        'window_by_role(item, role)["stack"] == len(EXPECTED) - 1',
        'Button2 = : window : f.lower',
        'lower_and_restore(control, wayland, x11, "native-a", "stack-native")',
        'lower_and_restore(control, wayland, x11, "x11-a", "stack-x11")',
        'wayland.command("UNMAP native-b", "OK UNMAPPED native-b")',
        'wayland.command("REMAP native-b", "OK REMAPPED native-b")',
        'x11.command("UNMAP x11-b", "OK UNMAPPED x11-b")',
        'x11.command("REMAP x11-b", "OK REMAPPED x11-b")',
        'and not lifecycle[0]["associated"]',
        'and not lifecycle[0]["mapped"]',
        'state["popups"] or state["override_redirect"]',
        'TITLE_TO_ROLE.get(state["focus"]) not in {"x11-a", "x11-b"}',
        'TITLE_TO_ROLE.get(state["focus"]) not in {"native-a", "native-b"}',
    )
    for marker in runner_markers:
        if marker not in runner:
            errors.append(f"mixed-session runner lacks {marker!r}")
    for forbidden in ("SystemExit(77)", "continue-on-error", "|| true"):
        if forbidden in runner:
            errors.append(f"mixed-session runner contains forbidden fallback {forbidden!r}")

    wayland_markers = (
        '"wtwm-mixed-native-a"',
        '"wtwm-mixed-native-b"',
        '"org.wtwm.MixedNativeA"',
        '"org.wtwm.MixedNativeB"',
        "wl_seat_get_keyboard",
        "static void keyboard_enter",
        "static void keyboard_key(void *data",
        'printf("EVENT KEY %s %s %" PRIu32',
        'sscanf(command, "UNMAP %63s"',
        'sscanf(command, "REMAP %63s"',
        "wl_surface_attach(role->surface, NULL, 0, 0);",
    )
    for marker in wayland_markers:
        if marker not in wayland_client:
            errors.append(f"mixed Wayland input/lifecycle client lacks {marker!r}")
    main_start = wayland_client.find("int main(void)")
    main_body = wayland_client[main_start:] if main_start >= 0 else ""
    barrier = "wl_display_roundtrip(client.display)"
    first_barrier = main_body.find(barrier)
    second_barrier = main_body.find(barrier, first_barrier + len(barrier))
    required_globals = main_body.find("client.compositor == NULL")
    if main_body.count(barrier) != 2:
        errors.append("mixed Wayland startup must use exactly two registry/seat barriers")
    elif not (0 <= first_barrier < second_barrier < required_globals):
        errors.append("mixed Wayland keyboard validation precedes the second seat barrier")

    x11_markers = (
        '"wtwm-mixed-x11-a"',
        '"wtwm-mixed-x11-b"',
        '"WtwmMixedX11A"',
        '"WtwmMixedX11B"',
        "XCB_EVENT_MASK_FOCUS_CHANGE | XCB_EVENT_MASK_KEY_PRESS",
        "type == XCB_KEY_PRESS || type == XCB_KEY_RELEASE",
        "key->detail >= 8 ? key->detail - 8 : key->detail",
        'printf("EVENT KEY %s %s %" PRIu32',
        'sscanf(command, "UNMAP %63s"',
        'sscanf(command, "REMAP %63s"',
        "xcb_unmap_window",
        "xcb_map_window",
        "bool desired_mapped;",
        "bool paint_alternate;",
        "if (!role->desired_mapped) return false;",
        "role->paint_alternate = !role->paint_alternate;",
        "static void repaint_mapped_roles",
        "if (sent) xcb_flush(client->connection);",
        "poll(descriptors, 2, 100)",
        "repaint_mapped_roles(&client);",
        "stop_repainting(client);",
    )
    for marker in x11_markers:
        if marker not in x11_client:
            errors.append(f"mixed X11 input/lifecycle client lacks {marker!r}")
    map_start = x11_client.find("static void map_role")
    map_end = x11_client.find("static void repaint_mapped_roles", map_start)
    map_body = x11_client[map_start:map_end]
    if not (0 <= map_body.find("role->desired_mapped = true;") <
            map_body.find("xcb_map_window")):
        errors.append("mixed X11 remap does not arm sustained damage before mapping")
    unmap_start = x11_client.find('if (sscanf(command, "UNMAP %63s"')
    unmap_end = x11_client.find('if (sscanf(command, "REMAP %63s"', unmap_start)
    unmap_body = x11_client[unmap_start:unmap_end]
    if not (0 <= unmap_body.find("role->desired_mapped = false;") <
            unmap_body.find("xcb_unmap_window")):
        errors.append("mixed X11 unmap does not disarm damage before the request")

    contract_start = meson.find("'mixed native and Xwayland session contract'")
    runtime_start = meson.find("'mixed native and Xwayland client integration'")
    if contract_start < 0:
        errors.append("Meson lacks the portable mixed-session contract")
    else:
        contract = meson[contract_start:contract_start + 500]
        for marker in ("validate_mixed_clients.py", "--self-test-tamper"):
            if marker not in contract:
                errors.append(f"portable mixed-session contract lacks {marker!r}")
    if runtime_start < 0:
        errors.append("Meson lacks the Linux mixed-session runtime test")
    else:
        runtime = meson[runtime_start:runtime_start + 650]
        for marker in (
            "run_mixed_clients.py",
            "wtwm_mixed_wayland_client",
            "wtwm_mixed_x11_client",
        ):
            if marker not in runtime:
                errors.append(f"mixed-session runtime test lacks {marker!r}")

    doc_markers = (
        "two native xdg toplevels and two managed X11 toplevels",
        "native→X11→native and X11→native→X11",
        "protocol-recipient keyboard acknowledgements",
        "unmap/remap",
        "Selection bridging and popup/override-redirect ordering remain separate",
    )
    for marker in doc_markers:
        if marker not in compatibility + "\n" + integration_readme:
            errors.append(f"mixed-session documentation lacks {marker!r}")
    return errors


def read_sources(source_root: Path) -> tuple[str, ...] | None:
    paths = tuple(source_root / path for path in PATHS)
    if not all(path.is_file() for path in paths):
        return None
    return tuple(path.read_text(encoding="utf-8") for path in paths)


def self_test_tamper(sources: tuple[str, ...]) -> list[str]:
    runner, wayland, x11, meson, compatibility, integration_readme = sources
    mutations = (
        (
            "focus-direction",
            runner.replace(
                '("native-a", "x11-a", "native-b", "x11-b")',
                '("native-a", "native-b", "x11-a", "x11-b")',
                1,
            ),
            wayland, x11, meson, compatibility, integration_readme,
        ),
        (
            "key-delivery",
            runner.replace('control.command("KEY 30 press")',
                           'control.command("KEY 29 press")', 1),
            wayland, x11, meson, compatibility, integration_readme,
        ),
        (
            "wrong-protocol-zero",
            runner.replace('f"OK REPORT {token} x11-a=0 x11-b=0 focus=none"',
                           'f"OK REPORT {token} focus=none"', 1),
            wayland, x11, meson, compatibility, integration_readme,
        ),
        (
            "native-unmap",
            runner.replace('wayland.command("UNMAP native-b", "OK UNMAPPED native-b")',
                           'wayland.command("REPORT native-b", "OK")', 1),
            wayland, x11, meson, compatibility, integration_readme,
        ),
        (
            "x11-dissociation",
            runner.replace('and not lifecycle[0]["associated"]',
                           'and lifecycle[0]["associated"]', 1),
            wayland, x11, meson, compatibility, integration_readme,
        ),
        (
            "wayland-input",
            runner,
            wayland.replace("static void keyboard_key(void *data",
                            "static void removed_key(void *data", 1),
            x11, meson, compatibility, integration_readme,
        ),
        (
            "seat-barrier",
            runner,
            wayland.replace(
                "if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||",
                "if (client.compositor == NULL ||",
                1,
            ),
            x11, meson, compatibility, integration_readme,
        ),
        (
            "seat-barrier-order",
            runner,
            wayland.replace(
                "if (wl_display_roundtrip(client.display) < 0 || client.compositor == NULL ||",
                "if (client.compositor == NULL ||\n"
                "\t\t\twl_display_roundtrip(client.display) < 0 ||",
                1,
            ),
            x11, meson, compatibility, integration_readme,
        ),
        (
            "x11-input",
            runner, wayland,
            x11.replace("XCB_EVENT_MASK_FOCUS_CHANGE | XCB_EVENT_MASK_KEY_PRESS",
                        "XCB_EVENT_MASK_FOCUS_CHANGE | XCB_EVENT_MASK_NO_EVENT", 1),
            meson, compatibility, integration_readme,
        ),
        (
            "alternating-damage",
            runner, wayland,
            x11.replace("role->paint_alternate = !role->paint_alternate;", "", 1),
            meson, compatibility, integration_readme,
        ),
        (
            "remap-rearm-order",
            runner, wayland,
            x11.replace(
                "role->desired_mapped = true;\n"
                "\txcb_map_window(client->connection, role->window);",
                "xcb_map_window(client->connection, role->window);\n"
                "\trole->desired_mapped = true;",
                1,
            ),
            meson, compatibility, integration_readme,
        ),
        (
            "unmap-disarm-order",
            runner, wayland,
            x11.replace(
                "role->desired_mapped = false;\n"
                "\t\txcb_unmap_window(client->connection, role->window);",
                "xcb_unmap_window(client->connection, role->window);\n"
                "\t\trole->desired_mapped = false;",
                1,
            ),
            meson, compatibility, integration_readme,
        ),
        (
            "sustained-damage",
            runner, wayland,
            x11.replace("\t\trepaint_mapped_roles(&client);\n", "", 1),
            meson, compatibility, integration_readme,
        ),
        (
            "damage-flush",
            runner, wayland,
            x11.replace("if (sent) xcb_flush(client->connection);", "", 1),
            meson, compatibility, integration_readme,
        ),
        (
            "runtime-registration",
            runner, wayland, x11,
            meson.replace("'mixed native and Xwayland client integration'",
                          "'removed mixed client integration'", 1),
            compatibility, integration_readme,
        ),
        (
            "documented-boundary",
            runner, wayland, x11, meson,
            compatibility.replace(
                "Selection bridging and popup/override-redirect ordering remain separate",
                "Other tests exist", 1,
            ),
            integration_readme.replace(
                "Selection bridging and popup/override-redirect ordering remain separate",
                "Other tests exist", 1,
            ),
        ),
    )
    failures: list[str] = []
    for label, *changed in mutations:
        if not validate_text(*changed):
            failures.append(f"{label} tamper was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    sources = read_sources(arguments.source_root.resolve())
    errors = ["missing mixed-session contract source"] if sources is None else validate_text(*sources)
    if arguments.self_test_tamper and not errors and sources is not None:
        errors.extend(self_test_tamper(sources))
    if errors:
        for error in errors:
            print(f"mixed-session contract failed: {error}")
        return 1
    print("native-Wayland/Xwayland mixed-session and tamper contracts valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
