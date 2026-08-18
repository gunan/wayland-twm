#!/usr/bin/env python3
"""Validate the frozen twm 1.0.13.1 Milestone 7 icon contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "reference/icons/twm-1.0.13.1/icon-contract.json"

EXPECTED_ARCHIVE_HASH = (
    "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5"
)
EXPECTED_TOPICS = {
    "icon-window-appearance",
    "mapping-policy",
    "image-selection",
    "bitmap-path-resolution",
    "icon-region-allocation",
    "client-icon-hints",
    "icon-manager-membership",
    "icon-manager-layout",
    "icon-manager-ordering",
    "icon-manager-visibility",
    "icon-manager-highlight-and-input",
    "icon-manager-navigation",
    "start-iconified",
    "animation-and-raise",
    "lifecycle-and-collision-testing",
}
EXPECTED_DIRECTIVES = {
    "DontIconifyByUnmapping",
    "ForceIcons",
    "IconBackground",
    "IconBorderColor",
    "IconBorderWidth",
    "IconDirectory",
    "IconFont",
    "IconForeground",
    "IconifyByUnmapping",
    "IconManagerBackground",
    "IconManagerDontShow",
    "IconManagerFont",
    "IconManagerForeground",
    "IconManagerGeometry",
    "IconManagerHighlight",
    "IconManagers",
    "IconManagerShow",
    "IconRegion",
    "Icons",
    "NoCaseSensitive",
    "NoIconManagers",
    "NoRaiseOnDeiconify",
    "ShowIconManager",
    "SortIconManager",
    "StartIconified",
    "UnknownIcon",
    "WarpCursor",
    "Zoom",
}
EXPECTED_ACTIONS = {
    "f.backiconmgr",
    "f.deiconify",
    "f.delete",
    "f.destroy",
    "f.downiconmgr",
    "f.forcemove",
    "f.forwiconmgr",
    "f.hideiconmgr",
    "f.iconify",
    "f.lefticonmgr",
    "f.lower",
    "f.move",
    "f.nexticonmgr",
    "f.previconmgr",
    "f.raise",
    "f.raiselower",
    "f.righticonmgr",
    "f.showiconmgr",
    "f.sorticonmgr",
    "f.upiconmgr",
    "f.warptoiconmgr",
}
EXPECTED_RULES = {
    "icon.text-source",
    "icon.geometry",
    "icon.border-colors",
    "icon.position",
    "icon.dynamic-hints",
    "mapping.visible-or-unmapped",
    "mapping.state",
    "mapping.restore",
    "mapping.transients",
    "region.geometry",
    "region.allocation",
    "region.gravity",
    "region.center",
    "region.collision",
    "region.moved",
    "manager.membership",
    "manager.geometry",
    "manager.order",
    "manager.lifecycle",
    "manager.appearance",
    "manager.pointer-focus",
    "manager.directional-navigation",
    "manager.cross-navigation",
    "manager.named-navigation",
    "startup.iconic",
    "animation.sequence",
    "raise.deiconify",
    "raise.actions",
}
EXPECTED_IMAGE_PRECEDENCE = [
    "usable-forced-Icons-bitmap",
    "client-IconWindowHint",
    "client-IconPixmapHint",
    "usable-nonforced-Icons-bitmap",
    "UnknownIcon-bitmap",
    "text-only",
]
EXPECTED_SCENARIOS = {
    "image-precedence-matrix",
    "mapping-policy-matrix",
    "region-creation-destruction-replay",
    "region-gravity-grid-matrix",
    "client-position-and-move",
    "manager-membership-order-layout",
    "manager-highlight-pointer-focus",
    "manager-directional-navigation",
    "multiple-managers-across-outputs",
    "start-animation-raise",
    "large-set-lifecycle-churn",
}
EXPECTED_COVERAGE = {
    "image-selection",
    "client-icon-hints",
    "bitmap-path-resolution",
    "screenshots",
    "mapping-policy",
    "navigation-traces",
    "creation-destruction",
    "icon-region-allocation",
    "collisions",
    "full-and-partial-regions",
    "icon-manager-membership",
    "icon-manager-layout",
    "icon-manager-ordering",
    "icon-manager-highlight-and-input",
    "icon-manager-navigation",
    "multiple-managers",
    "multiple-outputs",
    "start-iconified",
    "animation-and-raise",
    "lifecycle-churn",
}
EXPECTED_SOURCE_MEMBERS = {
    "twm-1.0.13.1/man/twm.man",
    "twm-1.0.13.1/src/add_window.c",
    "twm-1.0.13.1/src/events.c",
    "twm-1.0.13.1/src/gram.y",
    "twm-1.0.13.1/src/iconmgr.c",
    "twm-1.0.13.1/src/icons.c",
    "twm-1.0.13.1/src/list.c",
    "twm-1.0.13.1/src/menus.c",
    "twm-1.0.13.1/src/twm.c",
    "twm-1.0.13.1/src/util.c",
}


def load_json(path: Path) -> Any:
    """Load JSON while rejecting duplicate object keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicates)


