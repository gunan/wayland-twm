#!/usr/bin/env python3
"""Keep the live close/destruction differential fail-closed and wired."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tarfile


REQUIRED = {
    "tests/integration/run_m10_close_differential.py": (
        'GRACEFUL_TITLE = "m10-close-graceful"',
        'FORCED_TITLE = "m10-close-forced"',
        'NATIVE_TITLE = "m10-close-native"',
        'graceful.expect("EVENT DELETE 1")',
        'forced.command("REPORT", "OK REPORT close=1 mapped=1 cycle=0")',
        '"target_survived_delete": True',
        'if wait_process(forced_process, "reference forced client") == 0:',
        '"prior_lifecycle_removed_before_recreate": True',
        'sum(item["title"] == FORCED_TITLE for item in state["windows"]) != 1',
        'native.expect_event("EVENT CLOSE 1")',
        'native.expect_event("EVENT CLOSE 2")',
        '"unavoidable-native-close-only-translation"',
        '"unexplained_differences": 0',
        'if version != "twm 1.0.13.1":',
        'raise RuntimeError("close-outcome tamper was accepted")',
    ),
    "tests/integration/m10_close_observer.c": (
        "find_named(display, children[index], title, depth + 1, match);",
        "outer_frame(display, match.client, root, &reparented)",
        '"reparented\\\":%s}',
    ),
    "tests/integration/m10_close_differential.twmrc": (
        "NoDefaults",
        "NoGrabServer",
        "RandomPlacement",
        "Button1 = : title : f.delete",
        "Button2 = : title : f.destroy",
    ),
    ".github/workflows/build.yml": (
        "tests/integration/m10_close_observer.c",
        "Compare live close and destruction with reference twm",
        "python3 -B tests/integration/run_m10_close_differential.py",
        "--xvfb /usr/bin/Xvfb",
        "--config \"$GITHUB_WORKSPACE/tests/integration/m10_close_differential.twmrc\"",
        "--x11-client \"$GITHUB_WORKSPACE/build-differential/wtwm-stress-x11-client\"",
        "--native-client \"$GITHUB_WORKSPACE/build-differential/wtwm-stress-wayland-client\"",
        "Upload Milestone 10 close/destruction differential",
        "m10-close-differential-evidence",
    ),
    "meson.build": (
        "Milestone 10 close/destruction differential contract",
        "tests/integration/validate_m10_close_differential.py",
        "Milestone 10 close/destruction differential model",
        "tests/integration/run_m10_close_differential.py",
    ),
    "README.md": (
        "- [x] **Agent:** Add one end-to-end reference/`wtwm` X11 close-and-destruction",
    ),
    "tests/integration/README.md": (
        "run_m10_close_differential.py",
        "cooperative `WM_DELETE_WINDOW`",
        "destroy-and-recreate",
        "xdg-shell close-only translation",
    ),
    "docs/COMPATIBILITY.md": (
        "records ten as live reference differentials",
        "close/destruction differential",
        "native close-only translation",
    ),
    "tests/certification/validate_m10_differential_contract.py": (
        '"client-close-and-destruction": "live-reference-differential"',
        "live close differential coverage underclaim was accepted",
    ),
}

FORBIDDEN = {
    "tests/integration/run_m10_close_differential.py": (
        "allow_stale_state", "ignore_destroy_failure", "skip_native_close",
    ),
}

REFERENCE_SNIPPETS = (
    "case F_DESTROY:",
    "XKillClient(dpy, tmp_win->w);",
    "case F_DELETE:",
    "send_clientmessage(tmp->w, _XA_WM_DELETE_WINDOW, timestamp);",
)


def validate_contract(text: str) -> list[str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return [f"differential contract is invalid JSON: {error}"]
    matches = [
        item for item in value.get("dimensions", [])
        if isinstance(item, dict) and item.get("id") == "client-close-and-destruction"
    ] if isinstance(value, dict) else []
    if len(matches) != 1:
        return ["contract must contain exactly one close/destruction dimension"]
    close = matches[0]
    errors = []
    if close.get("coverage_status") != "live-reference-differential":
        errors.append("close/destruction is not a live reference differential")
    mappings = close.get("mappings", {})
    if "tests/integration/run_m10_close_differential.py" not in mappings.get(
            "runners", []):
        errors.append("close/destruction lacks the live runner mapping")
    if "tests/integration/validate_m10_close_differential.py" not in mappings.get(
            "validators", []):
        errors.append("close/destruction lacks the fail-closed validator mapping")
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
        tampered["tests/integration/run_m10_close_differential.py"] = tampered[
            "tests/integration/run_m10_close_differential.py"
        ].replace(
            '"target_survived_delete": True',
            '"target_survived_delete": False',
            1,
        )
        if not validate(tampered, reference_source):
            errors.append("ignored-delete outcome tamper was accepted")
        tampered = copy.deepcopy(files)
        contract = json.loads(tampered[
            "reference/certification/m10-differential-contract.json"
        ])
        contract["dimensions"][9]["coverage_status"] = (
            "partial-existing-infrastructure"
        )
        tampered["reference/certification/m10-differential-contract.json"] = (
            json.dumps(contract)
        )
        if not validate(tampered, reference_source):
            errors.append("close coverage-status tamper was accepted")
    if errors:
        for error in errors:
            print(f"m10 close differential error: {error}")
        return 1
    print("Milestone 10 live close/destruction differential contract verified")
    if arguments.self_test_tamper:
        print("Milestone 10 close/destruction tamper checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
