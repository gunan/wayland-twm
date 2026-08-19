#!/usr/bin/env python3
"""Fail-closed validation for the Milestone 10 final release gates."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


REFERENCE = "twm 1.0.13.1"
POLICY = (
    "Full observable twm parity may be claimed only when every final 1.0 "
    "release gate is passed with validated checked-in evidence."
)
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
SUPPORTED_PACKAGES = {
    ("Debian", "13 (Trixie)", "amd64"),
    ("Debian", "13 (Trixie)", "arm64"),
}


def exact_fields(value: Any, expected: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    if set(value) != expected:
        errors.append(f"{label} fields must be exactly {', '.join(sorted(expected))}")
        return False
    return True


def non_empty_string(value: Any, label: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return False
    return True


def integer(value: Any, label: str, errors: list[str], minimum: int = 0) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        errors.append(f"{label} must be an integer greater than or equal to {minimum}")
        return False
    return True


def parse_time(value: Any, label: str, errors: list[str]) -> dt.datetime | None:
    if not isinstance(value, str):
        errors.append(f"{label} must be an RFC 3339 timestamp")
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be an RFC 3339 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} must include a UTC offset")
        return None
    return parsed


def tracked(root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def repo_file(
    value: Any,
    label: str,
    root: Path,
    errors: list[str],
    *,
    json_only: bool = False,
) -> Path | None:
    if not non_empty_string(value, label, errors):
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        errors.append(f"{label} must be a normalized repository-relative path")
        return None
    if json_only and relative.suffix != ".json":
        errors.append(f"{label} must name a JSON evidence report")
    candidate = root / relative
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label} escapes the repository")
        return None
    if candidate.is_symlink() or not candidate.is_file():
        errors.append(f"{label} does not name a regular checked-in file: {value}")
        return None
    if not tracked(root, value):
        errors.append(f"{label} is not checked in: {value}")
        return None
    return candidate


def require_repo_path(
    result: dict[str, Any], field: str, prefix: str, root: Path, errors: list[str]
) -> None:
    repo_file(result.get(field), f"{prefix}.{field}", root, errors)


def check_coverage(
    result: Any,
    prefix: str,
    errors: list[str],
    *,
    item_name: str,
) -> None:
    covered_field = f"covered_{item_name}"
    total_field = f"total_{item_name}"
    uncovered_field = f"uncovered_{item_name}"
    fields = {"coverage_percent", covered_field, total_field, uncovered_field}
    if not exact_fields(result, fields, prefix, errors):
        return
    percent = result["coverage_percent"]
    if not isinstance(percent, (int, float)) or isinstance(percent, bool) or percent != 100:
        errors.append(f"{prefix}.coverage_percent must equal 100")
    covered_ok = integer(result[covered_field], f"{prefix}.{covered_field}", errors, 1)
    total_ok = integer(result[total_field], f"{prefix}.{total_field}", errors, 1)
    if covered_ok and total_ok and result[covered_field] != result[total_field]:
        errors.append(f"{prefix} covered and total counts must be equal")
    if result[uncovered_field] != []:
        errors.append(f"{prefix}.{uncovered_field} must be empty")


def grammar(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    del root
    check_coverage(result, prefix, errors, item_name="productions")


def actions(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    del root
    check_coverage(result, prefix, errors, item_name="actions")


def compatibility(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "ledger_path",
        "total_entries",
        "partial_entries",
        "parsed_only_entries",
        "unexplained_entries",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    if result["ledger_path"] != "reference/ledger/twm-1.0.13.1.json":
        errors.append(f"{prefix}.ledger_path must name the frozen compatibility ledger")
    require_repo_path(result, "ledger_path", prefix, root, errors)
    integer(result["total_entries"], f"{prefix}.total_entries", errors, 1)
    for field in ("partial_entries", "parsed_only_entries", "unexplained_entries"):
        if result[field] != 0:
            errors.append(f"{prefix}.{field} must equal zero")


def canonical_geometry(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {"profile", "scenario_count", "geometry_difference_count", "comparison_artifact_path"}
    if not exact_fields(result, fields, prefix, errors):
        return
    if result["profile"] != "canonical-one-output-1x":
        errors.append(f"{prefix}.profile must be canonical-one-output-1x")
    integer(result["scenario_count"], f"{prefix}.scenario_count", errors, 1)
    if result["geometry_difference_count"] != 0:
        errors.append(f"{prefix}.geometry_difference_count must equal zero")
    require_repo_path(result, "comparison_artifact_path", prefix, root, errors)


def focus_stacking(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "scenario_count",
        "unexplained_focus_differences",
        "unexplained_stacking_differences",
        "differential_trace_path",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    integer(result["scenario_count"], f"{prefix}.scenario_count", errors, 1)
    for field in ("unexplained_focus_differences", "unexplained_stacking_differences"):
        if result[field] != 0:
            errors.append(f"{prefix}.{field} must equal zero")
    require_repo_path(result, "differential_trace_path", prefix, root, errors)


def golden_images(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "golden_image_count",
        "reviewed_difference_count",
        "unreviewed_difference_count",
        "review_log_path",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    integer(result["golden_image_count"], f"{prefix}.golden_image_count", errors, 1)
    integer(result["reviewed_difference_count"], f"{prefix}.reviewed_difference_count", errors)
    if result["unreviewed_difference_count"] != 0:
        errors.append(f"{prefix}.unreviewed_difference_count must equal zero")
    require_repo_path(result, "review_log_path", prefix, root, errors)


def soak(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "started_at",
        "ended_at",
        "duration_hours",
        "successful",
        "crashes",
        "hangs",
        "protocol_violations",
        "unbounded_resource_leaks",
        "log_path",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    started = parse_time(result["started_at"], f"{prefix}.started_at", errors)
    ended = parse_time(result["ended_at"], f"{prefix}.ended_at", errors)
    duration = result["duration_hours"]
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 72:
        errors.append(f"{prefix}.duration_hours must be at least 72")
    if started is not None and ended is not None:
        actual = (ended - started).total_seconds() / 3600
        if actual < 72:
            errors.append(f"{prefix} timestamps cover less than 72 hours")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and abs(actual - duration) > 0.01:
            errors.append(f"{prefix}.duration_hours does not match its timestamps")
    if result["successful"] is not True:
        errors.append(f"{prefix}.successful must be true")
    for field in ("crashes", "hangs", "protocol_violations", "unbounded_resource_leaks"):
        if result[field] != 0:
            errors.append(f"{prefix}.{field} must equal zero")
    require_repo_path(result, "log_path", prefix, root, errors)


def platform_tuple(value: Any, prefix: str, errors: list[str]) -> tuple[str, str, str] | None:
    fields = {"distribution", "release", "architecture"}
    if not exact_fields(value, fields, prefix, errors):
        return None
    if not all(non_empty_string(value[field], f"{prefix}.{field}", errors) for field in fields):
        return None
    return value["distribution"], value["release"], value["architecture"]


def package_matrix(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    if not exact_fields(result, {"support_policy_path", "supported_platforms", "results"}, prefix, errors):
        return
    if result["support_policy_path"] != "docs/BUILD_AND_TEST.md":
        errors.append(f"{prefix}.support_policy_path must be docs/BUILD_AND_TEST.md")
    require_repo_path(result, "support_policy_path", prefix, root, errors)
    platforms = result["supported_platforms"]
    declared: set[tuple[str, str, str]] = set()
    if not isinstance(platforms, list):
        errors.append(f"{prefix}.supported_platforms must be an array")
    else:
        for index, platform in enumerate(platforms):
            key = platform_tuple(platform, f"{prefix}.supported_platforms[{index}]", errors)
            if key is not None and key in declared:
                errors.append(f"{prefix}.supported_platforms contains a duplicate: {key}")
            elif key is not None:
                declared.add(key)
    if declared != SUPPORTED_PACKAGES:
        errors.append(f"{prefix}.supported_platforms must exactly cover Debian 13 amd64 and arm64")

    observed: set[tuple[str, str, str]] = set()
    results = result["results"]
    result_fields = {
        "distribution",
        "release",
        "architecture",
        "install",
        "upgrade",
        "uninstall",
        "reinstall",
        "evidence_path",
    }
    if not isinstance(results, list):
        errors.append(f"{prefix}.results must be an array")
        return
    for index, item in enumerate(results):
        item_prefix = f"{prefix}.results[{index}]"
        if not exact_fields(item, result_fields, item_prefix, errors):
            continue
        key = item["distribution"], item["release"], item["architecture"]
        if not all(non_empty_string(part, f"{item_prefix}.{field}", errors) for part, field in zip(key, ("distribution", "release", "architecture"))):
            continue
        if key in observed:
            errors.append(f"{prefix}.results contains a duplicate: {key}")
        observed.add(key)
        for field in ("install", "upgrade", "uninstall", "reinstall"):
            if item[field] != "passed":
                errors.append(f"{item_prefix}.{field} must be passed")
        repo_file(item["evidence_path"], f"{item_prefix}.evidence_path", root, errors)
    if observed != declared:
        errors.append(f"{prefix}.results must exactly match supported_platforms")


def environments(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    if not exact_fields(result, {"results"}, prefix, errors):
        return
    required_kinds = {"nested", "vm-login", "physical-hardware"}
    result_fields = {
        "kind",
        "status",
        "architecture",
        "operating_system",
        "virtualized",
        "hardware_manufacturer",
        "hardware_model",
        "evidence_path",
    }
    values = result["results"]
    if not isinstance(values, list):
        errors.append(f"{prefix}.results must be an array")
        return
    observed: set[str] = set()
    for index, item in enumerate(values):
        item_prefix = f"{prefix}.results[{index}]"
        if not exact_fields(item, result_fields, item_prefix, errors):
            continue
        kind = item["kind"]
        if kind not in required_kinds:
            errors.append(f"{item_prefix}.kind is invalid")
        elif kind in observed:
            errors.append(f"{prefix}.results contains duplicate {kind} evidence")
        else:
            observed.add(kind)
        if item["status"] != "passed":
            errors.append(f"{item_prefix}.status must be passed")
        for field in ("architecture", "operating_system", "hardware_manufacturer", "hardware_model"):
            non_empty_string(item[field], f"{item_prefix}.{field}", errors)
        if not isinstance(item["virtualized"], bool):
            errors.append(f"{item_prefix}.virtualized must be boolean")
        if kind == "physical-hardware" and item["virtualized"] is not False:
            errors.append(f"{item_prefix} physical hardware must report virtualized=false")
        repo_file(item["evidence_path"], f"{item_prefix}.evidence_path", root, errors)
    if observed != required_kinds:
        errors.append(f"{prefix}.results must include nested, vm-login, and physical-hardware")


def blind_ab(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "profile",
        "blind",
        "repeatable_distinguishing_behavior",
        "protocol_path",
        "reviewer_results",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    if result["profile"] != "canonical-one-output-1x":
        errors.append(f"{prefix}.profile must be canonical-one-output-1x")
    if result["blind"] is not True:
        errors.append(f"{prefix}.blind must be true")
    if result["repeatable_distinguishing_behavior"] is not False:
        errors.append(f"{prefix}.repeatable_distinguishing_behavior must be false")
    require_repo_path(result, "protocol_path", prefix, root, errors)
    reviewers = result["reviewer_results"]
    reviewer_fields = {
        "reviewer_id",
        "experienced_twm_user",
        "trial_count",
        "repeatable_distinguishing_behavior",
        "result_path",
    }
    if not isinstance(reviewers, list) or len(reviewers) < 2:
        errors.append(f"{prefix}.reviewer_results must contain at least two reviewers")
        return
    identifiers: set[str] = set()
    for index, reviewer in enumerate(reviewers):
        item_prefix = f"{prefix}.reviewer_results[{index}]"
        if not exact_fields(reviewer, reviewer_fields, item_prefix, errors):
            continue
        reviewer_id = reviewer["reviewer_id"]
        if non_empty_string(reviewer_id, f"{item_prefix}.reviewer_id", errors):
            if reviewer_id in identifiers:
                errors.append(f"{prefix}.reviewer_results has duplicate reviewer_id {reviewer_id}")
            identifiers.add(reviewer_id)
        if reviewer["experienced_twm_user"] is not True:
            errors.append(f"{item_prefix}.experienced_twm_user must be true")
        integer(reviewer["trial_count"], f"{item_prefix}.trial_count", errors, 1)
        if reviewer["repeatable_distinguishing_behavior"] is not False:
            errors.append(f"{item_prefix}.repeatable_distinguishing_behavior must be false")
        repo_file(reviewer["result_path"], f"{item_prefix}.result_path", root, errors)


def translations(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    fields = {
        "manual_paths",
        "ledger_path",
        "unavoidable_translation_ids",
        "manual_documented_ids",
        "ledger_documented_ids",
        "audit_path",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    manual_paths = result["manual_paths"]
    if not isinstance(manual_paths, list) or not manual_paths:
        errors.append(f"{prefix}.manual_paths must be a non-empty array")
    else:
        for index, path in enumerate(manual_paths):
            repo_file(path, f"{prefix}.manual_paths[{index}]", root, errors)
    if result["ledger_path"] != "reference/ledger/twm-1.0.13.1.json":
        errors.append(f"{prefix}.ledger_path must name the frozen compatibility ledger")
    require_repo_path(result, "ledger_path", prefix, root, errors)
    require_repo_path(result, "audit_path", prefix, root, errors)
    id_fields = ("unavoidable_translation_ids", "manual_documented_ids", "ledger_documented_ids")
    id_sets: dict[str, set[str]] = {}
    for field in id_fields:
        values = result[field]
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item for item in values
        ):
            errors.append(f"{prefix}.{field} must be a non-empty string array")
            continue
        if len(values) != len(set(values)):
            errors.append(f"{prefix}.{field} must not contain duplicates")
        id_sets[field] = set(values)
    if len(id_sets) == 3 and not (
        id_sets["unavoidable_translation_ids"]
        == id_sets["manual_documented_ids"]
        == id_sets["ledger_documented_ids"]
    ):
        errors.append(f"{prefix} translation IDs must be documented in both the manual and ledger")


GateCheck = Callable[[Any, str, Path, list[str]], None]
GATES: tuple[tuple[str, str, GateCheck], ...] = (
    ("grammar-coverage", "One hundred percent grammar coverage.", grammar),
    ("builtin-action-coverage", "One hundred percent built-in action coverage.", actions),
    (
        "compatibility-entry-closure",
        "No “partial,” “parsed only,” or unexplained compatibility entries.",
        compatibility,
    ),
    ("canonical-geometry", "Zero geometry differences in the canonical profile.", canonical_geometry),
    ("focus-stacking", "Zero unexplained focus or stacking differences.", focus_stacking),
    ("golden-images", "No unreviewed golden-image differences.", golden_images),
    ("soak-72-hours", "Successful 72-hour soak testing.", soak),
    (
        "supported-package-matrix",
        "Successful package tests on every supported distribution and architecture.",
        package_matrix,
    ),
    (
        "deployment-environments",
        "Successful testing in nested, VM login, and physical hardware environments.",
        environments,
    ),
    (
        "blind-ab-evaluation",
        "Blind A/B evaluation by experienced `twm` users, with no repeatable distinguishing behavior in the canonical profile.",
        blind_ab,
    ),
    (
        "wayland-translation-documentation",
        "All unavoidable Wayland translations documented in the manual and compatibility ledger.",
        translations,
    ),
)


def evidence_report(
    path_value: Any,
    gate_id: str,
    checker: GateCheck,
    root: Path,
    prefix: str,
    errors: list[str],
) -> None:
    path = repo_file(path_value, f"{prefix}.evidence[0]", root, errors, json_only=True)
    if path is None:
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{prefix}.evidence[0] cannot be read as JSON: {error}")
        return
    fields = {"schema_version", "gate_id", "reference", "recorded_at", "revision", "result"}
    if not exact_fields(report, fields, f"{prefix}.evidence_report", errors):
        return
    if report["schema_version"] != 1:
        errors.append(f"{prefix}.evidence_report.schema_version must be 1")
    if report["gate_id"] != gate_id:
        errors.append(f"{prefix}.evidence_report.gate_id must be {gate_id}")
    if report["reference"] != REFERENCE:
        errors.append(f"{prefix}.evidence_report.reference must be {REFERENCE}")
    parse_time(report["recorded_at"], f"{prefix}.evidence_report.recorded_at", errors)
    revision = report["revision"]
    if exact_fields(revision, {"commit", "clean"}, f"{prefix}.evidence_report.revision", errors):
        if not isinstance(revision["commit"], str) or not COMMIT.fullmatch(revision["commit"]):
            errors.append(f"{prefix}.evidence_report.revision.commit must be a full object ID")
        if revision["clean"] is not True:
            errors.append(f"{prefix}.evidence_report.revision.clean must be true")
    checker(report["result"], f"{prefix}.evidence_report.result", root, errors)


def validate(data: Any, root: Path) -> list[str]:
    errors: list[str] = []
    fields = {"schema_version", "reference", "policy", "full_parity_claim_allowed", "gates"}
    if not exact_fields(data, fields, "manifest", errors):
        return errors
    if data["schema_version"] != 1:
        errors.append("manifest.schema_version must be 1")
    if data["reference"] != REFERENCE:
        errors.append(f"manifest.reference must be {REFERENCE}")
    if data["policy"] != POLICY:
        errors.append("manifest.policy does not match the full-parity release policy")
    if not isinstance(data["full_parity_claim_allowed"], bool):
        errors.append("manifest.full_parity_claim_allowed must be boolean")
    gates = data["gates"]
    if not isinstance(gates, list) or len(gates) != len(GATES):
        errors.append(f"manifest.gates must contain exactly {len(GATES)} entries")
        return errors

    all_passed = True
    gate_fields = {"id", "title", "status", "evidence", "pending_reason"}
    for index, ((gate_id, title, checker), gate) in enumerate(zip(GATES, gates)):
        prefix = f"manifest.gates[{index}]"
        if not exact_fields(gate, gate_fields, prefix, errors):
            all_passed = False
            continue
        if gate["id"] != gate_id:
            errors.append(f"{prefix}.id must be {gate_id}")
        if gate["title"] != title:
            errors.append(f"{prefix}.title does not exactly match the final release gate")
        status = gate["status"]
        if status not in {"pending", "passed"}:
            errors.append(f"{prefix}.status must be pending or passed")
            all_passed = False
            continue
        evidence = gate["evidence"]
        if not isinstance(evidence, list):
            errors.append(f"{prefix}.evidence must be an array")
            all_passed = False
            continue
        if status == "pending":
            all_passed = False
            if evidence:
                errors.append(f"{prefix}.evidence must be empty while the gate is pending")
            non_empty_string(gate["pending_reason"], f"{prefix}.pending_reason", errors)
        else:
            if gate["pending_reason"] is not None:
                errors.append(f"{prefix}.pending_reason must be null after the gate passes")
            if len(evidence) != 1:
                errors.append(f"{prefix}.passed gates require exactly one checked-in evidence report")
            else:
                evidence_report(evidence[0], gate_id, checker, root, prefix, errors)

    if data["full_parity_claim_allowed"] is not all_passed:
        errors.append("manifest.full_parity_claim_allowed must equal whether all 11 gates passed")
    return errors


def read_manifest(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def self_test_tamper(data: Any, root: Path) -> list[str]:
    failures: list[str] = []
    cases: list[tuple[str, Any, str]] = []

    unsupported = copy.deepcopy(data)
    unsupported["gates"][0]["status"] = "passed"
    unsupported["gates"][0]["pending_reason"] = None
    unsupported["gates"][0]["evidence"] = []
    cases.append(("unsupported pass claim", unsupported, "require exactly one checked-in evidence report"))

    missing = copy.deepcopy(data)
    missing["gates"][0]["status"] = "passed"
    missing["gates"][0]["pending_reason"] = None
    missing["gates"][0]["evidence"] = ["reference/certification/missing-evidence.json"]
    cases.append(("missing evidence path", missing, "does not name a regular checked-in file"))

    parity_claim = copy.deepcopy(data)
    parity_claim["full_parity_claim_allowed"] = True
    cases.append(("premature full-parity claim", parity_claim, "must equal whether all 11 gates passed"))

    with tempfile.TemporaryDirectory(prefix="wtwm-m10-release-gate-self-test-") as directory:
        temp = Path(directory)
        for index, (name, tampered, expected) in enumerate(cases):
            path = temp / f"case-{index}.json"
            path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
            observed = validate(read_manifest(path), root)
            if not any(expected in error for error in observed):
                failures.append(f"self-test did not reject {name} with the expected error")
            else:
                print(f"PASS: rejected {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="release-gate manifest (default: reference/certification/m10-release-gates.json)",
    )
    parser.add_argument(
        "--self-test-tamper",
        action="store_true",
        help="also prove deterministic rejection of false claims and missing evidence",
    )
    args = parser.parse_args()
    root = args.source_root.resolve()
    manifest = args.manifest or root / "reference/certification/m10-release-gates.json"
    try:
        data = read_manifest(manifest)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"release-gate validation failed: cannot read {manifest}: {error}")
        return 1
    errors = validate(data, root)
    if errors:
        print("release-gate validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.self_test_tamper:
        failures = self_test_tamper(data, root)
        if failures:
            print("release-gate tamper self-test failed:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
    pending = sum(gate["status"] == "pending" for gate in data["gates"])
    print(f"validated {len(GATES)} final release gates: {pending} pending, {len(GATES) - pending} passed")
    print(f"full parity claim allowed: {str(data['full_parity_claim_allowed']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
