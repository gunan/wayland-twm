#!/usr/bin/env python3
"""Keep the live Milestone 10 command differential fail-closed and wired."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tarfile


REQUIRED = {
    "tests/integration/run_m10_command_differential.py": (
        'PHASES = ("explicit", "alias", "shell", "empty", "startwm")',
        '"spelling": "f.exec"',
        '"spelling": "!"',
        '"spelling": "f.startwm"',
        '"canonical": "f.exec"',
        '"decoded_command": item["command"]',
        '"operation": "system"',
        '"operation": "execvp"',
        '"operation": "execl"',
        '"operation": "execlp"',
        '{"operation": "execl", "argv": ["/bin/sh", "-c", cases["shell"]["command"]]}',
        '"unchanged_shell_text": item["command"]',
        '"direct_argv": item["argv"]',
        '"intentional_non_execution": phase in {"empty", "startwm"}',
        '"unexplained_differences": 0',
        'if version != "twm 1.0.13.1":',
        '"unavoidable-wayland-handoff-translation"',
        'raise RuntimeError("shell-text tamper was accepted")',
        'select.select([process.stdout], [], [], 0.1)',
        '"result": "failed"',
        'result["error"] = str(error)',
        'for path in arguments.evidence.iterdir():',
    ),
    "tests/integration/m10_command_interposer.c": (
        'record_call("system", 1, arguments);',
        'record_call("execvp", argument_count(argv), argv);',
        'variadic_exec("execl", path, arg, values, false)',
        'variadic_exec("execlp", file, arg, values, true)',
        'WTWM_COMMAND_CALL_LOG',
    ),
    "tests/integration/m10_command_observer.c": (
        'usage: m10-command-observer LOG PHASE [ARGUMENT ...]',
        'O_WRONLY | O_CREAT | O_APPEND',
        'written != (ssize_t)used',
    ),
    ".github/workflows/build.yml": (
        "tests/integration/m10_command_interposer.c",
        "tests/integration/m10_command_observer.c",
        "Compare live command dispatch with reference twm",
        "python3 -B tests/integration/run_m10_command_differential.py",
        "--config-check \"$GITHUB_WORKSPACE/build-differential/wtwm-config\"",
        "Upload Milestone 10 live command differential",
        "m10-command-differential-evidence",
    ),
    "meson.build": (
        "Milestone 10 live command differential contract",
        "tests/integration/validate_m10_command_differential.py",
        "Milestone 10 live command differential model",
        "tests/integration/run_m10_command_differential.py",
    ),
    "README.md": (
        "- [x] **Agent:** Add controlled command observers and compare the action spelling,",
    ),
    "tests/integration/README.md": (
        "run_m10_command_differential.py",
        "controlled interposer at the libc",
        "intentional",
        "non-execution",
    ),
    "docs/COMPATIBILITY.md": (
        "command differential observes the libc launch boundary",
        "records all eleven as live reference differentials",
    ),
    "tests/certification/validate_m10_differential_contract.py": (
        '"commands-launched": "live-reference-differential"',
        "live command differential coverage underclaim was accepted",
    ),
}

FORBIDDEN = {
    "tests/integration/run_m10_command_differential.py": (
        "allowed_call_difference", "ignore_shell_text", "skip_execution_check",
    ),
}

REFERENCE_SNIPPETS = (
    "case F_EXEC:",
    "Execute(action);",
    "execlp(\"/bin/sh\", \"sh\", \"-c\", action, (void *) NULL);",
    "(void) system(s);",
)


def validate_contract(text: str) -> list[str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return [f"differential contract is invalid JSON: {error}"]
    matches = [
        item for item in value.get("dimensions", [])
        if isinstance(item, dict) and item.get("id") == "commands-launched"
    ] if isinstance(value, dict) else []
    if len(matches) != 1:
        return ["differential contract must contain exactly one commands-launched dimension"]
    command = matches[0]
    errors = []
    if command.get("coverage_status") != "live-reference-differential":
        errors.append("commands-launched is not a live reference differential")
    mappings = command.get("mappings", {})
    if "tests/integration/run_m10_command_differential.py" not in mappings.get(
            "runners", []):
        errors.append("commands-launched lacks the live runner mapping")
    if "tests/integration/validate_m10_command_differential.py" not in mappings.get(
            "validators", []):
        errors.append("commands-launched lacks the fail-closed validator mapping")
    return errors


def validate(files: dict[str, str], reference_source: str) -> list[str]:
    errors: list[str] = []
    for name, needles in REQUIRED.items():
        for needle in needles:
            if needle not in files.get(name, ""):
                errors.append(f"{name} lacks {needle!r}")
    for name, needles in FORBIDDEN.items():
        for needle in needles:
            if needle in files.get(name, ""):
                errors.append(f"{name} contains forbidden relaxation {needle!r}")
    for snippet in REFERENCE_SNIPPETS:
        if snippet not in reference_source:
            errors.append(f"frozen reference menus.c lacks {snippet!r}")
    errors.extend(validate_contract(files.get(
        "reference/certification/m10-differential-contract.json", ""
    )))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    root = arguments.source_root.resolve()
    names = set(REQUIRED) | set(FORBIDDEN) | {
        "reference/certification/m10-differential-contract.json",
    }
    files = {name: (root / name).read_text(encoding="utf-8") for name in names}
    archive = root / "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz"
    with tarfile.open(archive, "r:xz") as bundle:
        member = bundle.extractfile("twm-1.0.13.1/src/menus.c")
        reference_source = member.read().decode("utf-8") if member is not None else ""
    errors = validate(files, reference_source)
    if arguments.self_test_tamper and not errors:
        tampered = copy.deepcopy(files)
        tampered["tests/integration/run_m10_command_differential.py"] = tampered[
            "tests/integration/run_m10_command_differential.py"
        ].replace(
            '{"operation": "execl", "argv": ["/bin/sh", "-c", cases["shell"]["command"]]}',
            '{"operation": "execl", "argv": ["/bin/sh", "-c", "anything"]}',
            1,
        )
        if not validate(tampered, reference_source):
            errors.append("exact shell-text tamper was accepted")
        tampered = copy.deepcopy(files)
        contract = json.loads(tampered[
            "reference/certification/m10-differential-contract.json"
        ])
        contract["dimensions"][8]["coverage_status"] = "partial-existing-infrastructure"
        tampered["reference/certification/m10-differential-contract.json"] = json.dumps(
            contract
        )
        if not validate(tampered, reference_source):
            errors.append("command coverage-status tamper was accepted")
    if errors:
        for error in errors:
            print(f"m10 command differential error: {error}")
        return 1
    print("Milestone 10 live command differential contract verified")
    if arguments.self_test_tamper:
        print("Milestone 10 live command differential tamper checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
