#!/usr/bin/env python3
"""Protect the randomized lifecycle model and its headless invariant runner."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


PATHS = (
    Path("tests/integration/lifecycle_model_contract.json"),
    Path("include/wtwm/lifecycle_model.h"),
    Path("src/lifecycle_model.c"),
    Path("tests/lifecycle_model_test.c"),
    Path("tests/integration/run_randomized_lifecycle.py"),
    Path("meson.build"),
    Path("tests/integration/README.md"),
)

OPERATIONS = (
    "create", "map", "unmap", "remap", "title", "iconify", "deiconify",
    "destroy", "raise", "lower", "raiselower", "circle_up", "circle_down",
    "focus",
)
INVARIANTS = (
    "monotonic_creation_ids",
    "mapped_exactly_once_in_stack",
    "no_stale_or_duplicate_stack_ids",
    "focus_is_visible_or_empty",
    "iconified_implies_mapped",
    "transient_parent_is_live_or_empty",
)
SEEDS = (1, 7, 42, 305419896, 3735928559)


def validate_sources(
    contract_text: str,
    header: str,
    source: str,
    model_test: str,
    runner: str,
    meson: str,
    readme: str,
) -> list[str]:
    errors: list[str] = []
    try:
        contract = json.loads(contract_text)
    except json.JSONDecodeError as error:
        return [f"lifecycle model contract is invalid JSON: {error}"]
    if set(contract) != {
        "version", "operations_per_seed", "seeds", "operations",
        "invariants", "runtime",
    }:
        errors.append("lifecycle model contract schema changed")
    if contract.get("version") != 1:
        errors.append("lifecycle model contract version is not 1")
    if contract.get("operations_per_seed") != 6000:
        errors.append("portable randomized model must run 6000 operations per seed")
    if tuple(contract.get("seeds", ())) != SEEDS:
        errors.append("portable randomized model seeds changed")
    if tuple(contract.get("operations", ())) != OPERATIONS:
        errors.append("portable randomized model operation coverage changed")
    if tuple(contract.get("invariants", ())) != INVARIANTS:
        errors.append("portable randomized model invariant coverage changed")
    runtime_contract = contract.get("runtime", {})
    if runtime_contract != {
        "runs": 2, "steps_per_run": 96, "seed": 1279870533,
    }:
        errors.append("headless runtime repetition contract changed")

    header_markers = tuple(
        f"WTWM_LIFECYCLE_{operation.upper()}" for operation in OPERATIONS
    ) + (
        "WTWM_LIFECYCLE_OPERATION_COUNT",
        "WTWM_LIFECYCLE_MAX_WINDOWS 64",
        "uint64_t next_id;",
        "uint64_t focus_id;",
        "WTWM_LIFECYCLE_STACK_RAISE = 1",
        "WTWM_LIFECYCLE_STACK_LOWER = 2",
    )
    for marker in header_markers:
        if marker not in header:
            errors.append(f"lifecycle model header lacks {marker!r}")

    source_markers = (
        "model->next_id++",
        "insert_stack_top(model, window->id);",
        "repair_focus(model);",
        "model->windows[i].parent_id = 0;",
        '"duplicate active id %" PRIu64',
        '"duplicate stack id %" PRIu64',
        '"stale focus id %" PRIu64',
        '"unmapped icon %" PRIu64',
        '"stale parent for %" PRIu64',
        "wtwm_lifecycle_digest",
        "decision == WTWM_LIFECYCLE_STACK_RAISE",
        "decision == WTWM_LIFECYCLE_STACK_LOWER",
    )
    for marker in source_markers:
        if marker not in source:
            errors.append(f"lifecycle model implementation lacks {marker!r}")

    test_markers = (
        "#define OPERATIONS_PER_SEED 6000",
        "known_lifecycle_and_transients",
        "known_stacking",
        "randomized_sequences_are_valid_and_repeatable",
        "validator_rejects_tampering",
        "uint64_t first = run_randomized",
        "uint64_t second = run_randomized",
        "assert(first == second);",
        "assert(applied[i] != 0);",
    )
    for marker in test_markers:
        if marker not in model_test:
            errors.append(f"lifecycle model test lacks {marker!r}")
    for seed in SEEDS:
        if f"UINT32_C({seed})" not in model_test:
            errors.append(f"lifecycle model test lacks seed {seed}")

    try:
        ast.parse(runner)
    except SyntaxError as error:
        errors.append(f"randomized lifecycle runner is invalid Python: {error}")
    runner_markers = (
        "RUNTIME_RUNS = 2",
        "RUNTIME_STEPS = 96",
        "RUNTIME_SEED = 1279870533",
        '"create", "unmap", "remap", "title", "icon_cycle", "raise", "lower",',
        '"raiselower", "circle_up", "circle_down", "destroy",',
        '"Function \\"icon-cycle\\" { f.iconify f.deiconify }',
        'f"TITLE {new_title}", f"OK TITLE {new_title}"',
        "len(titles) != len(set(titles))",
        "set(range(len(windows)))",
        "focus names a stale or hidden client",
        "creation identity was reused or changed",
        "duplicate Xwayland lifecycle entry",
        'int(entry["xid"]) != client.xid',
        "exact X11 lifecycle teardown",
        "event sequence is stale or duplicated",
        "seeded lifecycle runtime was not repeatable",
        "for iteration in range(RUNTIME_RUNS)",
    )
    for marker in runner_markers:
        if marker not in runner:
            errors.append(f"randomized lifecycle runner lacks {marker!r}")
    for forbidden in ("SystemExit(77)", "continue-on-error", "|| true"):
        if forbidden in runner:
            errors.append(f"randomized lifecycle runner contains fallback {forbidden!r}")
    if runner.count("wait_for_client_teardown(control, target)") != 1:
        errors.append("randomized destroy lacks its exact teardown gate")
    if runner.count("wait_for_client_teardown(control, item)") != 1:
        errors.append("final cleanup lacks its exact teardown gate")

    contract_start = meson.find("'randomized lifecycle model contract'")
    runtime_start = meson.find("'randomized lifecycle and stacking integration'")
    if contract_start < 0:
        errors.append("Meson lacks portable randomized-lifecycle contract")
    else:
        registration = meson[contract_start:contract_start + 450]
        for marker in ("validate_lifecycle_model.py", "--self-test-tamper"):
            if marker not in registration:
                errors.append(f"portable lifecycle contract lacks {marker!r}")
    if runtime_start < 0:
        errors.append("Meson lacks randomized-lifecycle runtime integration")
    else:
        registration = meson[runtime_start:runtime_start + 700]
        for marker in (
            "run_randomized_lifecycle.py",
            "wtwm_stress_wayland_client",
            "wtwm_stress_x11_client",
            "is_parallel: false",
        ):
            if marker not in registration:
                errors.append(f"randomized lifecycle runtime lacks {marker!r}")
    for marker in (
        "6,000 operations over five",
        "fixed seeds",
        "second-run history digest",
        "96 lifecycle/stack actions twice",
        "stable creation IDs",
    ):
        if marker not in readme:
            errors.append(f"randomized lifecycle documentation lacks {marker!r}")
    return errors


def read_sources(source_root: Path) -> tuple[str, ...] | None:
    paths = tuple(source_root / path for path in PATHS)
    if not all(path.is_file() for path in paths):
        return None
    return tuple(path.read_text(encoding="utf-8") for path in paths)


def self_test_tamper(sources: tuple[str, ...]) -> list[str]:
    contract, header, source, model_test, runner, meson, readme = sources
    mutations = (
        (
            "operation-count",
            contract.replace('"operations_per_seed": 6000',
                             '"operations_per_seed": 60', 1),
            header, source, model_test, runner, meson, readme,
        ),
        (
            "operation-enum", contract,
            header.replace("WTWM_LIFECYCLE_DEICONIFY,", "", 1),
            source, model_test, runner, meson, readme,
        ),
        (
            "duplicate-validator", contract, header,
            source.replace('"duplicate stack id %" PRIu64',
                           '"stack id %" PRIu64', 1),
            model_test, runner, meson, readme,
        ),
        (
            "randomized-depth", contract, header, source,
            model_test.replace("#define OPERATIONS_PER_SEED 6000",
                               "#define OPERATIONS_PER_SEED 60", 1),
            runner, meson, readme,
        ),
        (
            "second-runtime-run", contract, header, source, model_test,
            runner.replace("RUNTIME_RUNS = 2", "RUNTIME_RUNS = 1", 1),
            meson, readme,
        ),
        (
            "runtime-destroy", contract, header, source, model_test,
            runner.replace('"raiselower", "circle_up", "circle_down", "destroy",',
                           '"raiselower", "circle_up", "circle_down",', 1),
            meson, readme,
        ),
        (
            "runtime-xid-teardown", contract, header, source, model_test,
            runner.replace('int(entry["xid"]) != client.xid',
                           'int(entry["xid"]) == client.xid', 1),
            meson, readme,
        ),
        (
            "runtime-final-teardown", contract, header, source, model_test,
            runner.replace("wait_for_client_teardown(control, item)",
                           "wait_for_title(control, item.title, False)", 1),
            meson, readme,
        ),
        (
            "portable-registration", contract, header, source, model_test,
            runner,
            meson.replace("'randomized lifecycle model contract'",
                          "'removed lifecycle model contract'", 1),
            readme,
        ),
        (
            "runtime-registration", contract, header, source, model_test,
            runner,
            meson.replace("'randomized lifecycle and stacking integration'",
                          "'removed lifecycle runtime'", 1),
            readme,
        ),
        (
            "documentation", contract, header, source, model_test, runner,
            meson,
            readme.replace("6,000 operations over five",
                           "a few operations", 1),
        ),
    )
    failures: list[str] = []
    for label, *changed in mutations:
        if not validate_sources(*changed):
            failures.append(f"{label} tamper was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    sources = read_sources(arguments.source_root.resolve())
    errors = (["missing randomized lifecycle contract source"]
              if sources is None else validate_sources(*sources))
    if arguments.self_test_tamper and not errors and sources is not None:
        errors.extend(self_test_tamper(sources))
    if errors:
        for error in errors:
            print(f"randomized lifecycle contract failed: {error}")
        return 1
    print("randomized lifecycle model, runtime, and tamper contracts valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
