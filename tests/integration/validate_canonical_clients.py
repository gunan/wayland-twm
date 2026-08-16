#!/usr/bin/env python3
"""Protect canonical real-client package, Meson, and runtime wiring."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


REQUIRED_PACKAGES = {"dialog", "emacs-gtk", "x11-apps", "xfonts-base", "xterm"}
REQUIRED_PROGRAMS = ("xterm", "xclock", "xload", "emacs", "dialog")
EMACS_IDENTITY = (
    'ExpectedWindow("emacs", "WTWM Real Emacs", '
    '"wtwm-real-emacs", "Emacs-gtk")'
)


def validate_text(packages_text: str, meson: str, runner: str) -> list[str]:
    errors: list[str] = []
    packages = {
        line.strip()
        for line in packages_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(REQUIRED_PACKAGES - packages)
    if missing:
        errors.append("canonical Debian packages are missing: " + ", ".join(missing))

    for program in REQUIRED_PROGRAMS:
        marker = f"canonical_{program} = find_program('{program}', required: true)"
        if marker not in meson:
            errors.append(f"Meson lacks required real program lookup: {program}")
        if f"'--{program}', canonical_{program}" not in meson:
            errors.append(f"Meson does not pass the real {program} executable")
    test_start = meson.find("'canonical X11 applications under wtwm'")
    test_end = meson.find("\n  test(\n", test_start + 1)
    test_block = meson[test_start:test_end if test_end >= 0 else len(meson)]
    for marker in (
        "tests/integration/run_canonical_x11_apps.py",
        "'--compositor', wtwm_test_compositor",
        "'--icccm-client', wtwm_xwayland_bridge_client",
        "timeout: 90",
        "is_parallel: false",
    ):
        if marker not in test_block:
            errors.append(f"canonical Meson test lacks {marker!r}")

    try:
        tree = ast.parse(runner)
    except SyntaxError as error:
        errors.append(f"canonical runtime runner is invalid Python: {error}")
        return errors
    sleeps = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
        and node.func.attr == "sleep"
    ]
    if any(
        not call.args
        or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, (int, float))
        or call.args[0].value > 0.01
        for call in sleeps
    ):
        errors.append("canonical runner uses an arbitrary sleep instead of a state gate")
    for marker in (
        "REAL_WINDOWS = (",
        'checked_program(getattr(arguments, name), name)',
        'wait_dialog_process(dialog_app.process.pid, programs["dialog"])',
        'control.command("WAIT 3")',
        "assert_runtime_state(stable_state)",
        "lifecycle_is_override(state, override_xid)",
        "xids_absent(item, observed_xids.icccm)",
        'icccm.stdin.write("EXIT\\n")',
        "purpose-built ICCCM managed and override-redirect cleanup",
        "real canonical application cleanup",
    ):
        if marker not in runner:
            errors.append(f"canonical runtime runner lacks {marker!r}")
    if runner.count(EMACS_IDENTITY) != 1:
        errors.append("canonical runtime runner lacks the Debian emacs-gtk identity")
    for marker in (
        "def stop_dialog_child(parent:",
        "if parent.poll() is not None:",
        "os.kill(dialog_pid, signal.SIGTERM)",
        "os.kill(dialog_pid, signal.SIGKILL)",
        "wait_pid_gone(dialog_pid, 2)",
        "wait_pid_gone(dialog_pid, 3)",
    ):
        if marker not in runner:
            errors.append(f"terminal-dialog parent-reap cleanup lacks {marker!r}")
    dialog_stop = runner.find("stop_dialog_child(dialog_app.process, dialog_pid)")
    group_stop = runner.find(
        "for app in apps:\n                diagnostic_logs.append(stop_group(app))",
        dialog_stop,
    )
    xid_cleanup = runner.find(
        'lambda item: xids_absent(item, observed_xids.real)', group_stop
    )
    if not 0 <= dialog_stop < group_stop < xid_cleanup:
        errors.append("dialog child must be reaped before app groups and XIDs are cleaned")
    for forbidden in ("SystemExit(77)", "continue-on-error", "pytest.skip"):
        if forbidden in runner:
            errors.append(f"canonical runtime runner contains forbidden fallback {forbidden!r}")
    return errors


def read_sources(source_root: Path) -> tuple[str, str, str] | None:
    packages_path = source_root / "scripts/ci/debian-trixie-build-packages.txt"
    meson_path = source_root / "meson.build"
    runner_path = source_root / "tests/integration/run_canonical_x11_apps.py"
    if not all(path.is_file() for path in (packages_path, meson_path, runner_path)):
        return None
    return (
        packages_path.read_text(encoding="utf-8"),
        meson_path.read_text(encoding="utf-8"),
        runner_path.read_text(encoding="utf-8"),
    )


def validate(source_root: Path) -> list[str]:
    sources = read_sources(source_root)
    if sources is None:
        return ["missing canonical-client package, Meson, or runtime file"]
    return validate_text(*sources)


def self_test_tamper(source_root: Path) -> list[str]:
    failures: list[str] = []
    sources = read_sources(source_root)
    if sources is None:
        return ["cannot run tamper tests with missing contract files"]
    packages, meson, runner = sources
    errors = validate_text(packages.replace("emacs-gtk\n", "", 1), meson, runner)
    if not any("emacs-gtk" in error for error in errors):
        failures.append("package-removal tamper was accepted")
    errors = validate_text(
        packages,
        meson,
        runner.replace('control.command("WAIT 3")', "time.sleep(3)", 1),
    )
    if not any("arbitrary sleep" in error or "WAIT 3" in error for error in errors):
        failures.append("sleep-based success tamper was accepted")
    errors = validate_text(
        packages,
        meson,
        runner.replace(
            '"wtwm-real-emacs", "Emacs-gtk")',
            '"wtwm-real-emacs", "Emacs")',
            1,
        ),
    )
    if not any("emacs-gtk identity" in error for error in errors):
        failures.append("emacs class tamper was accepted")
    errors = validate_text(
        packages,
        meson,
        runner.replace(
            "stop_dialog_child(dialog_app.process, dialog_pid)",
            "stop_group(dialog_app)",
            1,
        ),
    )
    if not any("reaped before app groups" in error for error in errors):
        failures.append("dialog parent-reap sequencing tamper was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    source_root = arguments.source_root.resolve()
    errors = validate(source_root)
    if arguments.self_test_tamper and not errors:
        errors.extend(self_test_tamper(source_root))
    if errors:
        for error in errors:
            print(f"canonical-client contract failed: {error}")
        return 1
    print("canonical real-client package, Meson, and runtime contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
