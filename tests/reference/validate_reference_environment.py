#!/usr/bin/env python3

"""Validate the controlled Debian Trixie reference-build contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


CONTRACT_PATH = Path("reference/environment/debian-trixie-x11.json")
EXPECTED_PACKAGES = [
    "bison",
    "build-essential",
    "flex",
    "libice-dev",
    "libsm-dev",
    "libx11-dev",
    "libxext-dev",
    "libxmu-dev",
    "libxrandr-dev",
    "libxt-dev",
    "pkgconf",
    "x11-utils",
    "x11proto-dev",
    "xfonts-base",
    "xvfb",
    "xz-utils",
]
EXPECTED_CONTRACT = {
    "schema_version": 1,
    "name": "Debian Trixie reference twm X11 build",
    "container": "debian:trixie",
    "runner": "ubuntu-latest",
    "packages": "reference/environment/debian-trixie-x11-packages.txt",
    "package_version_policy": (
        "Resolve from Debian Trixie and record exact versions in each CI log"
    ),
    "source": {
        "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
        "sha256": (
            "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5"
        ),
        "root": "twm-1.0.13.1",
        "version": "1.0.13.1",
    },
    "build": {
        "script": "tests/reference/build_reference_twm.sh",
        "system": "release-generated configure and Makefile.in files",
        "configure_arguments": ["--disable-silent-rules"],
        "parallel_jobs": 2,
        "version_command": "src/twm -V",
        "expected_version_output": "twm 1.0.13.1",
    },
    "x11_smoke": {
        "server": "Xvfb",
        "display": ":99",
        "screen": "1024x768x24",
        "readiness_probe": "xdpyinfo",
        "configuration": "empty temporary .twmrc",
    },
}


def load_json(path: Path) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicate_keys)


def validate(source_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        contract = load_json(source_root / CONTRACT_PATH)
    except (OSError, UnicodeError, ValueError) as error:
        return [f"cannot read {CONTRACT_PATH}: {error}"]
    if contract != EXPECTED_CONTRACT:
        errors.append("reference environment contract has drifted")

    packages_path = source_root / EXPECTED_CONTRACT["packages"]
    try:
        packages = packages_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        errors.append(f"cannot read package list: {error}")
        return errors
    if packages != EXPECTED_PACKAGES:
        errors.append("reference package list is incomplete, reordered, or has drifted")
    if packages != sorted(set(packages)):
        errors.append("reference package list must be sorted and contain no duplicates")

    workflow_path = source_root / ".github/workflows/build.yml"
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"cannot read build workflow: {error}")
        return errors
    workflow_markers = [
        "  reference-twm:\n",
        "    container: debian:trixie\n",
        "reference/environment/debian-trixie-x11-packages.txt",
        'sh tests/reference/build_reference_twm.sh "$GITHUB_WORKSPACE"',
    ]
    for marker in workflow_markers:
        if marker not in workflow:
            errors.append(f"build workflow is missing contract marker: {marker!r}")

    for relative_path in (
        EXPECTED_CONTRACT["source"]["archive"],
        EXPECTED_CONTRACT["build"]["script"],
    ):
        if not (source_root / relative_path).is_file():
            errors.append(f"contract path does not exist: {relative_path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()

    errors = validate(args.source_root.resolve())
    if errors:
        for error in errors:
            print(f"reference environment error: {error}")
        return 1
    print(
        "reference X11 environment valid: "
        f"{EXPECTED_CONTRACT['container']}, {len(EXPECTED_PACKAGES)} packages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
