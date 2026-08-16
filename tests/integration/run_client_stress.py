#!/usr/bin/env python3
"""Exercise hostile client lifecycle behavior without stalling wtwm."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import tempfile
import time

from run_compositor import Control


RAPID_CYCLES = 32
SURVIVOR_TITLE = "wtwm-stress-survivor"
SURVIVOR_APP_ID = "org.wtwm.StressSurvivor"


class ClientChannel:
    def __init__(self, process: subprocess.Popen[bytes], label: str) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError(f"{label} client lacks control pipes")
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
            raise RuntimeError(f"timed out waiting for {self.label} output")
        readable, _, _ = select.select([self.stdout], [], [], remaining)
        if not readable:
            raise RuntimeError(f"timed out waiting for {self.label} output")
        chunk = os.read(self.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError(
                f"{self.label} exited while awaiting output "
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
                    f"unexpected {self.label} response {line!r}; "
                    f"expected {expected!r}"
                )

    def expect_prefix(self, prefix: str, timeout: float = 10) -> str:
        deadline = time.monotonic() + timeout
        while True:
            line = self.line(deadline)
            if line.startswith(prefix):
                return line
            if not line.startswith("EVENT "):
                raise RuntimeError(
                    f"unexpected {self.label} response {line!r}; "
                    f"expected prefix {prefix!r}"
                )

    def expect_event(self, expected: str) -> None:
        deadline = time.monotonic() + 10
        while True:
            line = self.line(deadline)
            if line == expected:
                return
            raise RuntimeError(
                f"unexpected {self.label} event {line!r}; expected {expected!r}"
            )

    def command(self, command: str, expected: str) -> None:
        self.stdin.write((command + "\n").encode("utf-8"))
        self.stdin.flush()
        self.expect(expected)

    def wait_for_key_pair(self, token: str) -> None:
        expected = {
            f"EVENT KEY {token} 30 press",
            f"EVENT KEY {token} 30 release",
        }
        received: set[str] = set()
        deadline = time.monotonic() + 10
        while received != expected:
            line = self.line(deadline)
            if line in expected and line not in received:
                received.add(line)
            elif line in {f"EVENT ENTER {token}", f"EVENT LEAVE {token}"}:
                continue
            else:
                raise RuntimeError(f"misrouted or duplicate survivor event: {line!r}")


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
    raise RuntimeError(f"startup command did not populate {path}")


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {title!r} window: {state!r}")
    return matches[0]


def exact_titles(state: dict[str, object], titles: set[str]) -> bool:
    return (
        len(state["windows"]) == len(titles)
        and {item["title"] for item in state["windows"]} == titles
        and all(item["mapped"] for item in state["windows"])
        and not state["popups"]
        and not state["override_redirect"]
    )


def assert_survivor_only(state: dict[str, object]) -> None:
    if not exact_titles(state, {SURVIVOR_TITLE}):
        raise RuntimeError(f"stale scene state remains after client exit: {state!r}")
    survivor = window(state, SURVIVOR_TITLE)
    if (
        survivor["type"] != "wayland"
        or survivor["app_id"] != SURVIVOR_APP_ID
        or not survivor["decorated"]
        or state["focus"] != SURVIVOR_TITLE
        or state["xwayland_lifecycle"]
        or state["interactive"]
        or state["menu"] is not None
    ):
        raise RuntimeError(f"survivor or cleanup state is invalid: {state!r}")


def assert_mapped_target(
    state: dict[str, object], title: str, protocol: str, xid: int | None = None
) -> None:
    if not exact_titles(state, {SURVIVOR_TITLE, title}):
        raise RuntimeError(f"target scene is duplicated or incomplete: {state!r}")
    if {item["stack"] for item in state["windows"]} != {0, 1}:
        raise RuntimeError(f"target stack is not contiguous: {state!r}")
    target = window(state, title)
    if target["type"] != protocol or not target["decorated"]:
        raise RuntimeError(f"target protocol identity is wrong: {target!r}")
    lifecycle = state["xwayland_lifecycle"]
    if protocol == "wayland":
        if lifecycle:
            raise RuntimeError(f"native target created X11 lifecycle state: {state!r}")
        return
    if xid is None or target["xid"] != xid or len(lifecycle) != 1:
        raise RuntimeError(f"X11 target identity/lifecycle duplicated: {state!r}")
    entry = lifecycle[0]
    if (
        entry["xid"] != xid
        or not entry["associated"]
        or not entry["mapped"]
        or not entry["has_buffer"]
        or entry["override_redirect"]
    ):
        raise RuntimeError(f"X11 target lifecycle is not live: {state!r}")


def mapped_target_ready(
    state: dict[str, object], title: str, protocol: str, xid: int | None
) -> bool:
    try:
        assert_mapped_target(state, title, protocol, xid)
    except (KeyError, RuntimeError, TypeError):
        return False
    return True


def x11_target_unmapped(state: dict[str, object], xid: int) -> bool:
    if not exact_titles(state, {SURVIVOR_TITLE}):
        return False
    lifecycle = state["xwayland_lifecycle"]
    return (
        len(lifecycle) == 1
        and lifecycle[0]["xid"] == xid
        and not lifecycle[0]["associated"]
        and not lifecycle[0]["mapped"]
        and not lifecycle[0]["has_buffer"]
        and not lifecycle[0]["override_redirect"]
    )


def visible_content_point(
    state: dict[str, object], title: str
) -> tuple[int, int]:
    target = window(state, title)
    above = [
        item for item in state["windows"] if item["stack"] < target["stack"]
    ]
    x = int(target["x"])
    y = int(target["y"])
    width = int(target["width"])
    height = int(target["height"])
    title_height = int(target["title_height"])
    xs = (x + 12, x + width - 12, x + width // 2)
    ys = (y + title_height + 12, y + title_height + height - 12)
    for point_y in ys:
        for point_x in xs:
            covered = any(
                int(other["x"]) <= point_x < int(other["x"]) + int(other["width"])
                and int(other["y"]) <= point_y < int(other["y"])
                + int(other["title_height"])
                + int(other["height"])
                for other in above
            )
            if not covered:
                return point_x, point_y
    raise RuntimeError(f"survivor has no visible input point: {state!r}")


def click_content(control: Control, state: dict[str, object], title: str) -> None:
    x, y = visible_content_point(state, title)
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")


def click_title(control: Control, state: dict[str, object], title: str, button: int) -> None:
    item = window(state, title)
    x = int(item["x"]) + int(item["width"]) // 2
    y = int(item["y"]) + 8
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")


def prove_survivor_input(
    control: Control, survivor: ClientChannel, token: str
) -> None:
    survivor.command(f"ARM {token}", f"OK ARMED {token}")
    click_content(control, control.state(), SURVIVOR_TITLE)
    wait_state(
        control,
        lambda state: state["focus"] == SURVIVOR_TITLE,
        f"survivor focus for {token}",
    )
    control.command("KEY 30 press")
    control.command("KEY 30 release")
    survivor.wait_for_key_pair(token)
    survivor.command(
        f"REPORT {token}",
        f"OK REPORT {token} keys=2 focus=1 close=0",
    )
    control.command("WAIT 1")


def wait_process(process: subprocess.Popen[bytes], label: str) -> int:
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"timed out waiting for {label} process exit") from error


def run(
    compositor: Path, wayland_client: Path, x11_client: Path
) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-client-stress-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "stress.twmrc"
        config.write_text(
            "RandomPlacement\n"
            "Button1 = : title : f.delete\n"
            "Button2 = : title : f.destroy\n",
            encoding="utf-8",
        )
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        display_name = f"wtwm-stress-{os.getpid()}"
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", display_name,
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        clients: list[tuple[str, subprocess.Popen[bytes]]] = []

        wayland_environment = environment.copy()
        wayland_environment["WAYLAND_DISPLAY"] = display_name
        x11_environment = environment.copy()

        def launch_wayland(title: str, app_id: str) -> tuple[subprocess.Popen[bytes], ClientChannel]:
            child = subprocess.Popen(
                [str(wayland_client), title, app_id],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((title, child))
            channel = ClientChannel(child, title)
            channel.expect(f"OK READY {title}")
            return child, channel

        def launch_x11(title: str) -> tuple[subprocess.Popen[bytes], ClientChannel, int]:
            child = subprocess.Popen(
                [str(x11_client), title, title, "WtwmStressX11"],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((title, child))
            channel = ClientChannel(child, title)
            ready = channel.expect_prefix(f"OK READY {title} ")
            return child, channel, int(ready.rsplit(" ", 1)[1])

        def await_mapped(title: str, protocol: str, xid: int | None = None) -> dict[str, object]:
            state = wait_state(
                control,
                lambda item: mapped_target_ready(item, title, protocol, xid),
                f"one live {protocol} target {title}",
            )
            assert_mapped_target(state, title, protocol, xid)
            click_content(control, state, title)
            state = wait_state(
                control,
                lambda item: item["focus"] == title,
                f"explicit pointer focus for {protocol} target {title}",
            )
            if state["focus"] != title:
                raise RuntimeError(
                    f"explicitly entered {protocol} target did not own focus: {state!r}"
                )
            control.command("WAIT 1")
            return state

        def await_cleanup(description: str) -> dict[str, object]:
            state = wait_state(
                control,
                lambda item: exact_titles(item, {SURVIVOR_TITLE})
                and not item["xwayland_lifecycle"],
                description,
            )
            click_content(control, state, SURVIVOR_TITLE)
            state = wait_state(
                control,
                lambda item: item["focus"] == SURVIVOR_TITLE,
                description + " survivor refocus",
            )
            assert_survivor_only(state)
            control.command("WAIT 1")
            return state

        try:
            control = Control(control_path, process)
            control.socket.settimeout(10)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            control.command("SET CURSOR 8 8")
            control.command("WAIT 2")
            x11_environment["DISPLAY"] = wait_path(display_marker)

            survivor_process, survivor = launch_wayland(
                SURVIVOR_TITLE, SURVIVOR_APP_ID
            )
            state = wait_state(
                control,
                lambda item: exact_titles(item, {SURVIVOR_TITLE}),
                "survivor map",
            )
            assert_survivor_only(state)
            prove_survivor_input(control, survivor, "initial")

            for protocol in ("wayland", "x11"):
                title = f"wtwm-stress-{protocol}-crash"
                if protocol == "wayland":
                    target_process, target = launch_wayland(
                        title, "org.wtwm.StressNativeCrash"
                    )
                    xid = None
                else:
                    target_process, target, xid = launch_x11(title)
                await_mapped(title, protocol, xid)
                target.command("CRASH", "OK CRASH")
                status = wait_process(target_process, f"{protocol} crash")
                if status != -signal.SIGABRT:
                    raise RuntimeError(
                        f"{protocol} crash fixture exited with {status}, not SIGABRT"
                    )
                await_cleanup(f"{protocol} crash cleanup")
                prove_survivor_input(control, survivor, f"after-{protocol}-crash")

            for protocol in ("wayland", "x11"):
                title = f"wtwm-stress-{protocol}-hang"
                if protocol == "wayland":
                    target_process, target = launch_wayland(
                        title, "org.wtwm.StressNativeHang"
                    )
                    xid = None
                else:
                    target_process, target, xid = launch_x11(title)
                await_mapped(title, protocol, xid)
                target.command("HANG", "OK HANG")
                if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                    raise RuntimeError("control interface stopped during client hang")
                control.command("WAIT 2")
                prove_survivor_input(control, survivor, f"during-{protocol}-hang")
                assert_mapped_target(control.state(), title, protocol, xid)
                target_process.kill()
                status = wait_process(target_process, f"{protocol} hung-client kill")
                if status != -signal.SIGKILL:
                    raise RuntimeError(f"{protocol} hung client exited with {status}")
                await_cleanup(f"{protocol} hung-client cleanup")
                prove_survivor_input(control, survivor, f"after-{protocol}-hang")

            native_title = "wtwm-stress-native-ignore-close"
            native_process, native_close = launch_wayland(
                native_title, "org.wtwm.StressNativeIgnoreClose"
            )
            state = await_mapped(native_title, "wayland")
            click_title(control, state, native_title, 272)
            native_close.expect_event("EVENT CLOSE 1")
            control.command("WAIT 2")
            assert_mapped_target(control.state(), native_title, "wayland")
            if native_process.poll() is not None:
                raise RuntimeError("native client exited after ignored f.delete")
            click_title(control, control.state(), native_title, 274)
            native_close.expect_event("EVENT CLOSE 2")
            control.command("WAIT 2")
            assert_mapped_target(control.state(), native_title, "wayland")
            if native_process.poll() is not None:
                raise RuntimeError("native f.destroy killed an xdg-shell client")
            native_process.kill()
            if wait_process(native_process, "native ignored-close cleanup") != -signal.SIGKILL:
                raise RuntimeError("native ignored-close fixture was not externally killed")
            await_cleanup("native ignored-close external cleanup")

            x11_title = "wtwm-stress-x11-ignore-close"
            x11_process, x11_close, x11_close_xid = launch_x11(x11_title)
            state = await_mapped(x11_title, "x11", x11_close_xid)
            if not window(state, x11_title)["supports_delete"]:
                raise RuntimeError("X11 ignored-close fixture lacks WM_DELETE_WINDOW")
            click_title(control, state, x11_title, 272)
            x11_close.expect_event("EVENT DELETE 1")
            control.command("WAIT 2")
            assert_mapped_target(control.state(), x11_title, "x11", x11_close_xid)
            if x11_process.poll() is not None:
                raise RuntimeError("X11 client exited after ignored f.delete")
            click_title(control, control.state(), x11_title, 274)
            if wait_process(x11_process, "X11 f.destroy") == 0:
                raise RuntimeError("X11 f.destroy fixture reported cooperative exit")
            await_cleanup("X11 f.destroy connection cleanup")
            prove_survivor_input(control, survivor, "after-ignore-close")

            rapid_native_title = "wtwm-stress-native-rapid"
            rapid_native_process, rapid_native = launch_wayland(
                rapid_native_title, "org.wtwm.StressNativeRapid"
            )
            await_mapped(rapid_native_title, "wayland")
            for cycle in range(1, RAPID_CYCLES + 1):
                rapid_native.command(
                    f"UNMAP {cycle}", f"OK UNMAPPED {cycle}"
                )
                await_cleanup(f"native rapid unmap cycle {cycle}")
                rapid_native.command(
                    f"REMAP {cycle}", f"OK REMAPPED {cycle}"
                )
                await_mapped(rapid_native_title, "wayland")
                if cycle in {1, 8, 16, 24, RAPID_CYCLES}:
                    prove_survivor_input(
                        control, survivor, f"native-rapid-{cycle}"
                    )
            rapid_native.command("EXIT", "OK EXIT")
            if wait_process(rapid_native_process, "native rapid client") != 0:
                raise RuntimeError("native rapid client did not exit cleanly")
            await_cleanup("native rapid client final cleanup")

            rapid_x11_title = "wtwm-stress-x11-rapid"
            rapid_x11_process, rapid_x11, rapid_xid = launch_x11(rapid_x11_title)
            await_mapped(rapid_x11_title, "x11", rapid_xid)
            for cycle in range(1, RAPID_CYCLES + 1):
                rapid_x11.command(f"UNMAP {cycle}", f"OK UNMAPPED {cycle}")
                state = wait_state(
                    control,
                    lambda item: x11_target_unmapped(item, rapid_xid),
                    f"X11 rapid dissociation cycle {cycle}",
                )
                if not x11_target_unmapped(state, rapid_xid):
                    raise RuntimeError(f"X11 unmap state duplicated: {state!r}")
                control.command("WAIT 1")
                rapid_x11.command(f"REMAP {cycle}", f"OK REMAPPED {cycle}")
                await_mapped(rapid_x11_title, "x11", rapid_xid)
                if cycle in {1, 8, 16, 24, RAPID_CYCLES}:
                    prove_survivor_input(
                        control, survivor, f"x11-rapid-{cycle}"
                    )
            rapid_x11.command("EXIT", "OK EXIT")
            if wait_process(rapid_x11_process, "X11 rapid client") != 0:
                raise RuntimeError("X11 rapid client did not exit cleanly")
            await_cleanup("X11 rapid client final cleanup")

            survivor.command("EXIT", "OK EXIT")
            if wait_process(survivor_process, "survivor") != 0:
                raise RuntimeError("survivor did not exit cleanly")
            wait_state(
                control,
                lambda item: not item["windows"]
                and not item["xwayland_lifecycle"]
                and item["focus"] is None,
                "empty final client state",
            )
            control.command("QUIT")
            process.wait(timeout=10)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
        except Exception as error:
            diagnostics: list[str] = []
            for label, child in clients:
                if child.poll() is None:
                    child.kill()
                try:
                    _, stderr = child.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    _, stderr = child.communicate()
                diagnostics.append(
                    f"{label} status={child.returncode} stderr:\n"
                    f"{stderr.decode('utf-8', errors='replace')}"
                )
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
            raise RuntimeError(
                f"{error}\n" + "\n".join(diagnostics)
                + f"\ncompositor stderr:\n{compositor_error}"
            ) from error
        finally:
            for _, child in clients:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


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
