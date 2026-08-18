#!/usr/bin/env python3
"""Validate the frozen twm X-screen to wtwm Wayland-output contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/screen-output-contract.json"
)
EXPECTED_CANONICAL_SHA256 = (
    "0d1b99929119bc4992226520fae7cf3c18c48bd69b1052ab9176c1635cdbb0ce"
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
    "twm-1.0.13.1/src/menus.c": (
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83"
    ),
    "twm-1.0.13.1/src/parse.c": (
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c"
    ),
    "twm-1.0.13.1/src/screen.h": (
        "f238b482ee38fd1d75f410574d36b47e2dafec50808518b7ca374924785e48b0"
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
    "current_surface",
    "reference_behavior",
    "wayland_translation",
    "scope_boundaries",
    "requirements",
    "verification_scenarios",
}
EXPECTED_REQUIREMENT_IDS = {
    "screen.reference-model",
    "screen.global-config",
    "screen.screen-zero-search",
    "screen.explicit-global",
    "screen.canonical-index",
    "screen.numeric-safety",
    "screen.config-lifecycle",
    "screen.scope-boundary",
}
EXPECTED_SCENARIOS = {
    "reference-two-x-screens": "reference-positive",
    "reference-single-option": "reference-boundary",
    "reference-implicit-per-screen-files": "reference-search-order",
    "reference-explicit-file": "reference-search-order",
    "wtwm-zero-output-startup": "runtime-zero-output",
    "wtwm-one-output": "runtime-one-output",
    "wtwm-multiple-outputs-single-config": "runtime-multi-output",
    "wtwm-ignore-higher-screen-files": "runtime-negative",
    "wtwm-explicit-global": "runtime-multi-output",
    "canonical-name-order": "runtime-ordering",
    "canonical-secondary-fields": "runtime-ordering",
    "canonical-collision-ordinal": "runtime-ordering-boundary",
    "mode-scale-layout-stability": "runtime-stability",
    "valid-numeric-targets": "runtime-boundary",
    "negative-numeric-rejected": "runtime-negative",
    "signed-and-whitespace-rejected": "runtime-negative",
    "malformed-and-overflow-rejected": "runtime-negative",
    "out-of-range-rejected": "runtime-negative",
    "good-reload-all-outputs": "runtime-lifecycle",
    "invalid-reload-preserves": "runtime-lifecycle-negative",
    "restart-source-stability": "runtime-lifecycle",
    "output-add-active-config": "runtime-topology",
    "output-remove-config-stability": "runtime-topology",
    "deferred-behavior-not-claimed": "contract-scope",
}
EXPECTED_IMPLICIT_SEARCH = [
    "$HOME/.twmrc.0",
    "$HOME/.twmrc",
    "WTWM_SYSTEM_CONFIG or the packaged wtwm system.twmrc",
    "built-in defaults",
]
EXPECTED_DEFERRED = [
    "output-aware window placement and complete per-output root behavior",
    "f.warptoscreen execution, next/prev/back history, and pointer coordinate translation",
    "output addition/removal/scale/mode transaction mechanics",
    "safe restoration or relocation of windows after output removal",
    "input hotplug and multiple seats",
    "persistent physical-output identity across sessions when backend identity strings collide",
]
SOURCE_PATHS = (
    "src/config.c",
    "src/wtwm.c",
    "src/actions.c",
    "tests/config_test.c",
    "tests/actions_test.c",
)


def load_json(path: Path) -> Any:
    """Load JSON while rejecting duplicate keys."""

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
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def records_by_id(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return {}
    result: dict[str, Any] = {}
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            errors.append(f"{label}[{index}] must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{label}[{index}] has no nonempty id")
        elif record_id in result:
            errors.append(f"duplicate {label} id: {record_id}")
        else:
            result[record_id] = record
    return result


def evidence_references(value: Any, *, at_root: bool = True) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if at_root and key in {"evidence", "current_surface"}:
                continue
            if key == "evidence" and isinstance(nested, list):
                yield from (item for item in nested if isinstance(item, str))
            else:
                yield from evidence_references(nested, at_root=False)
    elif isinstance(value, list):
        for nested in value:
            yield from evidence_references(nested, at_root=False)


def validate_archive(
    root: Path,
    upstream: Any,
    source_members: Any,
    evidence: dict[str, Any],
    errors: list[str],
) -> None:
    if upstream != EXPECTED_UPSTREAM:
        return
    archive_path = root / EXPECTED_UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append(f"missing upstream archive: {archive_path}")
        return
    archive_data = archive_path.read_bytes()
    if sha256_bytes(archive_data) != EXPECTED_UPSTREAM["sha256"]:
        errors.append("upstream archive hash mismatch")
        return
    if source_members != EXPECTED_SOURCE_MEMBERS:
        return
    try:
        with tarfile.open(archive_path, "r:xz") as archive:
            member_lines: dict[str, list[str]] = {}
            for member, expected_hash in EXPECTED_SOURCE_MEMBERS.items():
                extracted = archive.extractfile(member)
                if extracted is None:
                    errors.append(f"missing archive member: {member}")
                    continue
                data = extracted.read()
                if sha256_bytes(data) != expected_hash:
                    errors.append(f"archive member hash mismatch: {member}")
                member_lines[member] = data.decode("utf-8").splitlines()
            for evidence_id, anchor in evidence.items():
                if not isinstance(anchor, dict) or set(anchor) != {
                    "member", "line", "text"
                }:
                    errors.append(f"{evidence_id} source anchor fields differ")
                    continue
                member = anchor.get("member")
                line = anchor.get("line")
                text = anchor.get("text")
                if member not in member_lines:
                    errors.append(f"{evidence_id} cites unknown member")
                    continue
                if not isinstance(line, int) or line < 1 or line > len(
                    member_lines[member]
                ):
                    errors.append(f"{evidence_id} line is out of range")
                    continue
                if member_lines[member][line - 1] != text:
                    errors.append(f"{evidence_id} exact source text mismatch")
    except (OSError, tarfile.TarError, UnicodeDecodeError) as exc:
        errors.append(f"unable to inspect upstream archive: {exc}")


def validate_inventory(inventory: Any, errors: list[str]) -> None:
    if not isinstance(inventory, dict):
        errors.append("inventory must be an object")
        return
    if inventory.get("schema_version") != 1:
        errors.append("inventory schema_version mismatch")
    if inventory.get("upstream") != {
        key: EXPECTED_UPSTREAM[key]
        for key in ("name", "version", "archive", "sha256")
    }:
        errors.append("inventory does not pin the same upstream release")


def load_sources(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in SOURCE_PATHS:
        result[relative] = (root / relative).read_text(encoding="utf-8")
    return result


def validate_current_surface(
    value: Any, sources: dict[str, str], errors: list[str]
) -> None:
    if not isinstance(value, dict) or set(value) != {"source_anchors", "observed"}:
        errors.append("current_surface fields differ from schema")
        return
    anchors = value.get("source_anchors")
    if not isinstance(anchors, dict) or len(anchors) != 12:
        errors.append("current source-anchor coverage mismatch")
        return
    for anchor_id, anchor in anchors.items():
        if not isinstance(anchor, dict) or set(anchor) != {"path", "text"}:
            errors.append(f"{anchor_id} current anchor fields differ")
            continue
        path = anchor.get("path")
        text = anchor.get("text")
        if path not in sources:
            errors.append(f"{anchor_id} cites an uninspected source")
        elif not isinstance(text, str) or text not in sources[path]:
            errors.append(f"{anchor_id} current source text missing")
    observed = value.get("observed")
    if not isinstance(observed, list) or len(observed) != 5 or not all(
        isinstance(item, str) and item for item in observed
    ):
        errors.append("current observed-surface record mismatch")

    config = sources.get("src/config.c", "")
    runtime = sources.get("src/wtwm.c", "")
    actions = sources.get("src/actions.c", "")
    required_config = (
        '"%s/.twmrc.%u", home, screen',
        "path == NULL ? screen_path : NULL",
        "path == NULL ? general_path : NULL",
        "return wtwm_config_load_for_screen(config, path, 0, error, error_size);",
        "static bool decimal_string(const char *text) {",
        "decimal_string(action->argument);",
    )
    for snippet in required_config:
        if snippet not in config:
            errors.append(f"screen-zero loader structure missing: {snippet}")
    if runtime.count("struct wtwm_config config;") != 1:
        errors.append("server must expose one global config field")
    if "wtwm_config_load(&server.config, config_path" not in runtime:
        errors.append("startup must use the screen-zero global loader")
    if "wtwm_config_load(&replacement, config_path" not in runtime:
        errors.append("restart must use the screen-zero global loader")
    required_action = (
        "strtol(argument, &end, 10)",
        "end == argument || *end != '\\0' || parsed < 0",
        "parsed >= count || parsed > INT_MAX",
    )
    for snippet in required_action:
        if snippet not in actions:
            errors.append(f"strict numeric screen parser missing: {snippet}")


def require_object(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def validate_reference_behavior(value: Any, errors: list[str]) -> None:
    behavior = require_object(value, "reference_behavior", errors)
    if set(behavior) != {"managed_screens", "configuration", "numeric_spatial_screen"}:
        errors.append("reference behavior sections differ")
        return
    managed = require_object(behavior.get("managed_screens"), "managed_screens", errors)
    if "0 through ScreenCount(dpy)-1" not in str(managed.get("default")):
        errors.append("reference all-screen range mismatch")
    if "DefaultScreen(dpy)" not in str(managed.get("single_option")):
        errors.append("reference -single behavior mismatch")
    if not all(
        term in str(managed.get("root_namespace"))
        for term in ("RootWindow", "ScreenInfo", "menus", "screen dimensions")
    ):
        errors.append("reference per-screen namespace mismatch")
    config = require_object(behavior.get("configuration"), "configuration", errors)
    expected_search = [
        "$HOME/.twmrc.<that X screen number>",
        "$HOME/.twmrc",
        "DATADIR/X11/twm/system.twmrc",
        "built-in defaults",
    ]
    if config.get("implicit_search_per_screen") != expected_search:
        errors.append("reference per-screen search order mismatch")
    if "same filename" not in str(config.get("explicit_file")) or "not merged" not in str(
        config.get("explicit_file")
    ):
        errors.append("reference explicit-file behavior mismatch")
    numeric = require_object(
        behavior.get("numeric_spatial_screen"), "numeric_spatial_screen", errors
    )
    if "zero-based" not in str(numeric.get("domain")) or "ScreenList" not in str(
        numeric.get("domain")
    ):
        errors.append("reference numeric screen domain mismatch")
    if "atoi" not in str(numeric.get("warp_parser")):
        errors.append("reference numeric conversion mismatch")
    if not all(
        term in str(numeric.get("warp_range"))
        for term in ("negative", "last X screen", "NumScreens", "unmanaged")
    ):
        errors.append("reference warp range behavior mismatch")


def validate_translation(value: Any, errors: list[str]) -> None:
    translation = require_object(value, "wayland_translation", errors)
    if set(translation) != {
        "classification",
        "configuration_namespace",
        "canonical_output_indices",
        "lifecycle",
    }:
        errors.append("Wayland translation sections differ")
        return
    if translation.get("classification") != (
        "behaviorally-equivalent global-namespace translation with a documented "
        "screen-index safety difference"
    ):
        errors.append("translation classification mismatch")
    namespace = require_object(
        translation.get("configuration_namespace"), "configuration_namespace", errors
    )
    if namespace.get("implicit_search") != EXPECTED_IMPLICIT_SEARCH:
        errors.append("screen-zero search order mismatch")
    if not all(
        term in str(namespace.get("screen_zero_rule"))
        for term in ("sole compatibility source", "Never read", ".twmrc.1")
    ):
        errors.append("screen-zero sole-source rule mismatch")
    if not all(
        term in str(namespace.get("explicit_file_rule"))
        for term in ("global configuration", "not suffixed", "not", "combined")
    ):
        errors.append("explicit global config rule mismatch")
    if "Every current or later-created output scene" not in str(
        namespace.get("application_rule")
    ):
        errors.append("all-output application rule mismatch")
    if "no output is active" not in str(namespace.get("zero_outputs")):
        errors.append("zero-output configuration behavior mismatch")
    if "index 0" not in str(namespace.get("one_output")):
        errors.append("one-output mapping mismatch")
    if "identical global configuration" not in str(namespace.get("multiple_outputs")):
        errors.append("multi-output global mapping mismatch")

    indices = require_object(
        translation.get("canonical_output_indices"),
        "canonical_output_indices",
        errors,
    )
    if not all(
        term in str(indices.get("domain"))
        for term in ("enabled", "compositor-managed", "dense zero-based")
    ):
        errors.append("canonical index domain mismatch")
    identity = str(indices.get("stable_identity"))
    if not all(
        term in identity
        for term in (
            "immutable session identity key",
            "wlr_output name",
            "(name, make, model, serial)",
            "never-reused announcement ordinal",
        )
    ):
        errors.append("stable output identity rule mismatch")
    order = str(indices.get("canonical_order"))
    if not all(
        term in order
        for term in (
            "unsigned-byte lexicographic",
            "(name, make, model, serial)",
            "announcement ordinal",
            "wl_list insertion order",
            "layout coordinates",
        )
    ):
        errors.append("canonical output ordering mismatch")
    stability = str(indices.get("stability"))
    if not all(
        term in stability
        for term in ("Mode, scale, transform", "cannot change", "may renumber")
    ):
        errors.append("output index stability boundary mismatch")
    if not all(
        term in str(indices.get("restart_expectation"))
        for term in ("unique stable output names", "discovery order", "not claimed persistent")
    ):
        errors.append("cross-restart identity expectation mismatch")
    valid = str(indices.get("valid_decimal"))
    if not all(
        term in valid
        for term in ("ASCII decimal digits only", "no sign", "whitespace", "suffix", "fit int")
    ):
        errors.append("valid numeric reference grammar mismatch")
    invalid = str(indices.get("invalid_reference"))
    if not all(
        term in invalid
        for term in ("negative", "malformed", "overflow", "out-of-range", "no spatial mutation")
    ):
        errors.append("invalid numeric reference behavior mismatch")
    if "intentional safety difference" not in str(indices.get("safety_difference")):
        errors.append("screen-index safety difference not documented")

    lifecycle = require_object(translation.get("lifecycle"), "lifecycle", errors)
    if not all(term in str(lifecycle.get("reload")) for term in ("atomically", "every output", "invalid")):
        errors.append("reload lifecycle mapping mismatch")
    if "focused output" not in str(lifecycle.get("restart")):
        errors.append("restart source-selection mapping mismatch")
    if "never triggers another startup-file search" not in str(
        lifecycle.get("output_add")
    ):
        errors.append("output-add config behavior mismatch")
    if "never changes the active configuration" not in str(
        lifecycle.get("output_remove")
    ):
        errors.append("output-remove config behavior mismatch")
    if not all(
        term in str(lifecycle.get("topology_boundary"))
        for term in ("window relocation", "output-aware placement", "warp execution", "later")
    ):
        errors.append("topology scope boundary mismatch")


def validate_scope(value: Any, errors: list[str]) -> None:
    scope = require_object(value, "scope_boundaries", errors)
    if set(scope) != {"this_mapping_requires", "explicitly_deferred", "non_claim"}:
        errors.append("scope boundary fields differ")
        return
    required = scope.get("this_mapping_requires")
    if not isinstance(required, list) or len(required) != 5:
        errors.append("mapping requirement summary mismatch")
    if scope.get("explicitly_deferred") != EXPECTED_DEFERRED:
        errors.append("deferred Milestone 8 scope mismatch")
    if "does not by itself complete" not in str(scope.get("non_claim")):
        errors.append("Roadmap non-claim missing")


def validate_contract(
    contract: Any,
    inventory: Any,
    source_root: Path,
    *,
    verify_canonical: bool = True,
    verify_archive: bool = True,
    sources: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]
    if set(contract) != EXPECTED_TOP_LEVEL:
        errors.append("contract top-level fields differ from schema")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if verify_canonical and canonical_sha256(contract) != EXPECTED_CANONICAL_SHA256:
        errors.append("contract differs from the reviewed canonical contract")
    if contract.get("upstream") != EXPECTED_UPSTREAM:
        errors.append("upstream provenance differs from pinned release")
    if contract.get("source_members") != EXPECTED_SOURCE_MEMBERS:
        errors.append("source member hashes differ from frozen set")

    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) < 35:
        errors.append("upstream source-anchor coverage mismatch")
        evidence = evidence if isinstance(evidence, dict) else {}
    if verify_archive:
        validate_archive(
            source_root,
            contract.get("upstream"),
            contract.get("source_members"),
            evidence,
            errors,
        )
    referenced = set(evidence_references(contract))
    unknown = sorted(referenced - set(evidence))
    unused = sorted(set(evidence) - referenced)
    if unknown:
        errors.append("unknown evidence references: " + ", ".join(unknown))
    if unused:
        errors.append("unused source anchors: " + ", ".join(unused))

    validate_inventory(inventory, errors)
    loaded_sources = sources or load_sources(source_root)
    validate_current_surface(contract.get("current_surface"), loaded_sources, errors)
    validate_reference_behavior(contract.get("reference_behavior"), errors)
    validate_translation(contract.get("wayland_translation"), errors)
    validate_scope(contract.get("scope_boundaries"), errors)

    requirements = records_by_id(contract.get("requirements"), "requirements", errors)
    if set(requirements) != EXPECTED_REQUIREMENT_IDS:
        errors.append("screen/output requirement coverage mismatch")
    required_terms = {
        "screen.reference-model": ("ScreenInfo", "root", "screen"),
        "screen.global-config": ("one active global configuration", "every output"),
        "screen.screen-zero-search": ("screen-zero", ".twmrc.1", "never"),
        "screen.explicit-global": ("explicit", "unsuffixed", "global"),
        "screen.canonical-index": ("dense zero-based", "identity", "ordinal"),
        "screen.numeric-safety": ("complete", "unsigned decimal", "no target"),
        "screen.config-lifecycle": ("Reload/restart", "atomically", "topology"),
        "screen.scope-boundary": ("placement", "warp", "hotplug", "restoration"),
    }
    for requirement_id, terms in required_terms.items():
        record = requirements.get(requirement_id, {})
        if set(record) != {"id", "rule", "evidence"}:
            errors.append(f"{requirement_id} fields differ from schema")
        rule = record.get("rule")
        if not isinstance(rule, str) or not all(term in rule for term in terms):
            errors.append(f"{requirement_id} semantic rule mismatch")
        cited = record.get("evidence")
        if not isinstance(cited, list) or not cited:
            errors.append(f"{requirement_id} must cite upstream evidence")

    scenarios = records_by_id(
        contract.get("verification_scenarios"), "verification_scenarios", errors
    )
    if {key: record.get("kind") for key, record in scenarios.items()} != EXPECTED_SCENARIOS:
        errors.append("verification scenario ids or kinds mismatch")
    if len(scenarios) < 15:
        errors.append("at least 15 verification scenarios are required")
    for scenario_id, record in scenarios.items():
        if set(record) != {"id", "kind", "oracle"}:
            errors.append(f"{scenario_id} fields differ from schema")
        if not isinstance(record.get("oracle"), str) or not record["oracle"]:
            errors.append(f"{scenario_id} oracle must be nonempty")
    return errors


def run_tamper_tests(
    contract: dict[str, Any], inventory: Any, source_root: Path
) -> list[str]:
    """Prove independent semantic pins reject representative mutations."""

    mutations: list[tuple[str, dict[str, Any], bool]] = []

    def mutate(name: str, path: tuple[Any, ...], value: Any) -> None:
        candidate = copy.deepcopy(contract)
        current: Any = candidate
        for component in path[:-1]:
            current = current[component]
        current[path[-1]] = value
        mutations.append((name, candidate, False))

    mutate("archive pin", ("upstream", "sha256"), "0" * 64)
    mutate(
        "source pin", ("source_members", "twm-1.0.13.1/src/twm.c"), "0" * 64
    )
    exact_anchor = copy.deepcopy(contract)
    exact_anchor["evidence"]["startup.screen-root"]["text"] += " tampered"
    mutations.append(("exact source anchor", exact_anchor, True))
    mutate(
        "reference screen range",
        ("reference_behavior", "managed_screens", "default"),
        "Attempt only screen zero.",
    )
    mutate(
        "reference single screen",
        ("reference_behavior", "managed_screens", "single_option"),
        "Ignore DefaultScreen.",
    )
    mutate(
        "reference search order",
        ("reference_behavior", "configuration", "implicit_search_per_screen"),
        [],
    )
    mutate(
        "reference explicit file",
        ("reference_behavior", "configuration", "explicit_file"),
        "Merge every .twmrc.N file.",
    )
    mutate(
        "reference atoi",
        ("reference_behavior", "numeric_spatial_screen", "warp_parser"),
        "Reject all numbers.",
    )
    mutate(
        "classification",
        ("wayland_translation", "classification"),
        "exact X-screen emulation",
    )
    mutate(
        "screen-zero order",
        ("wayland_translation", "configuration_namespace", "implicit_search"),
        list(reversed(EXPECTED_IMPLICIT_SEARCH)),
    )
    mutate(
        "higher screen merge",
        ("wayland_translation", "configuration_namespace", "screen_zero_rule"),
        "Merge .twmrc.1 for the second output.",
    )
    mutate(
        "per-output explicit",
        ("wayland_translation", "configuration_namespace", "explicit_file_rule"),
        "Suffix the explicit file for each output.",
    )
    mutate(
        "zero output",
        ("wayland_translation", "configuration_namespace", "zero_outputs"),
        "Do not load configuration.",
    )
    mutate(
        "one output index",
        ("wayland_translation", "configuration_namespace", "one_output"),
        "The output is index 1.",
    )
    mutate(
        "identity key",
        ("wayland_translation", "canonical_output_indices", "stable_identity"),
        "Use layout X coordinate.",
    )
    mutate(
        "canonical order",
        ("wayland_translation", "canonical_output_indices", "canonical_order"),
        "Use wl_list insertion order.",
    )
    mutate(
        "mode stability",
        ("wayland_translation", "canonical_output_indices", "stability"),
        "Renumber whenever scale changes.",
    )
    mutate(
        "restart persistence claim",
        ("wayland_translation", "canonical_output_indices", "restart_expectation"),
        "Every duplicate identity is permanently ordered.",
    )
    mutate(
        "numeric grammar",
        ("wayland_translation", "canonical_output_indices", "valid_decimal"),
        "Accept atoi prefixes and signs.",
    )
    mutate(
        "invalid target",
        ("wayland_translation", "canonical_output_indices", "invalid_reference"),
        "Wrap invalid values to zero.",
    )
    mutate(
        "safety difference",
        ("wayland_translation", "canonical_output_indices", "safety_difference"),
        "Match atoi exactly.",
    )
    mutate(
        "reload atomicity",
        ("wayland_translation", "lifecycle", "reload"),
        "Clear all config before parsing.",
    )
    mutate(
        "output add search",
        ("wayland_translation", "lifecycle", "output_add"),
        "Read .twmrc.N for every new output.",
    )
    mutate(
        "topology overclaim",
        ("wayland_translation", "lifecycle", "topology_boundary"),
        "All hotplug behavior is complete.",
    )
    mutate(
        "deferred scope",
        ("scope_boundaries", "explicitly_deferred"),
        [],
    )
    missing_requirement = copy.deepcopy(contract)
    missing_requirement["requirements"].pop()
    mutations.append(("requirement coverage", missing_requirement, False))
    missing_scenario = copy.deepcopy(contract)
    missing_scenario["verification_scenarios"].pop()
    mutations.append(("scenario coverage", missing_scenario, False))
    unknown_evidence = copy.deepcopy(contract)
    unknown_evidence["requirements"][0]["evidence"].append("missing.anchor")
    mutations.append(("evidence closure", unknown_evidence, False))

    failures: list[str] = []
    baseline_sources = load_sources(source_root)
    for name, candidate, inspect_archive in mutations:
        errors = validate_contract(
            candidate,
            inventory,
            source_root,
            verify_canonical=False,
            verify_archive=inspect_archive,
            sources=baseline_sources,
        )
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")

    source_mutations = [
        (
            "screen-zero wrapper",
            "src/config.c",
            "return wtwm_config_load_for_screen(config, path, 0, error, error_size);",
            "return wtwm_config_load_for_screen(config, path, 1, error, error_size);",
        ),
        (
            "startup global loader",
            "src/wtwm.c",
            "wtwm_config_load(&server.config, config_path",
            "wtwm_config_load_for_screen(&server.config, config_path, 1",
        ),
        (
            "strict negative rejection",
            "src/actions.c",
            "end == argument || *end != '\\0' || parsed < 0",
            "end == argument || *end != '\\0'",
        ),
        (
            "strict range rejection",
            "src/actions.c",
            "parsed >= count || parsed > INT_MAX",
            "parsed > INT_MAX",
        ),
    ]
    for name, path, before, after in source_mutations:
        changed = copy.deepcopy(baseline_sources)
        if before not in changed[path]:
            failures.append(f"tamper self-test fixture missing: {name}")
            continue
        changed[path] = changed[path].replace(before, after, 1)
        errors: list[str] = []
        validate_current_surface(contract["current_surface"], changed, errors)
        if not errors:
            failures.append(f"tamper self-test was not rejected: {name}")
    if len(mutations) + len(source_mutations) < 15:
        failures.append("tamper self-test has fewer than 15 independent mutations")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        contract = load_json(source_root / CONTRACT_PATH)
        inventory = load_json(source_root / EXPECTED_UPSTREAM["inventory"])
        errors = validate_contract(contract, inventory, source_root)
        if args.self_test_tamper and not errors:
            errors.extend(run_tamper_tests(contract, inventory, source_root))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"screen/output contract: {error}", file=sys.stderr)
        return 1
    if args.self_test_tamper:
        print("screen/output contract tamper self-test passed")
    else:
        print("screen/output contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
