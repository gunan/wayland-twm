#!/usr/bin/env python3
"""Verify complete f.warptoscreen navigation and screen history."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from run_compositor import Control


BUTTON_CODES = {
    1: 272,
    2: 274,
    3: 273,
    4: 275,
    5: 276,
    6: 277,
    7: 278,
    8: 279,
    9: 280,
}
OUTPUTS = (
    ("HEADLESS-1", 300, 200),
    ("HEADLESS-2", 140, 90),
    ("HEADLESS-3", 360, 240),
)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int


@dataclass
class WarpHistory:
    current: int
    previous: int = -1

    def apply(self, argument: str, count: int) -> tuple[int, int]:
        target = screen_target(argument, self.current, self.previous, count)
        if target >= 0 and target != self.current:
            self.previous, self.current = self.current, target
        return self.current, self.previous

    def restart(self) -> tuple[int, int]:
        self.previous = -1
        return self.current, self.previous


def config_text() -> str:
    return (
        "NoDefaults\n"
        'Button1 = : root : f.warptoscreen "0"\n'
        'Button2 = : root : f.warptoscreen "1"\n'
        'Button3 = : root : f.warptoscreen "2"\n'
        'Button4 = : root : f.warptoscreen "next"\n'
        'Button5 = : root : f.warptoscreen "prev"\n'
        'Button6 = : root : f.warptoscreen "back"\n'
        "Button7 = : root : f.restart\n"
        'Button8 = : root : f.warptoscreen "9"\n'
        'Button9 = : root : f.warptoscreen "garbage"\n'
    )


def canonical_output_names(names: list[str]) -> list[str]:
    return sorted(names, key=lambda name: name.encode("utf-8"))


def screen_target(
    argument: str | None,
    current: int,
    previous: int,
    count: int,
) -> int:
    if argument is None or count <= 0 or current < 0 or current >= count:
        return -1
    if argument == "next":
        return (current + 1) % count
    if argument == "prev":
        return (current + count - 1) % count
    if argument == "back":
        return previous if 0 <= previous < count else current
    if re.fullmatch(r"[0-9]+", argument) is None:
        return -1
    target = int(argument, 10)
    return target if target <= 2_147_483_647 and target < count else -1


def translated_point(source: Box, target: Box, point: tuple[int, int]) -> tuple[int, int]:
    relative_x = point[0] - source.x
    relative_y = point[1] - source.y
    return (
        target.x + min(max(relative_x, 0), target.width - 1),
        target.y + min(max(relative_y, 0), target.height - 1),
    )


def assert_history_sequence(
    label: str,
    model: WarpHistory,
    count: int,
    sequence: list[tuple[str, tuple[int, int]]],
) -> None:
    for argument, expected in sequence:
        observed = model.apply(argument, count)
        if observed != expected:
            raise RuntimeError(
                f"{label} {argument!r}: expected history {expected!r}, "
                f"observed {observed!r}"
            )


def validate_model() -> None:
    if canonical_output_names(["HEADLESS-2", "HEADLESS-1"]) != [
        "HEADLESS-1",
        "HEADLESS-2",
    ]:
        raise RuntimeError("two-output canonical order followed announcement order")
    if canonical_output_names(
        ["HEADLESS-3", "HEADLESS-1", "HEADLESS-2"]
    ) != ["HEADLESS-1", "HEADLESS-2", "HEADLESS-3"]:
        raise RuntimeError("three-output canonical order is unstable")

    one = WarpHistory(0)
    assert_history_sequence(
        "one output",
        one,
        1,
        [
            ("0", (0, -1)),
            ("next", (0, -1)),
            ("prev", (0, -1)),
            ("back", (0, -1)),
            ("9", (0, -1)),
            ("garbage", (0, -1)),
        ],
    )

    two = WarpHistory(0)
    assert_history_sequence(
        "two outputs",
        two,
        2,
        [
            ("next", (1, 0)),
            ("back", (0, 1)),
            ("back", (1, 0)),
            ("prev", (0, 1)),
            ("0", (0, 1)),
            ("9", (0, 1)),
            ("garbage", (0, 1)),
            ("back", (1, 0)),
            ("back", (0, 1)),
        ],
    )

    three = WarpHistory(0)
    assert_history_sequence(
        "three outputs",
        three,
        3,
        [
            ("2", (2, 0)),
            ("prev", (1, 2)),
            ("back", (2, 1)),
            ("back", (1, 2)),
            ("next", (2, 1)),
            ("next", (0, 2)),
            ("prev", (2, 0)),
            ("1", (1, 2)),
            ("1", (1, 2)),
            ("9", (1, 2)),
            ("garbage", (1, 2)),
            ("back", (2, 1)),
            ("back", (1, 2)),
        ],
    )
    if three.restart() != (1, -1) or three.apply("back", 3) != (1, -1):
        raise RuntimeError("restart did not clear screen history")
    for invalid in (
        None,
        "",
        "-1",
        "+1",
        " 1",
        "1 ",
        "1x",
        "2147483648",
        "999999999999999999999999999999999",
    ):
        if screen_target(invalid, 1, 2, 3) != -1:
            raise RuntimeError(f"invalid screen target was accepted: {invalid!r}")

    first = Box(0, 0, 300, 200)
    second = Box(300, 0, 140, 90)
    third = Box(440, 0, 360, 240)
    if translated_point(first, second, (37, 29)) != (337, 29):
        raise RuntimeError("relative coordinate was not preserved")
    if translated_point(first, second, (250, 180)) != (439, 89):
        raise RuntimeError("smaller target did not clamp both coordinates")
    if translated_point(second, third, (439, 89)) != (579, 89):
        raise RuntimeError("target origin was not applied after clamping")
    if translated_point(third, first, (579, 89)) != (139, 89):
        raise RuntimeError("relative coordinate did not survive unequal origins")


def validate_generated_configs(config_tool: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-warp-config-") as directory:
        path = Path(directory) / "warp-screen.twmrc"
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
                "portable wtwm-config rejected warp-screen.twmrc: "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        if "bindings=9\n" not in result.stdout:
            raise RuntimeError(
                "portable wtwm-config did not retain all nine bindings: "
                f"{result.stdout!r}"
            )
        if "compatibility-warnings=1\n" not in result.stdout:
            raise RuntimeError(
                "malformed-action no-op projection was not explicit: "
                f"{result.stdout!r}"
            )


def nonspatial_state(state: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in state.items()
        if key not in {"frame", "cursor"}
    }


def cursor_point(state: dict[str, object]) -> tuple[float, float]:
    cursor = state.get("cursor")
    if not isinstance(cursor, dict):
        raise RuntimeError(f"STATE cursor schema changed: {state!r}")
    return float(cursor["x"]), float(cursor["y"])


def assert_cursor(
    state: dict[str, object],
    expected: tuple[int, int],
    label: str,
) -> None:
    observed = cursor_point(state)
    if observed != (float(expected[0]), float(expected[1])):
        raise RuntimeError(
            f"{label}: expected cursor {expected!r}, observed {observed!r}; "
            f"state={state!r}"
        )
    if state.get("pointer_context") != "root" or state.get("pointer_window") is not None:
        raise RuntimeError(f"{label}: warp did not settle on output root: {state!r}")


class Session:
    def __init__(
        self,
        root: Path,
        compositor: Path,
        config: Path,
    ) -> None:
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = root / "control.sock"
        self.process = subprocess.Popen(
            [
                str(compositor),
                "-f",
                str(config),
                "--test-control",
                str(control_path),
                "--test-socket",
                f"wtwm-m8-warp-{os.getpid()}",
                "--test-backend",
                "headless",
            ],
            env={
                **os.environ,
                "XDG_RUNTIME_DIR": str(runtime),
                "WLR_RENDERER": "pixman",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.control = Control(control_path, self.process)
        except Exception as error:
            if self.process.poll() is None:
                self.process.kill()
            _, stderr = self.process.communicate(timeout=10)
            raise RuntimeError(
                f"warp-screen compositor startup failed: {error}\n{stderr}"
            ) from error
        self.control.socket.settimeout(10)
        response = self.control.command("SET ANIMATION_MS 0")
        if response != "OK ANIMATION_MS 0":
            raise RuntimeError(f"unexpected animation response: {response!r}")

    def frame_barrier(self, label: str) -> dict[str, object]:
        before = self.control.state()
        response = self.control.command("WAIT 2")
        match = re.fullmatch(r"OK FRAME ([0-9]+)", response)
        if match is None:
            raise RuntimeError(f"{label}: invalid frame barrier response {response!r}")
        sequence = int(match.group(1))
        after = self.control.state()
        if sequence <= int(before["frame"]) or int(after["frame"]) != sequence:
            raise RuntimeError(
                f"{label}: inexact frame barrier before={before['frame']!r}, "
                f"response={response!r}, after={after['frame']!r}"
            )
        return after

    def add_output(self, index: int) -> None:
        name, width, height = OUTPUTS[index]
        response = self.control.command(f"OUTPUT {width} {height}")
        expected = f"OK OUTPUT {name} {width} {height}"
        if response != expected:
            raise RuntimeError(
                f"canonical output {index} response mismatch: "
                f"expected={expected!r}, observed={response!r}"
            )
        self.frame_barrier(f"output {name} readiness")

    def point(self, expected: tuple[int, int], label: str) -> dict[str, object]:
        response = self.control.command(f"POINTER {expected[0]} {expected[1]}")
        exact = f"OK CURSOR {expected[0]:.3f} {expected[1]:.3f}"
        if response != exact:
            raise RuntimeError(
                f"{label}: expected pointer acknowledgement {exact!r}, "
                f"observed {response!r}"
            )
        state = self.frame_barrier(f"{label} pointer")
        assert_cursor(state, expected, label)
        return state

    def action(
        self,
        button: int,
        expected: tuple[int, int],
        label: str,
        *,
        check_nonspatial: bool = True,
    ) -> dict[str, object]:
        raw = BUTTON_CODES[button]
        before = self.control.state()
        if before.get("pointer_context") != "root":
            raise RuntimeError(f"{label}: action did not start on a root: {before!r}")
        press = self.control.command(f"BUTTON {raw} press")
        release = self.control.command(f"BUTTON {raw} release")
        if press != f"OK BUTTON {raw} press" or release != f"OK BUTTON {raw} release":
            raise RuntimeError(
                f"{label}: input barrier mismatch: press={press!r}, "
                f"release={release!r}"
            )
        after = self.frame_barrier(f"{label} action")
        assert_cursor(after, expected, label)
        if check_nonspatial and nonspatial_state(after) != nonspatial_state(before):
            raise RuntimeError(
                f"{label}: warp changed non-spatial context: "
                f"before={nonspatial_state(before)!r}, "
                f"after={nonspatial_state(after)!r}"
            )
        return after

    def finish(self) -> str:
        response = self.control.command("QUIT")
        if response != "OK QUIT":
            raise RuntimeError(f"unexpected quit response: {response!r}")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"warp-screen compositor failed: {stderr}")
        return self.process.stderr.read() if self.process.stderr else ""

    def abort(self) -> str:
        try:
            self.control.close()
        except (OSError, ValueError):
            pass
        if self.process.poll() is None:
            self.process.kill()
        _, stderr = self.process.communicate(timeout=10)
        return stderr


def exercise_one_output(session: Session, first: Box) -> None:
    point = (first.x + 37, first.y + 29)
    session.point(point, "one-output starting point")
    for button, name in (
        (1, "same numeric target"),
        (4, "one-output next"),
        (5, "one-output prev"),
        (6, "one-output back"),
        (8, "one-output out-of-range numeric"),
        (9, "one-output malformed argument"),
    ):
        session.action(button, point, name)


def exercise_two_outputs(session: Session, first: Box, second: Box) -> None:
    local = (37, 29)
    first_point = (first.x + local[0], first.y + local[1])
    second_point = (second.x + local[0], second.y + local[1])
    session.point(first_point, "two-output starting point")
    for button, expected, name in (
        (4, second_point, "two-output next 0->1"),
        (6, first_point, "two-output back 1->0"),
        (6, second_point, "two-output repeated back 0->1"),
        (5, first_point, "two-output prev 1->0"),
        (1, first_point, "two-output same numeric target"),
        (8, first_point, "two-output out-of-range numeric"),
        (9, first_point, "two-output malformed argument"),
        (6, second_point, "two-output history survived rejected targets"),
        (6, first_point, "two-output repeated back toggle"),
    ):
        session.action(button, expected, name)

    large_local = (250, 180)
    large_point = (first.x + large_local[0], first.y + large_local[1])
    clamped = translated_point(first, second, large_point)
    session.point(large_point, "two-output large relative coordinate")
    session.action(2, clamped, "two-output smaller-target clamp")
    returned = translated_point(second, first, clamped)
    session.action(1, returned, "two-output relative-coordinate return")


def exercise_three_outputs(
    session: Session,
    first: Box,
    second: Box,
    third: Box,
) -> None:
    local = (50, 60)
    points = (
        (first.x + local[0], first.y + local[1]),
        (second.x + local[0], second.y + local[1]),
        (third.x + local[0], third.y + local[1]),
    )
    session.point(points[0], "three-output starting point")
    for button, expected, name in (
        (3, points[2], "three-output numeric 0->2"),
        (5, points[1], "three-output prev 2->1"),
        (6, points[2], "three-output back 1->2"),
        (6, points[1], "three-output repeated back 2->1"),
        (4, points[2], "three-output next 1->2"),
        (4, points[0], "three-output wrapped next 2->0"),
        (5, points[2], "three-output wrapped prev 0->2"),
        (2, points[1], "three-output numeric 2->1"),
        (2, points[1], "three-output same numeric target"),
        (8, points[1], "three-output out-of-range numeric"),
        (9, points[1], "three-output malformed argument"),
        (6, points[2], "three-output history survived rejected targets"),
        (6, points[1], "three-output repeated back toggle"),
    ):
        session.action(button, expected, name)

    large = (first.x + 250, first.y + 180)
    clamped_second = translated_point(first, second, large)
    on_third = translated_point(second, third, clamped_second)
    returned_first = translated_point(third, first, on_third)
    session.point(large, "three-output unequal-size starting point")
    session.action(
        2,
        clamped_second,
        "three-output target-specific clamp beside third output",
    )
    session.action(3, on_third, "three-output preserved clamped coordinate")
    session.action(1, returned_first, "three-output returned relative coordinate")

    session.action(
        7,
        returned_first,
        "restart preserves pointer and resets history",
        check_nonspatial=False,
    )
    session.action(6, returned_first, "back after restart is a no-op")


def run(compositor: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-warp-screen-") as directory:
        root = Path(directory)
        config = root / "warp-screen.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        session = Session(root, compositor, config)
        first = Box(0, 0, OUTPUTS[0][1], OUTPUTS[0][2])
        second = Box(first.width, 0, OUTPUTS[1][1], OUTPUTS[1][2])
        third = Box(first.width + second.width, 0, OUTPUTS[2][1], OUTPUTS[2][2])
        try:
            session.add_output(0)
            exercise_one_output(session, first)
            session.add_output(1)
            exercise_two_outputs(session, first, second)
            session.add_output(2)
            exercise_three_outputs(session, first, second, third)
            session.finish()
        except Exception as error:
            stderr = session.abort()
            raise RuntimeError(
                f"warp-screen live session failed: {error}\n"
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--config-tool", type=Path)
    args = parser.parse_args()

    validate_model()
    if args.config_tool is not None:
        validate_generated_configs(executable(parser, args.config_tool, "config-tool"))
    if args.self_test_model:
        print("Milestone 8 warp-to-screen history model self-test passed")
        return 0
    if sys.platform != "linux":
        print("Milestone 8 warp-to-screen live integration requires Linux")
        return 77
    compositor = executable(parser, args.compositor, "compositor")
    executable(parser, args.config_tool, "config-tool")
    run(compositor)
    print("Milestone 8 warp-to-screen history integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
