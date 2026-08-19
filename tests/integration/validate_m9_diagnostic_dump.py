#!/usr/bin/env python3
"""Portable source contract for the SIGUSR2 diagnostic dump runtime test."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


MARKERS = (
    '"--diagnostic-dump", str(dump_path)',
    "os.kill(compositor.pid, signal.SIGUSR2)",
    'marker = f"event=diagnostic_dump outcome={outcome} signal={signal.SIGUSR2}"',
    'control.command("PING")',
    'SCHEMA = "wtwm-diagnostic-v1"',
    'stat.S_IMODE(status.st_mode) != 0o600',
    '"outputs": len(state["outputs"])',
    '"windows": len(state["windows"])',
    '"popups": len(state["popups"])',
    '"inputs": len(state["inputs"])',
    'len(payload["outputs"]) != min(expected_counts["outputs"], MAX_OUTPUTS)',
    'len(payload["windows"]) != min(expected_counts["windows"], MAX_WINDOWS)',
    "os.mkfifo(dump_path, mode=0o600)",
    "stat.S_ISFIFO(dump_path.lstat().st_mode)",
    "dump_path.symlink_to(sentinel)",
    "if not dump_path.is_symlink()",
    "sentinel.read_text(encoding=\"utf-8\") != sentinel_content",
    'trigger_dump(compositor, control, log_path, "failed", 2)',
    'control.command("QUIT")',
    "compositor.returncode != 0",
)

COMPOSITOR_MARKERS = (
    "if (!initialize_session_signals(&server)) goto fail_display;",
    "if (!initialize_diagnostic_signal(&server)) goto fail_display;",
    "server.backend = wlr_headless_backend_create(",
    "fail_display:\n\tfinish_input_adapter(&server);\n"
    "\tfinish_diagnostic_signal(&server);",
)


def validate_source(source: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"diagnostic dump runner is invalid Python: {error}"]
    for marker in MARKERS:
        if marker not in source:
            errors.append(f"diagnostic dump runner lacks {marker!r}")
    signal_calls = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "os"
        and call.func.attr == "kill"
    ]
    if len(signal_calls) != 1:
        errors.append("diagnostic dump runner must centralize SIGUSR2 in one helper")
    for forbidden in ("SystemExit(77)", "continue-on-error", "|| true"):
        if forbidden in source:
            errors.append(f"diagnostic dump runner contains fallback {forbidden!r}")
    return errors


def validate_compositor(source: str) -> list[str]:
    errors = [
        f"compositor lacks {marker!r}"
        for marker in COMPOSITOR_MARKERS if marker not in source
    ]
    if errors:
        return errors
    session_index = source.index(COMPOSITOR_MARKERS[0])
    diagnostic_index = source.index(COMPOSITOR_MARKERS[1])
    backend_index = source.index(COMPOSITOR_MARKERS[2])
    if not session_index < diagnostic_index < backend_index:
        errors.append(
            "SIGUSR2 must be blocked before wlroots can create worker threads"
        )
    return errors


def self_test(source: str, compositor: str) -> None:
    if validate_source(source):
        raise RuntimeError("valid diagnostic dump source was rejected")
    if validate_compositor(compositor):
        raise RuntimeError("valid compositor diagnostic wiring was rejected")
    tampers = {
        '"--diagnostic-dump", str(dump_path)': '"--dump", str(dump_path)',
        "os.kill(compositor.pid, signal.SIGUSR2)":
            "os.kill(compositor.pid, signal.SIGUSR1)",
        'stat.S_IMODE(status.st_mode) != 0o600':
            'stat.S_IMODE(status.st_mode) != 0o644',
        "os.mkfifo(dump_path, mode=0o600)": "os.mkfifo(dump_path, mode=0o644)",
        "dump_path.symlink_to(sentinel)": "dump_path.write_text(sentinel_content)",
        'trigger_dump(compositor, control, log_path, "failed", 2)':
            'trigger_dump(compositor, control, log_path, "failed", 1)',
        'control.command("QUIT")': 'control.command("QUIT_NOW")',
    }
    for marker, replacement in tampers.items():
        tampered = source.replace(marker, replacement, 1)
        if not validate_source(tampered):
            raise RuntimeError(f"diagnostic dump tamper was accepted: {marker!r}")
    for marker in COMPOSITOR_MARKERS:
        tampered = compositor.replace(marker, "REMOVED", 1)
        if not validate_compositor(tampered):
            raise RuntimeError(
                f"compositor diagnostic tamper was accepted: {marker!r}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner", type=Path,
        default=Path(__file__).with_name("run_m9_diagnostic_dump.py"),
    )
    parser.add_argument(
        "--source-root", type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    arguments = parser.parse_args()
    source = arguments.runner.read_text(encoding="utf-8")
    compositor = (arguments.source_root / "src/wtwm.c").read_text(encoding="utf-8")
    errors = validate_source(source) + validate_compositor(compositor)
    if errors:
        raise SystemExit("invalid diagnostic dump contract: " + "; ".join(errors))
    self_test(source, compositor)
    print("m9 diagnostic dump contract/tamper tests pass")


if __name__ == "__main__":
    main()
