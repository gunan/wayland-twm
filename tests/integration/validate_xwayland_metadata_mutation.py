#!/usr/bin/env python3
"""Protect the Xwayland live metadata-mutation runtime scenario."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


INITIAL_SIZE_HINTS = (880, 80, 60, 320, 240, 40, 30, 20, 10, 0, 0, 0, 0, 1)
UPDATED_SIZE_HINTS = (880, 100, 70, 300, 220, 50, 40, 25, 15, 0, 0, 0, 0, 1)
MUTATION_COMMANDS = (
    'command(client, "UPDATE", "UPDATED")',
    'command(client, "TRUNCATE_ICON", "TRUNCATED_ICON_SET")',
    'command(client, "RESTORE_ICON", "ICON_RESTORED")',
    'command(client, "CLEAR_TRANSIENT", "TRANSIENT_CLEARED")',
    'command(client, "RESTORE_TRANSIENT", "TRANSIENT_RESTORED")',
    'command(client, "CONFIGURE", "CONFIGURE_REQUESTED")',
)


def assigned_tuple(tree: ast.Module, name: str) -> tuple[object, ...] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            value = ast.literal_eval(node.value)
            return value if isinstance(value, tuple) else None
    return None


def function_text(source: str, start: str, end: str) -> str:
    begin = source.find(start)
    finish = source.find(end, begin + len(start))
    if begin < 0 or finish < 0:
        return ""
    return source[begin:finish]


def validate_text(client: str, runner: str, meson: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(runner)
    except SyntaxError as error:
        return [f"metadata mutation runner is invalid Python: {error}"]

    if assigned_tuple(tree, "INITIAL_SIZE_HINTS") != INITIAL_SIZE_HINTS:
        errors.append("initial WM_NORMAL_HINTS tuple is not exact")
    if assigned_tuple(tree, "UPDATED_SIZE_HINTS") != UPDATED_SIZE_HINTS:
        errors.append("updated WM_NORMAL_HINTS tuple is not exact")

    positions = [runner.find(command) for command in MUTATION_COMMANDS]
    if any(runner.count(command) != 1 for command in MUTATION_COMMANDS):
        errors.append("metadata mutation command sequence is incomplete or ambiguous")
    elif positions != sorted(positions) or len(set(positions)) != len(positions):
        errors.append("metadata mutation commands are out of order")

    for marker in (
        "initial_icon_ids, initial_net_icon = assert_initial_metadata(parent, transient)",
        '"xwm-parent-initial", "x11", "xwm-instance-initial", "XwmClassInitial"',
        'not parent["supports_delete"] or not parent["urgent"] or parent["input"]',
        'parent["icon_name"] != "xwm-icon-initial"',
        "size_hint_values(parent) != INITIAL_SIZE_HINTS",
        '("xwm-parent-updated", "x11", "xwm-instance-updated", "XwmClassUpdated")',
        'parent["icon_name"] == "xwm-icon-updated"',
        'parent["supports_delete"] and not parent["urgent"] and parent["input"]',
        "all(after != before for before, after in zip(initial_icon_ids, icon_ids))",
        "size_hint_values(parent) == UPDATED_SIZE_HINTS",
        "icon[:3] == (1, 3, 2) and icon[3] != 0 and icon[4] is False",
        "icon[3] != initial_net_icon[3]",
        "(0, 0, 0, 0, True)",
        "updated_net_icon",
        'window(item, "xwm-transient")["parent"] == 0',
        'window(item, "xwm-transient")["parent"] ==',
        'entry["width"] == 275 and entry["height"] == 190 and',
        "size_hint_values(entry) == UPDATED_SIZE_HINTS",
        'control.command("WAIT 1")',
    ):
        if marker not in runner:
            errors.append(f"metadata runtime assertion lacks {marker!r}")
    if runner.count("updated_net_icon") != 2:
        errors.append("restored _NET_WM_ICON is not compared with its updated tuple")

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "time"
            and node.func.attr == "sleep"
        ):
            continue
        if (
            not node.args
            or not isinstance(node.args[0], ast.Constant)
            or not isinstance(node.args[0].value, (int, float))
            or node.args[0].value > 0.01
        ):
            errors.append("metadata runner uses an arbitrary success sleep")

    initialize = function_text(
        client, "static bool initialize(struct client *client)",
        "static void update_metadata(struct client *client)",
    )
    update = function_text(
        client, "static void update_metadata(struct client *client)",
        "static void create_stubborn(struct client *client)",
    )
    for marker in (
        "create_hint_icons(client, 16);",
        "set_normal_hints(client, 80, 60, 320, 240, 40, 30, 20, 10);",
        "set_wm_hints(client, true, false);",
        "set_net_wm_icon(client, 2, 2, UINT32_C(0x10));",
    ):
        if marker not in initialize:
            errors.append(f"initial X11 metadata setup lacks {marker!r}")
    update_markers = (
        '"xwm-parent-updated"',
        '"xwm-icon-updated"',
        '"xwm-instance-updated"',
        '"XwmClassUpdated"',
        "set_normal_hints(client, 100, 70, 300, 220, 50, 40, 25, 15);",
        "create_hint_icons(client, 24);",
        "set_wm_hints(client, false, true);",
        "xcb_free_pixmap(client->connection, old_icon_pixmap);",
        "xcb_free_pixmap(client->connection, old_icon_mask);",
        "xcb_destroy_window(client->connection, old_icon_window);",
        "set_net_wm_icon(client, 3, 2, UINT32_C(0x20));",
    )
    update_positions = [update.find(marker) for marker in update_markers]
    if any(position < 0 for position in update_positions):
        errors.append("X11 UPDATE does not mutate every metadata and icon resource")
    elif update_positions != sorted(update_positions):
        errors.append("X11 UPDATE mutations are out of order")

    test_start = meson.find("'Xwayland metadata mutation contract'")
    test_end = meson.find("\ntest(\n", test_start + 1)
    test_block = meson[test_start:test_end if test_end >= 0 else len(meson)]
    for marker in (
        "tests/integration/validate_xwayland_metadata_mutation.py",
        "--source-root', meson.project_source_root()",
        "--self-test-tamper",
    ):
        if marker not in test_block:
            errors.append(f"metadata mutation Meson test lacks {marker!r}")
    return errors


def read_sources(source_root: Path) -> tuple[str, str, str] | None:
    paths = (
        source_root / "tests/integration/xwayland_bridge_client.c",
        source_root / "tests/integration/run_xwayland_bridge.py",
        source_root / "meson.build",
    )
    if not all(path.is_file() for path in paths):
        return None
    return (
        paths[0].read_text(encoding="utf-8"),
        paths[1].read_text(encoding="utf-8"),
        paths[2].read_text(encoding="utf-8"),
    )


def self_test_tamper(client: str, runner: str, meson: str) -> list[str]:
    failures: list[str] = []
    tampered = runner.replace(
        "UPDATED_SIZE_HINTS = (880, 100, 70, 300, 220, 50, 40, 25, 15,",
        "UPDATED_SIZE_HINTS = (880, 101, 70, 300, 220, 50, 40, 25, 15,",
        1,
    )
    if not validate_text(client, tampered, meson):
        failures.append("updated WM_NORMAL_HINTS tamper was accepted")

    tampered = runner.replace("after != before", "after == before", 1)
    if not validate_text(client, tampered, meson):
        failures.append("WM_HINTS icon identifier tamper was accepted")

    truncate, restore = MUTATION_COMMANDS[1:3]
    tampered = runner.replace(truncate, "MUTATION_ORDER_SENTINEL", 1)
    tampered = tampered.replace(restore, truncate, 1)
    tampered = tampered.replace("MUTATION_ORDER_SENTINEL", restore, 1)
    if not validate_text(client, tampered, meson):
        failures.append("metadata command-order tamper was accepted")

    tampered_client = client.replace("create_hint_icons(client, 24);", "", 1)
    if not validate_text(tampered_client, runner, meson):
        failures.append("WM_HINTS resource-rotation tamper was accepted")

    tampered = runner.replace("updated_net_icon", "truncated_net_icon", 1)
    if not validate_text(client, tampered, meson):
        failures.append("_NET_WM_ICON restoration tamper was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    sources = read_sources(arguments.source_root.resolve())
    if sources is None:
        errors = ["missing Xwayland metadata mutation contract source"]
    else:
        errors = validate_text(*sources)
        if arguments.self_test_tamper and not errors:
            errors.extend(self_test_tamper(*sources))
    if errors:
        for error in errors:
            print(f"Xwayland metadata mutation contract failed: {error}")
        return 1
    print("Xwayland metadata mutation and tamper contracts valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
