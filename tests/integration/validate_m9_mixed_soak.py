#!/usr/bin/env python3
"""Portable contract and tamper tests for the Milestone 9 soak evidence."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


EXPECTED_DURATION = 259200
EXPECTED_SMOKE_ITERATIONS = 2
RUNNER_MARKERS = {
    "explicit PointerRoot reset binding": '"Button3 = : window : f.unfocus\\n"',
    "Linux BTN_RIGHT drives Button3": (
        'control.command("BUTTON 273 press")\n'
        '    control.command("BUTTON 273 release")'
    ),
    "Linux BTN_MIDDLE drives Button2 resize": (
        'control.command("BUTTON 274 press")\n'
        '    active = control.state()["interaction"]'
    ),
    "auto-relative resize policy enabled": '"AutoRelativeResize\\n"',
    "resize oracle requires moved preview": 'or not preview.get("moved")',
    "PointerRoot activation and keyboard-focus split": (
        'if not state["focus_root"] and (\n'
        '        state["active"] != state["focus"]'
    ),
}


def validate_runner_contract(source: str) -> None:
    missing = [name for name, marker in RUNNER_MARKERS.items() if marker not in source]
    if missing:
        raise RuntimeError("missing mixed-soak runner contract: " + ", ".join(missing))


def load_runner(path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        specification = importlib.util.spec_from_file_location("wtwm_m9_soak", path)
        if specification is None or specification.loader is None:
            raise RuntimeError(f"cannot import {path}")
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def baseline(module, *, long: bool = False) -> dict[str, Any]:
    iterations = 9 if long else EXPECTED_SMOKE_ITERATIONS
    elapsed = EXPECTED_DURATION if long else 1.25
    run_profile = {
        "name": "72-hour" if long else "smoke",
        "requested_duration_seconds": EXPECTED_DURATION if long else None,
        "requested_iterations": None if long else EXPECTED_SMOKE_ITERATIONS,
    }
    limits = {"rss_bytes": 1000, "open_fds": 4, "threads": 2}
    initial = {"rss_bytes": 10000, "open_fds": 7, "threads": 2}
    current = {"rss_bytes": 10500, "open_fds": 8, "threads": 2}
    peak = {"rss_bytes": 11000, "open_fds": 8, "threads": 3}
    return {
        "schema": module.SCHEMA,
        "result": "pass",
        "profile": run_profile,
        "started_at_utc": "2026-01-01T00:00:00Z",
        "ended_at_utc": "2026-01-04T00:00:00Z" if long else "2026-01-01T00:00:02Z",
        "elapsed_seconds": elapsed,
        "iterations_completed": iterations,
        "qualified_72_hour": long,
        "pass_criteria": {
            "stopping_target_met": True,
            "workload_completed": True,
            "resource_limits_met": True,
            "compositor_clean_exit": True,
        },
        "operations": module.expected_operations(iterations),
        "resources": {
            "sampler": "linux-proc-v1",
            "samples_observed": iterations + 2,
            "initial": initial,
            "current": current,
            "peak": peak,
            "peak_iteration": {"rss_bytes": 1, "open_fds": 1, "threads": 1},
            "growth_limits": limits,
            "current_growth": {key: current[key] - initial[key] for key in initial},
            "hourly_and_endpoint_checkpoints": [],
        },
        "error": None,
        "provenance": {"harness_sha256": "a" * 64},
        "artifacts": {},
    }


def require_rejected(module, evidence: dict[str, Any], description: str,
                     expected_hash: str | None = None) -> None:
    if not module.validate_evidence(evidence, expected_hash):
        raise RuntimeError(f"tamper was accepted: {description}")


def self_test(module) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")
    validate_runner_contract(source)
    for name, marker in RUNNER_MARKERS.items():
        tampered = source.replace(marker, "REMOVED", 1)
        try:
            validate_runner_contract(tampered)
        except RuntimeError:
            pass
        else:
            raise RuntimeError(f"runner contract accepted missing marker: {name}")

    if module.DEFAULT_DURATION_SECONDS != EXPECTED_DURATION:
        raise RuntimeError("default soak duration is not exactly 72 hours")
    if module.SMOKE_ITERATIONS != EXPECTED_SMOKE_ITERATIONS:
        raise RuntimeError("bounded smoke iteration contract changed")
    smoke_profile = module.profile(True, None)
    default_profile = module.profile(False, None)
    if smoke_profile != {
        "name": "smoke",
        "requested_duration_seconds": None,
        "requested_iterations": EXPECTED_SMOKE_ITERATIONS,
    }:
        raise RuntimeError(f"unexpected smoke profile: {smoke_profile!r}")
    if default_profile != {
        "name": "72-hour",
        "requested_duration_seconds": float(EXPECTED_DURATION),
        "requested_iterations": None,
    }:
        raise RuntimeError(f"unexpected default profile: {default_profile!r}")

    obscured = {
        "windows": [
            {
                "title": "front", "stack": 0, "x": 80, "y": 80,
                "content_x": 2, "content_y": 21, "width": 180,
                "height": 120, "outer_width": 184, "outer_height": 143,
            },
            {
                "title": "back", "stack": 1, "x": 50, "y": 50,
                "content_x": 2, "content_y": 21, "width": 180,
                "height": 120, "outer_width": 184, "outer_height": 143,
            },
        ]
    }
    point = module.visible_content_point(obscured, "back")
    front = obscured["windows"][0]
    if (
        int(front["x"]) <= point[0] < int(front["x"]) + int(front["outer_width"])
        and int(front["y"]) <= point[1]
        < int(front["y"]) + int(front["outer_height"])
    ):
        raise RuntimeError(f"selected content point is obscured: {point!r}")

    smoke = baseline(module)
    long = baseline(module, long=True)
    for evidence, label in ((smoke, "smoke"), (long, "72-hour")):
        errors = module.validate_evidence(evidence)
        if errors:
            raise RuntimeError(f"valid {label} evidence rejected: {errors!r}")

    mutation = copy.deepcopy(smoke)
    mutation["qualified_72_hour"] = True
    require_rejected(module, mutation, "short run claimed 72-hour qualification")

    mutation = copy.deepcopy(long)
    mutation["elapsed_seconds"] = EXPECTED_DURATION - 0.001
    require_rejected(module, mutation, "under-duration 72-hour pass")

    mutation = copy.deepcopy(smoke)
    mutation["operations"]["resize_commits"] -= 1
    require_rejected(module, mutation, "missing resize operation")

    mutation = copy.deepcopy(smoke)
    mutation["resources"]["current"]["open_fds"] = 20
    require_rejected(module, mutation, "resource limit violation hidden as pass")

    mutation = copy.deepcopy(smoke)
    mutation["resources"]["peak"]["rss_bytes"] = 1
    require_rejected(module, mutation, "peak below observed RSS")

    mutation = copy.deepcopy(smoke)
    mutation["pass_criteria"]["workload_completed"] = False
    require_rejected(module, mutation, "pass with false criterion")

    require_rejected(module, smoke, "runner digest mismatch", expected_hash="b" * 64)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner", type=Path,
        default=Path(__file__).with_name("run_m9_mixed_soak.py"),
    )
    parser.add_argument("--evidence", type=Path)
    arguments = parser.parse_args()
    runner = arguments.runner.resolve()
    module = load_runner(runner)
    self_test(module)
    if arguments.evidence is not None:
        evidence = json.loads(arguments.evidence.read_text(encoding="utf-8"))
        expected_hash = module.sha256_file(runner)
        errors = module.validate_evidence(evidence, expected_hash)
        if errors:
            raise SystemExit("invalid soak evidence: " + "; ".join(errors))
    print("m9 mixed soak contract/tamper tests pass")


if __name__ == "__main__":
    main()
