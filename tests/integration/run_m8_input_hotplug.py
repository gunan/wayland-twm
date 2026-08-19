#!/usr/bin/env python3
"""Exercise one logical seat across bounded input-device hotplug churn."""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
from typing import Callable

from run_client_stress import ClientChannel
from run_compositor import Control


NATIVE_TITLE = "wtwm-input-hotplug-native"
NATIVE_APP_ID = "org.wtwm.InputHotplug"
KEY_A = 30
KEY_C = 46
KEY_B = 48
KEY_ALT = 56
KEY_F1 = 59
BTN_LEFT = 272
BTN_RIGHT = 273
BTN_MIDDLE = 274
BTN_TASK = 279
MAX_ACTIVITY = (1 << 64) - 1
ZERO_MODIFIERS = {
    "depressed": 0,
    "latched": 0,
    "locked": 0,
    "group": 0,
}
INPUT_RECORD_KEYS = {
    "name",
    "type",
    "ordinal",
    "last_activity",
    "active",
    "pressed",
    "modifiers",
}
INPUT_STATE_KEYS = {
    "inputs",
    "seat_capabilities",
    "seat_modifiers",
    "seat_pressed_keys",
    "seat_pressed_buttons",
    "active_keyboard",
    "active_pointer",
    "seat_keyboard_focus",
    "seat_pointer_focus",
}


def config_text() -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        "NoRaiseOnMove\n"
        "Button1 = : window : f.move\n"
        "Button3 = : all : f.focus\n"
        "Button8 = : root : f.restart\n"
        '"F1" = meta : all : f.nop\n'
    )


@dataclass
class ModelDevice:
    name: str
    kind: str
    ordinal: int
    last_activity: int = 0
    held: dict[int, bool] = field(default_factory=dict)


class SeatModel:
    """Small oracle for ownership, activity, fallback, and cancellation."""

    def __init__(self) -> None:
        self.devices: list[ModelDevice] = []
        self.next_ordinal = 0
        self.next_activity = 1
        self.active: dict[str, str | None] = {"keyboard": None, "pointer": None}
        self.client_keys: set[int] = set()
        self.client_buttons: set[int] = set()
        self.operation_button: int | None = None
        self.operation_aborted = False
        self.add("TEST-KEYBOARD-0", "keyboard")
        self.add("TEST-POINTER-0", "pointer")

    def snapshot(self) -> object:
        return copy.deepcopy(
            (
                self.devices,
                self.next_ordinal,
                self.next_activity,
                self.active,
                self.client_keys,
                self.client_buttons,
                self.operation_button,
                self.operation_aborted,
            )
        )

    def device(self, name: str) -> ModelDevice:
        matches = [item for item in self.devices if item.name == name]
        if len(matches) != 1:
            raise KeyError(name)
        return matches[0]

    def add(self, name: str, kind: str) -> ModelDevice:
        if kind not in {"keyboard", "pointer"} or any(
            item.name == name for item in self.devices
        ):
            raise ValueError(name)
        item = ModelDevice(name, kind, self.next_ordinal)
        self.next_ordinal += 1
        self.devices.append(item)
        if self.active[kind] is None:
            self.active[kind] = name
        return item

    def activate(self, item: ModelDevice) -> None:
        if self.next_activity == MAX_ACTIVITY:
            active = sorted(
                (record for record in self.devices if record.last_activity != 0),
                key=lambda record: (record.last_activity, record.ordinal),
            )
            for rank, record in enumerate(active, start=1):
                record.last_activity = rank
            self.next_activity = len(active) + 1
        item.last_activity = self.next_activity
        self.next_activity += 1
        self.active[item.kind] = item.name

    def owners(self, kind: str, code: int, *, visible_only: bool) -> list[ModelDevice]:
        return [
            item
            for item in self.devices
            if item.kind == kind
            and code in item.held
            and (item.held[code] or not visible_only)
        ]

    def event(self, name: str, code: int, pressed: bool, visible: bool = True) -> str:
        item = self.device(name)
        if (code in item.held) == pressed:
            raise ValueError("duplicate physical transition")
        self.activate(item)
        visible_owners = self.owners(item.kind, code, visible_only=True)
        aggregate = self.client_keys if item.kind == "keyboard" else self.client_buttons
        if pressed:
            item.held[code] = visible
            if visible and not visible_owners:
                aggregate.add(code)
                return "press"
            return "none"
        was_visible = item.held.pop(code)
        if was_visible and not self.owners(item.kind, code, visible_only=True):
            aggregate.remove(code)
            return "release"
        return "none"

    def fallback(self, kind: str) -> str | None:
        candidates = [item for item in self.devices if item.kind == kind]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (-item.last_activity, item.ordinal)).name

    def remove(self, name: str) -> list[tuple[int, str]]:
        item = self.device(name)
        transitions: list[tuple[int, str]] = []
        for code in sorted(item.held):
            if item.held[code] and len(
                self.owners(item.kind, code, visible_only=True)
            ) == 1:
                aggregate = (
                    self.client_keys if item.kind == "keyboard" else self.client_buttons
                )
                aggregate.remove(code)
                transitions.append((code, "release"))
        self.devices.remove(item)
        if self.active[item.kind] == name:
            self.active[item.kind] = self.fallback(item.kind)
        if item.kind == "pointer" and self.operation_button is not None:
            if not self.owners("pointer", self.operation_button, visible_only=False):
                self.operation_button = None
                self.operation_aborted = True
        return transitions

    def clear(self) -> tuple[list[int], list[int]]:
        keys = sorted(self.client_keys)
        buttons = sorted(self.client_buttons)
        for name in [item.name for item in self.devices]:
            self.remove(name)
        return keys, buttons

    def start_operation(self, button: int) -> None:
        if not self.owners("pointer", button, visible_only=False):
            raise ValueError("operation requires an owned button")
        self.operation_button = button
        self.operation_aborted = False


