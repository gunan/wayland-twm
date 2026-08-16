#!/usr/bin/env python3
"""Protect the live reference-twm/wtwm canonical X11 differential."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/build.yml")
RUNNER_PATH = Path("tests/integration/run_x11_differential.py")
PROBE_PATH = Path("tests/integration/x11_differential_probe.c")
COMPATIBILITY_PATH = Path("docs/COMPATIBILITY.md")
CONFIG_PATH = Path("tests/integration/x11_differential.twmrc")


def validate_text(
    workflow: str, runner: str, probe: str, compatibility: str, config: str
) -> list[str]:
    errors: list[str] = []
    job_start = workflow.find("  x11-differential:\n")
    job = workflow[job_start:] if job_start >= 0 else ""
    for marker in (
        "cat scripts/ci/debian-trixie-build-packages.txt",
        "cat reference/environment/debian-trixie-x11-packages.txt",
        "tests/reference/build_reference_twm.sh",
        "meson setup build-differential -Dcompositor=enabled -Dwerror=true",
        "-Wall -Wextra -Wpedantic -Werror",
        "tests/integration/x11_differential_probe.c",
        "tests/integration/run_x11_differential.py",
        "--reference-twm /tmp/reference-build/twm",
        "--compositor \"$GITHUB_WORKSPACE/build-differential/wtwm-test-compositor\"",
        "--icccm-client \"$GITHUB_WORKSPACE/build-differential/wtwm-xwayland-bridge-client\"",
        "--scenario \"$GITHUB_WORKSPACE/tests/integration/x11_differential.twmrc\"",
        "name: x11-differential",
        "/tmp/x11-differential.json",
        "/tmp/x11-differential-evidence",
        "if-no-files-found: error",
    ):
        if marker not in job:
            errors.append(f"dedicated X11 differential job lacks {marker!r}")
    if "if: always()" not in job:
        errors.append("X11 differential artifact is not uploaded on failure")
    for forbidden in ("continue-on-error", "|| true", "pytest.skip", "SystemExit(77)"):
        if forbidden in job or forbidden in runner:
            errors.append(f"X11 differential contains forbidden fallback {forbidden!r}")

    try:
        tree = ast.parse(runner)
    except SyntaxError as error:
        errors.append(f"X11 differential runner is invalid Python: {error}")
        return errors
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
        errors.append("X11 differential uses an arbitrary sleep instead of a bounded state gate")
    for marker in (
        "commands = canonical_commands(programs)",
        "reference = run_reference(",
        "wtwm = run_wtwm(",
        "if reference != wtwm:",
        'version != "twm 1.0.13.1"',
        '"reference twm sentinel reparent readiness"',
        "reference_ready(observed)",
        "wtwm_control_ready(state)",
        'state["xwayland_lifecycle"]',
        "if not item[\"root_parent\"]:",
        'control.command("WAIT 3")',
        "wait_dialog_process(dialog_app.process.pid, dialog)",
        'icccm.stdin.write("EXIT\\n")',
        '"result": "equivalent"',
        '"result": "failed"',
        'evidence / "reference.json"',
        'evidence / "wtwm.json"',
        'evidence / "runner-error.log"',
        '"reference": "managed client has a distinct reparent frame"',
        '"wtwm": "managed client has a compositor scene decoration"',
        "EXCLUDED_COMPARISONS = (",
        '"exact frame and client geometry (Milestone 4)"',
        '"pixel rendering and decoration appearance (Milestone 5)"',
        '"native-Wayland and cross-protocol semantics (later Milestone 3 testing)"',
    ):
        if marker not in runner:
            errors.append(f"X11 differential runner lacks {marker!r}")
    if runner.count("canonical_commands(programs)") != 1:
        errors.append("canonical client commands must be constructed exactly once and shared")
    if "WM_S0" in runner:
        errors.append("runner must prove reference readiness by reparenting, not WM_S0 ownership")
    if runner.count("launch_workload(commands, icccm_client, environment)") != 1 or runner.count(
        "launch_workload(commands, icccm_client, client_environment)"
    ) != 1:
        errors.append("reference and wtwm sessions do not consume the one shared command set")
    for role_marker in (
        'Role("xterm", "WTWM Real Xterm", "wtwm-real-xterm", "WtwmRealXterm")',
        'Role("xclock", "WTWM Real XClock", "wtwm-real-xclock", "XClock")',
        'Role("xload", "WTWM Real XLoad", "wtwm-real-xload", "XLoad")',
        'Role("emacs", "WTWM Real Emacs", "wtwm-real-emacs", "Emacs-gtk")',
        '"terminal-dialog"',
        '"icccm-normal"',
        '"icccm-transient"',
        'Role("icccm-override", "xwm-override-redirect", None, None, True)',
    ):
        if role_marker not in runner:
            errors.append(f"canonical role set lacks {role_marker!r}")

    for marker in (
        "wait_for_reference_reparent",
        "WTWM differential readiness sentinel",
        "XQueryTree",
        "XGetWindowAttributes",
        "XGetClassHint",
        "XGetTransientForHint",
        "XGetWMNormalHints",
        "XGetWMHints",
        "XGetWMProtocols",
        "XGetIconName",
        'XInternAtom(display, "_NET_WM_ICON", False)',
        "drawable_geometry",
        'fputs("{\\\"clients\\\":[", stdout)',
    ):
        if marker not in probe:
            errors.append(f"X11 observer lacks {marker!r}")
    if "usleep(" in probe or "sleep(" in probe or "nanosleep(" in probe:
        errors.append("X11 observer embeds a timing-based success condition")

    for marker in (
        "same Debian client commands and the same configuration",
        "reparent frame",
        "scene decoration",
        "Exact frame geometry, pixel rendering",
    ):
        if marker not in compatibility:
            errors.append(f"compatibility boundary lacks {marker!r}")
    expected_config = (
        "NoDefaults\nRandomPlacement\nNoGrabServer\nNoIconManagers\n"
        "NoHighlight\nNoTitleFocus\n"
    )
    if config != expected_config:
        errors.append("shared X11 differential configuration differs from its fixed content")
    return errors


def read_sources(source_root: Path) -> tuple[str, str, str, str, str] | None:
    paths = (
        source_root / WORKFLOW_PATH,
        source_root / RUNNER_PATH,
        source_root / PROBE_PATH,
        source_root / COMPATIBILITY_PATH,
        source_root / CONFIG_PATH,
    )
    if not all(path.is_file() for path in paths):
        return None
    return tuple(path.read_text(encoding="utf-8") for path in paths)  # type: ignore[return-value]


def validate(source_root: Path) -> list[str]:
    sources = read_sources(source_root)
    if sources is None:
        return ["missing X11 differential workflow, runner, observer, or documentation"]
    return validate_text(*sources)


def self_test_tamper(source_root: Path) -> list[str]:
    sources = read_sources(source_root)
    if sources is None:
        return ["cannot tamper-test missing X11 differential sources"]
    workflow, runner, probe, compatibility, config = sources
    failures: list[str] = []
    mutations = (
        (
            "workflow-job",
            workflow.replace("  x11-differential:\n", "  removed-differential:\n", 1),
            runner,
            probe,
            compatibility,
            config,
        ),
        (
            "live-comparison",
            workflow,
            runner.replace("if reference != wtwm:", "if False:", 1),
            probe,
            compatibility,
            config,
        ),
        (
            "shared-commands",
            workflow,
            runner.replace(
                "reference_twm, scenario, commands, icccm_client, probe,",
                "reference_twm, scenario, canonical_commands(programs), icccm_client, probe,",
                1,
            ),
            probe,
            compatibility,
            config,
        ),
        (
            "scene-management",
            workflow,
            runner.replace('if not item["root_parent"]:', "if False:", 1),
            probe,
            compatibility,
            config,
        ),
        (
            "timing-gate",
            workflow,
            runner.replace("time.sleep(0.01)", "time.sleep(1)", 1),
            probe,
            compatibility,
            config,
        ),
        (
            "icon-observation",
            workflow,
            runner,
            probe.replace('XInternAtom(display, "_NET_WM_ICON", False)',
                          'XInternAtom(display, "_REMOVED_ICON", False)', 1),
            compatibility,
            config,
        ),
        (
            "documented-boundary",
            workflow,
            runner,
            probe,
            compatibility.replace("Exact frame geometry, pixel rendering", "Later work", 1),
            config,
        ),
        (
            "shared-config",
            workflow,
            runner,
            probe,
            compatibility,
            config.replace("RandomPlacement\n", "", 1),
        ),
    )
    for (
        label,
        changed_workflow,
        changed_runner,
        changed_probe,
        changed_docs,
        changed_config,
    ) in mutations:
        if not validate_text(
            changed_workflow, changed_runner, changed_probe, changed_docs, changed_config
        ):
            failures.append(f"{label} tamper was accepted")
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
            print(f"X11 differential contract failed: {error}")
        return 1
    print("live reference-twm/wtwm X11 differential contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
