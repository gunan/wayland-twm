#!/usr/bin/env python3
"""Protect the crash, hang, ignored-close, and rapid-remap scenario."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


PATHS = (
    Path("tests/integration/run_client_stress.py"),
    Path("tests/integration/stress_wayland_client.c"),
    Path("tests/integration/stress_x11_client.c"),
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
        return [f"client-stress runner is invalid Python: {error}"]

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
        errors.append("client-stress runner uses an arbitrary success sleep")

    runner_markers = (
        "RAPID_CYCLES = 32",
        'for protocol in ("wayland", "x11"):',
        'target.command("CRASH", "OK CRASH")',
        "status != -signal.SIGABRT",
        'target.command("HANG", "OK HANG")',
        'control.command("PING")',
        'prove_survivor_input(control, survivor, f"during-{protocol}-hang")',
        "target_process.kill()",
        "status != -signal.SIGKILL",
        'native_close.expect_event("EVENT CLOSE 1")',
        'native_close.expect_event("EVENT CLOSE 2")',
        'x11_close.expect_event("EVENT DELETE 1")',
        'wait_process(x11_process, "X11 f.destroy")',
        'for cycle in range(1, RAPID_CYCLES + 1):',
        'lambda item: x11_target_unmapped(item, rapid_xid)',
        'not lifecycle[0]["associated"]',
        'not lifecycle[0]["mapped"]',
        'not lifecycle[0]["has_buffer"]',
        'control.command("KEY 30 press")',
        'survivor.wait_for_key_pair(token)',
        'control.socket.settimeout(10)',
        'control.command("WAIT 1")',
        'f"explicit pointer focus for {protocol} target {title}"',
        'description + " survivor refocus"',
        'if state["focus"] != title:',
        'state["focus"] not in (None, SURVIVOR_TITLE)',
        'state["active"] != state["focus"]',
        '(state["focus"] is None and not state["focus_root"])',
    )
    for marker in runner_markers:
        if marker not in runner:
            errors.append(f"client-stress runner lacks {marker!r}")
    if runner.count('for cycle in range(1, RAPID_CYCLES + 1):') != 2:
        errors.append("client-stress runner must cycle both protocol paths")
    for forbidden in ("SystemExit(77)", "continue-on-error", "|| true"):
        if forbidden in runner:
            errors.append(f"client-stress runner contains fallback {forbidden!r}")

    wayland_markers = (
        "wl_seat_get_keyboard",
        "static void keyboard_key(void *data",
        'printf("EVENT KEY %s %" PRIu32',
        "client->close_count++;",
        'printf("EVENT CLOSE %u\\n", client->close_count);',
        'sscanf(command, "UNMAP %u", &cycle)',
        'sscanf(command, "REMAP %u", &cycle)',
        'sscanf(command, "TITLE %127s", title)',
        "xdg_toplevel_set_title(client->toplevel, client->title);",
        'printf("OK TITLE %s\\n", client->title);',
        "cycle != client->cycle + 1",
        "cycle != client->cycle",
        "wl_surface_attach(client->surface, NULL, 0, 0);",
        "wl_display_roundtrip(client->display)",
        'strcmp(command, "CRASH")',
        "abort();",
        'strcmp(command, "HANG")',
        "for (;;) pause();",
    )
    for marker in wayland_markers:
        if marker not in wayland_client:
            errors.append(f"stress Wayland client lacks {marker!r}")
    if wayland_client.count(
        "xdg_toplevel_set_title(client->toplevel, client->title);"
    ) != 2:
        errors.append("stress Wayland client must set its title on map and mutation")

    x11_markers = (
        '"WM_DELETE_WINDOW"',
        "client->close_count++;",
        'printf("EVENT DELETE %u\\n", client->close_count);',
        'sscanf(command, "UNMAP %u", &cycle)',
        'sscanf(command, "REMAP %u", &cycle)',
        'sscanf(command, "TITLE %127s", title)',
        "set_string(client, XCB_ATOM_WM_NAME, client->title);",
        'printf("OK TITLE %s\\n", client->title);',
        "cycle != client->cycle + 1",
        "cycle != client->cycle",
        "client->desired_mapped = false;",
        "xcb_unmap_window(client->connection, client->window);",
        "client->desired_mapped = true;",
        "xcb_map_window(client->connection, client->window);",
        "client->alternate = !client->alternate;",
        "poll(descriptors, 2, 100)",
        'strcmp(command, "CRASH")',
        "abort();",
        'strcmp(command, "HANG")',
        "for (;;) pause();",
    )
    for marker in x11_markers:
        if marker not in x11_client:
            errors.append(f"stress X11 client lacks {marker!r}")
    if x11_client.count(
        "set_string(client, XCB_ATOM_WM_NAME, client->title);"
    ) != 2:
        errors.append("stress X11 client must set its title on map and mutation")
    unmap = x11_client[x11_client.find("static bool unmap_client"):]
    unmap = unmap[:unmap.find("static bool initialize")]
    if not (0 <= unmap.find("client->desired_mapped = false;") <
            unmap.find("xcb_unmap_window")):
        errors.append("X11 stress unmap does not disarm repaint before request")
    mapping = x11_client[x11_client.find("static bool map_client"):]
    mapping = mapping[:mapping.find("static bool unmap_client")]
    if not (0 <= mapping.find("client->desired_mapped = true;") <
            mapping.find("xcb_map_window")):
        errors.append("X11 stress remap does not arm repaint before request")

    contract_start = meson.find("'adversarial client lifecycle contract'")
    runtime_start = meson.find("'adversarial client lifecycle integration'")
    if contract_start < 0:
        errors.append("Meson lacks portable adversarial-client contract")
    else:
        contract = meson[contract_start:contract_start + 500]
        for marker in ("validate_client_stress.py", "--self-test-tamper"):
            if marker not in contract:
                errors.append(f"adversarial-client contract lacks {marker!r}")
    if runtime_start < 0:
        errors.append("Meson lacks adversarial-client runtime integration")
    else:
        runtime = meson[runtime_start:runtime_start + 650]
        for marker in (
            "run_client_stress.py",
            "wtwm_stress_wayland_client",
            "wtwm_stress_x11_client",
        ):
            if marker not in runtime:
                errors.append(f"adversarial-client runtime lacks {marker!r}")

    documentation = compatibility + "\n" + integration_readme
    doc_markers = (
        "32 numbered unmap/remap cycles",
        "SIGABRT",
        "non-dispatching",
        "survivor keyboard",
        "ignores `f.delete`",
        "native `f.destroy`",
        "X11 `f.destroy`",
        "Random placement leaves focus on PointerRoot",
    )
    for marker in doc_markers:
        if marker not in documentation:
            errors.append(f"adversarial-client documentation lacks {marker!r}")
    return errors


def read_sources(source_root: Path) -> tuple[str, ...] | None:
    paths = tuple(source_root / path for path in PATHS)
    if not all(path.is_file() for path in paths):
        return None
    return tuple(path.read_text(encoding="utf-8") for path in paths)


def self_test_tamper(sources: tuple[str, ...]) -> list[str]:
    runner, wayland, x11, meson, compatibility, integration_readme = sources
    mutations = (
        ("crash", runner.replace('target.command("CRASH", "OK CRASH")',
                                 'target.command("EXIT", "OK EXIT")', 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("focused-exit", runner.replace('if state["focus"] != title:',
                                        "if False:", 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("survivor-root-focus", runner.replace(
            'state["focus"] not in (None, SURVIVOR_TITLE)',
            'state["focus"] != SURVIVOR_TITLE', 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("hang-liveness", runner.replace('control.command("PING")',
                                         'control.command("WAIT 1")', 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("survivor-input", runner.replace('control.command("KEY 30 press")',
                                          'control.command("KEY 29 press")', 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("native-delete", runner.replace(
            'native_close.expect_event("EVENT CLOSE 1")', "", 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("x11-delete", runner.replace(
            'x11_close.expect_event("EVENT DELETE 1")', "", 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("cycle-count", runner.replace("RAPID_CYCLES = 32",
                                       "RAPID_CYCLES = 1", 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("x11-dissociation", runner.replace(
            'not lifecycle[0]["associated"]',
            'lifecycle[0]["associated"]', 1),
         wayland, x11, meson, compatibility, integration_readme),
        ("wayland-close", runner,
         wayland.replace("client->close_count++;", "", 1),
         x11, meson, compatibility, integration_readme),
        ("wayland-hang", runner,
         wayland.replace("for (;;) pause();", "return true;", 1),
         x11, meson, compatibility, integration_readme),
        ("wayland-title", runner,
         wayland.replace(
             "xdg_toplevel_set_title(client->toplevel, client->title);", "", 1),
         x11, meson, compatibility, integration_readme),
        ("x11-delete-protocol", runner, wayland,
         x11.replace('"WM_DELETE_WINDOW"', '"WM_TAKE_FOCUS"', 1),
         meson, compatibility, integration_readme),
        ("x11-title", runner, wayland,
         x11.replace("set_string(client, XCB_ATOM_WM_NAME, client->title);",
                     "", 1),
         meson, compatibility, integration_readme),
        ("x11-remap-order", runner, wayland,
         x11.replace(
             "client->desired_mapped = true;\n"
             "\txcb_map_window(client->connection, client->window);",
             "xcb_map_window(client->connection, client->window);\n"
             "\tclient->desired_mapped = true;",
             1,
         ), meson, compatibility, integration_readme),
        ("runtime-registration", runner, wayland, x11,
         meson.replace("'adversarial client lifecycle integration'",
                       "'removed adversarial lifecycle integration'", 1),
         compatibility, integration_readme),
        ("documentation", runner, wayland, x11, meson,
         compatibility.replace("32 numbered unmap/remap cycles", "few cycles", 1),
         integration_readme.replace("32 numbered unmap/remap cycles", "few cycles", 1)),
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
    errors = (["missing adversarial-client contract source"] if sources is None
              else validate_text(*sources))
    if arguments.self_test_tamper and not errors and sources is not None:
        errors.extend(self_test_tamper(sources))
    if errors:
        for error in errors:
            print(f"adversarial-client contract failed: {error}")
        return 1
    print("adversarial client lifecycle and tamper contracts valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