def validate_model() -> None:
    model = SeatModel()
    if model.active != {
        "keyboard": "TEST-KEYBOARD-0",
        "pointer": "TEST-POINTER-0",
    }:
        raise RuntimeError("initial synthetic devices did not become active")
    initial_next = model.next_ordinal
    model.clear()
    if model.devices or any(model.active.values()) or model.next_ordinal != initial_next:
        raise RuntimeError("CLEAR reset generators or retained live inventory")

    k1 = model.add("K1", "keyboard")
    k2 = model.add("K2", "keyboard")
    k3 = model.add("K3", "keyboard")
    if model.active["keyboard"] != "K1":
        raise RuntimeError("later keyboard add stole active selection")
    model.event("K2", KEY_A, True)
    model.event("K2", KEY_A, False)
    model.event("K3", KEY_B, True)
    model.event("K3", KEY_B, False)
    model.event("K2", KEY_C, True)
    model.event("K2", KEY_C, False)
    model.remove("K2")
    if model.active["keyboard"] != "K3":
        raise RuntimeError("activity/ordinal fallback changed")
    old_ordinal = k2.ordinal
    replacement = model.add("K2", "keyboard")
    if replacement.ordinal <= old_ordinal or model.active["keyboard"] != "K3":
        raise RuntimeError("removed name reused an ordinal or stole active")
    before_duplicate = model.snapshot()
    try:
        model.add("K2", "keyboard")
    except ValueError:
        pass
    if model.snapshot() != before_duplicate:
        raise RuntimeError("duplicate add mutated the portable model")

    if model.event("K1", KEY_A, True) != "press":
        raise RuntimeError("first physical key owner did not emit a press")
    if model.event("K2", KEY_A, True) != "none":
        raise RuntimeError("overlapping key owner emitted a duplicate press")
    if model.remove("K1"):
        raise RuntimeError("removing a non-final key owner emitted a release")
    if model.remove("K2") != [(KEY_A, "release")]:
        raise RuntimeError("final key owner did not drain one release")

    k4 = model.add("K4", "keyboard")
    model.add("K5", "keyboard")
    if model.event("K4", KEY_ALT, True) != "press":
        raise RuntimeError("cross-device modifier press was not forwarded")
    if model.event("K5", KEY_F1, True, visible=False) != "none":
        raise RuntimeError("handled binding key became client-visible")
    if model.remove("K5"):
        raise RuntimeError("handled held key drained a client release")
    if model.remove("K4") != [(KEY_ALT, "release")]:
        raise RuntimeError("modifier owner removal did not drain exactly once")
    if k4.ordinal <= k3.ordinal:
        raise RuntimeError("announcement ordinal did not remain monotonic")

    p1 = model.add("P1", "pointer")
    model.add("P2", "pointer")
    model.add("P3", "pointer")
    model.event("P2", BTN_MIDDLE, True)
    model.event("P2", BTN_MIDDLE, False)
    model.event("P3", BTN_RIGHT, True)
    model.event("P3", BTN_RIGHT, False)
    model.remove("P3")
    if model.active["pointer"] != "P2":
        raise RuntimeError("pointer activity fallback changed")
    if p1.ordinal >= model.next_ordinal:
        raise RuntimeError("pointer ordinal generator regressed")

    if model.event("P1", BTN_LEFT, True) != "press":
        raise RuntimeError("operation button did not emit initial press")
    if model.event("P2", BTN_LEFT, True) != "none":
        raise RuntimeError("shared operation button emitted duplicate press")
    model.start_operation(BTN_LEFT)
    model.remove("P1")
    if model.operation_button != BTN_LEFT or model.operation_aborted:
        raise RuntimeError("surviving operation-button owner did not continue")
    model.add("P4", "pointer")
    model.remove("P2")
    if model.operation_button is not None or not model.operation_aborted:
        raise RuntimeError("final operation-button owner did not abort with survivor")

    held_snapshot = model.snapshot()
    if copy.deepcopy(model).snapshot() != held_snapshot:
        raise RuntimeError("restart continuity snapshot was not stable")

    live = sorted(model.devices, key=lambda item: item.ordinal)
    for serial, item in enumerate(reversed(live), start=10):
        item.last_activity = serial
    model.next_activity = MAX_ACTIVITY
    target = live[0]
    target.held.pop(BTN_MIDDLE, None)
    model.event(target.name, BTN_MIDDLE, True)
    ranks = [item.last_activity for item in model.devices if item.last_activity != 0]
    if (
        len(ranks) != len(set(ranks))
        or target.last_activity != max(ranks)
        or model.next_activity != target.last_activity + 1
        or model.next_activity >= MAX_ACTIVITY
    ):
        raise RuntimeError("activity overflow did not renormalize before the event")


