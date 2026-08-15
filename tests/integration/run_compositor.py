#!/usr/bin/env python3
"""Launch and exercise wtwm's private compositor test binary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


class Control:
    def __init__(self, path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 10
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        while True:
            try:
                self.socket.connect(str(path))
                break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError(f"compositor exited early with {process.returncode}")
                if time.monotonic() >= deadline:
                    raise RuntimeError("timed out waiting for test control socket")
                time.sleep(0.01)
        self.stream = self.socket.makefile("rw", encoding="utf-8", newline="\n")
        greeting = self.stream.readline().rstrip("\n")
        if greeting != "OK WTWM_TEST_CONTROL 1":
            raise RuntimeError(f"unexpected control greeting: {greeting!r}")

    def command(self, command: str) -> str:
        self.stream.write(command + "\n")
        self.stream.flush()
        response = self.stream.readline().rstrip("\n")
        if not response.startswith("OK "):
            raise RuntimeError(f"{command!r} failed: {response!r}")
        return response

    def state(self) -> dict[str, object]:
        return json.loads(self.command("STATE").removeprefix("OK STATE "))

    def close(self) -> None:
        self.stream.close()
        self.socket.close()


def wait_for_window(control: Control, title: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        windows = state["windows"]
        if any(window["title"] == title and window["mapped"] for window in windows):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for mapped client {title!r}")


def run_once(compositor: Path, client_binary: Path, iteration: int,
             nested: bool) -> None:
    inherited_runtime = os.environ.get("XDG_RUNTIME_DIR")
    inherited_display = os.environ.get("WAYLAND_DISPLAY")
    if nested:
        if not inherited_runtime or not inherited_display:
            raise SystemExit(77)
        parent_socket = Path(inherited_display)
        if not parent_socket.is_absolute():
            parent_socket = Path(inherited_runtime) / parent_socket
        if not parent_socket.exists():
            raise SystemExit(77)

    with tempfile.TemporaryDirectory(prefix="wtwm-integration-") as directory:
        temporary = Path(directory)
        runtime = Path(inherited_runtime) if nested else temporary / "runtime"
        if not nested:
            runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_name = f"wtwm-test-{os.getpid()}-{iteration}"
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
            "WLR_WL_OUTPUTS": "1",
        })
        command = [
            str(compositor),
            "--test-control", str(control_path),
            "--test-socket", display_name,
            "--test-backend", "wayland" if nested else "headless",
        ]
        process = subprocess.Popen(
            command, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            if not nested:
                output = control.command("OUTPUT 640 480")
                if not output.endswith(" 640 480"):
                    raise RuntimeError(f"unexpected output response: {output!r}")
            control.command("SET CURSOR 8 8")
            control.command("WAIT 2")

            title = f"wtwm-test-client-{iteration}"
            client_environment = environment.copy()
            client_environment["WAYLAND_DISPLAY"] = display_name
            client = subprocess.Popen(
                [str(client_binary), title], env=client_environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            state = wait_for_window(control, title)
            if state["focus"] != title:
                raise RuntimeError(f"mapped client is not focused: {state!r}")
            window = next(window for window in state["windows"] if window["title"] == title)
            if (window["x"], window["y"]) != (32, 32):
                raise RuntimeError(f"placement is not deterministic: {window!r}")
            for key in ("stack", "iconified", "width", "height"):
                if key not in window:
                    raise RuntimeError(f"STATE omitted window field {key!r}")
            if "icons" not in state or "menu" not in state:
                raise RuntimeError("STATE omitted icons or menu state")

            control.command("POINTER 100 100")
            control.command("BUTTON 272 press")
            control.command("BUTTON 272 release")
            control.command("KEY 1 press")
            control.command("KEY 1 release")
            control.command("WAIT 2")
            if not nested:
                capture = temporary / "capture.ppm"
                control.command(f"CAPTURE {capture}")
                header = capture.read_bytes()[:15]
                if not header.startswith(b"P6\n640 480\n255"):
                    raise RuntimeError(f"invalid compositor capture header: {header!r}")

            client.terminate()
            client.wait(timeout=5)
            client = None
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
        except Exception as error:
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
            raise RuntimeError(f"iteration {iteration}: {error}\n{compositor_error}") from error
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--nested", action="store_true")
    arguments = parser.parse_args()
    if arguments.repeat < 1 or arguments.repeat > 100:
        parser.error("--repeat must be between 1 and 100")
    for iteration in range(arguments.repeat):
        run_once(arguments.compositor, arguments.client, iteration, arguments.nested)


if __name__ == "__main__":
    main()
