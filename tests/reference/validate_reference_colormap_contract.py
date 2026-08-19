#!/usr/bin/env python3
"""Validate the frozen twm f.colormap and Wayland translation contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/colormap-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "28dc696816d9e0cee7eecbddcd936c6917a773ae7c05dc15ed3d4f947e049176"
)
EXPECTED_UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/man/twm.man": (
        "a1743a47770bd63a2ff5e63b8c6e86d72ee02ddd126813951833fb33b8a56674"
    ),
    "twm-1.0.13.1/src/add_window.c": (
        "c3133cc763d2db086e3417b3c2f3c103dc23685690a59e4116cbd338feb7b888"
    ),
    "twm-1.0.13.1/src/events.c": (
        "4fe7f9746d569abe64c7301a1b31197a299eede117d54456929b6e82726366e3"
    ),
    "twm-1.0.13.1/src/gram.y": (
        "7b7c66abb6280891ffc265c25c7989b206e16d883008db44a94dd057f39e8a52"
    ),
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/menus.h": (
        "2ac660c04c2df65c7c2ee6fac5fc2e812cf06b518eedba37705aa68c2a13b572"
    ),
    "twm-1.0.13.1/src/parse.c": (
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c"
    ),
    "twm-1.0.13.1/src/twm.c": (
        "6a8c95df4df186a970e56ed7da4013f6305823c4a9b99cbebfe08f076f01ab3d"
    ),
}
EXPECTED_TOP_LEVEL = {
    "schema_version",
    "contract",
    "upstream",
    "source_members",
    "evidence",
    "reference_behavior",
    "wayland_translation",
    "requirements",
    "verification_scenarios",
}
EXPECTED_EVIDENCE_IDS = {
    "manual.identity",
    "manual.property-source",
    "manual.allowed-arguments",
    "parse.identity",
    "parser.action-rule",
    "parser.colormap-case",
    "parser.invalid-warning",
    "parser.invalid-nop",
    "parser.lowercase",
    "parser.allowed-comparison",
    "constant.next",
    "constant.prev",
    "constant.default",
    "dispatch.case",
    "dispatch.next",
    "dispatch.prev",
    "dispatch.default",
    "bump.targetless-return",
    "bump.rotation-guard",
    "bump.rotation-index",
    "bump.rotation-store",
    "bump.reinstall",
    "bump.default-refetch",
    "fetch.initial",
    "fetch.property",
    "fetch.top-level-search",
    "fetch.top-level-front",
    "fetch.property-order",
    "fetch.query-attributes",
    "fetch.attribute-colormap",
    "fetch.invalid-remove",
    "fetch.invalid-decrement",
    "fetch.fallback",
    "fetch.fallback-top-level",
    "property.reset",
    "install.max-source",
    "install.max-screen",
    "install.visible-and-bounded",
    "install.max-condition",
    "install.conflict-skip",
    "install.reverse-selected-order",
    "install.request",
}
EXPECTED_ARGUMENTS = [
    {"argument": "next", "function": "F_COLORMAP", "increment": 1},
    {"argument": "prev", "function": "F_COLORMAP", "increment": -1},
    {"argument": "default", "function": "F_COLORMAP", "increment": 0},
]
EXPECTED_INCREMENTS = {"next": 1, "prev": -1, "default": 0}
EXPECTED_ROTATIONS = {
    "property_order": ["A", "B", "C"],
    "next": ["B", "C", "A"],
    "prev": ["C", "A", "B"],
    "default": ["A", "B", "C"],
}
EXPECTED_TRIGGERS = [
    "initial management",
    "WM_COLORMAP_WINDOWS PropertyNotify",
    "f.colormap default",
]
EXPECTED_CLASSIFICATIONS = {
    "relevant_xwayland_target": "behaviorally-equivalent",
    "native_true_color_wayland_target": "verified-no-op",
    "no_target": "verified-no-op",
}
EXPECTED_REQUIREMENTS = {
    "colormap.parser",
    "colormap.xwayland-property",
    "colormap.rotation-reset",
    "colormap.installation",
    "colormap.native-no-op",
    "colormap.resource-safety",
}
EXPECTED_SCENARIOS = {
    "parser-accepted-casefold": "parser-positive",
    "parser-invalid-nop": "parser-negative",
    "xwayland-property-order-and-filter": "runtime-positive-negative-pair",
    "xwayland-next-prev-default": "runtime-state-machine",
    "xwayland-property-change-reset": "runtime-state-machine",
    "xwayland-install-capacity": "runtime-boundary",
    "native-wayland-no-op": "runtime-negative",
    "targetless-no-op": "runtime-negative",
    "xwayland-invalid-and-oversized-resources": "runtime-resource-safety",
}


def load_json(path: Path) -> Any:
    """Load JSON and reject duplicate keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def records_by_id(value: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    result: dict[str, Any] = {}
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            errors.append(f"{location}[{index}] must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{location}[{index}].id must be a nonempty string")
            continue
        if record_id in result:
            errors.append(f"duplicate {location} id {record_id!r}")
        result[record_id] = record
    return result


def evidence_references(value: Any, at_root: bool = True) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if at_root and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, str):
                yield child
            elif key == "evidence" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from evidence_references(child, False)
    elif isinstance(value, list):
        for child in value:
            yield from evidence_references(child, False)


