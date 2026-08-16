#!/usr/bin/env python3
"""Exercise CLIPBOARD and PRIMARY across native Wayland and Xwayland."""

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


def read_line(process: subprocess.Popen[str], timeout: float = 10) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], max(0.0, deadline - time.monotonic())
        )
        if not readable:
            break
        line = process.stdout.readline()
        if line:
            return line.rstrip("\n")
        if process.poll() is not None:
            break
    raise RuntimeError(f"timed out waiting for client output (status={process.poll()})")


def expect_line(process: subprocess.Popen[str], expected: str) -> None:
    line = read_line(process)
    if line != expected:
        raise RuntimeError(f"expected client line {expected!r}, received {line!r}")


def command(process: subprocess.Popen[str], request: str) -> str:
    assert process.stdin is not None
    process.stdin.write(request + "\n")
    process.stdin.flush()
    return read_line(process)


def expect_command(
    process: subprocess.Popen[str], request: str, expected: str
) -> None:
    line = command(process, request)
    if line != expected:
        raise RuntimeError(
            f"command {request!r} expected {expected!r}, received {line!r}"
        )


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
        raise RuntimeError(f"expected one {title!r} window: {state!r}")
    return matches[0]


def focus_window(control: Control, title: str) -> dict[str, object]:
    state = wait_state(
        control,
        lambda item: any(entry["title"] == title for entry in item["windows"]),
        f"{title} map",
    )
    item = window(state, title)
    x = int(item["x"]) + int(item["width"]) // 2
    y = int(item["y"]) + min(60, max(12, int(item["height"]) // 2))
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")
    return wait_state(
        control, lambda current: current["focus"] == title, f"{title} focus"
    )


def wait_display(path: Path, compositor: subprocess.Popen[str]) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            display = path.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        if compositor.poll() is not None:
            break
        time.sleep(0.01)
    raise RuntimeError("startup command did not record an allocated Xwayland DISPLAY")


def start_wayland_client(
    binary: Path, environment: dict[str, str]
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [str(binary)],
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    expect_line(process, "READY")
    return process


def start_x11_client(
    binary: Path, environment: dict[str, str]
) -> tuple[subprocess.Popen[str], int]:
    process = subprocess.Popen(
        [str(binary)],
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    ready = read_line(process)
    fields = ready.split()
    if len(fields) != 2 or fields[0] != "READY":
        raise RuntimeError(f"invalid X11 client readiness line: {ready!r}")
    return process, int(fields[1])


def stop_client(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    expect_command(process, "EXIT", "EXITING")
    process.wait(timeout=5)
    if process.returncode != 0:
        raise RuntimeError(f"client exited with status {process.returncode}")


def wait_x_owners_clear(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    last = ""
    while time.monotonic() < deadline:
        last = command(process, "STATUS")
        if last == "STATUS clipboard=none primary=none":
            return
        time.sleep(0.01)
    raise RuntimeError(f"selection proxy ownership survived Wayland teardown: {last}")


def wait_x_targets_served(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    last = ""
    while time.monotonic() < deadline:
        last = command(process, "SERVED")
        fields = dict(field.split("=", 1) for field in last.split()[1:])
        if fields.get("clipboard") == "1" and fields.get("primary") == "1":
            return
        time.sleep(0.01)
    raise RuntimeError(f"X11 owner did not serve both TARGETS requests: {last}")


def run(compositor_binary: Path, wayland_binary: Path, x11_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-selection-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "xwayland-display"
        config_path = temporary / "selection.twmrc"
        config_path.write_text("", encoding="utf-8")
        socket_name = f"wtwm-selection-{os.getpid()}"
        startup = (
            "printf '%s\\n' \"$DISPLAY\" > " + shlex.quote(str(display_path))
        )
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor = subprocess.Popen(
            [
                str(compositor_binary),
                "--test-control", str(control_path),
                "--test-socket", socket_name,
                "--test-backend", "headless",
                "-f", str(config_path),
                "-s", startup,
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        clients: list[subprocess.Popen[str]] = []
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 800 480")
            display = wait_display(display_path, compositor)
            wayland_environment = environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = socket_name
            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = display

            native = start_wayland_client(wayland_binary, wayland_environment)
            clients.append(native)
            x11, first_xid = start_x11_client(x11_binary, x11_environment)
            clients.append(x11)
            state = wait_state(
                control,
                lambda item: len(item["windows"]) == 2
                and any(entry["title"] == "wtwm-selection-wayland"
                        for entry in item["windows"])
                and any(entry["title"] == "wtwm-selection-x11"
                        for entry in item["windows"]),
                "native and Xwayland selection windows",
            )
            x_state = window(state, "wtwm-selection-x11")
            if x_state["type"] != "x11" or x_state["xid"] != first_xid:
                raise RuntimeError(f"Xwayland selection client was not bridged: {x_state!r}")

            focus_window(control, "wtwm-selection-wayland")
            serial_line = command(native, "WAIT SERIAL")
            if not serial_line.startswith("SERIAL ") or serial_line == "SERIAL 0":
                raise RuntimeError(f"native source lacks an input serial: {serial_line}")
            expect_command(
                native, "SET CLIPBOARD ONE", "SET CLIPBOARD native-clipboard-one"
            )
            expect_command(native, "SET PRIMARY", "SET PRIMARY native-primary")

            focus_window(control, "wtwm-selection-x11")
            expect_command(
                x11, "TARGETS CLIPBOARD", "TARGETS CLIPBOARD utf8=1 text=1"
            )
            expect_command(
                x11, "TARGETS PRIMARY", "TARGETS PRIMARY utf8=1 text=1"
            )
            expect_command(
                x11, "GET CLIPBOARD", "DATA CLIPBOARD native-clipboard-one"
            )
            expect_command(x11, "GET PRIMARY", "DATA PRIMARY native-primary")

            focus_window(control, "wtwm-selection-wayland")
            expect_command(
                native, "SET CLIPBOARD TWO", "SET CLIPBOARD native-clipboard-two"
            )
            expect_command(native, "CANCELS", "CANCELS clipboard=1 primary=0")
            focus_window(control, "wtwm-selection-x11")
            expect_command(
                x11, "GET CLIPBOARD", "DATA CLIPBOARD native-clipboard-two"
            )

            stop_client(native)
            clients.remove(native)
            wait_x_owners_clear(x11)

            recipient = start_wayland_client(wayland_binary, wayland_environment)
            clients.append(recipient)
            focus_window(control, "wtwm-selection-x11")
            expect_command(x11, "OWN CLIPBOARD", "OWN CLIPBOARD 1")
            expect_command(x11, "OWN PRIMARY", "OWN PRIMARY 1")
            wait_x_targets_served(x11)
            time.sleep(0.05)
            focus_window(control, "wtwm-selection-wayland")
            expect_command(
                recipient, "WAIT OFFERS",
                "OFFERS clipboard=1 primary=1 utf8=1/1",
            )
            expect_command(
                recipient, "GET CLIPBOARD", "DATA CLIPBOARD x11-clipboard"
            )
            expect_command(recipient, "GET PRIMARY", "DATA PRIMARY x11-primary")

            stop_client(x11)
            clients.remove(x11)
            expect_command(
                recipient, "WAIT CLEAR", "CLEAR clipboard=1 primary=1"
            )

            probe, _ = start_x11_client(x11_binary, x11_environment)
            clients.append(probe)
            wait_state(
                control,
                lambda item: any(entry["title"] == "wtwm-selection-x11"
                                 for entry in item["windows"]),
                "replacement Xwayland probe",
            )
            expect_command(
                probe, "STATUS", "STATUS clipboard=none primary=none"
            )
            stop_client(probe)
            clients.remove(probe)
            stop_client(recipient)
            clients.remove(recipient)

            control.command("QUIT")
            compositor.wait(timeout=5)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor exited with {compositor.returncode}")
        except Exception as error:
            diagnostics: list[str] = []
            for client in clients:
                if client.poll() is None:
                    client.terminate()
                try:
                    _, stderr = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    _, stderr = client.communicate()
                if stderr:
                    diagnostics.append(stderr)
            if compositor.poll() is None:
                compositor.terminate()
            try:
                _, compositor_stderr = compositor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
                _, compositor_stderr = compositor.communicate()
            raise RuntimeError(
                f"{error}\nclient stderr:\n{''.join(diagnostics)}"
                f"compositor stderr:\n{compositor_stderr}"
            ) from error
        finally:
            for client in clients:
                if client.poll() is None:
                    client.terminate()
                    client.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
                compositor.wait(timeout=5)


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