def validate_generated_config(config_tool: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-input-config-") as directory:
        path = Path(directory) / "input-hotplug.twmrc"
        path.write_text(config_text(), encoding="utf-8")
        result = subprocess.run(
            [str(config_tool), str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "portable wtwm-config rejected generated input-hotplug config: "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        if "bindings=4\n" not in result.stdout:
            raise RuntimeError(f"input-hotplug config lost a binding: {result.stdout!r}")
        if "compatibility-warnings=0\n" not in result.stdout:
            raise RuntimeError(
                "input-hotplug config emitted a compatibility warning: "
                f"{result.stdout!r}"
            )


def read_prefixed_line(
    process: subprocess.Popen[bytes], prefix: str, label: str
) -> str:
    if process.stdout is None:
        raise RuntimeError(f"{label} lacks stdout")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    buffer = bytearray()
    deadline = time.monotonic() + 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"timed out waiting for {label} {prefix!r}")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise RuntimeError(f"timed out waiting for {label} {prefix!r}")
        chunk = os.read(descriptor, 4096)
        if not chunk:
            raise RuntimeError(
                f"{label} exited before {prefix!r} (status={process.poll()})"
            )
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw, _, remainder = buffer.partition(b"\n")
            buffer = bytearray(remainder)
            line = raw.decode("utf-8", errors="strict")
            if line.startswith(prefix):
                return line


def raw_command(control: Control, command: str) -> str:
    control.stream.write(command + "\n")
    control.stream.flush()
    return control.stream.readline().rstrip("\n")


def expect_command(control: Control, command: str, expected: str) -> None:
    observed = control.command(command)
    if observed != expected:
        raise RuntimeError(
            f"{command!r}: expected {expected!r}, observed {observed!r}"
        )


def bounded_state(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    label: str,
    attempts: int = 64,
) -> dict[str, object]:
    last: dict[str, object] | None = None
    for _ in range(attempts):
        last = control.state()
        if predicate(last):
            return last
        control.command("WAIT 1")
    raise RuntimeError(f"bounded STATE barrier failed for {label}: {last!r}")


def semantic_state(state: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in state.items() if key != "frame"}


def modifiers(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(ZERO_MODIFIERS):
        raise RuntimeError(f"{label} modifier schema changed: {value!r}")
    if any(not isinstance(value[key], int) or value[key] < 0 for key in value):
        raise RuntimeError(f"{label} modifier value is invalid: {value!r}")
    return value  # type: ignore[return-value]


def input_map(state: dict[str, object]) -> dict[str, dict[str, object]]:
    if not INPUT_STATE_KEYS.issubset(state):
        raise RuntimeError(
            f"STATE omitted input-hotplug fields {sorted(INPUT_STATE_KEYS - set(state))}: "
            f"{state!r}"
        )
    records = state["inputs"]
    if not isinstance(records, list):
        raise RuntimeError(f"STATE input inventory is not an array: {state!r}")
    result: dict[str, dict[str, object]] = {}
    ordinals: list[int] = []
    active_by_kind: dict[str, list[str]] = {"keyboard": [], "pointer": []}
    unions: dict[str, set[int]] = {"keyboard": set(), "pointer": set()}
    for record in records:
        if not isinstance(record, dict) or set(record) != INPUT_RECORD_KEYS:
            raise RuntimeError(f"STATE input record schema changed: {record!r}")
        name = record["name"]
        kind = record["type"]
        ordinal = record["ordinal"]
        activity = record["last_activity"]
        if (
            not isinstance(name, str)
            or not name
            or kind not in {"keyboard", "pointer"}
            or not isinstance(ordinal, int)
            or ordinal < 0
            or not isinstance(activity, int)
            or activity < 0
            or not isinstance(record["active"], bool)
        ):
            raise RuntimeError(f"STATE input identity/activity is invalid: {record!r}")
        pressed = record["pressed"]
        if (
            not isinstance(pressed, list)
            or pressed != sorted(set(pressed))
            or any(not isinstance(code, int) or code < 0 for code in pressed)
        ):
            raise RuntimeError(f"STATE pressed codes are invalid: {record!r}")
        if kind == "keyboard":
            modifiers(record["modifiers"], name)
        elif record["modifiers"] is not None:
            raise RuntimeError(f"pointer exposed keyboard modifiers: {record!r}")
        if name in result:
            raise RuntimeError(f"STATE duplicated input name {name!r}")
        if record["active"]:
            active_by_kind[kind].append(name)
        unions[kind].update(pressed)
        ordinals.append(ordinal)
        result[name] = record
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise RuntimeError(f"input records lost stable ordinal order: {records!r}")
    for kind in ("keyboard", "pointer"):
        active_name = state[f"active_{kind}"]
        expected = active_by_kind[kind]
        if len(expected) > 1 or expected != ([] if active_name is None else [active_name]):
            raise RuntimeError(f"{kind} active record/top-level mismatch: {state!r}")
        exists = any(item["type"] == kind for item in records)
        if exists != (active_name is not None):
            raise RuntimeError(f"{kind} inventory lacks exact active selection: {state!r}")
    capabilities = state["seat_capabilities"]
    expected_capabilities = [
        kind for kind in ("keyboard", "pointer")
        if any(item["type"] == kind for item in records)
    ]
    if capabilities != expected_capabilities:
        raise RuntimeError(
            f"seat capabilities {capabilities!r} != {expected_capabilities!r}"
        )
    for field_name, kind in (
        ("seat_pressed_keys", "keyboard"),
        ("seat_pressed_buttons", "pointer"),
    ):
        aggregate = state[field_name]
        if (
            not isinstance(aggregate, list)
            or aggregate != sorted(set(aggregate))
            or any(not isinstance(code, int) or code < 0 for code in aggregate)
            or not set(aggregate).issubset(unions[kind])
        ):
            raise RuntimeError(
                f"logical aggregate {field_name} lacks physical ownership: {state!r}"
            )
    modifiers(state["seat_modifiers"], "seat")
    for key in ("seat_keyboard_focus", "seat_pointer_focus"):
        if state[key] is not None and not isinstance(state[key], str):
            raise RuntimeError(f"{key} is not a nullable title: {state!r}")
    return result


def assert_input_state(
    state: dict[str, object],
    names: set[str],
    *,
    keyboard: str | None,
    pointer: str | None,
) -> dict[str, dict[str, object]]:
    records = input_map(state)
    if set(records) != names:
        raise RuntimeError(f"input inventory {set(records)!r} != {names!r}: {state!r}")
    if state["active_keyboard"] != keyboard or state["active_pointer"] != pointer:
        raise RuntimeError(
            f"active sources {(state['active_keyboard'], state['active_pointer'])!r} "
            f"!= {(keyboard, pointer)!r}"
        )
    return records


def window(state: dict[str, object], title: str) -> dict[str, object]:
    windows = state.get("windows")
    if not isinstance(windows, list):
        raise RuntimeError(f"STATE windows schema changed: {state!r}")
    matches = [item for item in windows if isinstance(item, dict) and item.get("title") == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {title!r}: {state!r}")
    return matches[0]


def client_point(state: dict[str, object], title: str) -> tuple[int, int]:
    target = window(state, title)
    ordered = sorted(
        (item for item in state["windows"] if isinstance(item, dict)),  # type: ignore[index]
        key=lambda item: int(item["stack"]),
    )
    above = [item for item in ordered if int(item["stack"]) < int(target["stack"])]
    x = int(target["x"])
    y = int(target["y"])
    width = int(target["width"])
    height = int(target["height"])
    content_y = int(target["content_y"])
    xs = (x + 12, x + width - 12, x + width // 2, x + 28, x + width - 28)
    ys = (
        y + content_y + 12,
        y + content_y + height - 12,
        y + content_y + height // 2,
        y + content_y + 28,
        y + content_y + height - 28,
    )
    for point_y in ys:
        for point_x in xs:
            covered = any(
                int(other["x"]) <= point_x
                < int(other["x"]) + int(other["outer_width"])
                and int(other["y"]) <= point_y
                < int(other["y"]) + int(other["outer_height"])
                for other in above
            )
            if not covered:
                return point_x, point_y
    raise RuntimeError(f"no visible client point for {title!r}: {state!r}")


def root_point(state: dict[str, object]) -> tuple[int, int]:
    outputs = state.get("outputs")
    if not isinstance(outputs, list):
        raise RuntimeError(f"STATE omitted outputs: {state!r}")
    enabled = [item for item in outputs if isinstance(item, dict) and item.get("enabled")]
    if len(enabled) != 1 or not isinstance(enabled[0].get("box"), dict):
        raise RuntimeError(f"expected one enabled output: {state!r}")
    box = enabled[0]["box"]
    assert isinstance(box, dict)
    candidates = [
        (int(box["x"]) + int(box["width"]) - 2, int(box["y"]) + 2),
        (int(box["x"]) + 2, int(box["y"]) + int(box["height"]) - 2),
    ]
    for point in candidates:
        if not any(
            int(item["x"]) <= point[0] < int(item["x"]) + int(item["outer_width"])
            and int(item["y"]) <= point[1] < int(item["y"]) + int(item["outer_height"])
            for item in state["windows"]  # type: ignore[index]
        ):
            return point
    raise RuntimeError(f"no bounded root point: {state!r}")


REPORT_RE = re.compile(
    r"OK REPORT (?P<token>\S+) keyboard=(?P<keyboard>[01]) "
    r"pointer=(?P<pointer>[01]) cap_seq=(?P<cap_seq>[0-9]+) "
    r"key_gen=(?P<key_gen>[0-9]+) pointer_gen=(?P<pointer_gen>[0-9]+) "
    r"keyboard_focus=(?P<keyboard_focus>[01]) "
    r"pointer_focus=(?P<pointer_focus>[01]) keys=(?P<keys>[0-9]+) "
    r"buttons=(?P<buttons>[0-9]+) modifiers=(?P<depressed>[0-9]+),"
    r"(?P<latched>[0-9]+),(?P<locked>[0-9]+),(?P<group>[0-9]+) "
    r"close=(?P<close>[0-9]+)"
)


def observer_report(
    channel: ClientChannel, token: str
) -> tuple[list[str], dict[str, int]]:
    channel.stdin.write(f"REPORT {token}\n".encode("utf-8"))
    channel.stdin.flush()
    events: list[str] = []
    deadline = time.monotonic() + 10
    while True:
        line = channel.line(deadline)
        if line.startswith("EVENT "):
            events.append(line)
            continue
        match = REPORT_RE.fullmatch(line)
        if match is None or match.group("token") != token:
            raise RuntimeError(f"unexpected input-observer report: {line!r}")
        return events, {
            key: int(match.group(key))
            for key in (
                "keyboard",
                "pointer",
                "cap_seq",
                "key_gen",
                "pointer_gen",
                "keyboard_focus",
                "pointer_focus",
                "keys",
                "buttons",
                "depressed",
                "latched",
                "locked",
                "group",
                "close",
            )
        }


def arm_observer(channel: ClientChannel, token: str) -> None:
    channel.command(f"ARM {token}", f"OK ARMED {token}")


def input_add(control: Control, kind: str, name: str) -> dict[str, object]:
    expect_command(
        control,
        f"INPUT ADD {kind.upper()} {name}",
        f"OK INPUT ADD {kind.upper()} {name}",
    )
    state = control.state()
    input_map(state)
    return state


def input_remove(control: Control, name: str) -> dict[str, object]:
    expect_command(control, f"INPUT REMOVE {name}", f"OK INPUT REMOVE {name}")
    state = control.state()
    input_map(state)
    return state


def input_key(control: Control, name: str, code: int, action: str) -> dict[str, object]:
    expect_command(
        control,
        f"INPUT KEY {name} {code} {action}",
        f"OK INPUT KEY {name} {code} {action}",
    )
    state = control.state()
    input_map(state)
    return state


def input_pointer(
    control: Control, name: str, point: tuple[int, int]
) -> dict[str, object]:
    expect_command(
        control,
        f"INPUT POINTER {name} {point[0]} {point[1]}",
        f"OK INPUT POINTER {name} {point[0]:.3f} {point[1]:.3f}",
    )
    state = control.state()
    input_map(state)
    cursor = state.get("cursor")
    if not isinstance(cursor, dict) or (
        float(cursor.get("x", math.nan)), float(cursor.get("y", math.nan))
    ) != (float(point[0]), float(point[1])):
        raise RuntimeError(f"named pointer motion was not exact: {state!r}")
    return state


def input_button(
    control: Control, name: str, code: int, action: str
) -> dict[str, object]:
    expect_command(
        control,
        f"INPUT BUTTON {name} {code} {action}",
        f"OK INPUT BUTTON {name} {code} {action}",
    )
    state = control.state()
    input_map(state)
    return state


def focus_with_pointer(
    control: Control, pointer: str, state: dict[str, object], title: str
) -> dict[str, object]:
    input_pointer(control, pointer, client_point(state, title))
    input_button(control, pointer, BTN_RIGHT, "press")
    input_button(control, pointer, BTN_RIGHT, "release")
    return bounded_state(
        control,
        lambda item: item.get("active") == title,
        f"logical focus on {title}",
    )


def input_projection(state: dict[str, object]) -> dict[str, object]:
    input_map(state)
    return {key: copy.deepcopy(state[key]) for key in sorted(INPUT_STATE_KEYS)}


def restoration_projection(state: dict[str, object]) -> object:
    records = []
    for item in state.get("windows", []):
        if not isinstance(item, dict):
            continue
        records.append(
            (
                item.get("id"),
                item.get("title"),
                item.get("mapped"),
                item.get("visible"),
                item.get("restoration_pending"),
                item.get("placement_pending"),
                item.get("iconified"),
                item.get("stack"),
                item.get("x"),
                item.get("y"),
                item.get("width"),
                item.get("height"),
            )
        )
    return tuple(records)


class Session:
    def __init__(
        self,
        root: Path,
        compositor: Path,
        config_tool: Path,
        observer_binary: Path,
        x11_binary: Path,
    ) -> None:
        validate_generated_config(config_tool)
        self.config = root / "input-hotplug.twmrc"
        self.config.write_text(config_text(), encoding="utf-8")
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = root / "control.sock"
        socket_name = f"wtwm-m8-input-{os.getpid()}"
        environment = {
            **os.environ,
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        }
        self.process = subprocess.Popen(
            [
                str(compositor),
                "-f",
                str(self.config),
                "-s",
                'printf "WTWM_DISPLAY=%s\\n" "$DISPLAY"',
                "--test-control",
                str(control_path),
                "--test-socket",
                socket_name,
                "--test-backend",
                "headless",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control: Control | None = None
        self.observer_process: subprocess.Popen[bytes] | None = None
        self.observer: ClientChannel | None = None
        self.x11_process: subprocess.Popen[bytes] | None = None
        self.x11: ClientChannel | None = None
        try:
            self.control = Control(control_path, self.process)  # type: ignore[arg-type]
            self.control.socket.settimeout(10)
            expect_command(self.control, "SET ANIMATION_MS 0", "OK ANIMATION_MS 0")
            expect_command(self.control, "SET PLACEMENT_SEED 0", "OK PLACEMENT_SEED 0")
            expect_command(
                self.control,
                "OUTPUT 800 600",
                "OK OUTPUT HEADLESS-1 800 600",
            )
            self.control.command("WAIT 2")
            display_line = read_prefixed_line(self.process, "WTWM_DISPLAY=", "compositor")
            display = display_line.removeprefix("WTWM_DISPLAY=")
            if not display:
                raise RuntimeError("Xwayland startup printed an empty DISPLAY")

            wayland_environment = {**environment, "WAYLAND_DISPLAY": socket_name}
            self.observer_process = subprocess.Popen(
                [str(observer_binary), NATIVE_TITLE, NATIVE_APP_ID],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.observer = ClientChannel(self.observer_process, "input observer")
            ready = self.observer.expect_prefix(f"OK READY {NATIVE_TITLE} ")
            if re.fullmatch(
                rf"OK READY {re.escape(NATIVE_TITLE)} keyboard=1 pointer=1 "
                r"cap_seq=[1-9][0-9]* key_gen=1 pointer_gen=1",
                ready,
            ) is None:
                raise RuntimeError(f"initial wl_seat capabilities changed: {ready!r}")

            x11_environment = {**environment, "DISPLAY": display}
            self.x11_process = subprocess.Popen(
                [str(x11_binary)],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.x11 = ClientChannel(self.x11_process, "mixed X11 input client")
            self.x11.expect("OK READY x11-a x11-b")
            bounded_state(
                self.control,
                lambda state: {
                    item.get("title") for item in state.get("windows", [])
                    if isinstance(item, dict)
                } == {NATIVE_TITLE, "x11-a", "x11-b"},
                "native and Xwayland input clients",
            )
        except Exception:
            self.abort()
            raise

    def abort(self) -> str:
        for channel in (self.observer, self.x11):
            if channel is not None:
                try:
                    channel.stdin.close()
                except OSError:
                    pass
        for process in (self.observer_process, self.x11_process):
            if process is not None and process.poll() is None:
                process.kill()
        if self.control is not None:
            try:
                self.control.close()
            except (OSError, ValueError):
                pass
        if self.process.poll() is None:
            self.process.kill()
        _, stderr = self.process.communicate(timeout=10)
        return stderr.decode(errors="replace") if stderr else ""

    def finish(self) -> str:
        assert self.control is not None
        assert self.observer is not None and self.observer_process is not None
        assert self.x11 is not None and self.x11_process is not None
        self.observer.command("EXIT", "OK EXIT")
        self.x11.command("EXIT", "OK EXIT")
        if self.observer_process.wait(timeout=10) != 0:
            raise RuntimeError("input observer failed")
        if self.x11_process.wait(timeout=10) != 0:
            raise RuntimeError("mixed X11 input client failed")
        expect_command(self.control, "QUIT", "OK QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read().decode() if self.process.stderr else ""
            raise RuntimeError(f"input-hotplug compositor failed: {stderr}")
        return self.process.stderr.read().decode() if self.process.stderr else ""


def run(
    compositor: Path,
    config_tool: Path,
    observer_binary: Path,
    x11_binary: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-input-hotplug-") as directory:
        session = Session(
            Path(directory), compositor, config_tool, observer_binary, x11_binary
        )
        control = session.control
        observer = session.observer
        x11 = session.x11
        assert control is not None and observer is not None and x11 is not None
        try:
            initial = control.state()
            initial_records = assert_input_state(
                initial,
                {"TEST-KEYBOARD-0", "TEST-POINTER-0"},
                keyboard="TEST-KEYBOARD-0",
                pointer="TEST-POINTER-0",
            )
            if [initial_records[name]["ordinal"] for name in initial_records] != [0, 1]:
                raise RuntimeError(f"initial synthetic ordinals changed: {initial!r}")
            focus_with_pointer(control, "TEST-POINTER-0", initial, NATIVE_TITLE)
            arm_observer(observer, "clear")
            expect_command(control, "INPUT CLEAR", "OK INPUT CLEAR")
            cleared = control.state()
            assert_input_state(cleared, set(), keyboard=None, pointer=None)
            if (
                cleared["seat_capabilities"] != []
                or cleared["seat_modifiers"] != ZERO_MODIFIERS
                or cleared["seat_pressed_keys"] != []
                or cleared["seat_pressed_buttons"] != []
                or cleared["seat_keyboard_focus"] is not None
                or cleared["seat_pointer_focus"] is not None
                or cleared.get("active") != NATIVE_TITLE
            ):
                raise RuntimeError(f"CLEAR corrupted logical focus/seat state: {cleared!r}")
            clear_events, clear_report = observer_report(observer, "clear")
            clear_capabilities = [
                line for line in clear_events if line.startswith("EVENT CAPABILITIES ")
            ]
            if clear_report["keyboard"] or clear_report["pointer"]:
                raise RuntimeError(f"CLEAR retained a Wayland capability: {clear_report!r}")
            if len(clear_capabilities) != 1 or not clear_capabilities[0].startswith(
                "EVENT CAPABILITIES clear keyboard=0 pointer=0 "
            ):
                raise RuntimeError(f"CLEAR produced no wl_seat capability event: {clear_events!r}")

            arm_observer(observer, "keyboard-add")
            first_keyboard = input_add(control, "keyboard", "K1")
            assert_input_state(first_keyboard, {"K1"}, keyboard="K1", pointer=None)
            keyboard_add_events, keyboard_add_report = observer_report(
                observer, "keyboard-add"
            )
            keyboard_caps = [
                line for line in keyboard_add_events
                if line.startswith("EVENT CAPABILITIES ")
            ]
            if (
                keyboard_add_report["keyboard"] != 1
                or keyboard_add_report["keyboard_focus"] != 1
                or keyboard_add_report["key_gen"] != 2
                or len(keyboard_caps) != 1
                or not keyboard_caps[0].startswith(
                    "EVENT CAPABILITIES keyboard-add keyboard=1 pointer=0 "
                )
                or "EVENT KEYBOARD_ENTER keyboard-add held=0" not in keyboard_add_events
            ):
                raise RuntimeError(
                    "first keyboard did not publish capability/focus in order: "
                    f"{keyboard_add_events!r}, {keyboard_add_report!r}"
                )
            arm_observer(observer, "additional-keyboards")
            input_add(control, "keyboard", "K2")
            state = input_add(control, "keyboard", "K3")
            additional_events, additional_report = observer_report(
                observer, "additional-keyboards"
            )
            if (
                any(line.startswith("EVENT CAPABILITIES ") for line in additional_events)
                or additional_report["key_gen"] != keyboard_add_report["key_gen"]
            ):
                raise RuntimeError(
                    "additional keyboards republished the logical capability: "
                    f"{additional_events!r}"
                )
            records = assert_input_state(
                state, {"K1", "K2", "K3"}, keyboard="K1", pointer=None
            )
            old_k2_ordinal = int(records["K2"]["ordinal"])
            for name, code in (("K2", KEY_A), ("K3", KEY_B), ("K2", KEY_C)):
                input_key(control, name, code, "press")
                input_key(control, name, code, "release")
            state = input_remove(control, "K2")
            assert_input_state(state, {"K1", "K3"}, keyboard="K3", pointer=None)
            state = input_add(control, "keyboard", "K2")
            records = assert_input_state(
                state, {"K1", "K2", "K3"}, keyboard="K3", pointer=None
            )
            if int(records["K2"]["ordinal"]) <= old_k2_ordinal:
                raise RuntimeError(f"re-added name reused an ordinal: {state!r}")

            before_failure = semantic_state(control.state())
            duplicate = raw_command(control, "INPUT ADD KEYBOARD K2")
            if duplicate != "ERROR INPUT duplicate device: K2":
                raise RuntimeError(f"duplicate-input error changed: {duplicate!r}")
            if semantic_state(control.state()) != before_failure:
                raise RuntimeError("duplicate input ADD was not semantically atomic")
            unknown = raw_command(control, "INPUT REMOVE MISSING")
            if unknown != "ERROR INPUT unknown device: MISSING":
                raise RuntimeError(f"unknown-input error changed: {unknown!r}")
            if semantic_state(control.state()) != before_failure:
                raise RuntimeError("unknown input REMOVE was not semantically atomic")

            arm_observer(observer, "key-owners")
            input_key(control, "K1", KEY_A, "press")
            state = input_key(control, "K2", KEY_A, "press")
            if state["seat_pressed_keys"] != [KEY_A]:
                raise RuntimeError(f"overlapping key owners were not collapsed: {state!r}")
            input_remove(control, "K1")
            state = input_remove(control, "K2")
            assert_input_state(state, {"K3"}, keyboard="K3", pointer=None)
            key_events, key_report = observer_report(observer, "key-owners")
            observed_keys = [line for line in key_events if line.startswith("EVENT KEY ")]
            if observed_keys != [
                f"EVENT KEY key-owners {KEY_A} press",
                f"EVENT KEY key-owners {KEY_A} release",
            ] or key_report["keys"] != 2:
                raise RuntimeError(
                    f"overlapping key ownership leaked an event: {key_events!r}"
                )

            input_add(control, "keyboard", "K4")
            input_add(control, "keyboard", "K5")
            arm_observer(observer, "cross-modifier")
            state = input_key(control, "K4", KEY_ALT, "press")
            if state["seat_modifiers"] != {
                "depressed": 8,
                "latched": 0,
                "locked": 0,
                "group": 0,
            }:
                raise RuntimeError(f"logical aggregate Alt state changed: {state!r}")
            state = input_key(control, "K5", KEY_F1, "press")
            cross_records = input_map(state)
            if (
                state["active_keyboard"] != "K5"
                or state["seat_pressed_keys"] != [KEY_ALT]
                or cross_records["K4"]["modifiers"] != {
                    "depressed": 8,
                    "latched": 0,
                    "locked": 0,
                    "group": 0,
                }
                or cross_records["K5"]["modifiers"] != ZERO_MODIFIERS
            ):
                raise RuntimeError(f"cross-device binding source was not active: {state!r}")
            input_remove(control, "K5")
            state = input_remove(control, "K4")
            if state["seat_modifiers"] != ZERO_MODIFIERS:
                raise RuntimeError(f"modifier drain left aggregate state: {state!r}")
            modifier_events, modifier_report = observer_report(observer, "cross-modifier")
            observed_keys = [line for line in modifier_events if line.startswith("EVENT KEY ")]
            if observed_keys != [
                f"EVENT KEY cross-modifier {KEY_ALT} press",
                f"EVENT KEY cross-modifier {KEY_ALT} release",
            ] or modifier_report["keys"] != 2 or KEY_F1 in [
                int(line.split()[3]) for line in observed_keys
            ]:
                raise RuntimeError(
                    "handled cross-device F1 leaked or Alt failed to drain: "
                    f"{modifier_events!r}"
                )
            if (modifier_report["depressed"], modifier_report["latched"],
                    modifier_report["locked"], modifier_report["group"]) != (0, 0, 0, 0):
                raise RuntimeError(f"observer retained modifiers: {modifier_report!r}")

            arm_observer(observer, "pointer-add")
            state = input_add(control, "pointer", "P1")
            assert_input_state(state, {"K3", "P1"}, keyboard="K3", pointer="P1")
            pointer_events, pointer_report = observer_report(observer, "pointer-add")
            pointer_caps = [
                line for line in pointer_events if line.startswith("EVENT CAPABILITIES ")
            ]
            if (
                pointer_report["pointer"] != 1
                or pointer_report["pointer_focus"] != 1
                or pointer_report["pointer_gen"] != 2
                or len(pointer_caps) != 1
                or not pointer_caps[0].startswith(
                    "EVENT CAPABILITIES pointer-add keyboard=1 pointer=1 "
                )
                or not any(line.startswith("EVENT POINTER_ENTER pointer-add ") for line in pointer_events)
            ):
                raise RuntimeError(
                    f"first pointer did not re-enter preserved hit: {pointer_events!r}"
                )
            arm_observer(observer, "wrong-type")
            before_wrong_type = semantic_state(control.state())
            wrong_type = raw_command(control, f"INPUT KEY P1 {KEY_A} press")
            if wrong_type != "ERROR INPUT KEY requires keyboard: P1":
                raise RuntimeError(f"wrong-type input error changed: {wrong_type!r}")
            if semantic_state(control.state()) != before_wrong_type:
                raise RuntimeError("wrong-type input event was not semantically atomic")
            wrong_events, _ = observer_report(observer, "wrong-type")
            if wrong_events:
                raise RuntimeError(f"failed input event reached protocol clients: {wrong_events!r}")
            arm_observer(observer, "additional-pointers")
            input_add(control, "pointer", "P2")
            input_add(control, "pointer", "P3")
            additional_events, additional_report = observer_report(
                observer, "additional-pointers"
            )
            if (
                any(line.startswith("EVENT CAPABILITIES ") for line in additional_events)
                or additional_report["pointer_gen"] != pointer_report["pointer_gen"]
            ):
                raise RuntimeError(
                    "additional pointers republished the logical capability: "
                    f"{additional_events!r}"
                )
            native_point = client_point(control.state(), NATIVE_TITLE)
            input_pointer(control, "P2", native_point)
            input_pointer(control, "P3", (native_point[0] + 1, native_point[1] + 1))
            state = input_pointer(control, "P2", native_point)
            cursor_before = copy.deepcopy(state["cursor"])
            focus_before = state["seat_pointer_focus"]
            state = input_remove(control, "P2")
            if (
                state["active_pointer"] != "P3"
                or state["cursor"] != cursor_before
                or state["seat_pointer_focus"] != focus_before
            ):
                raise RuntimeError(f"non-last active pointer fallback changed hit: {state!r}")

            arm_observer(observer, "button-owners")
            input_button(control, "P1", BTN_MIDDLE, "press")
            state = input_button(control, "P3", BTN_MIDDLE, "press")
            if state["seat_pressed_buttons"] != [BTN_MIDDLE]:
                raise RuntimeError(f"overlapping pointer owners were not collapsed: {state!r}")
            input_remove(control, "P1")
            state = input_remove(control, "P3")
            if (
                state["seat_capabilities"] != ["keyboard"]
                or state["seat_pointer_focus"] is not None
                or state["seat_pressed_buttons"] != []
            ):
                raise RuntimeError(f"last pointer removal left seat state: {state!r}")
            button_events, button_report = observer_report(observer, "button-owners")
            observed_buttons = [
                line for line in button_events if line.startswith("EVENT BUTTON ")
            ]
            button_caps = [
                line for line in button_events if line.startswith("EVENT CAPABILITIES ")
            ]
            if observed_buttons != [
                f"EVENT BUTTON button-owners {BTN_MIDDLE} press",
                f"EVENT BUTTON button-owners {BTN_MIDDLE} release",
            ] or button_report["buttons"] != 2 or button_report["pointer"] != 0 or (
                len(button_caps) != 1
                or not button_caps[0].startswith(
                    "EVENT CAPABILITIES button-owners keyboard=1 pointer=0 "
                )
            ):
                raise RuntimeError(
                    f"overlapping button ownership leaked an event: {button_events!r}"
                )

            input_add(control, "pointer", "P4")
            input_add(control, "pointer", "P5")
            input_add(control, "pointer", "P6")
            before_move = control.state()
            original = tuple(
                window(before_move, NATIVE_TITLE)[key]
                for key in ("x", "y", "width", "height")
            )
            point = client_point(before_move, NATIVE_TITLE)
            input_pointer(control, "P4", point)
            input_button(control, "P4", BTN_LEFT, "press")
            input_button(control, "P5", BTN_LEFT, "press")
            state = input_pointer(control, "P4", (point[0] + 45, point[1] + 35))
            if state.get("interaction") is None or state.get("interactive") is not True:
                raise RuntimeError(f"named-pointer move did not start: {state!r}")
            state = input_remove(control, "P4")
            if state.get("interaction") is None:
                raise RuntimeError(
                    f"surviving required-button owner did not continue move: {state!r}"
                )
            state = input_remove(control, "P5")
            restored = tuple(
                window(state, NATIVE_TITLE)[key] for key in ("x", "y", "width", "height")
            )
            if (
                state.get("interaction") is not None
                or state.get("interactive") is not False
                or restored != original
                or state["active_pointer"] != "P6"
            ):
                raise RuntimeError(
                    "final required-button owner did not roll back with survivor: "
                    f"{state!r}"
                )
            state = input_remove(control, "P6")
            if state["seat_pointer_focus"] is not None or "pointer" in state["seat_capabilities"]:
                raise RuntimeError(f"last pointer retained protocol focus/capability: {state!r}")

            state = input_add(control, "pointer", "P7")
            state = focus_with_pointer(control, "P7", state, "x11-a")
            x11.command("WAIT FOCUS x11-a", "OK FOCUS x11-a")
            logical_focus = state.get("active")
            arm_observer(observer, "last-keyboard")
            state = input_remove(control, "K3")
            if (
                state["seat_keyboard_focus"] is not None
                or "keyboard" in state["seat_capabilities"]
                or state.get("active") != logical_focus
            ):
                raise RuntimeError(f"last keyboard corrupted logical X focus: {state!r}")
            x11.command("WAIT FOCUS x11-a", "OK FOCUS x11-a")
            keyboard_events, keyboard_report = observer_report(
                observer, "last-keyboard"
            )
            keyboard_caps = [
                line for line in keyboard_events
                if line.startswith("EVENT CAPABILITIES ")
            ]
            if (
                keyboard_report["keyboard"] != 0
                or len(keyboard_caps) != 1
                or not keyboard_caps[0].startswith(
                    "EVENT CAPABILITIES last-keyboard keyboard=0 pointer=1 "
                )
            ):
                raise RuntimeError(
                    f"last keyboard did not remove the capability once: {keyboard_events!r}"
                )
            arm_observer(observer, "keyboard-return")
            state = input_add(control, "keyboard", "K6")
            if state["seat_keyboard_focus"] != "x11-a" or state.get("active") != "x11-a":
                raise RuntimeError(f"first keyboard did not reassert X focus: {state!r}")
            return_events, return_report = observer_report(observer, "keyboard-return")
            return_caps = [
                line for line in return_events if line.startswith("EVENT CAPABILITIES ")
            ]
            if (
                return_report["keyboard"] != 1
                or return_report["keyboard_focus"] != 0
                or return_report["key_gen"] != keyboard_report["key_gen"] + 1
                or len(return_caps) != 1
                or not return_caps[0].startswith(
                    "EVENT CAPABILITIES keyboard-return keyboard=1 pointer=1 "
                )
            ):
                raise RuntimeError(
                    f"returning keyboard republished the wrong seat: {return_events!r}"
                )
            x11.command("ARM x-key", "OK ARMED x-key")
            input_key(control, "K6", KEY_A, "press")
            input_key(control, "K6", KEY_A, "release")
            x11.command(
                "REPORT x-key",
                "OK REPORT x-key x11-a=2 x11-b=0 focus=x11-a",
            )

            x11.command("ARM restart-held", "OK ARMED restart-held")
            input_key(control, "K6", KEY_A, "press")
            state = input_pointer(control, "P7", root_point(control.state()))
            before_restart = input_projection(state)
            input_button(control, "P7", BTN_TASK, "press")
            restarted = control.state()
            restarted_projection = input_projection(restarted)
            expected_projection = copy.deepcopy(before_restart)
            for item in expected_projection["inputs"]:  # type: ignore[index]
                if item["name"] == "P7":
                    item["pressed"] = [BTN_TASK]
                    item["active"] = True
                if item["type"] == "pointer" and item["name"] != "P7":
                    item["active"] = False
            expected_projection["active_pointer"] = "P7"
            # The restart-trigger event advances activity but must retain every
            # other physical, protocol-focus, and capability field.
            for projection in (restarted_projection, expected_projection):
                for item in projection["inputs"]:  # type: ignore[index]
                    item.pop("last_activity")
            if restarted_projection != expected_projection:
                raise RuntimeError(
                    "restart did not preserve live device/held/focus state: "
                    f"before={before_restart!r}, after={input_projection(restarted)!r}"
                )
            input_button(control, "P7", BTN_TASK, "release")
            input_key(control, "K6", KEY_A, "release")
            x11.command(
                "REPORT restart-held",
                "OK REPORT restart-held x11-a=2 x11-b=0 focus=x11-a",
            )

            session.config.write_text('Button1 = : window : f.move\n"unterminated\n',
                                      encoding="utf-8")
            state = input_pointer(control, "P7", root_point(control.state()))
            before_invalid_reload = input_projection(state)
            input_button(control, "P7", BTN_TASK, "press")
            input_button(control, "P7", BTN_TASK, "release")
            after_invalid_reload = input_projection(control.state())
            for projection in (before_invalid_reload, after_invalid_reload):
                for item in projection["inputs"]:  # type: ignore[index]
                    item.pop("last_activity")
            if before_invalid_reload != after_invalid_reload:
                raise RuntimeError("invalid restart replacement corrupted input state")
            session.config.write_text(config_text(), encoding="utf-8")

            expect_command(control, "OUTPUT DISABLE HEADLESS-1", "OK OUTPUT DISABLE HEADLESS-1")
            zero = bounded_state(
                control,
                lambda item: all(
                    record.get("restoration_pending") is True
                    and record.get("visible") is False
                    for record in item.get("windows", [])
                    if isinstance(record, dict)
                ),
                "zero-output hidden restoration state",
            )
            if zero["seat_pointer_focus"] is not None:
                raise RuntimeError(f"zero output retained protocol pointer focus: {zero!r}")
            zero_windows = restoration_projection(zero)
            zero_cursor = copy.deepcopy(zero["cursor"])
            input_add(control, "keyboard", "K7")
            input_add(control, "pointer", "P8")
            changed = input_remove(control, "K7")
            changed = input_remove(control, "P8")
            if (
                restoration_projection(changed) != zero_windows
                or changed["cursor"] != zero_cursor
                or changed["seat_pointer_focus"] is not None
            ):
                raise RuntimeError(
                    f"zero-output input churn changed restoration bookkeeping: {changed!r}"
                )
            expect_command(control, "OUTPUT ENABLE HEADLESS-1", "OK OUTPUT ENABLE HEADLESS-1")
            restored_state = bounded_state(
                control,
                lambda item: all(
                    record.get("restoration_pending") is False
                    and record.get("visible") is True
                    for record in item.get("windows", [])
                    if isinstance(record, dict)
                ),
                "output restoration before pointer refresh",
            )
            input_map(restored_state)
            x11.command("WAIT FOCUS x11-a", "OK FOCUS x11-a")

            last_ordinal = max(
                int(item["ordinal"]) for item in input_map(restored_state).values()
            )
            for index in range(12):
                kind = "keyboard" if index % 2 == 0 else "pointer"
                name = f"CHURN-{index}"
                state = input_add(control, kind, name)
                ordinal = int(input_map(state)[name]["ordinal"])
                if ordinal <= last_ordinal:
                    raise RuntimeError(f"churn reused/nonmonotonic ordinal: {state!r}")
                last_ordinal = ordinal
                input_remove(control, name)
            final = control.state()
            assert_input_state(final, {"K6", "P7"}, keyboard="K6", pointer="P7")
            if session.observer_process is None or session.observer_process.poll() is not None:
                raise RuntimeError("native observer died during input churn")
            if session.x11_process is None or session.x11_process.poll() is not None:
                raise RuntimeError("Xwayland client died during input churn")
            arm_observer(observer, "final-live")
            _, final_report = observer_report(observer, "final-live")
            if final_report["close"] != 0 or not final_report["keyboard"] or not final_report["pointer"]:
                raise RuntimeError(f"native observer was not live: {final_report!r}")
            stderr = session.finish()
            if "ERROR: AddressSanitizer" in stderr or "runtime error:" in stderr:
                raise RuntimeError(f"sanitizer diagnostic in compositor stderr:\n{stderr}")
        except Exception as error:
            stderr = session.abort()
            raise RuntimeError(
                f"input-hotplug live session failed: {error}\n"
                f"compositor stderr:\n{stderr}"
            ) from error


def executable(parser: argparse.ArgumentParser, path: Path | None, name: str) -> Path:
    if path is None:
        parser.error(f"--{name} is required")
    resolved = path.resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        parser.error(f"--{name} is not executable: {resolved}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="exercise Milestone 8 one-seat input-device hotplug semantics"
    )
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--config-tool", type=Path)
    parser.add_argument("--wayland-observer", type=Path)
    parser.add_argument("--x11-client", type=Path)
    arguments = parser.parse_args()

    validate_model()
    if arguments.config_tool is not None:
        validate_generated_config(
            executable(parser, arguments.config_tool, "config-tool")
        )
    if arguments.self_test_model:
        print("Milestone 8 input-hotplug model self-test passed")
        return 0
    if sys.platform != "linux":
        print("Milestone 8 input-hotplug live integration requires Linux")
        return 77
    run(
        executable(parser, arguments.compositor, "compositor"),
        executable(parser, arguments.config_tool, "config-tool"),
        executable(parser, arguments.wayland_observer, "wayland-observer"),
        executable(parser, arguments.x11_client, "x11-client"),
    )
    print("Milestone 8 input-hotplug live integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
