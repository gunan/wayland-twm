#!/usr/bin/env python3
"""Exercise native Wayland and managed X11 clients in one wtwm session."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


EXPECTED = {
    "native-a": {
        "title": "wtwm-mixed-native-a",
        "type": "wayland",
        "app_id": "org.wtwm.MixedNativeA",
    },
    "native-b": {
        "title": "wtwm-mixed-native-b",
        "type": "wayland",
        "app_id": "org.wtwm.MixedNativeB",
    },
    "x11-a": {
        "title": "wtwm-mixed-x11-a",
        "type": "x11",
        "instance": "wtwm-mixed-x11-a",
        "class": "WtwmMixedX11A",
    },
    "x11-b": {
        "title": "wtwm-mixed-x11-b",
        "type": "x11",
        "instance": "wtwm-mixed-x11-b",
        "class": "WtwmMixedX11B",
    },
}
TITLE_TO_ROLE = {values["title"]: role for role, values in EXPECTED.items()}


class ClientChannel:
    def __init__(self, process: subprocess.Popen[bytes], label: str) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError(f"{label} client lacks pipes")
        self.process = process
        self.label = label
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.buffer = bytearray()
        self.lines: list[str] = []
        os.set_blocking(self.stdout.fileno(), False)

    def _fill(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"timed out waiting for {self.label} client output")
        readable, _, _ = select.select([self.stdout], [], [], remaining)
        if not readable:
            raise RuntimeError(f"timed out waiting for {self.label} client output")
        chunk = os.read(self.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError(
                f"{self.label} client exited while waiting for output "
                f"(status={self.process.poll()})"
            )
        self.buffer.extend(chunk)
        while b"\n" in self.buffer:
            raw, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            self.lines.append(raw.decode("utf-8", errors="strict"))

    def line(self, deadline: float) -> str:
        while not self.lines:
            self._fill(deadline)
        return self.lines.pop(0)

    def expect(self, expected: str, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while True:
            line = self.line(deadline)
            if line == expected:
                return
            if not line.startswith("EVENT "):
                raise RuntimeError(
                    f"unexpected {self.label} response {line!r}; expected {expected!r}"
                )

    def command(self, command: str, expected: str) -> None:
        self.stdin.write((command + "\n").encode("utf-8"))
        self.stdin.flush()
        self.expect(expected)

    def wait_for_key_pair(self, token: str, role: str) -> None:
        expected = {
            f"EVENT KEY {token} {role} 30 press",
            f"EVENT KEY {token} {role} 30 release",
        }
        received: set[str] = set()
        deadline = time.monotonic() + 10
        while received != expected:
            line = self.line(deadline)
            if line.startswith(f"EVENT KEY {token} "):
                if line not in expected or line in received:
                    raise RuntimeError(f"misrouted or duplicate input event: {line!r}")
                received.add(line)
            elif not line.startswith("EVENT "):
                raise RuntimeError(f"unexpected {self.label} event gate line: {line!r}")


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
        if value:
            return value
        time.sleep(0.01)
    raise RuntimeError("startup command did not record the Xwayland DISPLAY")


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def window_by_role(state: dict[str, object], role: str) -> dict[str, object]:
    title = EXPECTED[role]["title"]
    matches = [window for window in state["windows"] if window["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {role} window: {state!r}")
    return matches[0]


def assert_clients(state: dict[str, object], roles: set[str]) -> None:
    windows = state["windows"]
    if len(windows) != len(roles):
        raise RuntimeError(f"wrong mixed managed-window count: {state!r}")
    actual_roles = {TITLE_TO_ROLE.get(window["title"]) for window in windows}
    if actual_roles != roles:
        raise RuntimeError(f"wrong mixed identities: {state!r}")
    if state["popups"] or state["override_redirect"]:
        raise RuntimeError(f"mixed managed test admitted popup/OR state: {state!r}")
    stacks = set()
    for role in roles:
        window = window_by_role(state, role)
        expected = EXPECTED[role]
        for key, value in expected.items():
            if key != "title" and window.get(key) != value:
                raise RuntimeError(f"{role} identity mismatch for {key}: {window!r}")
        if not window["mapped"] or not window["decorated"]:
            raise RuntimeError(f"{role} is not a mapped managed toplevel: {window!r}")
        stacks.add(window["stack"])
    if stacks != set(range(len(roles))):
        raise RuntimeError(f"managed stack is not unified and contiguous: {state!r}")

    lifecycle = {entry["xid"]: entry for entry in state["xwayland_lifecycle"]}
    for role in roles & {"x11-a", "x11-b"}:
        window = window_by_role(state, role)
        entry = lifecycle.get(window["xid"])
        if entry is None or not entry["associated"] or not entry["mapped"] or not entry["has_buffer"]:
            raise RuntimeError(f"{role} lacks live Xwayland association: {state!r}")
        if entry["override_redirect"]:
            raise RuntimeError(f"{role} unexpectedly uses override-redirect semantics")


def clients_ready(state: dict[str, object], roles: set[str]) -> bool:
    try:
        assert_clients(state, roles)
    except (KeyError, RuntimeError, TypeError):
        return False
    return True


def x11_dissociated(state: dict[str, object], xid: int) -> bool:
    lifecycle = [
        item for item in state["xwayland_lifecycle"]
        if item["xid"] == xid
    ]
    return (
        len(lifecycle) == 1
        and not lifecycle[0]["associated"]
        and not lifecycle[0]["mapped"]
    )


def visible_content_point(state: dict[str, object], role: str) -> tuple[int, int]:
    target = window_by_role(state, role)
    windows = sorted(state["windows"], key=lambda item: item["stack"])
    above = [item for item in windows if item["stack"] < target["stack"]]
    x = int(target["x"])
    y = int(target["y"])
    width = int(target["width"])
    height = int(target["height"])
    title_height = int(target["title_height"])
    xs = (x + 12, x + width - 12, x + width // 2, x + 28, x + width - 28)
    ys = (
        y + title_height + 12,
        y + title_height + height - 12,
        y + title_height + height // 2,
        y + title_height + 28,
        y + title_height + height - 28,
    )
    for point_y in ys:
        for point_x in xs:
            if not (0 <= point_x < 640 and 0 <= point_y < 480):
                continue
            covered = any(
                int(other["x"]) <= point_x < int(other["x"]) + int(other["width"])
                and int(other["y"]) <= point_y < int(other["y"]) +
                int(other["title_height"]) + int(other["height"])
                for other in above
            )
            if not covered:
                return point_x, point_y
    raise RuntimeError(f"no visible content point for {role}: {state!r}")


def click(control: Control, state: dict[str, object], role: str, button: int) -> None:
    x, y = visible_content_point(state, role)
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")


def focus_and_key(
    control: Control,
    wayland: ClientChannel,
    x11: ClientChannel,
    role: str,
    token: str,
) -> dict[str, object]:
    wayland.command(f"ARM {token}", f"OK ARMED {token}")
    x11.command(f"ARM {token}", f"OK ARMED {token}")
    click(control, control.state(), role, 272)
    title = EXPECTED[role]["title"]
    state = wait_state(
        control,
        lambda item: item["focus"] == title and
        window_by_role(item, role)["stack"] == 0,
        f"{role} cross-protocol focus and raise",
    )
    assert_clients(state, set(EXPECTED))
    if role.startswith("x11-"):
        x11.command(f"WAIT FOCUS {role}", f"OK FOCUS {role}")
    control.command("KEY 30 press")
    control.command("KEY 30 release")
    target = wayland if role.startswith("native-") else x11
    target.wait_for_key_pair(token, role)
    control.command("WAIT 1")

    if role.startswith("native-"):
        a = 2 if role == "native-a" else 0
        b = 2 if role == "native-b" else 0
        active_a = 1 if role == "native-a" else 0
        active_b = 1 if role == "native-b" else 0
        wayland.command(
            f"REPORT {token}",
            f"OK REPORT {token} native-a={a} native-b={b} focus={role} "
            f"active-a={active_a} active-b={active_b}",
        )
        x11.command(
            f"REPORT {token}",
            f"OK REPORT {token} x11-a=0 x11-b=0 focus=none",
        )
    else:
        a = 2 if role == "x11-a" else 0
        b = 2 if role == "x11-b" else 0
        wayland.command(
            f"REPORT {token}",
            f"OK REPORT {token} native-a=0 native-b=0 focus=none "
            "active-a=0 active-b=0",
        )
        x11.command(
            f"REPORT {token}",
            f"OK REPORT {token} x11-a={a} x11-b={b} focus={role}",
        )
    return state


def lower_and_restore(
    control: Control,
    wayland: ClientChannel,
    x11: ClientChannel,
    role: str,
    token: str,
) -> None:
    focus_and_key(control, wayland, x11, role, token + "-raise")
    click(control, control.state(), role, 274)
    state = wait_state(
        control,
        lambda item: window_by_role(item, role)["stack"] == len(EXPECTED) - 1,
        f"{role} unified lower",
    )
    if not any(
        window["type"] != EXPECTED[role]["type"] and window["stack"] < len(EXPECTED) - 1
        for window in state["windows"]
    ):
        raise RuntimeError(f"{role} did not lower across the protocol boundary: {state!r}")
    focus_and_key(control, wayland, x11, role, token + "-restore")
    restored = control.state()
    if not any(
        window["type"] != EXPECTED[role]["type"] and window["stack"] > 0
        for window in restored["windows"]
    ):
        raise RuntimeError(f"{role} did not restore above the other protocol: {restored!r}")


def exercise_cleanup(
    control: Control,
    wayland: ClientChannel,
    x11: ClientChannel,
) -> None:
    focus_and_key(control, wayland, x11, "native-b", "native-unmap-focus")
    wayland.command("UNMAP native-b", "OK UNMAPPED native-b")
    remaining = {"native-a", "x11-a", "x11-b"}
    state = wait_state(
        control,
        lambda item: {TITLE_TO_ROLE.get(window["title"]) for window in item["windows"]}
        == remaining,
        "native unmap while X11 remains live",
    )
    assert_clients(state, remaining)
    if TITLE_TO_ROLE.get(state["focus"]) not in {"x11-a", "x11-b"}:
        raise RuntimeError(f"native unmap did not transfer focus to live X11: {state!r}")
    wayland.command("REMAP native-b", "OK REMAPPED native-b")
    state = wait_state(control, lambda item: clients_ready(item, set(EXPECTED)),
                       "native remap into mixed session")
    assert_clients(state, set(EXPECTED))

    focused = focus_and_key(control, wayland, x11, "x11-b", "x11-unmap-focus")
    x11_b_xid = window_by_role(focused, "x11-b")["xid"]
    x11.command("UNMAP x11-b", "OK UNMAPPED x11-b")
    remaining = {"native-a", "native-b", "x11-a"}
    state = wait_state(
        control,
        lambda item: {TITLE_TO_ROLE.get(window["title"]) for window in item["windows"]}
        == remaining and x11_dissociated(item, x11_b_xid),
        "X11 unmap/dissociation while native clients remain live",
    )
    assert_clients(state, remaining)
    if TITLE_TO_ROLE.get(state["focus"]) not in {"native-a", "native-b"}:
        raise RuntimeError(f"X11 unmap did not transfer focus to live native: {state!r}")
    if not x11_dissociated(state, x11_b_xid):
        raise RuntimeError(f"X11 unmap did not cleanly dissociate: {state!r}")
    x11.command("REMAP x11-b", "OK REMAPPED x11-b")
    state = wait_state(control, lambda item: clients_ready(item, set(EXPECTED)),
                       "X11 remap into mixed session")
    assert_clients(state, set(EXPECTED))


def run(compositor: Path, wayland_binary: Path, x11_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-mixed-clients-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "mixed.twmrc"
        config.write_text(
            "NoDefaults\nRandomPlacement\nNoGrabServer\nNoIconManagers\n"
            "Button2 = : window : f.lower\n",
            encoding="utf-8",
        )
        display_name = f"wtwm-mixed-{os.getpid()}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor_process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", display_name,
                "--test-backend", "headless",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        control: Control | None = None
        processes: list[subprocess.Popen[bytes]] = []
        try:
            control = Control(control_path, compositor_process)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            display = wait_path(display_marker)

            wayland_environment = environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = display_name
            wayland_process = subprocess.Popen(
                [str(wayland_binary)],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            processes.append(wayland_process)
            wayland = ClientChannel(wayland_process, "Wayland")
            wayland.expect("OK READY native-a native-b")

            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = display
            x11_process = subprocess.Popen(
                [str(x11_binary)],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            processes.append(x11_process)
            x11 = ClientChannel(x11_process, "X11")
            x11.expect("OK READY x11-a x11-b")

            state = wait_state(
                control,
                lambda item: clients_ready(item, set(EXPECTED)),
                "two native and two X11 managed maps and associations",
            )
            assert_clients(state, set(EXPECTED))

            # This one trace proves both native -> X11 -> native and
            # X11 -> native -> X11 focus/input transitions.
            for index, role in enumerate(("native-a", "x11-a", "native-b", "x11-b")):
                focus_and_key(control, wayland, x11, role, f"cross-{index}-{role}")

            lower_and_restore(control, wayland, x11, "native-a", "stack-native")
            lower_and_restore(control, wayland, x11, "x11-a", "stack-x11")
            exercise_cleanup(control, wayland, x11)

            wayland.command("EXIT", "OK EXIT")
            x11.command("EXIT", "OK EXIT")
            for process in processes:
                process.wait(timeout=5)
                if process.returncode != 0:
                    raise RuntimeError(f"mixed client exited with {process.returncode}")
            processes.clear()
            control.command("QUIT")
            compositor_process.wait(timeout=5)
            if compositor_process.returncode != 0:
                raise RuntimeError(f"compositor returned {compositor_process.returncode}")
        except Exception as error:
            if compositor_process.poll() is None:
                compositor_process.terminate()
            try:
                _, compositor_error = compositor_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor_process.kill()
                _, compositor_error = compositor_process.communicate()
            client_errors = []
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    _, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _, stderr = process.communicate()
                client_errors.append(stderr.decode("utf-8", errors="replace"))
            raise RuntimeError(
                f"{error}\ncompositor stderr:\n{compositor_error}\n"
                f"client stderr:\n{''.join(client_errors)}"
            ) from error
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor_process.poll() is None:
                compositor_process.terminate()
                compositor_process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--wayland-client", type=Path, required=True)
    parser.add_argument("--x11-client", type=Path, required=True)
    arguments = parser.parse_args()
    run(
        arguments.compositor.resolve(),
        arguments.wayland_client.resolve(),
        arguments.x11_client.resolve(),
    )


if __name__ == "__main__":
    main()
