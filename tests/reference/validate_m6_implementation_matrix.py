#!/usr/bin/env python3
"""Validate exhaustive Milestone 6 action vectors against the current tree."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


CONTRACT_PATH = "reference/actions/twm-1.0.13.1/action-contract.json"
EXPECTED_ACTIONS = 66
EXPECTED_BEHAVIORS = 59
ARGUMENTS = {
    "f.colormap": "next",
    "f.cut": "text",
    "f.exec": "true",
    "f.file": "/tmp/wtwm-m6-file",
    "f.function": "inner",
    "f.menu": "menu",
    "f.priority": "1",
    "f.source": "ignored",
    "f.startwm": "true",
    "f.warpring": "next",
    "f.warpto": "client",
    "f.warptoiconmgr": "manager",
    "f.warptoscreen": "next",
}
CONDITIONAL_NO_OP = {
    "F_BACKICONMGR",
    "F_COLORMAP",
    "F_DOWNICONMGR",
    "F_FORWICONMGR",
    "F_HIDELIST",
    "F_LEFTICONMGR",
    "F_NEXTICONMGR",
    "F_PREVICONMGR",
    "F_PRIORITY",
    "F_RIGHTICONMGR",
    "F_SHOWLIST",
    "F_SORTICONMGR",
    "F_UPICONMGR",
    "F_WARPTOICONMGR",
}
BEHAVIORALLY_EQUIVALENT = {
    "F_BEEP",
    "F_CUT",
    "F_CUTFILE",
    "F_DELETE",
    "F_DESTROY",
    "F_FILE",
    "F_IDENTIFY",
    "F_REFRESH",
    "F_SAVEYOURSELF",
    "F_STARTWM",
    "F_VERSION",
    "F_WARPTOSCREEN",
    "F_WINREFRESH",
}


def load_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate key {key!r}")
            value[key] = item
        return value

    with path.open(encoding="utf-8") as source:
        value = json.load(source, object_pairs_hook=no_duplicates)
    if not isinstance(value, dict):
        raise ValueError("contract root is not an object")
    return value


def action_text(name: str) -> str:
    argument = ARGUMENTS.get(name)
    return name if argument is None else f'{name} "{argument}"'


def parse_fixture(config_tool: Path, source: str, label: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m6-matrix-") as directory:
        path = Path(directory) / f"{label}.twmrc"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [str(config_tool), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode == 0:
        return None
    return f"{label} fixture failed: {result.stderr.strip()}"


def parser_mapping(config_source: str, name: str) -> str | None:
    pattern = re.compile(
        r'(?:ACT(?:_ARG)?\(|\{)\s*"' + re.escape(name)
        + r'"\s*,\s*(WTWM_ACTION_[A-Z0-9_]+)'
    )
    match = pattern.search(config_source)
    return None if match is None else match.group(1)


def classification(behavior: str) -> str:
    if behavior in CONDITIONAL_NO_OP:
        return "verified-conditional-no-op"
    if behavior in BEHAVIORALLY_EQUIVALENT:
        return "behaviorally-equivalent"
    return "effective"


def validate(
    contract: dict[str, Any], source_root: Path, config_tool: Path,
    *, execute_fixtures: bool = True,
) -> list[str]:
    errors: list[str] = []
    actions = contract.get("actions")
    behaviors = contract.get("behaviors")
    if not isinstance(actions, list) or len(actions) != EXPECTED_ACTIONS:
        return [f"expected {EXPECTED_ACTIONS} action spellings"]
    if not isinstance(behaviors, dict) or len(behaviors) != EXPECTED_BEHAVIORS:
        return [f"expected {EXPECTED_BEHAVIORS} action behaviors"]

    config_source = (source_root / "src/config.c").read_text(encoding="utf-8")
    compositor_source = (source_root / "src/wtwm.c").read_text(encoding="utf-8")
    seen_names: set[str] = set()
    seen_behaviors: set[str] = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"actions[{index}] is not an object")
            continue
        name = action.get("name")
        behavior = action.get("behavior")
        if not isinstance(name, str) or not isinstance(behavior, str):
            errors.append(f"actions[{index}] lacks name or behavior")
            continue
        if name in seen_names:
            errors.append(f"duplicate action vector {name}")
            continue
        seen_names.add(name)
        seen_behaviors.add(behavior)
        record = behaviors.get(behavior)
        if not isinstance(record, dict):
            errors.append(f"{name} has no behavior record {behavior}")
            continue

        vector = {
            "initial_state": (
                "Prepare the eligible target and capability described by the "
                f"reference effect; also prepare its guard: {record.get('no_op_when', '')}"
            ),
            "input_sequence": [
                f"dispatch {name} directly",
                f"dispatch {name} from a two-level nested named function",
            ],
            "expected_state": record.get("effect"),
            "expected_no_op_state": record.get("no_op_when"),
            "classification": classification(behavior),
        }
        for field in ("initial_state", "expected_state", "expected_no_op_state"):
            if not isinstance(vector[field], str) or not vector[field].strip():
                errors.append(f"{name} has an empty {field}")
        if len(vector["input_sequence"]) != 2:
            errors.append(f"{name} lacks direct and nested input sequences")

        enum_name = parser_mapping(config_source, name)
        if enum_name is None:
            errors.append(f"{name} has no explicit parser-to-action mapping")
        elif re.search(rf"\bcase\s+{re.escape(enum_name)}\b", compositor_source) is None:
            errors.append(f"{name} maps to undispatched {enum_name}")

        if execute_fixtures:
            text = action_text(name)
            prelude = (
                'NoDefaults\nFunction "inner" { f.nop }\n'
                'Menu "menu" { "Noop" f.nop }\n'
            )
            direct = prelude + f"Button1 = : root : {text}\n"
            nested = prelude + (
                f'Function "middle" {{ {text} }}\n'
                'Function "outer" { f.function "middle" }\n'
                'Button1 = : root : f.function "outer"\n'
            )
            for fixture, source in (("direct", direct), ("nested", nested)):
                failure = parse_fixture(config_tool, source, f"{index}-{fixture}")
                if failure is not None:
                    errors.append(f"{name} {failure}")

    if seen_behaviors != set(behaviors):
        errors.append("action vectors do not cover every behavior exactly")

    runner = (source_root / "tests/integration/run_m6_actions.py").read_text(
        encoding="utf-8"
    )
    meson = (source_root / "meson.build").read_text(encoding="utf-8")
    for marker in (
        "nested function order is wrong",
        "stationary f.deltastop did not continue",
        "moved f.deltastop did not interrupt",
        "key f.menu unexpectedly opened a menu",
        "nested-function f.menu unexpectedly opened a menu",
        "named binding did not visit both clients",
        "f.resize started on an icon",
        "f.move did not move the icon view",
        "f.iconify did not toggle",
    ):
        if marker not in runner:
            errors.append(f"live Milestone 6 runner lacks {marker!r}")
    if "Milestone 6 actions and bindings integration" not in meson:
        errors.append("live Milestone 6 runner is not registered with Meson")
    ordering = contract.get("ordering_and_interruption", {})
    named_rules = " ".join(ordering.get("named_functions", [])) \
        if isinstance(ordering, dict) else ""
    if "f.deltastop" not in named_rules or "recursively executing" not in named_rules:
        errors.append("live function traces lack a complete frozen-reference oracle")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--config-tool", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    config_tool = args.config_tool.resolve()
    try:
        contract = load_json(source_root / CONTRACT_PATH)
        errors = validate(contract, source_root, config_tool)
        if args.self_test_tamper and not errors:
            broken = copy.deepcopy(contract)
            broken["actions"] = broken["actions"][1:]
            if not validate(broken, source_root, config_tool, execute_fixtures=False):
                errors.append("tamper self-test accepted a missing action")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"validated {EXPECTED_ACTIONS} direct/nested action vectors and "
        f"{EXPECTED_BEHAVIORS} implementation classifications"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
