#!/usr/bin/env python3
"""Fail-closed validation for the Milestone 10 final release gates."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


REFERENCE = "twm 1.0.13.1"
POLICY = (
    "Full observable twm parity may be claimed only when every final 1.0 "
    "release gate is passed with validated checked-in evidence."
)
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
TRANSLATION_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TRANSLATION_MARKER = re.compile(r"\[wayland-translation:([a-z0-9-]+)\]")
TRANSLATION_AUDIT_PATH = "reference/certification/wayland-translation-audit.json"
TRANSLATION_MANUAL_PATHS = {"data/wtwm.1", "docs/COMPATIBILITY.md"}
SUPPORTED_PACKAGE_RELEASES = {"13 (Trixie)", "14 (Forky)"}
SUPPORTED_PACKAGE_ARCHITECTURES = {"amd64", "arm64"}


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


def decode_index_v4_strip(data: bytes, offset: int) -> tuple[int, int]:
    """Decode the ofs-delta varint used for version-4 path compression."""
    value = data[offset] & 0x7F
    byte = data[offset]
    offset += 1
    while byte & 0x80:
        value += 1
        byte = data[offset]
        offset += 1
        value = (value << 7) + (byte & 0x7F)
    return value, offset


def path_tracked_in_index_data(data: bytes, relative: str) -> bool:
    if len(data) < 12:
        return False
    signature, version, count = struct.unpack("!4sII", data[:12])
    if signature != b"DIRC" or version not in {2, 3, 4}:
        return False
    offset = 12
    previous_path = b""
    for _ in range(count):
        start = offset
        if start + 62 > len(data):
            return False
        flags = struct.unpack("!H", data[start + 60:start + 62])[0]
        fixed_size = 64 if version >= 3 and flags & 0x4000 else 62
        path_start = start + fixed_size
        if version == 4:
            strip, path_start = decode_index_v4_strip(data, path_start)
            if strip > len(previous_path):
                return False
            path_end = data.index(b"\0", path_start)
            path = previous_path[:len(previous_path) - strip] + data[path_start:path_end]
            offset = path_end + 1
            previous_path = path
        else:
            path_end = data.index(b"\0", path_start)
            path = data[path_start:path_end]
            entry_size = path_end - start + 1
            offset = start + ((entry_size + 7) // 8) * 8
        if path.decode("utf-8", "surrogateescape") == relative:
            return True
    return False


def tracked_in_index(root: Path, relative: str) -> bool:
    try:
        git_directory = root / ".git"
        if git_directory.is_file():
            pointer = git_directory.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir: "):
                return False
            git_directory = (root / pointer.removeprefix("gitdir: ")).resolve()
        return path_tracked_in_index_data((git_directory / "index").read_bytes(), relative)
    except (OSError, UnicodeError, ValueError, struct.error):
        return False
    return False


def tracked(root: Path, relative: str) -> bool:
    resolved_root = root.resolve()
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "-C",
                str(resolved_root),
                "ls-files",
                "--error-unmatch",
                "--",
                relative,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return True
    except OSError:
        pass
    return tracked_in_index(resolved_root, relative)


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


def check_equal_counts(
    result: dict[str, Any], prefix: str, errors: list[str], *, item_name: str
) -> None:
    covered_field = f"covered_{item_name}"
    total_field = f"total_{item_name}"
    uncovered_field = f"uncovered_{item_name}"
    covered_ok = integer(result[covered_field], f"{prefix}.{covered_field}", errors, 1)
    total_ok = integer(result[total_field], f"{prefix}.{total_field}", errors, 1)
    if covered_ok and total_ok and result[covered_field] != result[total_field]:
        errors.append(f"{prefix} covered and total {item_name} counts must be equal")
    if result[uncovered_field] != []:
        errors.append(f"{prefix}.{uncovered_field} must be empty")


def grammar(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    del root
    check_coverage(result, prefix, errors, item_name="productions")


def actions(result: Any, prefix: str, root: Path, errors: list[str]) -> None:
    del root
    fields = {
        "coverage_percent",
        "covered_actions",
        "total_actions",
        "uncovered_actions",
        "covered_behaviors",
        "total_behaviors",
        "uncovered_behaviors",
    }
    if not exact_fields(result, fields, prefix, errors):
        return
    percent = result["coverage_percent"]
    if not isinstance(percent, (int, float)) or isinstance(percent, bool) or percent != 100:
        errors.append(f"{prefix}.coverage_percent must equal 100")
    check_equal_counts(result, prefix, errors, item_name="actions")
    check_equal_counts(result, prefix, errors, item_name="behaviors")


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
        "raw_evidence_path",
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
    raw_path = repo_file(
        result["raw_evidence_path"],
        f"{prefix}.raw_evidence_path",
        root,
        errors,
        json_only=True,
    )
    if raw_path is None:
        return
    runner = root / "tests/integration/run_m9_mixed_soak.py"
    validator = root / "tests/integration/validate_m9_mixed_soak.py"
    try:
        checked = subprocess.run(
            [
                sys.executable,
                "-B",
                str(validator),
                "--runner",
                str(runner),
                "--evidence",
                str(raw_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError as error:
        errors.append(f"{prefix}.raw_evidence_path cannot be validated: {error}")
        return
    if checked.returncode != 0:
        detail = checked.stdout.strip().replace("\n", "; ")
        errors.append(f"{prefix}.raw_evidence_path fails the soak contract: {detail}")
        return
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{prefix}.raw_evidence_path cannot be read as JSON: {error}")
        return
    if raw.get("schema") != "wtwm-mixed-soak-v3":
        errors.append(f"{prefix}.raw_evidence_path must use wtwm-mixed-soak-v3")
    if raw.get("result") != "pass" or raw.get("qualified_72_hour") is not True:
        errors.append(f"{prefix}.raw_evidence_path must be a qualified passing run")
    if raw.get("started_at_utc") != result["started_at"]:
        errors.append(f"{prefix}.started_at must match the raw evidence")
    if raw.get("ended_at_utc") != result["ended_at"]:
        errors.append(f"{prefix}.ended_at must match the raw evidence")
    raw_elapsed = raw.get("elapsed_seconds")
    if (
        isinstance(raw_elapsed, (int, float))
        and not isinstance(raw_elapsed, bool)
        and isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and abs(raw_elapsed / 3600 - duration) > 0.01
    ):
        errors.append(f"{prefix}.duration_hours must match the raw evidence")


def platform_tuple(value: Any, prefix: str, errors: list[str]) -> tuple[str, str, str] | None:
    fields = {"distribution", "release", "architecture"}
    if not exact_fields(value, fields, prefix, errors):
        return None
    if not all(non_empty_string(value[field], f"{prefix}.{field}", errors) for field in fields):
        return None
    return value["distribution"], value["release"], value["architecture"]


def supported_package_selection(declared: set[tuple[str, str, str]]) -> bool:
    releases = {
        release
        for distribution, release, architecture in declared
        if distribution == "Debian" and architecture in SUPPORTED_PACKAGE_ARCHITECTURES
    }
    if len(releases) != 1:
        return False
    release = next(iter(releases))
    if release not in SUPPORTED_PACKAGE_RELEASES:
        return False
    expected = {
        ("Debian", release, architecture)
        for architecture in SUPPORTED_PACKAGE_ARCHITECTURES
    }
    return declared == expected


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
    if not supported_package_selection(declared):
        errors.append(
            f"{prefix}.supported_platforms must exactly cover amd64 and arm64 for one "
            "selected release: Debian 13 (Trixie) or Debian 14 (Forky)"
        )

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
    manual_files: list[tuple[str, Path]] = []
    if not isinstance(manual_paths, list) or not manual_paths:
        errors.append(f"{prefix}.manual_paths must be a non-empty array")
    else:
        if len(manual_paths) != len(set(manual_paths)):
            errors.append(f"{prefix}.manual_paths must not contain duplicates")
        if set(manual_paths) != TRANSLATION_MANUAL_PATHS:
            errors.append(
                f"{prefix}.manual_paths must exactly name data/wtwm.1 and "
                "docs/COMPATIBILITY.md"
            )
        for index, path_value in enumerate(manual_paths):
            path = repo_file(
                path_value, f"{prefix}.manual_paths[{index}]", root, errors
            )
            if path is not None:
                manual_files.append((path_value, path))
    if result["ledger_path"] != "reference/ledger/twm-1.0.13.1.json":
        errors.append(f"{prefix}.ledger_path must name the frozen compatibility ledger")
    ledger_path = repo_file(
        result["ledger_path"], f"{prefix}.ledger_path", root, errors
    )
    if result["audit_path"] != TRANSLATION_AUDIT_PATH:
        errors.append(f"{prefix}.audit_path must name {TRANSLATION_AUDIT_PATH}")
    audit_path = repo_file(
        result["audit_path"], f"{prefix}.audit_path", root, errors, json_only=True
    )
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
        if values != sorted(values):
            errors.append(f"{prefix}.{field} must be sorted")
        if any(not TRANSLATION_ID.fullmatch(item) for item in values):
            errors.append(f"{prefix}.{field} contains an invalid translation ID")
        id_sets[field] = set(values)
    if len(id_sets) == 3 and not (
        id_sets["unavoidable_translation_ids"]
        == id_sets["manual_documented_ids"]
        == id_sets["ledger_documented_ids"]
    ):
        errors.append(f"{prefix} translation IDs must be documented in both the manual and ledger")

    expected_ids = id_sets.get("unavoidable_translation_ids")
    if expected_ids is None:
        return
    for path_value, path in manual_files:
        observed = set(TRANSLATION_MARKER.findall(path.read_text(encoding="utf-8")))
        if observed != expected_ids:
            errors.append(
                f"{prefix} translation markers in {path_value} do not exactly match "
                "unavoidable_translation_ids"
            )

    ledger_ids: set[str] = set()
    ledger_rows: set[str] = set()
    if ledger_path is not None:
        try:
            ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger_ids = set(TRANSLATION_MARKER.findall(
                ledger_path.read_text(encoding="utf-8")
            ))
            ledger_rows = {
                str(entry["id"])
                for entry in ledger_data.get("entries", [])
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            }
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append(f"{prefix}.ledger_path is not readable JSON")
        if ledger_ids != expected_ids:
            errors.append(
                f"{prefix} ledger translation markers do not exactly match "
                "unavoidable_translation_ids"
            )

    if audit_path is None:
        return
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append(f"{prefix}.audit_path is not readable JSON")
        return
    audit_fields = {"schema_version", "reference", "scope", "entries"}
    if not exact_fields(audit, audit_fields, f"{prefix}.audit", errors):
        return
    if audit["schema_version"] != 1:
        errors.append(f"{prefix}.audit.schema_version must be 1")
    if audit["reference"] != REFERENCE:
        errors.append(f"{prefix}.audit.reference must be {REFERENCE}")
    non_empty_string(audit["scope"], f"{prefix}.audit.scope", errors)
    entries = audit["entries"]
    if not isinstance(entries, list) or not entries:
        errors.append(f"{prefix}.audit.entries must be a non-empty array")
        return
    observed_ids: list[str] = []
    entry_fields = {
        "id", "summary", "unavoidable_reason", "ledger_rows", "test_paths"
    }
    for index, entry in enumerate(entries):
        entry_prefix = f"{prefix}.audit.entries[{index}]"
        if not exact_fields(entry, entry_fields, entry_prefix, errors):
            continue
        identifier = entry["id"]
        if not isinstance(identifier, str) or not TRANSLATION_ID.fullmatch(identifier):
            errors.append(f"{entry_prefix}.id is invalid")
        else:
            observed_ids.append(identifier)
        non_empty_string(entry["summary"], f"{entry_prefix}.summary", errors)
        non_empty_string(
            entry["unavoidable_reason"], f"{entry_prefix}.unavoidable_reason", errors
        )
        rows = entry["ledger_rows"]
        if not isinstance(rows, list) or not rows or not all(
            isinstance(row, str) and row for row in rows
        ):
            errors.append(f"{entry_prefix}.ledger_rows must be a non-empty string array")
        else:
            if rows != sorted(set(rows)):
                errors.append(f"{entry_prefix}.ledger_rows must be sorted and unique")
            unknown = set(rows) - ledger_rows
            if unknown:
                errors.append(f"{entry_prefix}.ledger_rows names unknown rows: {sorted(unknown)}")
        tests = entry["test_paths"]
        if not isinstance(tests, list) or not tests or not all(
            isinstance(path, str) and path for path in tests
        ):
            errors.append(f"{entry_prefix}.test_paths must be a non-empty string array")
        else:
            if tests != sorted(set(tests)):
                errors.append(f"{entry_prefix}.test_paths must be sorted and unique")
            for test_index, path in enumerate(tests):
                if not path.startswith("tests/"):
                    errors.append(f"{entry_prefix}.test_paths[{test_index}] must be under tests/")
                repo_file(path, f"{entry_prefix}.test_paths[{test_index}]", root, errors)
    if observed_ids != sorted(set(observed_ids)):
        errors.append(f"{prefix}.audit entries must be sorted by unique ID")
    if set(observed_ids) != expected_ids:
        errors.append(
            f"{prefix}.audit entry IDs do not exactly match unavoidable_translation_ids"
        )


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
    v4_path = b"reference/certification/reports/grammar-coverage.json"
    v4_entry = bytes(62) + b"\0" + v4_path + b"\0"
    v4_index = struct.pack("!4sII", b"DIRC", 4, 1) + v4_entry
    if not path_tracked_in_index_data(v4_index, v4_path.decode("ascii")):
        failures.append("self-test could not read a version-4 Git index")
    if not tracked_in_index(
        root, "reference/certification/reports/grammar-coverage.json"
    ):
        failures.append("self-test could not find tracked evidence in the Git index")
    if tracked_in_index(root, "reference/certification/reports/missing-evidence.json"):
        failures.append("self-test found nonexistent evidence in the Git index")
    accepted_package_sets = (
        {
            ("Debian", "13 (Trixie)", "amd64"),
            ("Debian", "13 (Trixie)", "arm64"),
        },
        {
            ("Debian", "14 (Forky)", "amd64"),
            ("Debian", "14 (Forky)", "arm64"),
        },
    )
    for declared in accepted_package_sets:
        if not supported_package_selection(declared):
            failures.append(f"self-test rejected supported package matrix: {sorted(declared)}")
    rejected_package_sets = (
        accepted_package_sets[0] | accepted_package_sets[1],
        {
            ("Debian", "13 (Trixie)", "amd64"),
            ("Debian", "14 (Forky)", "arm64"),
        },
        {("Debian", "14 (Forky)", "arm64")},
    )
    for declared in rejected_package_sets:
        if supported_package_selection(declared):
            failures.append(f"self-test accepted invalid package matrix: {sorted(declared)}")
    if not failures:
        print("PASS: accepted either complete Debian release matrix and rejected mixed matrices")
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
