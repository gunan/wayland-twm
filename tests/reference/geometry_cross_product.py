#!/usr/bin/env python3
"""Generate the deterministic Milestone 4 geometry Cartesian product."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path("reference/geometry/twm-1.0.13.1/cross-product.json")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_manifest(source_root: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with (source_root / MANIFEST_PATH).open(encoding="utf-8") as source:
        value = json.load(source, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("geometry cross-product manifest must be an object")
    return value


def render_config(
    manifest: dict[str, Any], title_policy: str, border_policy: str,
    transient_policy: str,
) -> str:
    profile = manifest["frame_profile"]
    lines = list(manifest["configuration_prelude"])
    lines.extend([
        f'UsePPosition "on"',
        f'BorderWidth {int(profile["border_width"])}',
        f'FramePadding {int(profile["frame_padding"])}',
        f'TitlePadding {int(profile["title_padding"])}',
        f'TitleFont "{profile["title_font"]}"',
    ])
    if border_policy == "client-border":
        lines.append("ClientBorderWidth")
    if title_policy == "untitled":
        lines.append("NoTitle")
    if transient_policy == "transient-decorated":
        lines.append("DecorateTransients")
    return "\n".join(lines) + "\n"


def generate_configurations(manifest: dict[str, Any]) -> list[dict[str, object]]:
    axes = manifest["axes"]
    profile = manifest["frame_profile"]
    result: list[dict[str, object]] = []
    for title_policy, border_policy, transient_policy in itertools.product(
        axes["title_policy"], axes["border_policy"], axes["transient_policy"]
    ):
        config_id = f"{title_policy}__{border_policy}__{transient_policy}"
        text = render_config(
            manifest, str(title_policy), str(border_policy), str(transient_policy)
        )
        result.append({
            "border_width": int(profile["border_width"]),
            "client_border_width": border_policy == "client-border",
            "decorate_transients": transient_policy == "transient-decorated",
            "frame_padding": int(profile["frame_padding"]),
            "id": config_id,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text": text,
            "title_font": str(profile["title_font"]),
            "title_padding": int(profile["title_padding"]),
        })
    return result


def generate_cases(manifest: dict[str, Any]) -> list[dict[str, object]]:
    axes = manifest["axes"]
    profiles = {profile["id"]: profile for profile in manifest["hint_profiles"]}
    configs = {config["id"]: config for config in generate_configurations(manifest)}
    result: list[dict[str, object]] = []
    for title_policy, border_policy, transient_policy, hint_profile in itertools.product(
        axes["title_policy"], axes["border_policy"], axes["transient_policy"],
        axes["hint_profile"],
    ):
        config_id = f"{title_policy}__{border_policy}__{transient_policy}"
        kind = "normal" if transient_policy == "normal" else "transient"
        expected_title = (
            title_policy == "titled" and transient_policy != "transient-suppressed"
        )
        profile = profiles[str(hint_profile)]
        result.append({
            "axes": {
                "border_policy": border_policy,
                "hint_profile": hint_profile,
                "title_policy": title_policy,
                "transient_policy": transient_policy,
            },
            "configuration_id": config_id,
            "configuration_sha256": configs[config_id]["sha256"],
            "expected_title": expected_title,
            "hint_profile": hint_profile,
            "id": (
                f"{title_policy}__{border_policy}__{transient_policy}"
                f"__{hint_profile}"
            ),
            "initial_border_width": int(manifest["initial_client_border_width"]),
            "kind": kind,
            "size": list(profile["size"]),
        })
    return result


def generated_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "cases_sha256": digest(generate_cases(manifest)),
        "configurations_sha256": digest(generate_configurations(manifest)),
    }
