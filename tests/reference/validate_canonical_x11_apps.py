#!/usr/bin/env python3

"""Validate the canonical X11 fixture manifest and optional runtime results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path


MANIFEST_PATH = Path("reference/fixtures/canonical-x11/manifest.json")
EXPECTED_TOP_KEYS = [
    "schema_version",
    "suite",
    "reference",
    "environment",
    "identity",
    "legacy_application",
    "categories",
    "runtime",
    "sources",
]
EXPECTED_CATEGORIES = [
    (
        "normal_windows",
        ["normal"],
        [
            ("normal-managed", "client parent is a distinct reference-twm frame"),
            ("normal-no-transient", "WM_TRANSIENT_FOR is absent"),
        ],
    ),
    (
        "dialogs_and_transients",
        ["dialog", "normal"],
        [
            (
                "dialog-managed",
                "dialog client parent is a distinct reference-twm frame",
            ),
            (
                "dialog-transient-for-normal",
                "WM_TRANSIENT_FOR identifies the normal client",
            ),
            (
                "dialog-window-type",
                "_NET_WM_WINDOW_TYPE is _NET_WM_WINDOW_TYPE_DIALOG",
            ),
        ],
    ),
    (
        "fixed_size_windows",
        ["fixed"],
        [
            ("fixed-managed", "client parent is a distinct reference-twm frame"),
            ("fixed-min-max", "PMinSize and PMaxSize both specify 140x90"),
        ],
    ),
    (
        "resize_increment_and_aspect_hints",
        ["resize"],
        [
            ("resize-managed", "client parent is a distinct reference-twm frame"),
            (
                "resize-increments",
                "PBaseSize is 40x30 and PResizeInc is 13x7",
            ),
            ("resize-aspect", "PAspect range is exactly 4:3 through 16:9"),
        ],
    ),
    (
        "long_and_changing_titles",
        ["title"],
        [
            ("title-managed", "client parent is a distinct reference-twm frame"),
            (
                "title-initial-long",
                "initial WM_NAME is exact and longer than 200 bytes",
            ),
            ("title-mutated", "a later exact WM_NAME mutation is observable"),
        ],
    ),
    (
        "icon_names_and_icon_bitmaps",
        ["icon"],
        [
            ("icon-managed", "client parent is a distinct reference-twm frame"),
            ("icon-name", "WM_ICON_NAME is WTWM canonical icon name"),
            (
                "icon-pixmap-depth1",
                "IconPixmapHint names a live 16x16 depth-1 pixmap",
            ),
            (
                "icon-mask-depth1",
                "IconMaskHint names a distinct live 16x16 depth-1 mask",
            ),
        ],
    ),
    (
        "urgency_and_focus_behavior",
        ["urgent"],
        [
            ("urgency-managed", "client parent is a distinct reference-twm frame"),
            (
                "urgency-hint",
                "WM_HINTS has InputHint true and XUrgencyHint",
            ),
            (
                "focus-target-urgent",
                "explicit input focus is the urgent client with PointerRoot revert",
            ),
        ],
    ),
    (
        "override_redirect_windows",
        ["override"],
        [
            (
                "override-redirect",
                "XWindowAttributes.override_redirect is true",
            ),
            (
                "override-root-parent",
                "client remains a direct child of the X root",
            ),
        ],
    ),
    (
        "legacy_x11_applications",
        ["legacy-xterm"],
        [
            (
                "legacy-xterm-class",
                "real xterm WM_CLASS is wtwm-legacy-xterm/WtwmLegacyXterm",
            ),
            (
                "legacy-xterm-managed",
                "real xterm client parent is a distinct reference-twm frame",
            ),
        ],
    ),
]
EXPECTED_SOURCE_PATHS = [
    "reference/fixtures/canonical-x11/scenario.twmrc",
    "tests/reference/canonical_x11_client.c",
    "tests/reference/verify_canonical_x11_apps.sh",
]
EXPECTED_RUNTIME_PHASES = [
    {
        "id": "initial",
        "assertions": [
            "normal-managed",
            "normal-no-transient",
            "dialog-managed",
            "dialog-transient-for-normal",
            "dialog-window-type",
            "fixed-managed",
            "fixed-min-max",
            "resize-managed",
            "resize-increments",
            "resize-aspect",
            "title-managed",
            "title-initial-long",
            "icon-managed",
            "icon-name",
            "icon-pixmap-depth1",
            "icon-mask-depth1",
            "urgency-managed",
            "urgency-hint",
            "override-redirect",
            "override-root-parent",
            "legacy-xterm-class",
            "legacy-xterm-managed",
        ],
    },
    {
        "id": "mutation_and_focus",
        "assertions": ["title-mutated", "focus-target-urgent"],
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_text(path: Path) -> tuple[object, str]:
    text = path.read_text(encoding="utf-8")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicate_keys), text


def expected_assertion_ids() -> list[str]:
    return [
        assertion_id
        for _, _, assertions in EXPECTED_CATEGORIES
        for assertion_id, _ in assertions
    ]


def expected_runtime_assertion_ids() -> list[str]:
    return [
        assertion_id
        for phase in EXPECTED_RUNTIME_PHASES
        for assertion_id in phase["assertions"]
    ]


def validate_manifest(manifest: object, source_root: Path) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    errors: list[str] = []
    if list(manifest) != EXPECTED_TOP_KEYS:
        errors.append("manifest top-level keys are incomplete, reordered, or unknown")
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    if manifest.get("suite") != "wtwm canonical X11 applications":
        errors.append("manifest suite identity has drifted")
    if manifest.get("reference") != {
        "name": "X.Org twm",
        "version": "1.0.13.1",
        "binary_contract": "verified tests/reference/build_reference_twm.sh output",
    }:
        errors.append("reference binary contract has drifted")
    if manifest.get("environment") != {
        "contract": "reference/environment/debian-trixie-x11.json",
        "screen": "1024x768x24",
        "server": "private Xvfb display allocated with -displayfd",
    }:
        errors.append("canonical X11 environment has drifted")
    if manifest.get("identity") != {
        "role_property": "_WTWM_CANONICAL_ROLE",
        "volatile_values_forbidden": [
            "display numbers",
            "process IDs",
            "timestamps",
            "temporary paths",
            "XIDs",
        ],
    }:
        errors.append("symbolic role or volatile-value policy has drifted")
    if manifest.get("legacy_application") != {
        "package": "xterm",
        "executable": "xterm",
        "role": "legacy-xterm",
        "wm_class": {
            "res_class": "WtwmLegacyXterm",
            "res_name": "wtwm-legacy-xterm",
        },
    }:
        errors.append("legacy xterm contract has drifted")

    categories = manifest.get("categories")
    expected_categories = [
        {
            "id": category_id,
            "roles": roles,
            "assertions": [
                {"id": assertion_id, "expected": expected}
                for assertion_id, expected in assertions
            ],
        }
        for category_id, roles, assertions in EXPECTED_CATEGORIES
    ]
    if categories != expected_categories:
        errors.append("category, role, or concrete assertion coverage has drifted")
    if isinstance(categories, list):
        category_ids = [
            category.get("id") for category in categories if isinstance(category, dict)
        ]
        if len(category_ids) != len(set(category_ids)):
            errors.append("category IDs must be unique")
        assertions = [
            assertion.get("id")
            for category in categories
            if isinstance(category, dict)
            for assertion in category.get("assertions", [])
            if isinstance(assertion, dict)
        ]
        if len(assertions) != len(set(assertions)):
            errors.append("assertion IDs must be unique")

    if manifest.get("runtime") != {
        "script": "tests/reference/verify_canonical_x11_apps.sh",
        "assertion_protocol": (
            "one exact PASS\\t<assertion-id> record per manifest assertion"
        ),
        "configuration": "reference/fixtures/canonical-x11/scenario.twmrc",
        "baseline_policy": "fixture assertions only; no compatibility baselines",
        "phases": EXPECTED_RUNTIME_PHASES,
    }:
        errors.append("runtime verifier contract has drifted")
    if set(expected_runtime_assertion_ids()) != set(expected_assertion_ids()):
        errors.append("runtime phases do not cover the category assertion set exactly")

    sources = manifest.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be an array")
    else:
        paths = [
            entry.get("path") for entry in sources if isinstance(entry, dict)
        ]
        if paths != EXPECTED_SOURCE_PATHS or len(paths) != len(sources):
            errors.append("canonical source set is incomplete, reordered, or unknown")
        for entry in sources:
            if not isinstance(entry, dict) or list(entry) != ["path", "sha256"]:
                errors.append("each source must contain only path and sha256")
                continue
            relative_path = entry.get("path")
            expected_hash = entry.get("sha256")
            if not isinstance(relative_path, str) or not isinstance(
                expected_hash, str
            ):
                errors.append("source path and sha256 must be strings")
                continue
            path = source_root / relative_path
            try:
                actual_hash = sha256(path)
            except OSError as error:
                errors.append(f"cannot hash canonical source {relative_path}: {error}")
                continue
            if expected_hash != actual_hash:
                errors.append(f"canonical source hash has drifted: {relative_path}")

    workflow_path = source_root / ".github/workflows/build.yml"
    packages_path = source_root / "reference/environment/debian-trixie-x11-packages.txt"
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
        packages = packages_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        errors.append(f"cannot read environment wiring: {error}")
    else:
        marker = (
            'sh tests/reference/verify_canonical_x11_apps.sh "$GITHUB_WORKSPACE" '
            "/tmp/reference-build"
        )
        if marker not in workflow:
            errors.append("reference-twm workflow does not run the canonical suite")
        if "xterm" not in packages:
            errors.append("controlled package list does not include xterm")
    return errors


def validate_runtime_log(text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    observed: list[str] = []
    for line in lines:
        if not line.startswith("PASS\t") or line.count("\t") != 1:
            errors.append(f"invalid runtime assertion record: {line!r}")
            continue
        observed.append(line.split("\t", 1)[1])
    expected = expected_runtime_assertion_ids()
    if observed != expected:
        errors.append("runtime assertions are missing, reordered, duplicated, or unknown")
    return errors


def self_test_tamper(manifest: dict[str, object], source_root: Path) -> list[str]:
    failures: list[str] = []
    tampered = copy.deepcopy(manifest)
    assert isinstance(tampered["categories"], list)
    tampered["categories"] = tampered["categories"][:-1]
    if not validate_manifest(tampered, source_root):
        failures.append("removed category was accepted")

    tampered = copy.deepcopy(manifest)
    categories = tampered["categories"]
    assert isinstance(categories, list) and isinstance(categories[0], dict)
    assertions = categories[0]["assertions"]
    assert isinstance(assertions, list) and isinstance(assertions[0], dict)
    assertions[0]["id"] = "invented-assertion"
    if not validate_manifest(tampered, source_root):
        failures.append("changed assertion ID was accepted")

    tampered = copy.deepcopy(manifest)
    sources = tampered["sources"]
    assert isinstance(sources, list) and isinstance(sources[0], dict)
    sources[0]["sha256"] = "0" * 64
    if not validate_manifest(tampered, source_root):
        failures.append("changed source hash was accepted")

    correct_runtime = "".join(
        f"PASS\t{assertion_id}\n" for assertion_id in expected_runtime_assertion_ids()
    )
    if validate_runtime_log(correct_runtime):
        failures.append("correct synthetic runtime log was rejected")
    runtime_cases = {
        "missing assertion": "\n".join(correct_runtime.splitlines()[:-1]) + "\n",
        "duplicate assertion": correct_runtime + correct_runtime.splitlines()[0] + "\n",
        "unknown assertion": correct_runtime + "PASS\tunknown\n",
        "invalid protocol": correct_runtime.replace("PASS\t", "OK\t", 1),
    }
    for name, text in runtime_cases.items():
        if not validate_runtime_log(text):
            failures.append(f"{name} runtime tamper was accepted")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--runtime-log", type=Path)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        loaded, text = load_json_text(source_root / MANIFEST_PATH)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"canonical X11 manifest error: cannot read manifest: {error}")
        return 1
    errors = validate_manifest(loaded, source_root)
    if isinstance(loaded, dict):
        canonical = json.dumps(loaded, indent=2, ensure_ascii=False) + "\n"
        if text != canonical:
            errors.append("manifest JSON is not in canonical deterministic form")
    if args.runtime_log is not None:
        try:
            runtime_text = args.runtime_log.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"cannot read runtime assertion log: {error}")
        else:
            errors.extend(validate_runtime_log(runtime_text))
    if args.self_test_tamper:
        if not isinstance(loaded, dict):
            errors.append("cannot run tamper tests on a non-object manifest")
        else:
            errors.extend(self_test_tamper(loaded, source_root))
    if errors:
        for error in errors:
            print(f"canonical X11 manifest error: {error}")
        return 1
    print(
        "canonical X11 application manifest valid: "
        f"{len(EXPECTED_CATEGORIES)} categories, "
        f"{len(expected_assertion_ids())} runtime assertions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
