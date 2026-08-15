#!/usr/bin/env python3
"""Validate self-contained wtwm VM or physical-Linux evidence bundles."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any


CHECK_NAMES = (
    "host_native",
    "headless_stability",
    "nested_wayland",
    "drm_login",
    "launch_failure_recovery",
    "package_lifecycle",
    "session_isolation",
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_128 = re.compile(r"^[0-9a-f]{128}$")
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def parse_time(value: Any, field: str, errors: list[str]) -> dt.datetime | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an RFC 3339 string")
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} is not a valid RFC 3339 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a UTC offset")
        return None
    return parsed


def validate_artifact(
    artifact: Any, field: str, bundle_dir: Path, errors: list[str]
) -> None:
    if not isinstance(artifact, dict):
        errors.append(f"{field} must be an artifact object")
        return
    if set(artifact) != {"path", "sha256", "description"}:
        errors.append(f"{field} must contain only path, sha256, and description")
        return
    path_value = artifact.get("path")
    digest = artifact.get("sha256")
    description = artifact.get("description")
    if not isinstance(path_value, str) or not path_value:
        errors.append(f"{field}.path must be non-empty")
        return
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{field}.path must stay inside the evidence bundle")
        return
    if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
        errors.append(f"{field}.sha256 must be 64 lowercase hex digits")
    if not isinstance(description, str) or not description:
        errors.append(f"{field}.description must be non-empty")
    artifact_path = bundle_dir / relative
    if not artifact_path.is_file():
        errors.append(f"{field}.path does not exist: {path_value}")
        return
    actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if isinstance(digest, str) and actual != digest:
        errors.append(f"{field}.sha256 does not match {path_value}")


def read_vm_definition(source_root: Path, errors: list[str]) -> dict[str, str]:
    definition: dict[str, str] = {}
    path = source_root / "vm/debian-arm64/image.env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        errors.append(f"cannot read VM definition: {error}")
        return definition
    for line in lines:
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            definition[key] = value
    return definition


def validate(
    data: Any, bundle_dir: Path, source_root: Path, allow_incomplete: bool
) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["evidence root must be an object"]
    required = {
        "schema_version",
        "run_id",
        "recorded_at",
        "revision",
        "platform",
        "environment",
        "checks",
        "artifacts",
        "notes",
    }
    if set(data) != required:
        errors.append("evidence root fields do not exactly match schema version 1")
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(data.get("run_id"), str) or not RUN_ID.fullmatch(data["run_id"]):
        errors.append("run_id has an invalid format")
    parse_time(data.get("recorded_at"), "recorded_at", errors)

    revision = data.get("revision")
    if not isinstance(revision, dict) or set(revision) != {"commit", "clean"}:
        errors.append("revision must contain exactly commit and clean")
    else:
        if not isinstance(revision["commit"], str) or not COMMIT.fullmatch(revision["commit"]):
            errors.append("revision.commit must be a full hexadecimal object ID")
        if not isinstance(revision["clean"], bool):
            errors.append("revision.clean must be boolean")
        elif not revision["clean"] and not allow_incomplete:
            errors.append("complete evidence must come from a clean tree")

    platform = data.get("platform")
    platform_fields = {
        "kind",
        "architecture",
        "os_release",
        "kernel",
        "virtualized",
        "manufacturer",
        "model",
        "login_manager",
        "drm_devices",
        "connectors",
        "input_devices",
    }
    if not isinstance(platform, dict) or set(platform) != platform_fields:
        errors.append("platform fields do not exactly match schema version 1")
    else:
        kind = platform.get("kind")
        if kind not in {"utm-arm64", "physical-linux"}:
            errors.append("platform.kind is invalid")
        for field in ("architecture", "os_release", "kernel", "manufacturer", "model", "login_manager"):
            if not isinstance(platform.get(field), str) or not platform[field].strip():
                errors.append(f"platform.{field} must be non-empty")
        if not isinstance(platform.get("virtualized"), bool):
            errors.append("platform.virtualized must be boolean")
        for field in ("drm_devices", "connectors", "input_devices"):
            values = platform.get(field)
            if not isinstance(values, list) or not values or not all(
                isinstance(item, str) and item for item in values
            ):
                errors.append(f"platform.{field} must be a non-empty string array")
        if kind == "physical-linux" and platform.get("virtualized") is not False:
            errors.append("physical-linux evidence must report virtualized=false")
        if kind == "physical-linux" and str(platform.get("manufacturer", "")).lower() == "unknown":
            errors.append("physical-linux evidence requires an identified manufacturer")
        if kind == "physical-linux" and str(platform.get("model", "")).lower() == "unknown":
            errors.append("physical-linux evidence requires an identified model")
        if kind == "utm-arm64" and platform.get("architecture") not in {"aarch64", "arm64"}:
            errors.append("utm-arm64 evidence must report an ARM64 architecture")

    environment = data.get("environment")
    environment_fields = {
        "wtwm_version",
        "package_lock_sha256",
        "vm_image_build",
        "vm_image_sha512",
    }
    if not isinstance(environment, dict) or set(environment) != environment_fields:
        errors.append("environment fields do not exactly match schema version 1")
    else:
        if not isinstance(environment["wtwm_version"], str) or not environment["wtwm_version"]:
            errors.append("environment.wtwm_version must be non-empty")
        if not isinstance(environment["package_lock_sha256"], str) or not HEX_64.fullmatch(
            environment["package_lock_sha256"]
        ):
            errors.append("environment.package_lock_sha256 must be 64 lowercase hex digits")
        if isinstance(platform, dict) and platform.get("kind") == "utm-arm64":
            definition = read_vm_definition(source_root, errors)
            if environment.get("vm_image_build") != definition.get("WTWM_VM_IMAGE_BUILD"):
                errors.append("VM image build does not match the checked-in definition")
            image_digest = environment.get("vm_image_sha512")
            if not isinstance(image_digest, str) or not HEX_128.fullmatch(image_digest):
                errors.append("environment.vm_image_sha512 must be 128 lowercase hex digits")
            elif image_digest != definition.get("WTWM_VM_IMAGE_SHA512"):
                errors.append("VM image digest does not match the checked-in definition")
        elif environment.get("vm_image_build") is not None or environment.get("vm_image_sha512") is not None:
            errors.append("physical-linux evidence must use null VM image fields")

    checks = data.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECK_NAMES):
        errors.append("checks must contain exactly the seven required platform checks")
    else:
        for name in CHECK_NAMES:
            check = checks[name]
            prefix = f"checks.{name}"
            required_check = {
                "status",
                "iterations",
                "started_at",
                "ended_at",
                "command",
                "assertions",
                "log",
            }
            if not isinstance(check, dict) or set(check) != required_check:
                errors.append(f"{prefix} fields do not exactly match schema version 1")
                continue
            status = check.get("status")
            if status not in {"pass", "fail", "not-run"}:
                errors.append(f"{prefix}.status is invalid")
            iterations = check.get("iterations")
            if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 0:
                errors.append(f"{prefix}.iterations must be a non-negative integer")
            command = check.get("command")
            assertions = check.get("assertions")
            if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
                errors.append(f"{prefix}.command must be a string array")
            if not isinstance(assertions, list) or not all(
                isinstance(item, str) and item for item in assertions
            ):
                errors.append(f"{prefix}.assertions must be a string array")
            if status == "not-run":
                if not allow_incomplete:
                    errors.append(f"{prefix} is not complete")
                if check.get("started_at") is not None or check.get("ended_at") is not None:
                    errors.append(f"{prefix} not-run timestamps must be null")
                if check.get("log") is not None:
                    errors.append(f"{prefix} not-run log must be null")
            else:
                started = parse_time(check.get("started_at"), f"{prefix}.started_at", errors)
                ended = parse_time(check.get("ended_at"), f"{prefix}.ended_at", errors)
                if started is not None and ended is not None and ended < started:
                    errors.append(f"{prefix}.ended_at precedes started_at")
                if not command:
                    errors.append(f"{prefix}.command is required after a run")
                if not assertions:
                    errors.append(f"{prefix}.assertions is required after a run")
                validate_artifact(check.get("log"), f"{prefix}.log", bundle_dir, errors)
                if status != "pass" and not allow_incomplete:
                    errors.append(f"{prefix} did not pass")
            if name == "headless_stability" and status == "pass" and iterations < 100:
                errors.append("headless_stability requires at least 100 iterations")

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array")
    else:
        for index, artifact in enumerate(artifacts):
            validate_artifact(artifact, f"artifacts[{index}]", bundle_dir, errors)
    notes = data.get("notes")
    if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
        errors.append("notes must be a string array")
    return errors


def self_test(source_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-evidence-test.") as directory:
        bundle = Path(directory)
        log = bundle / "check.log"
        log.write_text("pass\n", encoding="utf-8")
        digest = hashlib.sha256(log.read_bytes()).hexdigest()
        timestamp = "2026-08-15T12:00:00Z"
        check = {
            "status": "pass",
            "iterations": 1,
            "started_at": timestamp,
            "ended_at": timestamp,
            "command": ["test-command"],
            "assertions": ["observable result checked"],
            "log": {"path": "check.log", "sha256": digest, "description": "test"},
        }
        checks = {name: dict(check) for name in CHECK_NAMES}
        checks["headless_stability"] = dict(check, iterations=100)
        evidence = {
            "schema_version": 1,
            "run_id": "self-test-physical",
            "recorded_at": timestamp,
            "revision": {"commit": "a" * 40, "clean": True},
            "platform": {
                "kind": "physical-linux",
                "architecture": "x86_64",
                "os_release": "Debian 13",
                "kernel": "6.12.0",
                "virtualized": False,
                "manufacturer": "Test Vendor",
                "model": "Test Model",
                "login_manager": "gdm",
                "drm_devices": ["card0:test"],
                "connectors": ["card0-HDMI-A-1:connected"],
                "input_devices": ["keyboard", "pointer"],
            },
            "environment": {
                "wtwm_version": "self-test",
                "package_lock_sha256": "b" * 64,
                "vm_image_build": None,
                "vm_image_sha512": None,
            },
            "checks": checks,
            "artifacts": [],
            "notes": [],
        }
        errors = validate(evidence, bundle, source_root, False)
        if errors:
            raise AssertionError(f"valid evidence rejected: {errors}")
        evidence["checks"]["headless_stability"]["iterations"] = 99
        errors = validate(evidence, bundle, source_root, False)
        if "headless_stability requires at least 100 iterations" not in errors:
            raise AssertionError("short stability run was accepted")
        evidence["checks"]["headless_stability"]["iterations"] = 100
        evidence["checks"]["nested_wayland"]["log"]["sha256"] = "0" * 64
        errors = validate(evidence, bundle, source_root, False)
        if not any("does not match" in error for error in errors):
            raise AssertionError("tampered artifact was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", nargs="?", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root or Path(__file__).resolve().parents[2]
    if args.self_test:
        self_test(source_root)
        print("validate-platform-evidence.py: self-test passes")
        return 0
    if args.evidence is None:
        parser.error("EVIDENCE is required unless --self-test is used")
    try:
        data = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"validate-platform-evidence.py: cannot read evidence: {error}")
        return 1
    errors = validate(data, args.evidence.resolve().parent, source_root, args.allow_incomplete)
    if errors:
        for error in errors:
            print(f"validate-platform-evidence.py: {error}")
        return 1
    print(f"validate-platform-evidence.py: passes: {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
