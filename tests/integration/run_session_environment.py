#!/usr/bin/env python3
"""Verify that a managed login publishes its live display environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_text(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8")
            if value:
                return value
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_lines(path: Path, count: int) -> list[str]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) >= count:
                return lines
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {count} lines in {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="wtwm-session-environment-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        binary_directory = temporary / "bin"
        runtime.mkdir(mode=0o700)
        binary_directory.mkdir(mode=0o700)
        import_marker = temporary / "activation-environment"
        startup_marker = temporary / "startup-environment"
        sequence = temporary / "sequence"
        updater = binary_directory / "dbus-update-activation-environment"
        updater.write_text(
            "#!/bin/sh\n"
            "{\n"
            "printf 'args=%s\\n' \"$*\"\n"
            "printf 'WAYLAND_DISPLAY=%s\\n' \"${WAYLAND_DISPLAY:-}\"\n"
            "printf 'DISPLAY=%s\\n' \"${DISPLAY:-}\"\n"
            "printf 'XDG_CURRENT_DESKTOP=%s\\n' \"${XDG_CURRENT_DESKTOP:-}\"\n"
            "printf 'XDG_SESSION_DESKTOP=%s\\n' \"${XDG_SESSION_DESKTOP:-}\"\n"
            "printf 'XDG_SESSION_TYPE=%s\\n' \"${XDG_SESSION_TYPE:-}\"\n"
            "} > \"$WTWM_ACTIVATION_MARKER\"\n"
            "printf '%s\\n' import >> \"$WTWM_SEQUENCE_MARKER\"\n",
            encoding="utf-8",
        )
        updater.chmod(0o700)

        socket_name = f"wtwm-session-environment-{os.getpid()}"
        control_path = temporary / "control.sock"
        startup = (
            f'printf "%s\\n" "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" '
            f'"DISPLAY=$DISPLAY" > {shlex.quote(str(startup_marker))}; '
            f'printf "%s\\n" startup >> {shlex.quote(str(sequence))}'
        )
        environment = os.environ.copy()
        environment.update({
            "PATH": f"{binary_directory}:{environment.get('PATH', '')}",
            "WTWM_MANAGED_SESSION": "1",
            "WTWM_ACTIVATION_MARKER": str(import_marker),
            "WTWM_SEQUENCE_MARKER": str(sequence),
            "XDG_CURRENT_DESKTOP": "wtwm",
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_SESSION_DESKTOP": "wtwm",
            "XDG_SESSION_TYPE": "wayland",
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen([
            str(arguments.compositor.resolve()), "-s", startup,
            "--test-control", str(control_path),
            "--test-socket", socket_name,
            "--test-backend", "headless",
        ], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        control: Control | None = None
        try:
            control = Control(control_path, process)
            control.command("OUTPUT 640 480")
            imported = dict(
                line.split("=", 1) for line in wait_text(import_marker).splitlines()
            )
            expected_arguments = (
                "--systemd WAYLAND_DISPLAY DISPLAY XDG_CURRENT_DESKTOP "
                "XDG_SESSION_DESKTOP XDG_SESSION_TYPE"
            )
            if imported != {
                "args": expected_arguments,
                "WAYLAND_DISPLAY": socket_name,
                "DISPLAY": imported.get("DISPLAY", ""),
                "XDG_CURRENT_DESKTOP": "wtwm",
                "XDG_SESSION_DESKTOP": "wtwm",
                "XDG_SESSION_TYPE": "wayland",
            } or not imported["DISPLAY"].startswith(":"):
                raise RuntimeError(f"incorrect activation environment: {imported!r}")
            startup_values = dict(
                line.split("=", 1) for line in wait_text(startup_marker).splitlines()
            )
            if startup_values != {
                "WAYLAND_DISPLAY": socket_name,
                "DISPLAY": imported["DISPLAY"],
            }:
                raise RuntimeError(f"startup environment disagrees: {startup_values!r}")
            sequence_lines = wait_lines(sequence, 2)
            if sequence_lines != ["import", "startup"]:
                raise RuntimeError(f"startup raced activation import: {sequence_lines!r}")
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
        except Exception as error:
            if process.poll() is None:
                process.terminate()
            try:
                _, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate()
            raise RuntimeError(f"managed session environment failed: {error}\n{stderr}") from error
        finally:
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

        import_marker.unlink()
        unmanaged_environment = environment.copy()
        unmanaged_environment.pop("WTWM_MANAGED_SESSION")
        unmanaged_control_path = temporary / "unmanaged-control.sock"
        unmanaged_process = subprocess.Popen([
            str(arguments.compositor.resolve()),
            "--test-control", str(unmanaged_control_path),
            "--test-socket", f"{socket_name}-unmanaged",
            "--test-backend", "headless",
        ], env=unmanaged_environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        unmanaged_control: Control | None = None
        try:
            unmanaged_control = Control(unmanaged_control_path, unmanaged_process)
            unmanaged_control.command("OUTPUT 640 480")
            unmanaged_control.command("WAIT 2")
            time.sleep(0.05)
            if import_marker.exists():
                raise RuntimeError("unmanaged nested launch changed activation state")
            unmanaged_control.command("QUIT")
            unmanaged_process.wait(timeout=5)
            if unmanaged_process.returncode != 0:
                raise RuntimeError(
                    f"unmanaged compositor returned {unmanaged_process.returncode}"
                )
        except Exception as error:
            if unmanaged_process.poll() is None:
                unmanaged_process.terminate()
            try:
                _, stderr = unmanaged_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                unmanaged_process.kill()
                _, stderr = unmanaged_process.communicate()
            raise RuntimeError(f"unmanaged session isolation failed: {error}\n{stderr}") from error
        finally:
            if unmanaged_control is not None:
                unmanaged_control.close()
            if unmanaged_process.poll() is None:
                unmanaged_process.terminate()
                unmanaged_process.wait(timeout=5)

    print("managed session activation environment integration passed")


if __name__ == "__main__":
    main()