class ArchiveMembers:
    """Read and cache members from the pinned upstream archive."""

    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self._bytes: dict[str, bytes] = {}

    def read(self, member: str) -> bytes:
        if member not in self._bytes:
            with tarfile.open(self.archive, "r:xz") as source:
                extracted = source.extractfile(member)
                if extracted is None:
                    raise KeyError(f"archive member does not exist: {member}")
                self._bytes[member] = extracted.read()
        return self._bytes[member]

    def line(self, member: str, number: int) -> str:
        lines = self.read(member).decode("utf-8").splitlines()
        if number < 1 or number > len(lines):
            raise IndexError(f"line {number} is outside {member} (1..{len(lines)})")
        return lines[number - 1]


def records_by_name(
    value: Any, field: str, location: str, errors: list[str]
) -> dict[str, dict[str, Any]]:
    """Index an array of objects by a required string field."""

    if not isinstance(value, list):
        errors.append(f"{location} must be an array")
        return {}
    records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(value):
        where = f"{location}[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{where} must be an object")
            continue
        name = record.get(field)
        if not isinstance(name, str) or not name:
            errors.append(f"{where}.{field} must be a nonempty string")
            continue
        if name in records:
            errors.append(f"duplicate {location} {field} {name!r}")
        records[name] = record
    return records


def referenced_evidence(value: Any, location: str = "contract") -> Iterable[tuple[str, str]]:
    """Yield evidence identifiers referenced outside the evidence catalog."""

    if isinstance(value, dict):
        for key, child in value.items():
            if location == "contract" and key == "evidence":
                continue
            if key == "evidence" and isinstance(child, list):
                for index, evidence_id in enumerate(child):
                    if isinstance(evidence_id, str):
                        yield f"{location}.evidence[{index}]", evidence_id
                continue
            yield from referenced_evidence(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from referenced_evidence(child, f"{location}[{index}]")


def require_text(record: dict[str, Any], field: str, where: str, errors: list[str]) -> None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}.{field} must be a nonempty string")


def require_evidence_list(
    record: dict[str, Any], where: str, evidence_ids: set[str], errors: list[str]
) -> None:
    value = record.get("evidence")
    if not isinstance(value, list) or not value:
        errors.append(f"{where}.evidence must be a nonempty array")
        return
    if len(value) != len(set(item for item in value if isinstance(item, str))):
        errors.append(f"{where}.evidence contains duplicates or non-string values")
    for evidence_id in value:
        if not isinstance(evidence_id, str):
            errors.append(f"{where}.evidence values must be strings")
        elif evidence_id not in evidence_ids:
            errors.append(f"{where}.evidence references unknown anchor {evidence_id!r}")