def require_object(parent: Any, key: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(parent, dict) or not isinstance(parent.get(key), dict):
        errors.append(f"{key} must be an object")
        return {}
    return parent[key]


def validate_inventory(root: Path, identity: dict[str, Any], errors: list[str]) -> None:
    inventory_path = root / EXPECTED_UPSTREAM["inventory"]
    try:
        inventory = load_json(inventory_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load inventory: {exc}")
        return
    keywords = inventory.get("keywords") if isinstance(inventory, dict) else None
    if not isinstance(keywords, list):
        errors.append("inventory keywords must be an array")
        return
    item = next(
        (
            entry
            for entry in keywords
            if isinstance(entry, dict) and entry.get("id") == "keyword.f.colormap"
        ),
        None,
    )
    if not isinstance(item, dict):
        errors.append("inventory lacks keyword.f.colormap")
        return
    expected = {
        "spelling": "f.colormap",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_COLORMAP",
    }
    for key, value in expected.items():
        if item.get(key) != value:
            errors.append(f"inventory f.colormap {key} mismatch")
    if identity.get("inventory_id") != item.get("id"):
        errors.append("contract identity does not match inventory id")


def validate_archive(
    root: Path,
    upstream: dict[str, Any],
    source_members: Any,
    evidence: Any,
    errors: list[str],
) -> None:
    archive_path = root / EXPECTED_UPSTREAM["archive"]
    try:
        archive_bytes = archive_path.read_bytes()
    except OSError as exc:
        errors.append(f"cannot read upstream archive: {exc}")
        return
    actual_archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    if actual_archive_hash != EXPECTED_UPSTREAM["sha256"]:
        errors.append("upstream archive bytes do not match pinned sha256")
    if upstream.get("sha256") != actual_archive_hash:
        errors.append("contract upstream sha256 does not match archive bytes")

    if not isinstance(source_members, dict):
        return
    if not isinstance(evidence, dict):
        return
    member_bytes: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, "r:xz") as archive:
            for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
                extracted = archive.extractfile(member)
                if extracted is None:
                    errors.append(f"archive lacks pinned source member {member}")
                    continue
                content = extracted.read()
                member_bytes[member] = content
                if hashlib.sha256(content).hexdigest() != expected_hash:
                    errors.append(f"archive member hash mismatch: {member}")
    except (OSError, tarfile.TarError) as exc:
        errors.append(f"cannot inspect upstream archive: {exc}")
        return

    for evidence_id, anchor in evidence.items():
        if not isinstance(anchor, dict):
            errors.append(f"evidence {evidence_id!r} must be an object")
            continue
        member = anchor.get("member")
        line = anchor.get("line")
        text = anchor.get("text")
        if not isinstance(member, str) or member not in member_bytes:
            errors.append(f"evidence {evidence_id!r} has an unknown member")
            continue
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            errors.append(f"evidence {evidence_id!r} has an invalid line")
            continue
        if not isinstance(text, str):
            errors.append(f"evidence {evidence_id!r} has invalid text")
            continue
        lines = member_bytes[member].decode("utf-8").splitlines()
        if line > len(lines) or lines[line - 1] != text:
            errors.append(f"evidence {evidence_id!r} does not match the archive line")


def validate_contract(
    contract: Any,
    *,
    root: Path = ROOT,
    verify_archive_bytes: bool = True,
    verify_canonical: bool = True,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract root must be an object"]
    if set(contract) != EXPECTED_TOP_LEVEL:
        errors.append("top-level keys do not match the colormap contract schema")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if verify_canonical and canonical_sha256(contract) != EXPECTED_CANONICAL_SHA256:
        errors.append("canonical contract sha256 mismatch")

    upstream = require_object(contract, "upstream", errors)
    if upstream != EXPECTED_UPSTREAM:
        errors.append("upstream identity or archive pin mismatch")
    source_members = contract.get("source_members")
    if source_members != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes do not match the pinned set")
    evidence = contract.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
        evidence = {}
    elif set(evidence) != EXPECTED_EVIDENCE_IDS:
        errors.append("evidence ids do not match the required colormap anchors")
    if verify_archive_bytes:
        validate_archive(root, upstream, source_members, evidence, errors)

    behavior = require_object(contract, "reference_behavior", errors)
    identity = require_object(behavior, "identity", errors)
    expected_identity = {
        "name": "f.colormap",
        "inventory_id": "keyword.f.colormap",
        "parser_token": "FSKEYWORD",
        "parser_value": "F_COLORMAP",
        "argument_count": 1,
    }
    for key, value in expected_identity.items():
        if identity.get(key) != value:
            errors.append(f"f.colormap identity {key} mismatch")
    validate_inventory(root, identity, errors)

    decoding = require_object(behavior, "argument_decoding", errors)
    if decoding.get("normalization") != (
        "ISO Latin-1 lowercase in place before comparison"
    ):
        errors.append("argument lowercase normalization mismatch")
    if decoding.get("accepted") != EXPECTED_ARGUMENTS:
        errors.append("accepted next/prev/default decoding mismatch")
    invalid = decoding.get("invalid")
    if invalid != {
        "function": "F_NOP",
        "diagnostic": "ignoring invalid f.colormap argument",
        "dispatches": False,
    }:
        errors.append("invalid f.colormap must diagnose and decode to non-dispatching F_NOP")

    dispatch = require_object(behavior, "dispatch", errors)
    if dispatch.get("callee") != "BumpWindowColormap":
        errors.append("f.colormap dispatch callee mismatch")
    if dispatch.get("increments") != EXPECTED_INCREMENTS:
        errors.append("dispatch next/prev/default increments mismatch")
    targetless = dispatch.get("targetless")
    if not isinstance(targetless, str) or not all(
        term in targetless for term in ("return", "property", "installation", "state")
    ):
        errors.append("targetless dispatch must be an observable no-op")

    fetch = require_object(behavior, "fetch_and_reset", errors)
    if fetch.get("triggers") != EXPECTED_TRIGGERS:
        errors.append("fetch/reset triggers mismatch")
    valid_property = fetch.get("valid_property")
    if not isinstance(valid_property, str) or not all(
        term in valid_property
        for term in ("preserve", "insert it at index zero", "original order")
    ):
        errors.append("WM_COLORMAP_WINDOWS order/top-level insertion mismatch")
    fallback = fetch.get("invalid_or_empty_property")
    if not isinstance(fallback, str) or "sole entry" not in fallback:
        errors.append("invalid or empty property must fall back to the top-level")
    resolution = fetch.get("entry_resolution")
    if not isinstance(resolution, str) or not all(
        term in resolution for term in ("attributes", "colormap")
    ):
        errors.append("property entries must resolve their X colormap attributes")
    invalid_entry = fetch.get("invalid_entry")
    if not isinstance(invalid_entry, str) or not all(
        term in invalid_entry for term in ("remove", "relative order", "remaining")
    ):
        errors.append("invalid property entries must be filtered stably")
    if fetch.get("client_property_mutation") is not False:
        errors.append("reference fetch/rotation must not mutate the client property")

    rotation = require_object(behavior, "rotation", errors)
    if rotation.get("index_rule") != (
        "destination = (source_index - increment) modulo entry_count"
    ):
        errors.append("rotation index rule mismatch")
    if rotation.get("examples") != EXPECTED_ROTATIONS:
        errors.append("next/prev/default circular rotation directions mismatch")
    if rotation.get("reinstall_when_active") is not True:
        errors.append("active rotated lists must be reinstalled")
    allocation_failure = rotation.get("allocation_failure")
    if not isinstance(allocation_failure, str) or not all(
        term in allocation_failure for term in ("existing", "unchanged")
    ):
        errors.append("rotation allocation failure must preserve active state")

    installation = require_object(behavior, "installation", errors)
    if installation.get("capacity") != "MaxCmapsOfScreen for the target X screen":
        errors.append("installation capacity must come from MaxCmapsOfScreen")
    selection = installation.get("selection_order")
    if not isinstance(selection, str) or not all(
        term in selection
        for term in ("index zero", "non-fully-obscured", "capacity", "conflicts")
    ):
        errors.append("visible conflict-free installation selection mismatch")
    if installation.get("request_order") != (
        "issue XInstallColormap for selected entries in reverse list-index order"
    ):
        errors.append("XInstallColormap request order mismatch")
    observable = installation.get("observable_result")
    if not isinstance(observable, str) or not all(
        term in observable
        for term in ("XInstallColormap", "installed-colormap list", "capacity one")
    ):
        errors.append("installed-colormap observability is underspecified")

    translation = require_object(contract, "wayland_translation", errors)
    if translation.get("classification") != EXPECTED_CLASSIFICATIONS:
        errors.append("Xwayland/native/no-target classifications mismatch")
    xwayland = require_object(translation, "xwayland", errors)
    xwayland_checks = {
        "property": ("WM_COLORMAP_WINDOWS", "without mutating"),
        "resolution": ("colormap attribute", "unqueryable"),
        "state": ("per managed Xwayland toplevel", "property change"),
        "rotation": ("next/prev",),
        "installation": ("XWM connection", "maximum installed maps"),
        "observability": ("installed-colormap list", "byte-for-byte unchanged"),
    }
    for key, terms in xwayland_checks.items():
        value = xwayland.get(key)
        if not isinstance(value, str) or not all(term in value for term in terms):
            errors.append(f"Xwayland translation {key} boundary mismatch")
    native = require_object(translation, "native_wayland", errors)
    if native.get("x_requests") != []:
        errors.append("native true-color Wayland action must issue no X requests")
    if native.get("installed_x_colormaps") != "unchanged":
        errors.append("native action must preserve installed X colormaps")
    native_result = native.get("result")
    if not isinstance(native_result, str) or not all(
        term in native_result
        for term in ("pixels", "focus", "geometry", "stacking", "input", "liveness")
    ):
        errors.append("native no-op invariants are incomplete")
    no_target = require_object(translation, "no_target", errors)
    no_target_result = no_target.get("result")
    if not isinstance(no_target_result, str) or not all(
        term in no_target_result for term in ("without X requests", "state changes")
    ):
        errors.append("no-target translation must issue no X requests or state changes")

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENTS:
        errors.append("requirement ids do not match the colormap contract")
    resource = requirements.get("colormap.resource-safety", {})
    resource_text = resource.get("text") if isinstance(resource, dict) else None
    resource_terms = (
        "at most 4096 entries",
        "overflow",
        "release every X reply",
        "destroyed",
        "invalid X resources",
        "checked X requests",
        "never mutate the client property",
    )
    if not isinstance(resource_text, str) or not all(
        term in resource_text for term in resource_terms
    ):
        errors.append("bounded X resource-safety requirements are incomplete")

    scenarios = records_by_id(
        contract.get("verification_scenarios"),
        "verification_scenarios",
        errors,
    )
    if {key: value.get("kind") for key, value in scenarios.items()} != (
        EXPECTED_SCENARIOS
    ):
        errors.append("verification scenario ids or kinds mismatch")
    for scenario_id, scenario in scenarios.items():
        assertions = scenario.get("assertions")
        if not isinstance(assertions, list) or len(assertions) < 2 or not all(
            isinstance(item, str) and item for item in assertions
        ):
            errors.append(f"verification scenario {scenario_id!r} lacks assertions")

    referenced = set(evidence_references(contract))
    unknown = sorted(referenced - set(evidence))
    unused = sorted(set(evidence) - referenced)
    if unknown:
        errors.append("unknown evidence references: " + ", ".join(unknown))
    if unused:
        errors.append("unused evidence anchors: " + ", ".join(unused))
    return errors


Mutation = Callable[[dict[str, Any]], None]


def run_self_tests(contract: dict[str, Any]) -> list[str]:
    """Prove distinct semantic pins reject representative in-memory tampering."""

    cases: list[tuple[str, Mutation, str, bool]] = []

    def case(
        name: str,
        mutation: Mutation,
        expected_error: str,
        *,
        archive: bool = False,
    ) -> None:
        cases.append((name, mutation, expected_error, archive))

    case(
        "archive-pin",
        lambda value: value["upstream"].__setitem__("sha256", "0" * 64),
        "upstream identity or archive pin mismatch",
    )
    case(
        "source-member-pin",
        lambda value: value["source_members"].__setitem__(
            "twm-1.0.13.1/src/menus.c", "0" * 64
        ),
        "source member hashes do not match",
    )
    case(
        "exact-anchor",
        lambda value: value["evidence"]["dispatch.next"].__setitem__(
            "text", "            BumpWindowColormap(tmp_win, 2);"
        ),
        "does not match the archive line",
        archive=True,
    )
    case(
        "parser-token",
        lambda value: value["reference_behavior"]["identity"].__setitem__(
            "parser_token", "FKEYWORD"
        ),
        "identity parser_token mismatch",
    )
    case(
        "accepted-arguments",
        lambda value: value["reference_behavior"]["argument_decoding"][
            "accepted"
        ].pop(),
        "accepted next/prev/default decoding mismatch",
    )
    case(
        "invalid-nop",
        lambda value: value["reference_behavior"]["argument_decoding"][
            "invalid"
        ].__setitem__("function", "F_COLORMAP"),
        "invalid f.colormap must diagnose",
    )
    case(
        "dispatch-direction",
        lambda value: value["reference_behavior"]["dispatch"]["increments"].__setitem__(
            "next", -1
        ),
        "dispatch next/prev/default increments mismatch",
    )
    case(
        "property-order",
        lambda value: value["reference_behavior"]["fetch_and_reset"].__setitem__(
            "valid_property", "sort all entries by window id"
        ),
        "WM_COLORMAP_WINDOWS order/top-level insertion mismatch",
    )
    case(
        "invalid-entry-filter",
        lambda value: value["reference_behavior"]["fetch_and_reset"].__setitem__(
            "invalid_entry", "fail the entire action"
        ),
        "invalid property entries must be filtered stably",
    )
    case(
        "next-rotation",
        lambda value: value["reference_behavior"]["rotation"]["examples"].__setitem__(
            "next", ["C", "A", "B"]
        ),
        "circular rotation directions mismatch",
    )
    case(
        "default-reset",
        lambda value: value["reference_behavior"]["rotation"]["examples"].__setitem__(
            "default", ["B", "C", "A"]
        ),
        "circular rotation directions mismatch",
    )
    case(
        "screen-capacity",
        lambda value: value["reference_behavior"]["installation"].__setitem__(
            "capacity", "one"
        ),
        "capacity must come from MaxCmapsOfScreen",
    )
    case(
        "install-order",
        lambda value: value["reference_behavior"]["installation"].__setitem__(
            "request_order", "forward"
        ),
        "XInstallColormap request order mismatch",
    )
    case(
        "xwayland-classification",
        lambda value: value["wayland_translation"]["classification"].__setitem__(
            "relevant_xwayland_target", "verified-no-op"
        ),
        "classifications mismatch",
    )
    case(
        "native-no-x-request",
        lambda value: value["wayland_translation"]["native_wayland"][
            "x_requests"
        ].append("GetProperty"),
        "must issue no X requests",
    )
    case(
        "resource-bound",
        lambda value: value["requirements"][5].__setitem__(
            "text", "Accept an arbitrary number of entries."
        ),
        "resource-safety requirements are incomplete",
    )
    case(
        "scenario-coverage",
        lambda value: value["verification_scenarios"].pop(),
        "verification scenario ids or kinds mismatch",
    )
    case(
        "evidence-closure",
        lambda value: value["requirements"][0]["evidence"].append("missing.anchor"),
        "unknown evidence references",
    )

    failures: list[str] = []
    for name, mutation, expected_error, archive in cases:
        candidate = copy.deepcopy(contract)
        mutation(candidate)
        errors = validate_contract(
            candidate,
            root=ROOT,
            verify_archive_bytes=archive,
            verify_canonical=False,
        )
        if not any(expected_error in error for error in errors):
            failures.append(
                f"tamper test {name!r} did not produce {expected_error!r}; "
                f"errors were {errors!r}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="also run the in-memory semantic tamper suite",
    )
    args = parser.parse_args()
    path = ROOT / CONTRACT_PATH
    try:
        contract = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"colormap contract validation: FAIL: {exc}", file=sys.stderr)
        return 1
    errors = validate_contract(contract)
    if args.self_test and not errors:
        errors.extend(run_self_tests(contract))
    if errors:
        for error in errors:
            print(f"colormap contract validation: FAIL: {error}", file=sys.stderr)
        return 1
    suffix = "; 18 tamper tests passed" if args.self_test else ""
    print(
        "colormap contract validation: PASS "
        f"({len(EXPECTED_EVIDENCE_IDS)} exact upstream anchors{suffix})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
