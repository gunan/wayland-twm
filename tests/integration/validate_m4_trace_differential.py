#!/usr/bin/env python3
"""Protect the exact Milestone 4 reference/wtwm event-trace differential."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path


CONTRACT_PATH = Path("reference/interactions/twm-1.0.13.1/trace-differential.json")
RUNNER_PATH = Path("tests/integration/run_m4_trace_differential.py")
CLIENT_PATH = Path("tests/integration/m4_trace_client.c")
PROBE_PATH = Path("tests/integration/m4_trace_probe.c")
INPUT_PATH = Path("tests/integration/m4_trace_input.c")
CONFIG_PATH = Path("tests/integration/m4_trace_differential.twmrc")
README_PATH = Path("reference/interactions/twm-1.0.13.1/README.md")
WORKFLOW_PATH = Path(".github/workflows/build.yml")
MESON_PATH = Path("meson.build")

EXPECTED_EVENTS = [
    {"id": "pointer-root", "kind": "pointer", "x": 250, "y": 170},
    {"id": "pointer-alpha-client", "kind": "pointer", "x": 60, "y": 80},
    {"id": "focus-alpha-press", "kind": "button", "button": 3, "state": "press"},
    {"id": "focus-alpha-release", "kind": "button", "button": 3, "state": "release"},
    {"id": "raise-alpha-press", "kind": "button", "button": 2, "state": "press"},
    {"id": "raise-alpha-release", "kind": "button", "button": 2, "state": "release"},
    {"id": "lower-alpha-press", "kind": "key", "key": "F2", "state": "press"},
    {"id": "lower-alpha-release", "kind": "key", "key": "F2", "state": "release"},
    {"id": "pointer-alpha-title", "kind": "pointer", "x": 60, "y": 40},
    {"id": "move-alpha-press", "kind": "button", "button": 1, "state": "press"},
    {"id": "move-alpha-motion", "kind": "pointer", "x": 80, "y": 50},
    {"id": "move-alpha-release", "kind": "button", "button": 1, "state": "release"},
    {"id": "pointer-bravo-client", "kind": "pointer", "x": 180, "y": 100},
    {"id": "focus-bravo-press", "kind": "button", "button": 3, "state": "press"},
    {"id": "focus-bravo-release", "kind": "button", "button": 3, "state": "release"},
    {"id": "raise-bravo-press", "kind": "key", "key": "F1", "state": "press"},
    {"id": "raise-bravo-release", "kind": "key", "key": "F1", "state": "release"},
    {"id": "lower-bravo-press", "kind": "key", "key": "F2", "state": "press"},
    {"id": "lower-bravo-release", "kind": "key", "key": "F2", "state": "release"},
    {"id": "iconify-bravo-press", "kind": "key", "key": "F3", "state": "press"},
    {"id": "iconify-bravo-release", "kind": "key", "key": "F3", "state": "release"},
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duplicate_rejecting_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def validate_contract(value: object, source_root: Path) -> list[str]:
    if not isinstance(value, dict):
        return ["trace differential contract root must be an object"]
    errors: list[str] = []
    if value.get("schema_version") != 1:
        errors.append("trace differential schema_version must be 1")
    reference = value.get("reference")
    if not isinstance(reference, dict) or reference.get("version") != "1.0.13.1":
        errors.append("trace differential does not pin twm 1.0.13.1")
    elif digest(source_root / str(reference.get("archive"))) != reference.get(
        "archive_sha256"
    ):
        errors.append("trace differential reference archive hash is stale")
    if value.get("screen") != {"width": 260, "height": 180, "depth": 24}:
        errors.append("trace differential screen must match the frozen alpha/bravo capture")
    if value.get("configuration") != CONFIG_PATH.as_posix():
        errors.append("trace differential configuration path has drifted")
    elif value.get("configuration_sha256") != digest(source_root / CONFIG_PATH):
        errors.append("trace differential configuration hash is stale")
    oracle = value.get("initial_oracle")
    expected_oracles = {
        "alpha": "reference/captures/twm-1.0.13.1/baseline/phase-alpha.json",
        "bravo": "reference/captures/twm-1.0.13.1/baseline/phase-bravo.json",
    }
    if not isinstance(oracle, dict):
        errors.append("trace differential initial oracle is missing")
    else:
        for role, relative in expected_oracles.items():
            if oracle.get(role) != relative:
                errors.append(f"trace differential {role} oracle path has drifted")
                continue
            if oracle.get(f"{role}_sha256") != digest(source_root / relative):
                errors.append(f"trace differential {role} oracle hash is stale")
    normalization = value.get("normalization")
    if not isinstance(normalization, dict):
        errors.append("trace differential normalization is missing")
    else:
        for key in ("reference_frame", "wtwm_frame", "focus", "stack", "pointer"):
            if not isinstance(normalization.get(key), str):
                errors.append(f"trace differential normalization lacks {key}")
        excluded = normalization.get("excluded_observations")
        if excluded != ["decoration pixels", "temporary rubber-band outline pixels"]:
            errors.append("trace differential excludes more than pixels and temporary outlines")
        forbidden = ("geometry", "focus", "stack", "mapped", "iconified", "title")
        if any(word in " ".join(excluded or []).lower() for word in forbidden):
            errors.append("trace differential excludes a required Milestone 4 observation")
        volatile = normalization.get("volatile_fields_omitted")
        if volatile != ["display_number", "event_time", "frame_sequence", "pid", "xid"]:
            errors.append("trace differential volatile-field list has drifted")
    if value.get("events") != EXPECTED_EVENTS:
        errors.append("trace differential identical-input program has drifted")
    ids = [event["id"] for event in value.get("events", []) if isinstance(event, dict)]
    if len(ids) != len(set(ids)):
        errors.append("trace differential event IDs must be unique")
    return errors


def validate_sources(
    runner: str, client: str, probe: str, input_driver: str, config: str,
    readme: str, workflow: str, meson: str,
) -> list[str]:
    errors: list[str] = []
    try:
        ast.parse(runner)
    except SyntaxError as error:
        errors.append(f"trace differential runner is invalid Python: {error}")
    for marker in (
        "STABLE_SAMPLES = 3",
        "MAX_SAMPLES = 24",
        "check=False, timeout=10",
        "check=True, timeout=10",
        'print(f"reference trace input {index}/{len(events)}:',
        'print(f"wtwm trace input {index}/{len(events)}:',
        "def oracle_windows(",
        'outer_x = int(frame["x"]) - border',
        'if initial["windows"] != oracle:',
        "def normalize_wtwm(",
        'raw_cursor = state.get("cursor")',
        '"pointer": pointer,',
        'key=lambda pair: int(pair[1]["stack"]), reverse=True',
        '"mapped": bool(item["mapped"]) and not iconified',
        '"titled": bool(item["decorated"])',
        "for index, event in enumerate(events, 1):",
        "reference_input(driver, event, environment)",
        "wtwm_input(control, event)",
        "reference_input(driver, events[0], environment)",
        "wtwm_input(control, events[0])",
        "if reference != wtwm:",
        '"result": "failed"',
        'result["result"] = "equivalent"',
        'evidence / "reference-trace.json"',
        'evidence / "wtwm-trace.json"',
        'evidence / "runner-error.log"',
    ):
        if marker not in runner:
            errors.append(f"trace differential runner lacks {marker!r}")
    if runner.count("for index, event in enumerate(events, 1):") != 2:
        errors.append("both backends must snapshot every indexed input event")
    for forbidden in ("timestamp", "serial", "continue-on-error", "SystemExit(77)"):
        if forbidden in runner:
            errors.append(f"trace differential runner contains forbidden {forbidden!r}")
    for marker in (
        'ROLE_PROPERTY "_WTWM_REFERENCE_ROLE"',
        '"alpha", "Reference Alpha", 30, 28, 100, 65',
        '"bravo", "Reference Bravo", 88, 58, 110, 70',
        "USPosition | USSize",
        '"sentinel", "M4 Trace Readiness", 4, 4, 16, 16',
        "parent != root",
        'puts("READY")',
    ):
        if marker not in client:
            errors.append(f"trace differential client lacks {marker!r}")
    for marker in (
        "XQueryTree",
        "XTranslateCoordinates",
        "XGetInputFocus",
        "XQueryPointer",
        r'\"pointer\":{\"x\":%d,\"y\":%d}',
        'XInternAtom(display, "WM_STATE", False)',
        "item->frame_inner_x - border",
        "item->client_x - outer_x",
        'item->client_attributes.map_state == IsViewable ? "true" : "false"',
        'stack[stack_count++] = items[role].role',
    ):
        if marker not in probe:
            errors.append(f"trace differential reference observer lacks {marker!r}")
    for marker in (
        "XTestFakeMotionEvent",
        "XTestFakeButtonEvent",
        "XTestFakeKeyEvent",
        "XStringToKeysym",
        "XSync(display, False)",
    ):
        if marker not in input_driver:
            errors.append(f"trace differential input driver lacks {marker!r}")
    for marker in (
        'UsePPosition "on"', 'BorderWidth 3', 'TitleFont "fixed"', 'OpaqueMove',
        'Button1 = : title : f.move',
        'Button2 = : window|title|frame : f.raise',
        'Button3 = : window|title|frame : f.focus',
        '"F1" = : all : f.raise', '"F2" = : all : f.lower',
        '"F3" = : all : f.iconify',
    ):
        if marker not in config:
            errors.append(f"trace differential configuration lacks {marker!r}")
    for marker in (
        "same deterministic pointer, button, and key program",
        "root-relative pointer coordinates",
        "client and outer-frame geometry",
        "bottom-to-top stack",
        "m4-trace-differential",
    ):
        if marker not in readme:
            errors.append(f"trace differential documentation lacks {marker!r}")
    job_start = workflow.find("  x11-differential:\n")
    job = workflow[job_start:] if job_start >= 0 else ""
    for marker in (
        "libxtst-dev",
        "tests/integration/m4_trace_client.c",
        "tests/integration/m4_trace_probe.c",
        "tests/integration/m4_trace_input.c",
        "tests/integration/run_m4_trace_differential.py",
        "--reference-twm /tmp/reference-build/twm",
        "--contract \"$GITHUB_WORKSPACE/reference/interactions/twm-1.0.13.1/trace-differential.json\"",
        "name: m4-trace-differential",
        "/tmp/m4-trace-differential.json",
        "/tmp/m4-trace-differential-evidence",
        "if: always()",
        "if-no-files-found: error",
    ):
        if marker not in job:
            errors.append(f"X11 differential CI job lacks {marker!r}")
    if "continue-on-error" in job or "|| true" in job:
        errors.append("M4 live differential must fail its CI job on mismatch")
    for marker in (
        "Milestone 4 trace differential contract",
        "tests/integration/validate_m4_trace_differential.py",
        "--self-test-tamper",
    ):
        if marker not in meson:
            errors.append(f"Meson portable trace contract lacks {marker!r}")
    if "run_m4_trace_differential.py" in meson:
        errors.append("live M4 differential must not run in ordinary Meson jobs")
    return errors


def load_contract(text: str) -> object:
    return json.loads(text, object_pairs_hook=duplicate_rejecting_pairs)


def read_texts(source_root: Path) -> tuple[str, ...] | None:
    paths = (
        CONTRACT_PATH, RUNNER_PATH, CLIENT_PATH, PROBE_PATH, INPUT_PATH,
        CONFIG_PATH, README_PATH, WORKFLOW_PATH, MESON_PATH,
    )
    if not all((source_root / path).is_file() for path in paths):
        return None
    return tuple((source_root / path).read_text(encoding="utf-8") for path in paths)


def validate(source_root: Path) -> list[str]:
    texts = read_texts(source_root)
    if texts is None:
        return ["M4 trace differential source set is incomplete"]
    contract_text, *source_texts = texts
    try:
        contract = load_contract(contract_text)
    except (json.JSONDecodeError, ValueError) as error:
        return [f"M4 trace differential contract is invalid JSON: {error}"]
    return validate_contract(contract, source_root) + validate_sources(*source_texts)


def self_test_tamper(source_root: Path) -> list[str]:
    texts = read_texts(source_root)
    if texts is None:
        return ["cannot tamper-test incomplete M4 trace differential sources"]
    contract_text, runner, client, probe, input_driver, config, readme, workflow, meson = texts
    contract = load_contract(contract_text)
    failures: list[str] = []
    mutated = copy.deepcopy(contract)
    assert isinstance(mutated, dict)
    mutated["events"][0]["x"] = 249
    if not validate_contract(mutated, source_root):
        failures.append("event-coordinate tamper was accepted")
    mutations = (
        ("outer-normalization", runner.replace(
            'outer_x = int(frame["x"]) - border',
            'outer_x = int(frame["x"])', 1), client, probe, input_driver, config,
         readme, workflow, meson),
        ("X-frame-border", runner, client,
         probe.replace("item->frame_inner_x - border", "item->frame_inner_x", 1),
         input_driver, config, readme, workflow, meson),
        ("per-event-snapshot", runner.replace(
            "for index, event in enumerate(events, 1):",
            "for index, event in enumerate(events[:-1], 1):", 1),
         client, probe, input_driver, config, readme, workflow, meson),
        ("pointer-normalization", runner.replace(
            '        "pointer": pointer,\n', "", 1),
         client, probe, input_driver, config, readme, workflow, meson),
        ("live-CI", runner, client, probe, input_driver, config, readme,
         workflow.replace("name: m4-trace-differential",
                          "name: removed-trace-artifact", 1), meson),
    )
    for label, *sources in mutations:
        if not validate_sources(*sources):
            failures.append(f"{label} tamper was accepted")
    duplicate = contract_text.replace('"schema_version": 1,',
                                      '"schema_version": 1,\n  "schema_version": 1,', 1)
    try:
        load_contract(duplicate)
    except ValueError:
        pass
    else:
        failures.append("duplicate JSON-key tamper was accepted")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    source_root = arguments.source_root.resolve()
    errors = validate(source_root)
    if arguments.self_test_tamper:
        errors.extend(self_test_tamper(source_root))
    if errors:
        for error in errors:
            print(f"M4 trace differential contract: {error}")
        raise SystemExit(1)
    print(f"M4 trace differential contract valid: {len(EXPECTED_EVENTS)} indexed events")


if __name__ == "__main__":
    main()
