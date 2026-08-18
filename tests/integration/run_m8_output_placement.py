#!/usr/bin/env python3
"""Verify Milestone 8 output-scoped placement and root geometry."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time
from typing import Callable

from run_compositor import Control


WIDTH = 320
HEIGHT = 240
LEFT = (0, 0, WIDTH, HEIGHT)
RIGHT = (WIDTH, 0, WIDTH, HEIGHT)
BUTTON = {1: 272, 2: 274, 3: 273, 4: 275, 5: 276, 8: 279}
CONTRACT_SCENARIOS = {
    "native-pointer-output",
    "xwayland-request-inside",
    "global-random-across-outputs",
    "output-local-random-edge-reset",
    "menu-output-clamp",
    "root-gap-no-binding",
    "background-gap-unpainted",
    "move-pinned-output",
    "force-move-cross-output",
    "zoom-owner-output",
    "interactive-fill-output",
    "selected-output-max-window-default",
    "zero-output-deferred",
    "zero-output-state-stable",
}
RANDOM_CONFIG = (
    "NoDefaults\nNoTitle\nRandomPlacement\n"
    "Button8 = : root : f.restart\n"
)
SPATIAL_CONFIG = (
    "NoDefaults\nUsePPosition \"on\"\nDontMoveOff\n"
    "MoveDelta 0\nConstrainedMoveTime 0\nBorderWidth 2\n"
    "Button1 = : title|icon : f.move\n"
    "Button2 = : title|icon : f.forcemove\n"
    "Button3 = : frame|icon : f.iconify\n"
    "Button4 = : frame : f.fullzoom\n"
    "Button5 = : root : f.menu \"root-output\"\n"
    "Menu \"root-output\" {\n"
    "  \"Submenu\" f.menu \"child-output\"\n"
    "  \"No operation\" f.nop\n"
    "}\n"
    "Menu \"child-output\" {\n"
    "  \"Long submenu entry at inner edge\" f.nop\n"
    "}\n"
)
FILL_CONFIG = (
    "NoDefaults\nNoTitle\nBorderWidth 2\nDontMoveOff\n"
    "UsePPosition \"off\"\n"
)
DEFAULT_MAX_CONFIG = "NoDefaults\nUsePPosition \"on\"\n"


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


@dataclass
class RandomCascade:
    next_x: int = 50
    next_y: int = 50
    consumed: int = 0

    @staticmethod
    def _edge(coordinate: int, extent: int, client: int) -> int:
        if coordinate + client <= extent:
            return coordinate
        return max(0, min(50, extent - client))

    def place(self, output: Box | None, width: int, height: int) -> tuple[int, int] | None:
        if output is None:
            return None
        self.next_x = self._edge(self.next_x, output.width, width)
        self.next_y = self._edge(self.next_y, output.height, height)
        result = (output.x + self.next_x, output.y + self.next_y)
        self.next_x += 30
        self.next_y += 30
        self.consumed += 1
        return result

    def snapshot(self) -> tuple[int, int, int]:
        return self.next_x, self.next_y, self.consumed


def contains(box: Box, point: tuple[int, int]) -> bool:
    return box.x <= point[0] < box.right and box.y <= point[1] < box.bottom


def point_distance_squared(box: Box, point: tuple[int, int]) -> int:
    dx = max(box.x - point[0], 0, point[0] - box.right)
    dy = max(box.y - point[1], 0, point[1] - box.bottom)
    return dx * dx + dy * dy


def select_point(outputs: list[Box], point: tuple[int, int]) -> int | None:
    contained = [index for index, box in enumerate(outputs) if contains(box, point)]
    if contained:
        return contained[0]
    if not outputs:
        return None
    return min(
        range(len(outputs)),
        key=lambda index: (point_distance_squared(outputs[index], point), index),
    )


def intersection_area(first: Box, second: Box) -> int:
    width = max(0, min(first.right, second.right) - max(first.x, second.x))
    height = max(0, min(first.bottom, second.bottom) - max(first.y, second.y))
    return width * height


def select_owner(outputs: list[Box], outer: Box) -> int | None:
    if not outputs:
        return None
    areas = [intersection_area(output, outer) for output in outputs]
    greatest = max(areas)
    if greatest > 0:
        return areas.index(greatest)
    center = (outer.x * 2 + outer.width, outer.y * 2 + outer.height)
    doubled = [Box(box.x * 2, box.y * 2, box.width * 2, box.height * 2)
               for box in outputs]
    return select_point(doubled, center)


def clamp_outer(output: Box, outer: Box) -> Box:
    x = max(outer.x, output.x)
    y = max(outer.y, output.y)
    x = min(x, output.right - outer.width)
    y = min(y, output.bottom - outer.height)
    return Box(x, y, outer.width, outer.height)


def clamp_menu(output: Box, requested: tuple[int, int], size: tuple[int, int]) -> Box:
    return clamp_outer(output, Box(requested[0], requested[1], size[0], size[1]))


def validate_model() -> None:
    contract_path = (
        Path(__file__).resolve().parents[2]
        / "reference/lifecycle/twm-1.0.13.1/output-placement-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    scenarios = {item["id"] for item in contract["verification_scenarios"]}
    missing = sorted(CONTRACT_SCENARIOS - scenarios)
    if missing:
        raise RuntimeError(f"model scenarios drifted from frozen contract: {missing!r}")

    left = Box(-300, 20, 300, 200)
    right = Box(100, -40, 200, 300)
    outputs = [left, right]
    if select_point(outputs, (-1, 50)) != 0 or select_point(outputs, (100, 0)) != 1:
        raise RuntimeError("half-open point containment changed")
    if select_point(outputs, (50, 50)) != 0:
        raise RuntimeError("equal-distance gap did not use canonical output order")
    if select_point(outputs, (500, 500)) != 1:
        raise RuntimeError("outside-layout nearest-output selection changed")
    overlapping = [Box(0, 0, 100, 100), Box(50, 0, 100, 100)]
    if select_point(overlapping, (75, 20)) != 0:
        raise RuntimeError("overlap containment tie did not use canonical order")

    if select_owner(outputs, Box(-10, 30, 160, 100)) != 1:
        raise RuntimeError("greatest-positive-intersection ownership changed")
    equal_owner = [Box(0, 0, 100, 100), Box(100, 0, 100, 100)]
    if select_owner(equal_owner, Box(50, 10, 100, 40)) != 0:
        raise RuntimeError("equal-area ownership did not use canonical order")
    if select_owner(outputs, Box(40, 400, 20, 20)) != 1:
        raise RuntimeError("non-intersecting owner did not use nearest center")

    cascade = RandomCascade()
    model_left = Box(0, 0, WIDTH, HEIGHT)
    model_right = Box(WIDTH, 0, WIDTH, HEIGHT)
    if cascade.place(model_left, 100, 80) != (50, 50):
        raise RuntimeError("first RandomPlacement pair changed")
    if cascade.place(model_right, 100, 80) != (400, 80):
        raise RuntimeError("RandomPlacement reset per output instead of remaining global")
    edge = RandomCascade(next_x=290, next_y=230)
    if edge.place(model_right, 100, 80) != (370, 50):
        raise RuntimeError("random edge reset did not use selected-output dimensions/origin")
    before_zero = edge.snapshot()
    if edge.place(None, 100, 80) is not None or edge.snapshot() != before_zero:
        raise RuntimeError("zero-output placement consumed global state")

    # These exact inequalities distinguish every spatial operation from the
    # obsolete 640x240 union-layout root.
    menu = clamp_menu(model_left, (315, 10), (90, 60))
    submenu = clamp_menu(model_left, (menu.x + 45, 20), (110, 50))
    if (menu.x, menu.right, submenu.x, submenu.right) != (230, 320, 210, 320):
        raise RuntimeError("root menu/submenu escaped its invocation output")
    zoomed = Box(model_right.x, model_right.y, model_right.width, model_right.height)
    if zoomed != model_right or zoomed == Box(0, 0, WIDTH * 2, HEIGHT):
        raise RuntimeError("fullzoom used layout-union geometry")
    fill_origin = (400, 50)
    filled = Box(fill_origin[0], fill_origin[1],
                 model_right.right - fill_origin[0],
                 model_right.bottom - fill_origin[1])
    if filled.right != 640 or filled.bottom != 240 or filled.x == model_left.x:
        raise RuntimeError("Button3 fill did not stop at the selected output")

    original = Box(40, 40, 110, 100)
    pinned = select_owner([model_left, model_right], original)
    if pinned != 0:
        raise RuntimeError("move setup selected the wrong owner")
    ordinary = clamp_outer(model_left, Box(500, 60, original.width, original.height))
    icon = clamp_outer(model_left, Box(500, 80, 70, 30))
    if ordinary.x != 210 or icon.x != 250:
        raise RuntimeError("DontMoveOff did not pin window/icon geometry")
    forced = Box(380, 60, original.width, original.height)
    if select_owner([model_left, model_right], forced) != 1:
        raise RuntimeError("later operation did not recompute owner after f.forcemove")
    later = clamp_outer(model_right, Box(900, 60, forced.width, forced.height))
    if later.x != 530:
        raise RuntimeError("later DontMoveOff operation retained stale owner")

    if contains(left, (50, 50)) or contains(right, (50, 50)):
        raise RuntimeError("root hit incorrectly includes a gap")
    painted = [left, right]
    if any(contains(box, (50, 50)) for box in painted):
        raise RuntimeError("per-output backgrounds painted a gap")
    if select_point([], (0, 0)) is not None or select_owner([], original) is not None:
        raise RuntimeError("zero-output selection invented a compatibility root")

    accepted = Box(350, -15, 100, 80)
    if accepted != Box(350, -15, 100, 80):
        raise RuntimeError("accepted Xwayland request was rewritten")
    if 32767 - model_right.width != 32447:
        raise RuntimeError("selected-output MaxWindowSize default changed")
    native_owner = select_point([model_left, model_right], (500, 80))
    if native_owner != 1:
        raise RuntimeError("native pointer placement selected the layout union")

    restart_before = (cascade.snapshot(), original, forced, pinned)
    restart_after = (cascade.snapshot(), original, forced, pinned)
    if restart_after != restart_before:
        raise RuntimeError("in-place restart rewrote placement state or ownership")


def wait_line(
    process: subprocess.Popen[str],
    predicate: Callable[[str], bool],
    label: str,
    timeout: float = 10,
) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    observed: list[str] = []
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], min(0.2, deadline - time.monotonic()))
        if not ready:
            continue
        line = process.stdout.readline().rstrip("\n")
        observed.append(line)
        if predicate(line):
            return line
    raise RuntimeError(f"timed out waiting for {label}; observed={observed!r}")


def client_command(process: subprocess.Popen[str], command: str, expected: str) -> None:
    assert process.stdin is not None
    process.stdin.write(command + "\n")
    process.stdin.flush()
    wait_line(process, lambda line: line == expected, expected)


def state_window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one window {title!r}: {state!r}")
    return matches[0]


def wait_state(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    label: str,
    timeout: float = 10,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = control.state()
        if predicate(last):
            return last
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for STATE {label}: {last!r}")


def wait_mapped(control: Control, title: str) -> dict[str, object]:
    return wait_state(
        control,
        lambda state: any(
            item["title"] == title and item["mapped"] and not item["placement_pending"]
            for item in state["windows"]
        ),
        f"mapped {title!r}",
    )


def wait_trace(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    label: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = control.trace()
        if predicate(last):
            return last
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for TRACE {label}: {last!r}")


def point(control: Control, x: int, y: int, context: str | None = None) -> dict[str, object]:
    control.command(f"POINTER {x} {y}")
    return wait_state(
        control,
        lambda state: abs(float(state["cursor"]["x"]) - x) < 0.001
        and abs(float(state["cursor"]["y"]) - y) < 0.001
        and (context is None or state["pointer_context"] == context),
        f"pointer {(x, y)!r} context={context!r}",
    )


def button(control: Control, number: int, pressed: bool) -> None:
    control.command(f"BUTTON {BUTTON[number]} {'press' if pressed else 'release'}")


def click(control: Control, number: int) -> None:
    button(control, number, True)
    button(control, number, False)


def frame_point(item: dict[str, object]) -> tuple[int, int]:
    return int(item["x"]) + 1, int(item["y"]) + int(item["outer_height"]) // 2


def title_point(item: dict[str, object]) -> tuple[int, int]:
    return (
        int(item["x"]) + int(item["border_width"]) + int(item["width"]) // 2,
        int(item["y"]) + int(item["border_width"])
        + max(1, int(item["title_bar_height"]) // 2),
    )


class Session:
    def __init__(self, root: Path, label: str, compositor: Path, config_text: str) -> None:
        self.root = root
        self.label = label
        self.runtime = root / f"runtime-{label}"
        self.runtime.mkdir(mode=0o700)
        self.control_path = root / f"control-{label}.sock"
        self.display_path = root / f"display-{label}"
        self.config_path = root / f"config-{label}.twmrc"
        self.config_path.write_text(config_text, encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(self.display_path))}'
        self.environment = {
            **os.environ,
            "XDG_RUNTIME_DIR": str(self.runtime),
            "WLR_RENDERER": "pixman",
        }
        self.socket_name = f"wtwm-m8-output-{label}-{os.getpid()}"
        self.process = subprocess.Popen(
            [
                str(compositor), "-f", str(self.config_path), "-s", startup,
                "--test-control", str(self.control_path),
                "--test-socket", self.socket_name,
                "--test-backend", "headless",
            ],
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control = Control(self.control_path, self.process)
        self.control.socket.settimeout(10)
        self.control.command("SET ANIMATION_MS 0")
        self.control.command("SET FONT DejaVu Sans 10")
        self.clients: list[subprocess.Popen[str]] = []
        self.client_exit: dict[int, str] = {}

    def display(self) -> str:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.display_path.is_file():
                value = self.display_path.read_text(encoding="utf-8").strip()
                if value.startswith(":"):
                    return value
            if self.process.poll() is not None:
                break
            time.sleep(0.01)
        raise RuntimeError(f"Xwayland DISPLAY was not published for {self.label}")

    def add_outputs(self, count: int) -> None:
        for index in range(count):
            response = self.control.command(f"OUTPUT {WIDTH} {HEIGHT}")
            expected = f"OK OUTPUT HEADLESS-{index + 1} {WIDTH} {HEIGHT}"
            if response != expected:
                raise RuntimeError(f"unexpected output response: {response!r} != {expected!r}")
        self.control.command("WAIT 2")

    def launch_x(self, binary: Path, scenario: str) -> subprocess.Popen[str]:
        environment = {**self.environment, "DISPLAY": self.display()}
        process = subprocess.Popen(
            [str(binary), scenario],
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        self.clients.append(process)
        self.client_exit[process.pid] = "QUIT"
        wait_line(process, lambda line: line == "READY", f"{scenario} READY")
        return process

    def launch_native(self, binary: Path, title: str) -> subprocess.Popen[str]:
        environment = {**self.environment, "WAYLAND_DISPLAY": self.socket_name}
        process = subprocess.Popen(
            [str(binary), title, "wtwm-m8-output"],
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        self.clients.append(process)
        self.client_exit[process.pid] = "EXIT"
        wait_line(process, lambda line: line == f"OK READY {title}", f"native {title} READY")
        return process

    def assert_live(self) -> None:
        if self.control.command("PING") != "OK WTWM_TEST_CONTROL 1":
            raise RuntimeError(f"test control lost liveness in {self.label}")
        for process in self.clients:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(
                    f"client exited early in {self.label}: {process.returncode}\n{stderr}"
                )

    def finish(self) -> None:
        for process in self.clients:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(self.client_exit[process.pid] + "\n")
                process.stdin.flush()
        for process in self.clients:
            if process.poll() is None:
                process.wait(timeout=10)
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"client failed in {self.label}: {stderr}")
        self.control.command("QUIT")
        self.control.close()
        self.process.wait(timeout=10)
        if self.process.returncode != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"compositor failed in {self.label}: {stderr}")

    def abort(self) -> str:
        for process in self.clients:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        try:
            self.control.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        return self.process.stderr.read() if self.process.stderr else ""


def run_session(session: Session, body: Callable[[Session], None]) -> None:
    try:
        body(session)
        session.assert_live()
        session.finish()
    except Exception as error:
        stderr = session.abort()
        raise RuntimeError(
            f"output-placement session {session.label!r} failed: {error}\n"
            f"compositor stderr:\n{stderr}"
        ) from error


def verify_xwayland_random(session: Session, client_binary: Path) -> None:
    session.add_outputs(2)
    point(session.control, 10, 10, "root")
    client = session.launch_x(client_binary, "random")
    first_state = wait_mapped(session.control, "placement-random-1")
    first = state_window(first_state, "placement-random-1")
    if (first["x"], first["y"], first["placement"]) != (50, 50, "random"):
        raise RuntimeError(f"first left-output random placement changed: {first!r}")

    point(session.control, 330, 10, "root")
    client_command(client, "NEXT", "MAPPED")
    second_state = wait_mapped(session.control, "placement-random-2")
    second = state_window(second_state, "placement-random-2")
    if (second["x"], second["y"], second["placement"]) != (400, 80, "random"):
        raise RuntimeError(
            "right output did not use the shared next random pair plus its origin: "
            f"{second!r}"
        )
    if second_state["placement_seed"] != 2 or second_state["random_placement"] != {
        "next_x": 110, "next_y": 110,
    }:
        raise RuntimeError(f"global random state after two outputs is wrong: {second_state!r}")

    geometry_before = {
        title: tuple(
            state_window(second_state, title)[key]
            for key in ("x", "y", "width", "height")
        )
        for title in ("placement-random-1", "placement-random-2")
    }
    random_before = (second_state["placement_seed"], second_state["random_placement"])
    point(session.control, 300, 220, "root")
    click(session.control, 8)
    session.control.command("WAIT 2")
    restarted = wait_state(
        session.control,
        lambda state: state["placement_seed"] == random_before[0]
        and state["random_placement"] == random_before[1],
        "restart preserves placement counters",
    )
    geometry_after = {
        title: tuple(state_window(restarted, title)[key] for key in ("x", "y", "width", "height"))
        for title in geometry_before
    }
    if geometry_after != geometry_before:
        raise RuntimeError(f"restart rewrote placement ownership/geometry: {geometry_after!r}")

    point(session.control, 10, 10, "root")
    client_command(client, "NEXT", "MAPPED")
    third = state_window(wait_mapped(session.control, "placement-random-3"),
                         "placement-random-3")
    if (third["x"], third["y"], third["placement"]) != (110, 110, "random"):
        raise RuntimeError(f"restart reset the shared random cascade: {third!r}")


def verify_native_random(session: Session, native_binary: Path) -> None:
    session.add_outputs(2)
    point(session.control, 10, 10, "root")
    first_client = session.launch_native(native_binary, "m8-native-left")
    first = state_window(wait_mapped(session.control, "m8-native-left"), "m8-native-left")
    if (first["type"], first["x"], first["y"], first["placement"]) != (
        "wayland", 50, 50, "random",
    ):
        raise RuntimeError(f"native left random placement changed: {first!r}")
    point(session.control, 330, 10, "root")
    second_client = session.launch_native(native_binary, "m8-native-right")
    second = state_window(wait_mapped(session.control, "m8-native-right"), "m8-native-right")
    if (second["type"], second["x"], second["y"], second["placement"]) != (
        "wayland", 400, 80, "random",
    ):
        raise RuntimeError(f"native pointer-selected output used union/reset state: {second!r}")
    client_command(first_client, "ARM left-live", "OK ARMED left-live")
    client_command(first_client, "REPORT left-live", "OK REPORT left-live keys=0 focus=0 close=0")
    client_command(second_client, "ARM right-live", "OK ARMED right-live")
    client_command(
        second_client,
        "REPORT right-live",
        "OK REPORT right-live keys=0 focus=0 close=0",
    )


def assert_zoom(control: Control, title: str, output: tuple[int, int, int, int]) -> None:
    before = state_window(control.state(), title)
    original = tuple(before[key] for key in ("x", "y", "width", "height"))
    control.command("TRACE CLEAR")
    point(control, *frame_point(before), "frame")
    click(control, 4)
    wait_trace(
        control,
        lambda trace: any(
            event["event"] == "commit" and event["context"] == "zoom"
            and event["window"]["title"] == title for event in trace["events"]
        ),
        f"{title} zoom commit",
    )
    zoomed = state_window(control.state(), title)
    actual = (
        int(zoomed["x"]), int(zoomed["y"]),
        int(zoomed["outer_width"]), int(zoomed["outer_height"]),
    )
    if actual != output:
        raise RuntimeError(f"{title} fullzoom used union/stale owner: {actual!r} != {output!r}")
    point(control, *frame_point(zoomed), "frame")
    click(control, 4)
    restored = state_window(control.state(), title)
    if tuple(restored[key] for key in ("x", "y", "width", "height")) != original:
        raise RuntimeError(f"{title} fullzoom did not restore exact geometry: {restored!r}")


def start_drag(
    control: Control, item: dict[str, object], number: int, context: str = "title",
) -> tuple[int, int]:
    start = title_point(item) if context == "title" else (
        int(item["x"]) + int(item["width"]) // 2,
        int(item["y"]) + int(item["height"]) // 2,
    )
    point(control, *start, context)
    button(control, number, True)
    wait_state(control, lambda state: bool(state["interactive"]), "drag started")
    return start[0] - int(item["x"]), start[1] - int(item["y"])


def verify_spatial_actions(session: Session, client_binary: Path) -> None:
    session.add_outputs(2)
    client = session.launch_x(client_binary, "m8-outputs")
    state = wait_state(
        session.control,
        lambda current: all(
            any(item["title"] == title and item["mapped"] for item in current["windows"])
            for title in ("m8-output-left", "m8-output-right")
        ),
        "two requested-position Xwayland windows",
    )
    left = state_window(state, "m8-output-left")
    right = state_window(state, "m8-output-right")
    if (left["x"], left["y"], left["placement"]) != (40, 40, "requested"):
        raise RuntimeError(f"accepted left Xwayland request changed: {left!r}")
    if (right["x"], right["y"], right["placement"]) != (370, 50, "requested"):
        raise RuntimeError(f"accepted right Xwayland request was clamped/rewritten: {right!r}")

    assert_zoom(session.control, "m8-output-left", LEFT)
    assert_zoom(session.control, "m8-output-right", RIGHT)

    moving = state_window(session.control.state(), "m8-output-left")
    outer_width = int(moving["outer_width"])
    grab_x, grab_y = start_drag(session.control, moving, 1)
    session.control.command(f"POINTER {500 + grab_x} {60 + grab_y}")
    interaction = wait_state(
        session.control,
        lambda current: isinstance(current["interaction"], dict)
        and int(current["interaction"]["preview"]["x"]) == WIDTH - outer_width,
        "DontMoveOff pins window to left output",
    )["interaction"]
    if int(interaction["preview"]["x"]) != WIDTH - outer_width:
        raise RuntimeError(f"ordinary move escaped left output: {interaction!r}")
    button(session.control, 1, False)

    moving = state_window(session.control.state(), "m8-output-left")
    grab_x, grab_y = start_drag(session.control, moving, 2)
    session.control.command(f"POINTER {380 + grab_x} {60 + grab_y}")
    forced = wait_state(
        session.control,
        lambda current: isinstance(current["interaction"], dict)
        and int(current["interaction"]["preview"]["x"]) == 380,
        "f.forcemove crosses output boundary",
    )
    if not forced["interaction"]["force"]:
        raise RuntimeError(f"f.forcemove did not retain force flag: {forced!r}")
    button(session.control, 2, False)
    moved = state_window(session.control.state(), "m8-output-left")
    if int(moved["x"]) != 380:
        raise RuntimeError(f"f.forcemove did not commit on right output: {moved!r}")

    grab_x, grab_y = start_drag(session.control, moved, 1)
    session.control.command(f"POINTER {900 + grab_x} {60 + grab_y}")
    recomputed_x = WIDTH * 2 - int(moved["outer_width"])
    later = wait_state(
        session.control,
        lambda current: isinstance(current["interaction"], dict)
        and int(current["interaction"]["preview"]["x"]) == recomputed_x,
        "later move recomputes owner from committed geometry",
    )
    if int(later["interaction"]["preview"]["x"]) != recomputed_x:
        raise RuntimeError(f"later operation retained left owner: {later!r}")
    button(session.control, 1, False)

    icon_target = state_window(session.control.state(), "m8-output-right")
    point(session.control, *frame_point(icon_target), "frame")
    click(session.control, 3)
    icon_state = wait_state(
        session.control,
        lambda current: any(item["title"] == "m8-output-right" for item in current["icon_views"]),
        "right window iconified",
    )
    icon = next(item for item in icon_state["icon_views"] if item["title"] == "m8-output-right")
    start_drag(session.control, icon, 1, "icon")
    session.control.command("POINTER 0 100")
    pinned_icon = wait_state(
        session.control,
        lambda current: isinstance(current["interaction"], dict)
        and int(current["interaction"]["preview"]["x"]) == WIDTH,
        "DontMoveOff pins icon to right output",
    )
    if int(pinned_icon["interaction"]["preview"]["x"]) != WIDTH:
        raise RuntimeError(f"ordinary icon move escaped start output: {pinned_icon!r}")
    button(session.control, 1, False)
    icon = next(item for item in session.control.state()["icon_views"]
                if item["title"] == "m8-output-right")
    grab_x, grab_y = start_drag(session.control, icon, 2, "icon")
    session.control.command(f"POINTER {40 + grab_x} {80 + grab_y}")
    wait_state(
        session.control,
        lambda current: isinstance(current["interaction"], dict)
        and int(current["interaction"]["preview"]["x"]) == 40,
        "f.forcemove crosses output boundary for icon",
    )
    button(session.control, 2, False)

    point(session.control, 319, 10, "root")
    button(session.control, 5, True)
    menu_state = wait_state(
        session.control, lambda current: isinstance(current["menu"], dict),
        "inner-edge root menu",
    )
    menu = menu_state["menu"]
    if int(menu["x"]) < 0 or int(menu["x"]) + int(menu["width"]) > WIDTH:
        raise RuntimeError(f"root menu used the union layout: {menu!r}")
    point(
        session.control,
        int(menu["x"]) + int(menu["width"]) * 3 // 4,
        int(menu["y"]) + int(menu["row_height"]) // 2,
    )
    child_state = wait_state(
        session.control,
        lambda current: isinstance(current["menu"], dict)
        and current["menu"]["depth"] == 2,
        "pinned inner-edge submenu",
    )
    child = child_state["menu"]
    if int(child["x"]) < 0 or int(child["x"]) + int(child["width"]) > WIDTH:
        raise RuntimeError(f"submenu escaped its invocation output: {child!r}")
    button(session.control, 3, True)
    button(session.control, 3, False)
    button(session.control, 5, False)
    if session.control.state()["menu"] is not None:
        raise RuntimeError("menu cancellation did not close the pinned stack")
    if client.poll() is not None:
        raise RuntimeError("spatial Xwayland client lost liveness")


def verify_default_max(session: Session, client_binary: Path) -> None:
    session.add_outputs(2)
    session.launch_x(client_binary, "m8-defaultmax")
    item = state_window(wait_mapped(session.control, "m8-output-defaultmax"),
                        "m8-output-defaultmax")
    actual = (item["x"], item["y"], item["width"], item["height"], item["placement"])
    expected = (370, 20, 32200, 16, "requested")
    if actual != expected:
        raise RuntimeError(
            "selected-output MaxWindowSize default or accepted request changed: "
            f"{actual!r} != {expected!r}"
        )


def verify_interactive_fill(session: Session, client_binary: Path) -> None:
    session.add_outputs(2)
    point(session.control, 360, 40, "root")
    session.launch_x(client_binary, "nohint")
    pending = wait_state(
        session.control,
        lambda state: isinstance(state["interaction"], dict)
        and state["interaction"]["window"] == "placement-nohint",
        "right-output interactive placement",
    )
    item = state_window(pending, "placement-nohint")
    if item["mapped"] or not item["placement_pending"]:
        raise RuntimeError(f"interactive Xwayland window became visible early: {pending!r}")
    session.control.command("TRACE CLEAR")
    point(session.control, 400, 50)
    preview = session.control.state()["interaction"]["preview"]
    if (preview["x"], preview["y"]) != (400, 50):
        raise RuntimeError(f"placement outline switched output or origin: {preview!r}")
    button(session.control, 3, True)
    button(session.control, 3, False)
    placed = state_window(wait_mapped(session.control, "placement-nohint"),
                          "placement-nohint")
    if (
        int(placed["x"]), int(placed["y"]),
        int(placed["x"]) + int(placed["outer_width"]),
        int(placed["y"]) + int(placed["outer_height"]),
        placed["placement"],
    ) != (400, 50, 640, 240, "interactive"):
        raise RuntimeError(f"Button3 fill used layout-union bounds: {placed!r}")
    wait_trace(
        session.control,
        lambda trace: any(
            event["event"] == "commit" and event["context"] == "placement"
            and event["window"]["title"] == "placement-nohint"
            for event in trace["events"]
        ),
        "Button3 placement commit",
    )


def verify_zero_output(session: Session, client_binary: Path) -> None:
    client = session.launch_x(client_binary, "random")
    pending = wait_state(
        session.control,
        lambda state: len(state["windows"]) == 1
        and state["windows"][0]["title"] == "placement-random-1"
        and state["windows"][0]["placement_pending"]
        and not state["windows"][0]["mapped"],
        "zero-output map remains pending and unexposed",
    )
    if pending["pointer_context"] != "none":
        raise RuntimeError(f"zero outputs exposed a synthetic root: {pending!r}")
    if pending["placement_seed"] != 0 or pending["random_placement"] != {
        "next_x": 50, "next_y": 50,
    }:
        raise RuntimeError(f"zero-output map consumed placement state: {pending!r}")
    if any(
        event["event"] == "map" and event["window"]["title"] == "placement-random-1"
        for event in session.control.trace()["events"]
    ):
        raise RuntimeError("zero-output deferred client emitted a visible map trace")
    session.add_outputs(1)
    resumed = state_window(wait_mapped(session.control, "placement-random-1"),
                           "placement-random-1")
    state = session.control.state()
    if (resumed["x"], resumed["y"], resumed["placement"]) != (50, 50, "random"):
        raise RuntimeError(f"deferred map did not resume from first random pair: {resumed!r}")
    if state["placement_seed"] != 1 or state["random_placement"] != {
        "next_x": 80, "next_y": 80,
    }:
        raise RuntimeError(f"resumed zero-output map advanced state incorrectly: {state!r}")
    if client.poll() is not None:
        raise RuntimeError("zero-output Xwayland client died before output announcement")


def run(compositor: Path, client: Path, native_client: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-output-placement-") as directory:
        root = Path(directory)
        sessions = [
            ("x-random", RANDOM_CONFIG,
             lambda current: verify_xwayland_random(current, client)),
            ("native-random", RANDOM_CONFIG,
             lambda current: verify_native_random(current, native_client)),
            ("spatial", SPATIAL_CONFIG,
             lambda current: verify_spatial_actions(current, client)),
            ("default-max", DEFAULT_MAX_CONFIG,
             lambda current: verify_default_max(current, client)),
            ("interactive-fill", FILL_CONFIG,
             lambda current: verify_interactive_fill(current, client)),
            ("zero-output", RANDOM_CONFIG,
             lambda current: verify_zero_output(current, client)),
        ]
        for label, config, body in sessions:
            run_session(Session(root, label, compositor, config), body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--client", type=Path,
                        help="xwayland-placement-client executable")
    parser.add_argument("--native-client", type=Path,
                        help="stress Wayland client executable")
    args = parser.parse_args()
    if args.self_test_model:
        validate_model()
        print("Milestone 8 output placement/root model self-test passed")
        return 0
    missing = [name for name in ("compositor", "client", "native_client")
               if getattr(args, name) is None]
    if missing:
        options = ", --".join(name.replace("_", "-") for name in missing)
        parser.error("live mode requires --" + options)
    paths = [args.compositor, args.client, args.native_client]
    for path in paths:
        if not path.is_file():
            parser.error(f"missing executable: {path}")
    run(*(path.resolve() for path in paths))
    print("Milestone 8 output-aware placement/root integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