def integer_at_least(record: dict[str, Any], field: str, minimum: int) -> bool:
    value = record.get(field)
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def validate(contract: dict[str, Any], contract_path: Path) -> list[str]:
    errors: list[str] = []

    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    require_text(contract, "contract", "contract", errors)

    upstream = contract.get("upstream")
    if not isinstance(upstream, dict):
        errors.append("upstream must be an object")
        upstream = {}
    if upstream.get("sha256") != EXPECTED_ARCHIVE_HASH:
        errors.append("upstream.sha256 does not pin the approved twm archive")
    if upstream.get("version") != "1.0.13.1":
        errors.append("upstream.version must be 1.0.13.1")
    archive_value = upstream.get("archive")
    if not isinstance(archive_value, str):
        errors.append("upstream.archive must be a repository-relative path")
        archive_path = ROOT / "missing-archive"
    else:
        archive_path = ROOT / archive_value
    if not archive_path.is_file():
        errors.append(f"upstream archive is missing: {archive_path}")
        return errors
    actual_archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual_archive_hash != EXPECTED_ARCHIVE_HASH:
        errors.append(
            f"archive hash mismatch: expected {EXPECTED_ARCHIVE_HASH}, "
            f"got {actual_archive_hash}"
        )

    archive = ArchiveMembers(archive_path)
    source_members = contract.get("source_members")
    if not isinstance(source_members, dict) or not source_members:
        errors.append("source_members must be a nonempty object")
        source_members = {}
    if set(source_members) != EXPECTED_SOURCE_MEMBERS:
        errors.append(
            "source_members must pin the complete icon-contract source set: "
            f"got {sorted(source_members)}"
        )
    for member, expected_hash in source_members.items():
        if not isinstance(member, str) or not isinstance(expected_hash, str):
            errors.append("source_members keys and values must be strings")
            continue
        try:
            data = archive.read(member)
        except KeyError as exc:
            errors.append(str(exc))
            continue
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            errors.append(
                f"source member hash mismatch for {member}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

    topics = contract.get("required_topics")
    if not isinstance(topics, list) or not all(isinstance(item, str) for item in topics):
        errors.append("required_topics must be an array of strings")
        topics = []
    elif len(topics) != len(set(topics)):
        errors.append("required_topics must be a duplicate-free array")
        topics = []
    if set(topics) != EXPECTED_TOPICS:
        errors.append(f"required_topics are incomplete: got {sorted(set(topics))}")

    matching = contract.get("matching")
    if not isinstance(matching, dict):
        errors.append("matching must be an object")
        matching = {}
    if matching.get("order") != ["WM_NAME", "WM_CLASS.res_name", "WM_CLASS.res_class"]:
        errors.append("matching.order must preserve twm name/res_name/res_class precedence")
    if matching.get("case_sensitive") is not True:
        errors.append("matching.case_sensitive must document default exact matching")
    require_text(matching, "duplicate_rule", "matching", errors)

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        errors.append("evidence must be a nonempty object")
        evidence = {}
    evidence_ids = set(evidence)
    require_evidence_list(matching, "matching", evidence_ids, errors)
    for evidence_id, anchor in evidence.items():
        where = f"evidence.{evidence_id}"
        if not isinstance(anchor, dict) or set(anchor) != {"member", "line", "text"}:
            errors.append(f"{where} must contain exactly member, line, and text")
            continue
        member = anchor.get("member")
        line = anchor.get("line")
        text = anchor.get("text")
        if member not in source_members:
            errors.append(f"{where}.member is not pinned in source_members")
            continue
        if not isinstance(line, int) or isinstance(line, bool):
            errors.append(f"{where}.line must be an integer")
            continue
        if not isinstance(text, str) or not text:
            errors.append(f"{where}.text must be a nonempty string")
            continue
        try:
            actual_line = archive.line(member, line).strip()
        except (KeyError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"{where} cannot be read: {exc}")
            continue
        if actual_line != text:
            errors.append(
                f"{where} mismatch at {member}:{line}: "
                f"expected {text!r}, got {actual_line!r}"
            )

    used_evidence: set[str] = set()
    for location, evidence_id in referenced_evidence(contract):
        used_evidence.add(evidence_id)
        if evidence_id not in evidence:
            errors.append(f"{location} references unknown evidence {evidence_id!r}")
    unused_evidence = sorted(evidence_ids - used_evidence)
    if unused_evidence:
        errors.append(f"unreferenced evidence anchors: {', '.join(unused_evidence)}")

    directives = records_by_name(contract.get("directives"), "name", "directives", errors)
    if set(directives) != EXPECTED_DIRECTIVES:
        errors.append(
            "directive coverage mismatch: "
            f"missing={sorted(EXPECTED_DIRECTIVES - set(directives))}, "
            f"extra={sorted(set(directives) - EXPECTED_DIRECTIVES)}"
        )
    for name, record in directives.items():
        require_text(record, "kind", f"directive {name}", errors)
        require_text(record, "rule", f"directive {name}", errors)
        require_evidence_list(record, f"directive {name}", evidence_ids, errors)

    actions = records_by_name(contract.get("actions"), "name", "actions", errors)
    if set(actions) != EXPECTED_ACTIONS:
        errors.append(
            "action coverage mismatch: "
            f"missing={sorted(EXPECTED_ACTIONS - set(actions))}, "
            f"extra={sorted(set(actions) - EXPECTED_ACTIONS)}"
        )
    for name, record in actions.items():
        require_text(record, "rule", f"action {name}", errors)
        require_evidence_list(record, f"action {name}", evidence_ids, errors)

    icon_window = contract.get("icon_window_contract")
    if not isinstance(icon_window, dict):
        errors.append("icon_window_contract must be an object")
        icon_window = {}
    if icon_window.get("image_precedence") != EXPECTED_IMAGE_PRECEDENCE:
        errors.append("icon_window_contract.image_precedence is not the frozen order")
    require_text(
        icon_window,
        "precedence_qualification",
        "icon_window_contract",
        errors,
    )

    region = contract.get("icon_region_contract")
    if not isinstance(region, dict):
        errors.append("icon_region_contract must be an object")
        region = {}
    directions = region.get("directions")
    if directions != {"vertical": ["North", "South"], "horizontal": ["East", "West"]}:
        errors.append("icon_region_contract.directions must freeze North/South and East/West")

    rule_locations = {
        "icon_window_contract": icon_window,
        "mapping_contract": contract.get("mapping_contract"),
        "icon_region_contract": region,
        "icon_manager_contract": contract.get("icon_manager_contract"),
        "startup_animation_raise_contract": contract.get(
            "startup_animation_raise_contract"
        ),
    }
    all_rules: dict[str, dict[str, Any]] = {}
    for section_name, section in rule_locations.items():
        if not isinstance(section, dict):
            errors.append(f"{section_name} must be an object")
            continue
        rules = records_by_name(
            section.get("rules"), "id", f"{section_name}.rules", errors
        )
        for rule_id, record in rules.items():
            if rule_id in all_rules:
                errors.append(f"duplicate contract rule id {rule_id!r}")
            all_rules[rule_id] = record
            require_text(record, "rule", f"rule {rule_id}", errors)
            require_evidence_list(record, f"rule {rule_id}", evidence_ids, errors)
    if set(all_rules) != EXPECTED_RULES:
        errors.append(
            "rule coverage mismatch: "
            f"missing={sorted(EXPECTED_RULES - set(all_rules))}, "
            f"extra={sorted(set(all_rules) - EXPECTED_RULES)}"
        )

    scenarios = records_by_name(
        contract.get("test_scenarios"), "id", "test_scenarios", errors
    )
    if set(scenarios) != EXPECTED_SCENARIOS:
        errors.append(
            "scenario coverage mismatch: "
            f"missing={sorted(EXPECTED_SCENARIOS - set(scenarios))}, "
            f"extra={sorted(set(scenarios) - EXPECTED_SCENARIOS)}"
        )
    observed_coverage: set[str] = set()
    for scenario_id, scenario in scenarios.items():
        where = f"scenario {scenario_id}"
        coverage = scenario.get("coverage")
        if not isinstance(coverage, list) or not coverage:
            errors.append(f"{where}.coverage must be a nonempty array")
        else:
            if not all(isinstance(item, str) for item in coverage):
                errors.append(f"{where}.coverage values must be strings")
            else:
                if len(coverage) != len(set(coverage)):
                    errors.append(f"{where}.coverage must not contain duplicates")
                observed_coverage.update(coverage)
        parameters = scenario.get("parameters")
        if not isinstance(parameters, dict) or not parameters:
            errors.append(f"{where}.parameters must be a nonempty object")
        for field in ("operations", "oracle"):
            value = scenario.get(field)
            if not isinstance(value, list) or not value:
                errors.append(f"{where}.{field} must be a nonempty array")
            elif not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"{where}.{field} values must be nonempty strings")
    if observed_coverage != EXPECTED_COVERAGE:
        errors.append(
            "scenario coverage tags mismatch: "
            f"missing={sorted(EXPECTED_COVERAGE - observed_coverage)}, "
            f"extra={sorted(observed_coverage - EXPECTED_COVERAGE)}"
        )

    multi = scenarios.get("multiple-managers-across-outputs", {}).get("parameters", {})
    if not isinstance(multi, dict):
        multi = {}
    if not integer_at_least(multi, "managers", 3) or not integer_at_least(
        multi, "outputs", 2
    ):
        errors.append("multiple-manager scenario requires at least 3 managers and 2 outputs")
    churn = scenarios.get("large-set-lifecycle-churn", {}).get("parameters", {})
    if not isinstance(churn, dict):
        churn = {}
    if not integer_at_least(churn, "windows", 200) or not integer_at_least(
        churn, "iterations", 1000
    ):
        errors.append("lifecycle churn requires at least 200 windows and 1000 iterations")
    replay = scenarios.get("region-creation-destruction-replay", {}).get(
        "parameters", {}
    )
    if not isinstance(replay, dict):
        replay = {}
    if not integer_at_least(replay, "clients", 32) or not integer_at_least(
        replay, "replays", 2
    ):
        errors.append("creation/destruction replay is not large or repeated enough")

    if contract_path.resolve() != DEFAULT_CONTRACT.resolve():
        # Alternate contracts are supported for negative validator tests. This
        # note intentionally does not make them invalid.
        pass

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "contract",
        nargs="?",
        type=Path,
        default=DEFAULT_CONTRACT,
        help="contract JSON to validate",
    )
    args = parser.parse_args()

    try:
        contract = load_json(args.contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: unable to load {args.contract}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(contract, dict):
        print("error: contract root must be an object", file=sys.stderr)
        return 1

    errors = validate(contract, args.contract)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    rule_count = sum(
        len(contract[name]["rules"])
        for name in (
            "icon_window_contract",
            "mapping_contract",
            "icon_region_contract",
            "icon_manager_contract",
            "startup_animation_raise_contract",
        )
    )
    print(
        "validated twm 1.0.13.1 icon contract: "
        f"{len(contract['directives'])} directives, "
        f"{len(contract['actions'])} actions, "
        f"{rule_count} rules, "
        f"{len(contract['test_scenarios'])} scenarios, "
        f"{len(contract['evidence'])} source anchors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
