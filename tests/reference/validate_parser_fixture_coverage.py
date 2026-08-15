#!/usr/bin/env python3
"""Validate frozen twm grammar fixtures and build their exact ledger crosswalk."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_PATH = Path("reference/grammar/manifest.json")
ARCHIVE_SHA256 = "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5"
INVENTORY_SHA256 = "818e4d90dbaea31edfc5004159b4c758772b5236b157bdefbed38314a5860337"
UPSTREAM_SAMPLES = {
    "reference/upstream/twm-1.0.13.1/sample-twmrc/jim.twmrc",
    "reference/upstream/twm-1.0.13.1/sample-twmrc/keith.twmrc",
    "reference/upstream/twm-1.0.13.1/sample-twmrc/lemke.twmrc",
}
UPSTREAM_DEFAULT = "reference/upstream/twm-1.0.13.1/defaults/system.twmrc"
INVENTORY_SECTIONS = ("keywords", "grammar", "lexical_forms")


class CoverageError(ValueError):
    """A deterministic grammar-fixture contract violation."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CoverageError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source, object_pairs_hook=no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CoverageError(f"cannot read {path}: {error}") from error


def repository_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CoverageError(f"{field} must be a non-empty repository path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != value:
        raise CoverageError(f"{field} is not a normalized repository path: {value!r}")
    return value


def keyword_tokens(text: str) -> set[str]:
    """Return lexer-like keywords outside comments and quoted strings."""
    clean: list[str] = []
    in_string = False
    escaped = False
    in_comment = False
    for character in text:
        if in_comment:
            if character == "\n":
                in_comment = False
                clean.append("\n")
            continue
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == "#":
            in_comment = True
        elif character == '"':
            in_string = True
        else:
            clean.append(character)
    return {token.lower() for token in re.findall(r"[A-Za-z.]+", "".join(clean))}


def _expect_keys(value: object, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverageError(f"{field} must be an object")
    if set(value) != expected:
        raise CoverageError(
            f"{field} keys are {sorted(value)}, expected {sorted(expected)}"
        )
    return value


def _fixture_bytes(
    source_root: Path, path: str, overrides: dict[str, bytes] | None
) -> bytes:
    if overrides and path in overrides:
        return overrides[path]
    try:
        return (source_root / path).read_bytes()
    except OSError as error:
        raise CoverageError(f"cannot read fixture {path}: {error}") from error


def build_coverage(
    source_root: Path,
    *,
    manifest_override: dict[str, Any] | None = None,
    content_overrides: dict[str, bytes] | None = None,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Validate the contract and return ledger-id to stable test mapping."""
    manifest = manifest_override or load_json(source_root / MANIFEST_PATH)
    root = _expect_keys(
        manifest,
        {"schema_version", "reference", "fixtures", "coverage_policy"},
        "manifest",
    )
    if root["schema_version"] != 1:
        raise CoverageError("manifest schema_version must be 1")

    reference = _expect_keys(
        root["reference"],
        {
            "name", "version", "archive", "archive_sha256", "grammar_member",
            "lexer_member", "manual_member", "inventory", "inventory_sha256",
        },
        "reference",
    )
    if reference["name"] != "twm" or reference["version"] != "1.0.13.1":
        raise CoverageError("reference must remain twm 1.0.13.1")
    if reference["archive_sha256"] != ARCHIVE_SHA256:
        raise CoverageError("reference archive hash has drifted")
    if reference["inventory_sha256"] != INVENTORY_SHA256:
        raise CoverageError("reference inventory hash has drifted")
    archive_name = repository_path(reference["archive"], "reference.archive")
    inventory_name = repository_path(reference["inventory"], "reference.inventory")
    archive_bytes = _fixture_bytes(source_root, archive_name, content_overrides)
    inventory_bytes = _fixture_bytes(source_root, inventory_name, content_overrides)
    if sha256(archive_bytes) != ARCHIVE_SHA256:
        raise CoverageError("pinned reference archive content has drifted")
    if sha256(inventory_bytes) != INVENTORY_SHA256:
        raise CoverageError("pinned inventory content has drifted")
    try:
        with tarfile.open(source_root / archive_name, "r:xz") as archive:
            members = set(archive.getnames())
    except (OSError, tarfile.TarError) as error:
        raise CoverageError(f"cannot inspect reference archive: {error}") from error
    for field in ("grammar_member", "lexer_member", "manual_member"):
        if reference[field] not in members:
            raise CoverageError(f"reference archive is missing {field}: {reference[field]}")

    try:
        inventory = json.loads(inventory_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CoverageError(f"cannot decode pinned inventory: {error}") from error
    rows: dict[str, tuple[str, dict[str, Any]]] = {}
    for section in INVENTORY_SECTIONS:
        values = inventory.get(section)
        if not isinstance(values, list) or not values:
            raise CoverageError(f"inventory section {section} is empty or invalid")
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise CoverageError(f"inventory section {section} contains an invalid row")
            row_id = value["id"]
            if row_id in rows:
                raise CoverageError(f"duplicate inventory id {row_id}")
            rows[row_id] = (section, value)

    fixture_values = root["fixtures"]
    if not isinstance(fixture_values, list) or not fixture_values:
        raise CoverageError("fixtures must be a non-empty array")
    fixtures: dict[str, dict[str, Any]] = {}
    tokens: dict[str, set[str]] = {}
    test_ids: set[str] = set()
    for index, raw_fixture in enumerate(fixture_values):
        if not isinstance(raw_fixture, dict):
            raise CoverageError(f"fixtures[{index}] must be an object")
        expected = raw_fixture.get("expected")
        required = {"id", "test_id", "path", "sha256", "expected", "kind"}
        if expected == "reject":
            required.add("diagnostic_class")
        fixture = _expect_keys(raw_fixture, required, f"fixtures[{index}]")
        fixture_id = fixture["id"]
        test_id = fixture["test_id"]
        if not isinstance(fixture_id, str) or not re.fullmatch(r"[a-z0-9-]+", fixture_id):
            raise CoverageError(f"fixtures[{index}].id is invalid")
        if fixture_id in fixtures:
            raise CoverageError(f"duplicate fixture id {fixture_id}")
        if test_id != f"test.parser-fixture.{fixture_id}" or test_id in test_ids:
            raise CoverageError(f"fixture {fixture_id} has an invalid or duplicate test_id")
        if expected not in {"accept", "reject"}:
            raise CoverageError(f"fixture {fixture_id} expected must be accept or reject")
        if expected == "reject" and fixture["diagnostic_class"] not in {
            "unknown-keyword", "parse-error"
        }:
            raise CoverageError(f"fixture {fixture_id} has an invalid diagnostic_class")
        path = repository_path(fixture["path"], f"fixture {fixture_id} path")
        content = _fixture_bytes(source_root, path, content_overrides)
        if sha256(content) != fixture["sha256"]:
            raise CoverageError(f"fixture {fixture_id} hash does not match its content")
        try:
            tokens[fixture_id] = keyword_tokens(content.decode("utf-8"))
        except UnicodeError as error:
            raise CoverageError(f"fixture {fixture_id} is not UTF-8: {error}") from error
        fixtures[fixture_id] = fixture
        test_ids.add(test_id)

    sample_paths = {
        fixture["path"] for fixture in fixtures.values()
        if fixture["kind"] == "upstream-sample"
    }
    if sample_paths != UPSTREAM_SAMPLES:
        raise CoverageError("fixture set must contain the complete upstream sample-twmrc set")
    default_paths = {
        fixture["path"] for fixture in fixtures.values()
        if fixture["kind"] == "upstream-default"
    }
    if default_paths != {UPSTREAM_DEFAULT}:
        raise CoverageError("fixture set must contain the upstream system default")

    rejection_classes = {
        fixture.get("diagnostic_class") for fixture in fixtures.values()
        if fixture["expected"] == "reject"
    }
    if rejection_classes != {"unknown-keyword", "parse-error"}:
        raise CoverageError("fixtures must cover detailed and general parser rejection")
    if sum(
        fixture["kind"] == "malformed-truncated" for fixture in fixtures.values()
    ) < 2:
        raise CoverageError("fixtures must contain multiple explicit truncated inputs")

    policy = _expect_keys(
        root["coverage_policy"],
        {
            "inventory_sections", "keyword_fixture_order",
            "accepted_grammar_fixture", "grammar_rejection_overrides",
            "lexical_fixture",
        },
        "coverage_policy",
    )
    if policy["inventory_sections"] != list(INVENTORY_SECTIONS):
        raise CoverageError("coverage_policy must cover all inventory sections in order")
    order = policy["keyword_fixture_order"]
    if not isinstance(order, list) or not order or len(set(order)) != len(order):
        raise CoverageError("keyword_fixture_order must be a non-empty unique list")
    for fixture_id in order:
        if fixture_id not in fixtures or fixtures[fixture_id]["expected"] != "accept":
            raise CoverageError(f"keyword coverage fixture is missing or not accepted: {fixture_id}")
    grammar_fixture = policy["accepted_grammar_fixture"]
    lexical_fixture = policy["lexical_fixture"]
    for label, fixture_id in (
        ("accepted grammar", grammar_fixture), ("lexical", lexical_fixture)
    ):
        if fixture_id not in fixtures or fixtures[fixture_id]["expected"] != "accept":
            raise CoverageError(f"{label} fixture is missing or not accepted: {fixture_id}")
    overrides = policy["grammar_rejection_overrides"]
    if overrides != {"grammar.stmt.1": "malformed-unknown-keyword"}:
        raise CoverageError("grammar rejection overrides have drifted")

    coverage: dict[str, dict[str, str]] = {}
    accepted_productions: set[str] = set()
    for row_id, (section, row) in rows.items():
        if section == "keywords":
            spelling = str(row["spelling"]).lower()
            fixture_id = next(
                (candidate for candidate in order if spelling in tokens[candidate]), None
            )
            if fixture_id is None:
                raise CoverageError(
                    f"upstream keyword {row_id} ({spelling}) has no accepted fixture token"
                )
        elif section == "grammar":
            fixture_id = overrides.get(row_id, grammar_fixture)
            if fixture_id not in fixtures:
                raise CoverageError(f"grammar row {row_id} maps to missing fixture {fixture_id}")
            if fixtures[fixture_id]["expected"] == "accept":
                accepted_productions.add(str(row["production"]))
        else:
            fixture_id = lexical_fixture
        fixture = fixtures[fixture_id]
        coverage[row_id] = {
            "test_id": fixture["test_id"],
            "path": fixture["path"],
            "case": fixture_id,
            "expected": fixture["expected"],
        }

    all_productions = {
        str(row["production"])
        for section, row in rows.values() if section == "grammar"
    }
    missing_productions = all_productions - accepted_productions
    if missing_productions:
        raise CoverageError(
            "grammar productions without an accepted fixture: "
            + ", ".join(sorted(missing_productions))
        )
    for row_id, (section, row) in rows.items():
        if section == "keywords" and "directive" in row["categories"]:
            if coverage[row_id]["expected"] != "accept":
                raise CoverageError(f"upstream directive {row_id} lacks an accepted fixture")
    if set(coverage) != set(rows):
        raise CoverageError("not every frozen inventory row has a stable test mapping")

    counts = {
        "fixtures": len(fixtures),
        "accepted": sum(fixture["expected"] == "accept" for fixture in fixtures.values()),
        "rejected": sum(fixture["expected"] == "reject" for fixture in fixtures.values()),
        "keywords": len(inventory["keywords"]),
        "grammar": len(inventory["grammar"]),
        "lexical_forms": len(inventory["lexical_forms"]),
        "rows": len(rows),
        "productions": len(all_productions),
    }
    return coverage, counts


def self_test(source_root: Path) -> None:
    manifest = load_json(source_root / MANIFEST_PATH)

    tampered = copy.deepcopy(manifest)
    tampered["coverage_policy"]["keyword_fixture_order"] = [
        "grammar-lexical-behavior"
    ]
    _expect_failure(source_root, "missing keyword mappings", manifest_override=tampered)

    tampered = copy.deepcopy(manifest)
    tampered["coverage_policy"]["accepted_grammar_fixture"] = (
        "malformed-truncated-list"
    )
    _expect_failure(source_root, "accepted production loss", manifest_override=tampered)

    complete = "reference/grammar/fixtures/complete-language.twmrc"
    changed = (source_root / complete).read_bytes().replace(b"NoDefaults", b"NoDefaultx", 1)
    _expect_failure(
        source_root,
        "fixture hash drift",
        content_overrides={complete: changed},
    )

    changed = (source_root / complete).read_bytes().replace(b"DontMoveOff\n", b"", 1)
    tampered = copy.deepcopy(manifest)
    for fixture in tampered["fixtures"]:
        if fixture["id"] == "grammar-complete-language":
            fixture["sha256"] = sha256(changed)
    _expect_failure(
        source_root,
        "recognized directive disappearance with a refreshed fixture hash",
        manifest_override=tampered,
        content_overrides={complete: changed},
    )

    tampered = copy.deepcopy(manifest)
    for fixture in tampered["fixtures"]:
        if fixture["expected"] == "reject":
            fixture["expected"] = "accept"
            fixture.pop("diagnostic_class")
    tampered["coverage_policy"]["grammar_rejection_overrides"] = {
        "grammar.stmt.1": "grammar-complete-language"
    }
    _expect_failure(source_root, "lost rejection coverage", manifest_override=tampered)


def _expect_failure(source_root: Path, label: str, **kwargs: Any) -> None:
    try:
        build_coverage(source_root, **kwargs)
    except CoverageError:
        return
    raise CoverageError(f"self-test did not detect {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        _, counts = build_coverage(source_root)
        if args.self_test_tamper:
            self_test(source_root)
    except CoverageError as error:
        print(f"parser fixture coverage error: {error}")
        return 1
    print(
        "parser fixture coverage valid: "
        f"{counts['rows']} rows, {counts['productions']} productions, "
        f"{counts['accepted']} accepted and {counts['rejected']} rejected fixtures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
