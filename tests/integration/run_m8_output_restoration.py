#!/usr/bin/env python3
"""Verify safe managed-window restoration after output disappearance."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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


BUTTON_CODES = {1: 272, 2: 274, 3: 273}
NATIVE_VISIBLE = "restore-native-visible"
NATIVE_PARENT = "restore-native-parent"
NATIVE_CHILD = "restore-native-child"
NATIVE_ICON = "restore-native-icon"
NATIVE_ZOOM = "restore-native-zoom"
X11_VISIBLE = "restore-x11-visible"
X11_PARENT = "focus-a"
X11_CHILD = "focus-b"
X11_ICON = "restore-x11-icon"
X11_ZOOM = "restore-x11-zoom"
WAITER = "restore-native-waiter"
INITIAL_TITLES = {
    NATIVE_VISIBLE,
    NATIVE_PARENT,
    NATIVE_CHILD,
    NATIVE_ICON,
    NATIVE_ZOOM,
    X11_VISIBLE,
    X11_PARENT,
    X11_CHILD,
    X11_ICON,
    X11_ZOOM,
}
WINDOW_STABLE_FIELDS = {
    "id",
    "title",
    "app_id",
    "type",
    "instance",
    "class",
    "x",
    "y",
    "width",
    "height",
    "outer_width",
    "outer_height",
    "border_width",
    "title_bar_height",
    "title_height",
    "content_x",
    "content_y",
    "stack",
    "mapped",
    "placement_pending",
    "iconified",
    "iconify_by_unmapping",
    "decorated",
    "auto_raise",
    "active",
    "placement",
    "restoration_pending",
    "visible",
    "zoom",
    "parent_id",
}
ZOOM_MODES = {"none", "vertical", "horizontal", "full", "left", "right", "top", "bottom"}


def config_text() -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        "DontMoveOff\n"
        "NoRaiseOnResize\n"
        "Button1 = : all : f.iconify\n"
        "Button2 = : all : f.fullzoom\n"
        "Button3 = : all : f.focus\n"
    )


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x * 2 + self.width, self.y * 2 + self.height

    def moved(self, dx: int, dy: int) -> Box:
        return Box(self.x + dx, self.y + dy, self.width, self.height)


@dataclass(frozen=True)
class PlannedBox:
    box: Box
    source: str | None
    target: str | None
    changed: bool


def intersection_area(first: Box, second: Box) -> int:
    width = max(0, min(first.right, second.right) - max(first.x, second.x))
    height = max(0, min(first.bottom, second.bottom) - max(first.y, second.y))
    return width * height


def point_distance_squared(box: Box, doubled_point: tuple[int, int]) -> int:
    left = box.x * 2
    top = box.y * 2
    right = box.right * 2
    bottom = box.bottom * 2
    dx = max(left - doubled_point[0], 0, doubled_point[0] - right)
    dy = max(top - doubled_point[1], 0, doubled_point[1] - bottom)
    return dx * dx + dy * dy


def select_owner(outputs: list[tuple[str, Box]], outer: Box) -> tuple[str, Box] | None:
    if not outputs:
        return None
    areas = [intersection_area(box, outer) for _, box in outputs]
    greatest = max(areas)
    if greatest > 0:
        return outputs[areas.index(greatest)]
    return min(outputs, key=lambda item: point_distance_squared(item[1], outer.center))


def clamp_box(target: Box, candidate: Box) -> Box:
    if candidate.width <= target.width:
        x = min(max(candidate.x, target.x), target.right - candidate.width)
    else:
        x = target.x
    if candidate.height <= target.height:
        y = min(max(candidate.y, target.y), target.bottom - candidate.height)
    else:
        y = target.y
    return Box(x, y, candidate.width, candidate.height)


def restore_box(
    outer: Box,
    before: list[tuple[str, Box]],
    after: list[tuple[str, Box]],
) -> PlannedBox:
    if not after:
        source = select_owner(before, outer)
        return PlannedBox(outer, source[0] if source else None, None, False)
    if any(intersection_area(box, outer) > 0 for _, box in after):
        return PlannedBox(outer, None, None, False)
    source = select_owner(before, outer)
    if source is None:
        raise RuntimeError("nonempty restoration plan has no source output")
    matching = next((item for item in after if item[0] == source[0]), None)
    target = matching if matching is not None else select_owner(after, outer)
    if target is None:
        raise RuntimeError("nonempty restoration plan has no target output")
    candidate = Box(
        target[1].x + outer.x - source[1].x,
        target[1].y + outer.y - source[1].y,
        outer.width,
        outer.height,
    )
    planned = clamp_box(target[1], candidate)
    return PlannedBox(planned, source[0], target[0], planned != outer)


def restore_family(
    root: Box,
    descendants: list[Box],
    before: list[tuple[str, Box]],
    after: list[tuple[str, Box]],
) -> tuple[Box, list[Box]]:
    root_plan = restore_box(root, before, after)
    if not after:
        return root_plan.box, descendants.copy()
    selected = next(
        (item for item in after if item[0] == root_plan.target),
        select_owner(after, root),
    )
    if selected is None:
        raise RuntimeError("restored family has no target output")
    target = selected[1]
    dx = root_plan.box.x - root.x
    dy = root_plan.box.y - root.y
    restored = []
    for child in descendants:
        if not root_plan.changed and any(
            intersection_area(box, child) > 0 for _, box in after
        ):
            restored.append(child)
        else:
            restored.append(clamp_box(target, child.moved(dx, dy)))
    return root_plan.box, restored


def validate_model() -> None:
    left = ("LEFT", Box(-320, 0, 320, 240))
    right = ("RIGHT", Box(0, 0, 400, 300))
    before = [left, right]
    after = [left]

    visible = Box(-300, 20, 120, 80)
    if restore_box(visible, before, after).box != visible:
        raise RuntimeError("positive-intersection frame was not byte-exact")
    stranded = Box(250, 190, 180, 120)
    planned = restore_box(stranded, before, after)
    if planned != PlannedBox(Box(-180, 120, 180, 120), "RIGHT", "LEFT", True):
        raise RuntimeError(f"relative translation/fit clamp changed: {planned!r}")
    oversize = Box(20, 10, 500, 260)
    if restore_box(oversize, [right], after).box != Box(-320, 0, 500, 260):
        raise RuntimeError("oversized frame was not pinned to the target origin")

    parent = Box(100, 60, 180, 120)
    children = [Box(150, 90, 140, 90), Box(370, 250, 140, 90)]
    restored_parent, restored_children = restore_family(parent, children, before, after)
    if restored_parent != Box(-220, 60, 180, 120):
        raise RuntimeError("transient root restoration changed")
    if restored_children != [Box(-170, 90, 140, 90), Box(-140, 150, 140, 90)]:
        raise RuntimeError("family delta/member safety clamp changed")
    stable_parent, child_only = restore_family(
        Box(-300, 20, 100, 80), [Box(300, 200, 80, 60)], before, after
    )
    if stable_parent != Box(-300, 20, 100, 80) or child_only != [
        Box(-80, 180, 80, 60)
    ]:
        raise RuntimeError("stranded transient was not clamped to its root output")

    moved_owner = restore_box(
        Box(40, 40, 100, 80), [right], [("RIGHT", Box(500, 0, 400, 300))]
    )
    if moved_owner.box != Box(540, 40, 100, 80):
        raise RuntimeError("surviving moved owner lost source-relative placement")
    canonical_tie = restore_box(
        Box(1000, 100, 100, 100),
        [("OLD", Box(900, 0, 300, 300))],
        [("A", Box(0, 0, 100, 100)), ("B", Box(0, 200, 100, 100))],
    )
    if canonical_tie.target != "A":
        raise RuntimeError("missing-owner nearest tie ignored canonical order")
    partially_visible = Box(190, 140, 80, 60)
    if restore_box(
        partially_visible, [right], [("RIGHT", Box(0, 0, 200, 150))]
    ).box != partially_visible:
        raise RuntimeError("shrunk output moved a positively intersecting frame")

    icon_frame = restore_box(Box(260, 200, 180, 120), before, after).box
    icon = restore_box(Box(350, 260, 40, 30), before, after).box
    if icon_frame != Box(-180, 120, 180, 120) or icon != Box(-40, 210, 40, 30):
        raise RuntimeError("icon frame and presentation were not independent")

    zoom_current = restore_box(right[1], before, after)
    zoom_saved = restore_box(stranded, before, after)
    if zoom_current.target != "LEFT" or zoom_saved.box != Box(-180, 120, 180, 120):
        raise RuntimeError("zoom target/saved geometry repair changed")
    if left[1] != Box(-320, 0, 320, 240):
        raise RuntimeError("zoom model mutated its output input")
    if restore_box(visible, before, after).box != visible:
        raise RuntimeError("visible saved zoom geometry moved")

    pending = restore_box(stranded, before, [])
    if pending.box != stranded or pending.target is not None or pending.changed:
        raise RuntimeError("zero outputs mutated deferred geometry")
    resumed = restore_box(pending.box, before, [("NEW", Box(500, -20, 300, 220))])
    if resumed.box != Box(620, 80, 180, 120):
        raise RuntimeError("pending geometry did not restore on first output")
    same_identity = restore_box(
        pending.box, before, [("RIGHT", Box(500, 0, 400, 300))]
    )
    if same_identity.box != Box(720, 180, 180, 120):
        raise RuntimeError("pending same-identity restoration lost relative origin")
    returned = restore_box(planned.box, after, before)
    if returned.box != planned.box or returned.changed:
        raise RuntimeError("returning output repatriated a visible frame")

    churn_right = restore_box(planned.box, after, [right])
    if churn_right.box != Box(140, 120, 180, 120):
        raise RuntimeError("survivor-to-survivor repeated churn changed")
    if restore_box(churn_right.box, [right], before).box != churn_right.box:
        raise RuntimeError("repeated churn repatriated after enable")

    target = {
        "title": "target", "visible": True, "stack": 1,
        "x": 10, "y": 10, "width": 20, "height": 10,
        "outer_width": 24, "outer_height": 14,
        "content_x": 2, "content_y": 2,
    }
    blocker = {
        "title": "blocker", "visible": True, "stack": 0,
        "x": 10, "y": 10, "width": 10, "height": 10,
        "outer_width": 14, "outer_height": 14,
        "content_x": 2, "content_y": 2,
    }
    point = select_visible_content_point({1: target, 2: blocker}, "target")
    if point is None or point[0] < 24:
        raise RuntimeError(f"visible-content target selection changed: {point!r}")


def validate_generated_config(config_tool: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-restore-config-") as directory:
        path = Path(directory) / "output-restoration.twmrc"
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
                "wtwm-config rejected restoration config: "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        if (
            "bindings=3\n" not in result.stdout
            or "compatibility-warnings=0\n" not in result.stdout
        ):
            raise RuntimeError(f"generated restoration config changed: {result.stdout!r}")


def read_prefixed_line(process: subprocess.Popen[bytes], prefix: str) -> str:
    if process.stdout is None:
        raise RuntimeError("compositor lacks stdout")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    buffer = bytearray()
    deadline = time.monotonic() + 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"timed out waiting for compositor {prefix!r}")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            raise RuntimeError(f"timed out waiting for compositor {prefix!r}")
        chunk = os.read(descriptor, 4096)
        if not chunk:
            raise RuntimeError(f"compositor exited before {prefix!r}")
        buffer.extend(chunk)
        while b"\n" in buffer:
            raw, _, remainder = buffer.partition(b"\n")
            buffer = bytearray(remainder)
            line = raw.decode("utf-8", errors="strict")
            if line.startswith(prefix):
                return line


def bounded_state(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    label: str,
    *,
    active_outputs: bool = True,
    attempts: int = 128,
) -> dict[str, object]:
    last: dict[str, object] | None = None
    for _ in range(attempts):
        last = control.state()
        if predicate(last):
            return last
        if active_outputs:
            control.command("WAIT 1")
        else:
            control.command("PING")
    raise RuntimeError(f"bounded STATE barrier failed for {label}: {last!r}")


def expect_command(control: Control, command: str, expected: str) -> None:
    observed = control.command(command)
    if observed != expected:
        raise RuntimeError(f"{command!r}: expected {expected!r}, observed {observed!r}")


def raw_command(control: Control, command: str) -> str:
    control.stream.write(command + "\n")
    control.stream.flush()
    return control.stream.readline().rstrip("\n")


def frame_barrier(control: Control, label: str) -> dict[str, object]:
    before = control.state()
    response = control.command("WAIT 2")
    match = re.fullmatch(r"OK FRAME ([0-9]+)", response)
    after = control.state()
    if match is None:
        raise RuntimeError(f"{label}: invalid frame response {response!r}")
    sequence = int(match.group(1))
    if sequence <= int(before["frame"]) or int(after["frame"]) != sequence:
        raise RuntimeError(
            f"{label}: frame mismatch before={before['frame']!r}, "
            f"response={response!r}, after={after['frame']!r}"
        )
    return after


def outputs(state: dict[str, object]) -> list[tuple[str, Box]]:
    records = state.get("outputs")
    if not isinstance(records, list):
        raise RuntimeError(f"STATE lacks output inventory: {state!r}")
    result: list[tuple[str, Box]] = []
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"invalid output record: {record!r}")
        if not record.get("enabled"):
            if record.get("index") is not None or record.get("box") is not None:
                raise RuntimeError(f"disabled output retained spatial state: {record!r}")
            continue
        value = record.get("box")
        if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
            raise RuntimeError(f"invalid enabled output box: {record!r}")
        dimensions = (int(value[key]) for key in ("x", "y", "width", "height"))
        result.append((str(record["name"]), Box(*dimensions)))
    return result


def windows(state: dict[str, object]) -> dict[int, dict[str, object]]:
    records = state.get("windows")
    if not isinstance(records, list):
        raise RuntimeError(f"STATE lacks window inventory: {state!r}")
    result: dict[int, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError(f"invalid window record: {record!r}")
        missing = WINDOW_STABLE_FIELDS - set(record)
        if missing or "zoom_saved" not in record:
            raise RuntimeError(
                "window restoration STATE schema missing "
                f"{sorted(missing)!r}: {record!r}"
            )
        identity = record.get("id")
        if not isinstance(identity, int) or identity <= 0 or identity in result:
            raise RuntimeError(f"invalid managed window identity: {record!r}")
        if record["zoom"] not in ZOOM_MODES:
            raise RuntimeError(f"invalid zoom mode: {record!r}")
        parent = record["parent_id"]
        if parent is not None and (not isinstance(parent, int) or parent <= 0):
            raise RuntimeError(f"invalid managed parent identity: {record!r}")
        for field in (
            "mapped",
            "placement_pending",
            "iconified",
            "active",
            "restoration_pending",
            "visible",
        ):
            if not isinstance(record[field], bool):
                raise RuntimeError(f"non-boolean {field}: {record!r}")
        result[identity] = record
    return result


def by_title(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in windows(state).values() if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {title!r} window: {state!r}")
    return matches[0]


def outer(record: dict[str, object]) -> Box:
    return Box(
        int(record["x"]),
        int(record["y"]),
        int(record["outer_width"]),
        int(record["outer_height"]),
    )


def zoom_saved_outer(record: dict[str, object]) -> Box | None:
    value = record["zoom_saved"]
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise RuntimeError(f"invalid zoom_saved schema: {record!r}")
    decoration_width = int(record["outer_width"]) - int(record["width"])
    decoration_height = int(record["outer_height"]) - int(record["height"])
    return Box(
        int(value["x"]),
        int(value["y"]),
        int(value["width"]) + decoration_width,
        int(value["height"]) + decoration_height,
    )


def icon_views(state: dict[str, object]) -> dict[str, dict[str, object]]:
    records = state.get("icon_views")
    if not isinstance(records, list):
        raise RuntimeError(f"STATE lacks icon views: {state!r}")
    result = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "title", "x", "y", "width", "height", "source", "region_allocated"
        }:
            raise RuntimeError(f"invalid icon view schema: {record!r}")
        result[str(record["title"])] = record
    return result


def icon_box(record: dict[str, object]) -> Box:
    return Box(*(int(record[key]) for key in ("x", "y", "width", "height")))


def family_members(records: dict[int, dict[str, object]]) -> list[list[int]]:
    roots = [
        identity
        for identity, item in records.items()
        if item["parent_id"] not in records
    ]
    result = []
    for root in roots:
        family = []
        pending = [root]
        while pending:
            current = pending.pop(0)
            family.append(current)
            pending.extend(
                identity for identity, item in records.items()
                if item["parent_id"] == current
            )
        result.append(family)
    if sorted(identity for family in result for identity in family) != sorted(records):
        raise RuntimeError(f"managed parent graph is cyclic or incomplete: {records!r}")
    return result


def planned_frames(
    before_state: dict[str, object],
    after_outputs: list[tuple[str, Box]],
    source_outputs: list[tuple[str, Box]] | None = None,
) -> tuple[dict[int, Box], set[int]]:
    records = windows(before_state)
    before_outputs = (
        outputs(before_state) if source_outputs is None else source_outputs
    )
    planned: dict[int, Box] = {}
    changed: set[int] = set()
    for family in family_members(records):
        root_record = records[family[0]]
        root_box = outer(root_record)
        root_plan = restore_box(root_box, before_outputs, after_outputs)
        selected = next(
            (item for item in after_outputs if item[0] == root_plan.target),
            select_owner(after_outputs, root_box),
        )
        target = selected[1] if selected is not None else None
        dx = root_plan.box.x - root_box.x
        dy = root_plan.box.y - root_box.y
        for offset, identity in enumerate(family):
            record = records[identity]
            current = outer(record)
            if offset == 0:
                expected = root_plan.box
            elif root_plan.changed and target is not None:
                expected = clamp_box(target, current.moved(dx, dy))
            elif target is not None and not any(
                intersection_area(box, current) > 0 for _, box in after_outputs
            ):
                expected = clamp_box(target, current)
            else:
                expected = current
            if (
                record["zoom"] == "full"
                and expected != current
                and target is not None
            ):
                expected = target
            planned[identity] = expected
            if expected != current:
                changed.add(identity)
    return planned, changed


def assert_transition(
    before: dict[str, object],
    after: dict[str, object],
    label: str,
    *,
    preserve_active: bool = True,
    source_outputs: list[tuple[str, Box]] | None = None,
) -> set[int]:
    before_windows = windows(before)
    after_windows = windows(after)
    if set(after_windows) != set(before_windows):
        raise RuntimeError(f"{label}: managed identities changed")
    post_outputs = outputs(after)
    before_outputs = outputs(before) if source_outputs is None else source_outputs
    expected_frames, changed = planned_frames(
        before, post_outputs, source_outputs
    )
    before_icons = icon_views(before)
    after_icons = icon_views(after)
    expected_icons: dict[str, Box] = {}
    for title, item in before_icons.items():
        expected_icons[title] = restore_box(
            icon_box(item), before_outputs, post_outputs
        ).box

    for identity, previous in before_windows.items():
        current = after_windows[identity]
        if previous["title"] != current["title"]:
            raise RuntimeError(f"{label}: stable identity changed title: {current!r}")
        expected = expected_frames[identity]
        if outer(current) != expected:
            raise RuntimeError(
                f"{label}: frame restoration mismatch for {current['title']!r}: "
                f"expected={expected!r}, observed={outer(current)!r}"
            )
        ignored_fields = {
            "x", "y", "restoration_pending", "visible"
        }
        if not preserve_active:
            ignored_fields.update({"active", "stack"})
        for field in WINDOW_STABLE_FIELDS - ignored_fields:
            if (
                field in {"width", "height", "outer_width", "outer_height"}
                and current["zoom"] == "full"
            ):
                continue
            if previous[field] != current[field]:
                raise RuntimeError(
                    f"{label}: {field} changed for {current['title']!r}: "
                    f"{previous[field]!r} != {current[field]!r}"
                )
        if post_outputs:
            if (
                current["restoration_pending"]
                or not current["visible"]
                or not current["mapped"]
            ):
                raise RuntimeError(
                    f"{label}: restored window is not live/visible: {current!r}"
                )
        else:
            if (
                not current["restoration_pending"]
                or current["visible"]
                or not current["mapped"]
            ):
                raise RuntimeError(
                    f"{label}: zero-output window exposure changed: {current!r}"
                )

        previous_saved = zoom_saved_outer(previous)
        current_saved = zoom_saved_outer(current)
        if previous_saved is None:
            if current_saved is not None:
                raise RuntimeError(f"{label}: non-zoomed window gained saved geometry")
        else:
            expected_saved = restore_box(
                previous_saved, before_outputs, post_outputs
            ).box
            if current_saved != expected_saved:
                raise RuntimeError(
                    f"{label}: zoom saved geometry mismatch: "
                    f"expected={expected_saved!r}, observed={current_saved!r}"
                )
            before_raw = previous["zoom_saved"]
            after_raw = current["zoom_saved"]
            assert isinstance(before_raw, dict) and isinstance(after_raw, dict)
            if (before_raw["width"], before_raw["height"]) != (
                after_raw["width"], after_raw["height"]
            ):
                raise RuntimeError(f"{label}: zoom saved client size changed")

    if set(before_icons) != set(after_icons):
        raise RuntimeError(f"{label}: icon presentation membership changed")
    for title, previous in before_icons.items():
        current = after_icons[title]
        if icon_box(current) != expected_icons[title]:
            raise RuntimeError(f"{label}: icon restoration mismatch for {title!r}")
        if expected_icons[title] != icon_box(previous):
            identity = next(
                key for key, item in before_windows.items() if item["title"] == title
            )
            changed.add(identity)
        if (
            previous["source"] != current["source"]
            or previous["region_allocated"] != current["region_allocated"]
        ):
            raise RuntimeError(f"{label}: icon ownership changed for {title!r}")

    if not outputs(before) and post_outputs:
        changed.update(before_windows)

    if preserve_active and (before["focus"], before["active"]) != (
        after["focus"],
        after["active"],
    ):
        raise RuntimeError(f"{label}: focus changed during restoration")
    if preserve_active:
        if {
            identity: item["stack"] for identity, item in before_windows.items()
        } != {
            identity: item["stack"] for identity, item in after_windows.items()
        }:
            raise RuntimeError(f"{label}: stacking changed during restoration")
    else:
        before_order = sorted(before_windows, key=lambda key: before_windows[key]["stack"])
        after_order = sorted(after_windows, key=lambda key: after_windows[key]["stack"])
        if before_order != after_order:
            raise RuntimeError(f"{label}: relative stack order changed before waiter map")
    return changed


def pointer(control: Control, x: int, y: int, label: str) -> dict[str, object]:
    expect_command(control, f"POINTER {x} {y}", f"OK CURSOR {x:.3f} {y:.3f}")
    state = frame_barrier(control, label)
    cursor = state["cursor"]
    if not isinstance(cursor, dict) or (
        float(cursor["x"]), float(cursor["y"])
    ) != (float(x), float(y)):
        raise RuntimeError(f"{label}: pointer was not exact: {state!r}")
    return state


def window_point(record: dict[str, object]) -> tuple[int, int]:
    return (
        int(record["x"]) + int(record["content_x"]) + max(1, int(record["width"]) // 2),
        int(record["y"]) + int(record["content_y"]) + max(1, int(record["height"]) // 2),
    )


def select_visible_content_point(
    records: dict[int, dict[str, object]], title: str
) -> tuple[int, int] | None:
    target = next(
        (item for item in records.values() if item["title"] == title), None
    )
    if target is None or not target["visible"]:
        return None
    left = int(target["x"]) + int(target["content_x"])
    top = int(target["y"]) + int(target["content_y"])
    right = left + int(target["width"])
    bottom = top + int(target["height"])
    blockers = [
        outer(item)
        for item in records.values()
        if item["visible"] and int(item["stack"]) < int(target["stack"])
    ]

    def exposed(x: int, y: int) -> bool:
        return not any(
            box.x <= x < box.right and box.y <= y < box.bottom
            for box in blockers
        )

    center = window_point(target)
    if exposed(*center):
        return center
    for y in range(top, bottom):
        for x in range(left, right):
            if (x, y) != center and exposed(x, y):
                return x, y
    return None


def visible_content_point(
    state: dict[str, object], title: str
) -> tuple[int, int] | None:
    return select_visible_content_point(windows(state), title)


def pointer_inside(control: Control, title: str, label: str) -> dict[str, object]:
    deadline = time.monotonic() + 10.0
    attempts = 0
    last: dict[str, object] | None = None
    last_point: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        before = control.state()
        point = visible_content_point(before, title)
        if point is None:
            raise RuntimeError(
                f"{label}: no exposed content point for {title!r}: {before!r}"
            )
        last_point = point
        attempts += 1
        expect_command(
            control,
            f"POINTER {point[0]} {point[1]}",
            f"OK CURSOR {point[0]:.3f} {point[1]:.3f}",
        )
        last = frame_barrier(control, label + " pointer")
        if (
            last["pointer_window"] == title
            and last["pointer_context"] == "window"
        ):
            return last
    raise RuntimeError(
        f"{label}: pointer never entered exact content after {attempts} attempts; "
        f"last_point={last_point!r}, last_state={last!r}"
    )


def click_action(control: Control, title: str, button: int, label: str) -> None:
    pointer_inside(control, title, label)
    code = BUTTON_CODES[button]
    expect_command(control, f"BUTTON {code} press", f"OK BUTTON {code} press")
    expect_command(control, f"BUTTON {code} release", f"OK BUTTON {code} release")
    frame_barrier(control, label + " action")


def validate_trace(trace: dict[str, object]) -> list[dict[str, object]]:
    if set(trace) != {"version", "first_seq", "next_seq", "dropped", "events"}:
        raise RuntimeError(f"TRACE schema changed: {trace!r}")
    if trace["version"] != 1 or trace["dropped"] != 0:
        raise RuntimeError(f"TRACE is incomplete: {trace!r}")
    events = trace["events"]
    if not isinstance(events, list):
        raise RuntimeError(f"TRACE events is not a list: {trace!r}")
    if [item.get("seq") for item in events if isinstance(item, dict)] != list(
        range(1, len(events) + 1)
    ):
        raise RuntimeError(f"TRACE sequence changed: {trace!r}")
    if trace["first_seq"] != 1 or trace["next_seq"] != len(events):
        raise RuntimeError(f"TRACE bounds changed: {trace!r}")
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "seq",
            "event",
            "context",
            "window",
            "geometry",
            "state",
        }:
            raise RuntimeError(f"TRACE event schema changed: {event!r}")
        identity = event["window"]
        if not isinstance(identity, dict) or set(identity) != {
            "id",
            "type",
            "title",
            "app_id",
            "instance",
            "class",
            "icon_name",
        }:
            raise RuntimeError(f"TRACE identity schema changed: {event!r}")
        geometry = event["geometry"]
        if not isinstance(geometry, dict) or set(geometry) != {"client", "frame"}:
            raise RuntimeError(f"TRACE geometry schema changed: {event!r}")
        state = event["state"]
        if not isinstance(state, dict) or set(state) != {
            "mapped",
            "iconified",
            "focused",
            "stack",
            "placement",
            "active",
        }:
            raise RuntimeError(f"TRACE state schema changed: {event!r}")
        if event["event"] in {"unmap", "destroy"}:
            raise RuntimeError(f"topology change killed a managed client: {event!r}")
    return events


class Session:
    def __init__(
        self,
        root: Path,
        compositor: Path,
        config_tool: Path,
        wayland_client: Path,
        x11_client: Path,
        x11_family_client: Path,
    ) -> None:
        validate_generated_config(config_tool)
        config = root / "output-restoration.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        self.socket_name = f"wtwm-m8-restore-{os.getpid()}"
        control_path = root / "control.sock"
        environment = {
            **os.environ,
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        }
        self.environment = environment
        self.wayland_client = wayland_client
        self.x11_client = x11_client
        self.x11_family_client = x11_family_client
        self.process = subprocess.Popen(
            [
                str(compositor), "-f", str(config),
                "-s", 'printf "WTWM_DISPLAY=%s\\n" "$DISPLAY"',
                "--test-control", str(control_path),
                "--test-socket", self.socket_name,
                "--test-backend", "headless",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control: Control | None = None
        self.clients: list[tuple[str, subprocess.Popen[bytes], ClientChannel | None]] = []
        try:
            self.control = Control(control_path, self.process)  # type: ignore[arg-type]
            self.control.socket.settimeout(10)
            expect_command(self.control, "SET ANIMATION_MS 0", "OK ANIMATION_MS 0")
            expect_command(self.control, "SET PLACEMENT_SEED 0", "OK PLACEMENT_SEED 0")
            display_line = read_prefixed_line(self.process, "WTWM_DISPLAY=")
            self.display = display_line.removeprefix("WTWM_DISPLAY=")
            if not self.display:
                raise RuntimeError("Xwayland published an empty DISPLAY")
        except Exception:
            self.abort()
            raise

    def add_initial_outputs(self) -> None:
        assert self.control is not None
        expect_command(self.control, "OUTPUT 320 240", "OK OUTPUT HEADLESS-1 320 240")
        frame_barrier(self.control, "first output add")
        expect_command(self.control, "OUTPUT 400 300", "OK OUTPUT HEADLESS-2 400 300")
        frame_barrier(self.control, "second output add")
        expect_command(
            self.control,
            "OUTPUT POSITION HEADLESS-1 -320 0",
            "OK OUTPUT POSITION HEADLESS-1 -320 0",
        )
        frame_barrier(self.control, "left output position")
        expect_command(
            self.control,
            "OUTPUT POSITION HEADLESS-2 0 0",
            "OK OUTPUT POSITION HEADLESS-2 0 0",
        )
        state = frame_barrier(self.control, "right output position")
        if outputs(state) != [
            ("HEADLESS-1", Box(-320, 0, 320, 240)),
            ("HEADLESS-2", Box(0, 0, 400, 300)),
        ]:
            raise RuntimeError(f"initial restoration topology changed: {state!r}")

    def launch_native(
        self, title: str, app_id: str, child: tuple[str, str] | None = None
    ) -> ClientChannel:
        arguments = [str(self.wayland_client), title, app_id]
        if child is not None:
            arguments.extend(child)
        environment = {**self.environment, "WAYLAND_DISPLAY": self.socket_name}
        process = subprocess.Popen(
            arguments,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, title)
        self.clients.append((title, process, channel))
        if child is None:
            channel.expect(f"OK READY {title}")
        else:
            channel.expect(f"OK READY FAMILY {title} {child[0]}")
        return channel

    def launch_x11(self, title: str) -> ClientChannel:
        environment = {**self.environment, "DISPLAY": self.display}
        process = subprocess.Popen(
            [str(self.x11_client), title, title, "WtwmRestore"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, title)
        self.clients.append((title, process, channel))
        channel.expect_prefix(f"OK READY {title} ")
        channel.command("FREEZE", "OK FROZEN 0x007030a0")
        return channel

    def launch_x11_family(self) -> ClientChannel:
        environment = {**self.environment, "DISPLAY": self.display}
        process = subprocess.Popen(
            [str(self.x11_family_client)],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, "X11 restoration family")
        self.clients.append(("X11 restoration family", process, channel))
        channel.expect("READY")
        return channel

    def launch_waiter(self) -> tuple[subprocess.Popen[bytes], ClientChannel]:
        environment = {**self.environment, "WAYLAND_DISPLAY": self.socket_name}
        process = subprocess.Popen(
            [str(self.wayland_client), WAITER, "org.wtwm.RestoreWaiter"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        channel = ClientChannel(process, WAITER)
        self.clients.append((WAITER, process, channel))
        return process, channel

    def assert_protocols(self, token: str) -> None:
        assert self.control is not None
        for label, process, channel in self.clients:
            if label == WAITER and by_title(self.control.state(), WAITER)["placement_pending"]:
                continue
            if process.poll() is not None:
                raise RuntimeError(f"{token}: {label} exited with {process.returncode}")
            if channel is None:
                continue
            if label == "X11 restoration family":
                channel.stdin.write(b"STATUS\n")
                channel.stdin.flush()
                status = channel.expect_prefix("STATUS ")
                if re.fullmatch(r"STATUS [0-9]+ [0-9]+ (a|b|root|other|error)", status) is None:
                    raise RuntimeError(f"{token}: invalid X11 family status {status!r}")
            elif label.startswith("restore-x11"):
                channel.command("REPORT", "OK REPORT close=0 mapped=1 cycle=0")
            elif label == NATIVE_PARENT:
                channel.command(f"ARM {token}", f"OK ARMED {token}")
                channel.stdin.write(f"REPORT_FAMILY {token}\n".encode())
                channel.stdin.flush()
                report = channel.expect_prefix(f"OK REPORT_FAMILY {token} ")
                if re.fullmatch(
                    rf"OK REPORT_FAMILY {re.escape(token)} parent_mapped=1 "
                    r"child_mapped=1 focus=(parent|child|none) "
                    r"parent_close=0 child_close=0",
                    report,
                ) is None:
                    raise RuntimeError(f"{token}: invalid native family report {report!r}")
            else:
                channel.command(f"ARM {token}", f"OK ARMED {token}")
                channel.stdin.write(f"REPORT {token}\n".encode())
                channel.stdin.flush()
                report = channel.expect_prefix(f"OK REPORT {token} ")
                if re.fullmatch(
                    rf"OK REPORT {re.escape(token)} keys=0 focus=[01] close=0",
                    report,
                ) is None:
                    raise RuntimeError(f"{token}: invalid native report {report!r}")

    def finish(self) -> str:
        assert self.control is not None
        for label, process, channel in self.clients:
            if channel is not None and process.poll() is None:
                if label == "X11 restoration family":
                    channel.stdin.write(b"EXIT\n")
                    channel.stdin.flush()
                else:
                    channel.command("EXIT", "OK EXIT")
            if process.wait(timeout=10) != 0:
                raise RuntimeError(f"client {label} failed")
        expect_command(self.control, "QUIT", "OK QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read().decode() if self.process.stderr else ""
            raise RuntimeError(f"restoration compositor failed: {stderr}")
        return self.process.stderr.read().decode() if self.process.stderr else ""

    def abort(self) -> str:
        for _, process, channel in self.clients:
            if channel is not None:
                try:
                    channel.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
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


def wait_titles(control: Control, expected: set[str], label: str) -> dict[str, object]:
    return bounded_state(
        control,
        lambda state: {item["title"] for item in windows(state).values()} == expected
        and all(item["mapped"] for item in windows(state).values()),
        label,
    )


def prepare_clients(session: Session) -> dict[str, object]:
    control = session.control
    assert control is not None
    pointer(control, -300, 20, "left native placement")
    session.launch_native(NATIVE_VISIBLE, "org.wtwm.RestoreVisible")
    pointer(control, -280, 30, "left X11 placement")
    session.launch_x11(X11_VISIBLE)

    pointer(control, 20, 20, "right native family placement")
    session.launch_native(
        NATIVE_PARENT,
        "org.wtwm.RestoreParent",
        (NATIVE_CHILD, "org.wtwm.RestoreChild"),
    )
    pointer(control, 30, 30, "right native icon placement")
    session.launch_native(NATIVE_ICON, "org.wtwm.RestoreIcon")
    pointer(control, 40, 40, "right native zoom placement")
    session.launch_native(NATIVE_ZOOM, "org.wtwm.RestoreZoom")

    pointer(control, 50, 50, "right X11 family placement")
    session.launch_x11_family()
    pointer(control, 60, 60, "right X11 icon placement")
    session.launch_x11(X11_ICON)
    pointer(control, 70, 70, "right X11 zoom placement")
    session.launch_x11(X11_ZOOM)
    state = wait_titles(control, INITIAL_TITLES, "all restoration clients mapped")
    records = windows(state)
    for parent_title, child_title in (
        (NATIVE_PARENT, NATIVE_CHILD),
        (X11_PARENT, X11_CHILD),
    ):
        parent = by_title(state, parent_title)
        child = by_title(state, child_title)
        if child["parent_id"] != parent["id"]:
            raise RuntimeError(f"{child_title} lacks managed parent identity: {state!r}")
    if any(item["restoration_pending"] for item in records.values()):
        raise RuntimeError(f"initial client unexpectedly pending restoration: {state!r}")

    click_action(control, NATIVE_ICON, 1, "native iconify")
    bounded_state(
        control, lambda item: bool(by_title(item, NATIVE_ICON)["iconified"]),
        "native iconified",
    )
    click_action(control, X11_ICON, 1, "X11 iconify")
    bounded_state(
        control, lambda item: bool(by_title(item, X11_ICON)["iconified"]),
        "X11 iconified",
    )
    click_action(control, NATIVE_ZOOM, 2, "native fullzoom")
    bounded_state(
        control,
        lambda item: (
            by_title(item, NATIVE_ZOOM)["zoom"] == "full"
            and outer(by_title(item, NATIVE_ZOOM)) == Box(0, 0, 400, 300)
        ),
        "native zoomed",
    )
    click_action(control, X11_ZOOM, 2, "X11 fullzoom")
    bounded_state(
        control,
        lambda item: (
            by_title(item, X11_ZOOM)["zoom"] == "full"
            and outer(by_title(item, X11_ZOOM)) == Box(0, 0, 400, 300)
        ),
        "X11 zoomed",
    )
    click_action(control, NATIVE_VISIBLE, 3, "stable survivor focus")
    focused = bounded_state(
        control,
        lambda item: item["focus"] == NATIVE_VISIBLE and item["active"] == NATIVE_VISIBLE,
        "stable survivor focus",
    )
    pointer(control, -310, 230, "survivor root before mutation")
    focused = control.state()
    if focused["focus"] != NATIVE_VISIBLE or focused["active"] != NATIVE_VISIBLE:
        raise RuntimeError(f"root pointer changed explicit focus: {focused!r}")
    if set(icon_views(focused)) != {NATIVE_ICON, X11_ICON}:
        raise RuntimeError(f"icon presentations are incomplete: {focused!r}")
    return focused


def topology_transition(
    control: Control,
    before: dict[str, object],
    command: str,
    expected: str,
    label: str,
    *,
    active_after: bool = True,
) -> tuple[dict[str, object], set[int]]:
    expect_command(control, "TRACE CLEAR", "OK TRACE CLEAR")
    expect_command(control, command, expected)
    if active_after:
        expected_frames, _ = planned_frames(before, outputs(control.state()))

        def committed_geometry(state: dict[str, object]) -> bool:
            records = windows(state)
            return set(records) == set(expected_frames) and all(
                outer(records[identity]) == frame
                for identity, frame in expected_frames.items()
            )

        after = bounded_state(control, committed_geometry, label)
    else:
        after = control.state()
    changed = assert_transition(before, after, label)
    events = validate_trace(control.trace())
    restored = [
        event for event in events
        if event.get("event") == "restore" and event.get("context") == "topology"
    ]
    records = windows(after)
    for event in restored:
        identity = int(event["window"]["id"])
        if identity not in records:
            raise RuntimeError(f"{label}: restore TRACE has unknown identity: {event!r}")
        record = records[identity]
        frame = event["geometry"]["frame"]
        if not isinstance(frame, dict) or (
            int(frame["x"]),
            int(frame["y"]),
            int(frame["outer_width"]),
            int(frame["outer_height"]),
        ) != (
            int(record["x"]),
            int(record["y"]),
            int(record["outer_width"]),
            int(record["outer_height"]),
        ):
            raise RuntimeError(
                f"{label}: restore TRACE geometry differs from STATE: {event!r}"
            )
    restored_ids = {event["window"]["id"] for event in restored}
    if active_after and restored_ids != changed:
        raise RuntimeError(
            f"{label}: restore TRACE identities {restored_ids!r} != {changed!r}; "
            f"trace={events!r}"
        )
    return after, changed


def exercise(
    compositor: Path,
    config_tool: Path,
    wayland_client: Path,
    x11_client: Path,
    x11_family_client: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-output-restoration-") as directory:
        session = Session(
            Path(directory), compositor, config_tool,
            wayland_client, x11_client, x11_family_client,
        )
        control = session.control
        assert control is not None
        try:
            session.add_initial_outputs()
            state = prepare_clients(session)
            session.assert_protocols("initial")

            state, _ = topology_transition(
                control,
                state,
                "OUTPUT DISABLE HEADLESS-2",
                "OK OUTPUT DISABLE HEADLESS-2",
                "disable stranded right output",
            )
            session.assert_protocols("disable_right")
            before_failure = control.state()
            failure = raw_command(
                control, "OUTPUT MODE HEADLESS-2 800 600 60000"
            )
            if failure != "ERROR OUTPUT MODE requires enabled output: HEADLESS-2":
                raise RuntimeError(f"disabled MODE failure changed: {failure!r}")
            if control.state() != before_failure:
                raise RuntimeError("failed topology mutation changed restoration state")
            disabled_geometry = {
                identity: outer(item) for identity, item in windows(state).items()
            }

            state, changed = topology_transition(
                control,
                state,
                "OUTPUT ENABLE HEADLESS-2",
                "OK OUTPUT ENABLE HEADLESS-2",
                "enable right without repatriation",
            )
            if changed or disabled_geometry != {
                identity: outer(item) for identity, item in windows(state).items()
            }:
                raise RuntimeError("returning right output repatriated a visible family")

            state, _ = topology_transition(
                control,
                state,
                "OUTPUT DISABLE HEADLESS-1",
                "OK OUTPUT DISABLE HEADLESS-1",
                "repeated churn to right survivor",
            )
            session.assert_protocols("disable_left")
            state, changed = topology_transition(
                control,
                state,
                "OUTPUT ENABLE HEADLESS-1",
                "OK OUTPUT ENABLE HEADLESS-1",
                "enable left without repatriation",
            )
            if changed:
                raise RuntimeError("returning left output repatriated a visible family")

            state, changed = topology_transition(
                control,
                state,
                "OUTPUT DESTROY HEADLESS-2",
                "OK OUTPUT DESTROY HEADLESS-2",
                "destroy stranded owner with survivor",
            )
            if changed != set(windows(state)):
                raise RuntimeError(
                    "non-last owner destruction did not restore every family"
                )
            session.assert_protocols("destroy_owner")

            disabled_last, _ = topology_transition(
                control,
                state,
                "OUTPUT DISABLE HEADLESS-1",
                "OK OUTPUT DISABLE HEADLESS-1",
                "disable last output",
                active_after=False,
            )
            if outputs(disabled_last):
                raise RuntimeError("last output disable retained a spatial root")
            session.assert_protocols("disable_last")
            state, _ = topology_transition(
                control,
                disabled_last,
                "OUTPUT ENABLE HEADLESS-1",
                "OK OUTPUT ENABLE HEADLESS-1",
                "same-identity output resume",
            )
            session.assert_protocols("reenable_last")

            expect_command(control, "TRACE CLEAR", "OK TRACE CLEAR")
            before_zero = state
            expect_command(
                control,
                "OUTPUT DESTROY HEADLESS-1",
                "OK OUTPUT DESTROY HEADLESS-1",
            )
            zero = control.state()
            assert_transition(before_zero, zero, "destroy last output")
            validate_trace(control.trace())
            if outputs(zero):
                raise RuntimeError(f"last output destruction retained a root: {zero!r}")
            session.assert_protocols("zero_outputs")

            _, waiter = session.launch_waiter()
            pending = bounded_state(
                control,
                lambda item: any(
                    record["title"] == WAITER
                    and record["placement_pending"]
                    and not record["mapped"]
                    and not record["visible"]
                    for record in windows(item).values()
                ),
                "new map waits behind restoration",
                active_outputs=False,
            )
            existing = {
                identity: item for identity, item in windows(pending).items()
                if item["title"] != WAITER
            }
            if not all(item["restoration_pending"] for item in existing.values()):
                raise RuntimeError(f"existing zero-output families are not pending: {pending!r}")

            expect_command(control, "TRACE CLEAR", "OK TRACE CLEAR")
            expect_command(control, "OUTPUT 300 220", "OK OUTPUT HEADLESS-3 300 220")
            resumed = frame_barrier(control, "first returning output")
            waiter.expect(f"OK READY {WAITER}")
            resumed = bounded_state(
                control,
                lambda item: by_title(item, WAITER)["mapped"]
                and not by_title(item, WAITER)["placement_pending"],
                "waiting map resumed after restoration",
            )
            prior_without_waiter = dict(pending)
            prior_without_waiter["windows"] = [
                item for item in pending["windows"] if item["title"] != WAITER
            ]
            resumed_without_waiter = dict(resumed)
            resumed_without_waiter["windows"] = [
                item for item in resumed["windows"] if item["title"] != WAITER
            ]
            assert_transition(
                prior_without_waiter,
                resumed_without_waiter,
                "resume existing families before waiter",
                preserve_active=False,
                source_outputs=outputs(before_zero),
            )
            events = validate_trace(control.trace())
            restore_positions = [
                index for index, event in enumerate(events)
                if event.get("event") == "restore" and event.get("context") == "topology"
            ]
            waiter_maps = [
                index for index, event in enumerate(events)
                if event.get("event") == "map"
                and event.get("window", {}).get("title") == WAITER
            ]
            if (
                not restore_positions
                or len(waiter_maps) != 1
                or max(restore_positions) >= waiter_maps[0]
            ):
                raise RuntimeError(
                    f"existing restoration did not precede waiting map: {events!r}"
                )
            session.assert_protocols("resumed")

            expect_command(control, "OUTPUT 360 260", "OK OUTPUT HEADLESS-4 360 260")
            state = frame_barrier(control, "second returning output")
            before_destroy = state
            state, _ = topology_transition(
                control,
                before_destroy,
                "OUTPUT DESTROY HEADLESS-3",
                "OK OUTPUT DESTROY HEADLESS-3",
                "post-resume repeated destruction",
            )
            session.assert_protocols("repeated_destroy")
            session.finish()
        except Exception as error:
            stderr = session.abort()
            raise RuntimeError(
                f"output-restoration live session failed: {error}\n"
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
        description="exercise Milestone 8 output-disappearance window restoration"
    )
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--config-tool", type=Path)
    parser.add_argument("--wayland-client", type=Path)
    parser.add_argument("--x11-client", type=Path)
    parser.add_argument("--x11-family-client", type=Path)
    arguments = parser.parse_args()

    validate_model()
    if arguments.config_tool is not None:
        validate_generated_config(
            executable(parser, arguments.config_tool, "config-tool")
        )
    if arguments.self_test_model:
        print("Milestone 8 output-restoration model self-test passed")
        return 0
    if sys.platform != "linux":
        print("Milestone 8 output-restoration live integration requires Linux")
        return 77
    exercise(
        executable(parser, arguments.compositor, "compositor"),
        executable(parser, arguments.config_tool, "config-tool"),
        executable(parser, arguments.wayland_client, "wayland-client"),
        executable(parser, arguments.x11_client, "x11-client"),
        executable(parser, arguments.x11_family_client, "x11-family-client"),
    )
    print("Milestone 8 output-restoration live integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
