#!/usr/bin/env python3
"""Portable source contract for the rapid native popup lifecycle stress test."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


MARKERS = (
    "DEFAULT_ITERATIONS = 128",
    "MAX_ITERATIONS = 4096",
    "for iteration in range(1, iterations + 1):",
    'client_command(client, "MAP_POPUP", "POPUP_MAPPED")',
    'client_command(client, "DESTROY_POPUP", "POPUP_DESTROYED")',
    'client_command(client, "UNMAP_TOPLEVEL", "TOPLEVEL_UNMAPPED")',
    'client, "DROP_DISMISSED_POPUP", "DISMISSED_POPUP_DROPPED"',
    'client_command(client, "REMAP_TOPLEVEL", "TOPLEVEL_REMAPPED")',
    'assert_bounded_state(state, mapped=True, popup_mapped=True)',
    'assert_bounded_state(state, mapped=False, popup_mapped=False)',
    'state["focus"] is not None or state["active"] is not None',
    'state["pointer_window"] == TITLE',
    'not popup["mapped"] or not popup["visible"]',
    'popup["x"] + popup["width"] > 640',
    'control.command("PING")',
    'control.command("QUIT")',
    "compositor.returncode != 0",
)


def validate_source(source: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"popup lifecycle stress runner is invalid Python: {error}"]
    for marker in MARKERS:
        if marker not in source:
            errors.append(f"popup lifecycle stress runner lacks {marker!r}")
    if source.count('client_command(client, "MAP_POPUP", "POPUP_MAPPED")') != 1:
        errors.append("popup map operation is not uniquely inside the bounded loop")
    sleeps = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "time"
        and call.func.attr == "sleep"
    ]
    if any(
        not call.args or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, (int, float))
        or call.args[0].value > 0.01
        for call in sleeps
    ):
        errors.append("popup lifecycle stress uses an arbitrary success sleep")
    for forbidden in ("SystemExit(77)", "continue-on-error", "|| true"):
        if forbidden in source:
            errors.append(f"popup lifecycle stress contains fallback {forbidden!r}")
    return errors


def self_test(source: str) -> None:
    if validate_source(source):
        raise RuntimeError("valid popup lifecycle stress source was rejected")
    for marker in (
        "DEFAULT_ITERATIONS = 128",
        'client_command(client, "UNMAP_TOPLEVEL", "TOPLEVEL_UNMAPPED")',
        'assert_bounded_state(state, mapped=True, popup_mapped=True)',
        'control.command("PING")',
        'control.command("QUIT")',
    ):
        tampered = source.replace(marker, marker + "_TAMPERED", 1)
        if not validate_source(tampered):
            raise RuntimeError(f"popup lifecycle stress tamper was accepted: {marker!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner", type=Path,
        default=Path(__file__).with_name("run_m9_popup_lifecycle_stress.py"),
    )
    arguments = parser.parse_args()
    source = arguments.runner.read_text(encoding="utf-8")
    errors = validate_source(source)
    if errors:
        raise SystemExit("invalid popup lifecycle stress contract: " + "; ".join(errors))
    self_test(source)
    print("m9 popup lifecycle stress contract/tamper tests pass")


if __name__ == "__main__":
    main()
