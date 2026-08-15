#!/usr/bin/env python3

"""Validate the pinned real-world twmrc regression corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


MANIFEST_PATH = Path("reference/fixtures/twmrc/manifest.json")
EXPECTED_CORPUS = {
    "name": "Historical X.Org twm user configurations",
    "selection": "Complete sample-twmrc set from the signed twm 1.0.13.1 release",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "archive_sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "signature": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz.sig",
    "license_member": "twm-1.0.13.1/COPYING",
}
EXPECTED_FIXTURES = [
    {
        "id": "jim",
        "path": "reference/upstream/twm-1.0.13.1/sample-twmrc/jim.twmrc",
        "archive_member": "twm-1.0.13.1/sample-twmrc/jim.twmrc",
        "sha256": "704e2699d9677b3b976df13277e8147efd04e24027714a319012670013848ee3",
        "represents": [
            "title buttons, squeeze-title rules, and pixmaps",
            "color and monochrome settings",
            "mouse bindings, composed functions, and menus",
            "icon-manager and per-window lists",
        ],
    },
    {
        "id": "keith",
        "path": "reference/upstream/twm-1.0.13.1/sample-twmrc/keith.twmrc",
        "archive_member": "twm-1.0.13.1/sample-twmrc/keith.twmrc",
        "sha256": "fe33be5f80e238f1a5aefd3ffad0637d356c3ba34714870d8df8414723365e08",
        "represents": [
            "cursor, font, color, and monochrome settings",
            "squeeze-title and per-window rules",
            "mouse modifiers and window contexts",
            "composed functions and multi-entry menus",
        ],
    },
    {
        "id": "lemke",
        "path": "reference/upstream/twm-1.0.13.1/sample-twmrc/lemke.twmrc",
        "archive_member": "twm-1.0.13.1/sample-twmrc/lemke.twmrc",
        "sha256": "6f8406d44c9176935bb38d0668a866c216a21b9857593eea234bc93b3f186130",
        "represents": [
            "icon-manager, iconification, and auto-raise lists",
            "cursor, font, and monochrome settings",
            "abbreviated mouse contexts",
            "composed functions and command-heavy menus",
        ],
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    manifest_path = source_root / MANIFEST_PATH
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return [f"cannot read {MANIFEST_PATH}: {error}"]

    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    if set(manifest) != {"schema_version", "corpus", "fixtures"}:
        errors.append("manifest must contain only schema_version, corpus, and fixtures")
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("corpus") != EXPECTED_CORPUS:
        errors.append("corpus provenance or selection has drifted")
    if manifest.get("fixtures") != EXPECTED_FIXTURES:
        errors.append("fixture list, order, metadata, path, or hash has drifted")
    if errors:
        return errors

    archive_path = source_root / EXPECTED_CORPUS["archive"]
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as error:
        return [f"cannot read archive {archive_path}: {error}"]
    if sha256(archive_bytes) != EXPECTED_CORPUS["archive_sha256"]:
        errors.append("release archive hash does not match the pinned corpus provenance")
        return errors

    try:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            try:
                archive.getmember(EXPECTED_CORPUS["license_member"])
            except KeyError:
                errors.append("release archive does not contain its declared license member")

            for fixture in EXPECTED_FIXTURES:
                fixture_path = source_root / fixture["path"]
                try:
                    fixture_bytes = fixture_path.read_bytes()
                except OSError as error:
                    errors.append(f"cannot read fixture {fixture['id']}: {error}")
                    continue
                if sha256(fixture_bytes) != fixture["sha256"]:
                    errors.append(f"fixture {fixture['id']} does not match its pinned hash")
                try:
                    member = archive.extractfile(fixture["archive_member"])
                except KeyError:
                    member = None
                if member is None:
                    errors.append(f"archive member for fixture {fixture['id']} is missing")
                elif member.read() != fixture_bytes:
                    errors.append(
                        f"fixture {fixture['id']} differs from its release archive member"
                    )
    except (OSError, tarfile.TarError) as error:
        errors.append(f"cannot inspect release archive: {error}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()

    errors = validate(args.source_root.resolve())
    if errors:
        for error in errors:
            print(f"twmrc corpus error: {error}")
        return 1
    print(f"real-world twmrc corpus valid: {len(EXPECTED_FIXTURES)} fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
