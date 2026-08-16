#!/usr/bin/env python3
"""Verify Xwayland startup-command inheritance, connection, and teardown."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_marker(path: Path, event: str) -> list[str]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if fields and fields[0] == event:
                    return fields
        time.sleep(0.01)
    contents = path.read_text(encoding="utf-8") if path.exists() else ""
    raise RuntimeError(f"timed out waiting for {event}: {contents!r}")


def run(compositor: Path, probe: Path) -> None:
    inherited_display = "wtwm-invalid-parent-display"
    with tempfile.TemporaryDirectory(prefix="wtwm-xwayland-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        marker = temporary / "xwayland.marker"
        environment = os.environ.copy()
        environment.update({
            "DISPLAY": inherited_display,
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        startup = shlex.join([str(probe), str(marker)])
        process = subprocess.Popen(
            [
                str(compositor), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", f"wtwm-xwayland-{os.getpid()}",
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        probe_pid: int | None = None
        try:
            control = Control(control_path, process)
            connected = wait_marker(marker, "CONNECTED")
            if len(connected) != 4:
                raise RuntimeError(f"malformed connection marker: {connected!r}")
            allocated_display = connected[1]
            probe_pid = int(connected[2])
            if allocated_display == inherited_display or not allocated_display.startswith(":"):
                raise RuntimeError(
                    f"startup command inherited invalid DISPLAY={allocated_display!r}"
                )

            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
            disconnected = wait_marker(marker, "DISCONNECTED")
            if disconnected[1:] != connected[1:]:
                raise RuntimeError(
                    f"disconnect marker does not match connection: {disconnected!r}"
                )
            unavailable = subprocess.run(
                [str(probe), "--expect-unavailable", allocated_display],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                check=False,
            )
            if unavailable.returncode != 0:
                raise RuntimeError(
                    f"retired Xwayland display remained available:\n{unavailable.stderr}"
                )
            probe_pid = None
        except Exception as error:
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
            raise RuntimeError(f"{error}\n{compositor_error}") from error
        finally:
            if probe_pid is not None:
                try:
                    os.kill(probe_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def check_failed_setup_preserves_display(compositor: Path, probe: Path) -> None:
    inherited_display = "wtwm-preserved-parent-display"
    with tempfile.TemporaryDirectory(prefix="wtwm-xwayland-failure-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        marker = temporary / "display.marker"
        environment = os.environ.copy()
        environment.update({
            "DISPLAY": inherited_display,
            "WLR_XWAYLAND": str(temporary / "missing-Xwayland"),
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        startup = shlex.join([str(probe), "--record-display", str(marker)])
        process = subprocess.Popen(
            [
                str(compositor), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", f"wtwm-xwayland-failure-{os.getpid()}",
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        try:
            control = Control(control_path, process)
            inherited = wait_marker(marker, "INHERITED")
            if len(inherited) != 4 or inherited[1] != inherited_display:
                raise RuntimeError(
                    f"failed Xwayland setup clobbered DISPLAY: {inherited!r}"
                )
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
            raise RuntimeError(f"{error}\n{compositor_error}") from error
        finally:
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.probe.resolve())
    check_failed_setup_preserves_display(
        arguments.compositor.resolve(), arguments.probe.resolve()
    )


if __name__ == "__main__":
    main()
