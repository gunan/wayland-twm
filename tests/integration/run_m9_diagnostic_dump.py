#!/usr/bin/env python3
"""Exercise the optional SIGUSR2 diagnostic dump and its safe path handling."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import tempfile
import time

from run_compositor import Control


SCHEMA = "wtwm-diagnostic-v1"
MAX_OUTPUTS = 64
MAX_WINDOWS = 256


def wait_client_line(client: subprocess.Popen[str], expected: str) -> None:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [client.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected:
            return
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected diagnostic client event: {line!r}")
    raise RuntimeError(f"timed out waiting for diagnostic client event {expected!r}")


def client_command(client: subprocess.Popen[str], command: str, expected: str) -> None:
    assert client.stdin is not None
    client.stdin.write(command + "\n")
    client.stdin.flush()
    wait_client_line(client, expected)


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.002)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def trigger_dump(
    compositor: subprocess.Popen[str], control: Control, log_path: Path,
    outcome: str, occurrence: int,
) -> None:
    if compositor.poll() is not None:
        raise RuntimeError(f"compositor exited before SIGUSR2: {compositor.returncode}")
    os.kill(compositor.pid, signal.SIGUSR2)
    marker = f"event=diagnostic_dump outcome={outcome} signal={signal.SIGUSR2}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if log_path.read_text(encoding="utf-8", errors="replace").count(marker) >= occurrence:
            if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("compositor liveness probe failed after SIGUSR2")
            return
        if compositor.poll() is not None:
            raise RuntimeError(f"compositor exited while handling SIGUSR2: {compositor.returncode}")
        control.command("PING")
        time.sleep(0.002)
    raise RuntimeError(f"timed out waiting for diagnostic dump outcome {outcome!r}")


def validate_dump(path: Path, state: dict[str, object]) -> None:
    status = path.stat()
    if not stat.S_ISREG(status.st_mode):
        raise RuntimeError("diagnostic dump is not a regular file")
    if stat.S_IMODE(status.st_mode) != 0o600:
        raise RuntimeError(
            f"diagnostic dump mode is {stat.S_IMODE(status.st_mode):#o}, expected 0o600"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema", "frame", "topology_epoch", "focus_root", "cursor", "counts",
        "outputs", "outputs_truncated", "windows", "windows_truncated",
    }
    if set(payload) != expected_keys or payload["schema"] != SCHEMA:
        raise RuntimeError(f"diagnostic dump schema changed: {payload!r}")
    if (not isinstance(payload["frame"], int) or payload["frame"] < 0 or
            not isinstance(payload["topology_epoch"], int) or
            payload["topology_epoch"] < 0 or
            not isinstance(payload["focus_root"], bool)):
        raise RuntimeError(f"diagnostic scalar state is invalid: {payload!r}")
    cursor = payload["cursor"]
    if set(cursor) != {"x", "y"} or not all(
        isinstance(cursor[key], (int, float)) and math.isfinite(cursor[key])
        for key in ("x", "y")
    ):
        raise RuntimeError(f"diagnostic cursor is invalid: {cursor!r}")

    expected_counts = {
        "outputs": len(state["outputs"]),
        "windows": len(state["windows"]),
        "popups": len(state["popups"]),
        "inputs": len(state["inputs"]),
    }
    if payload["counts"] != expected_counts:
        raise RuntimeError(
            f"diagnostic counts disagree with live STATE: {payload['counts']!r} "
            f"!= {expected_counts!r}"
        )
    if len(payload["outputs"]) != min(expected_counts["outputs"], MAX_OUTPUTS):
        raise RuntimeError("diagnostic output truncation count is invalid")
    if payload["outputs_truncated"] != (expected_counts["outputs"] > MAX_OUTPUTS):
        raise RuntimeError("diagnostic output truncation flag is invalid")
    if len(payload["windows"]) != min(expected_counts["windows"], MAX_WINDOWS):
        raise RuntimeError("diagnostic window truncation count is invalid")
    if payload["windows_truncated"] != (expected_counts["windows"] > MAX_WINDOWS):
        raise RuntimeError("diagnostic window truncation flag is invalid")

    for output in payload["outputs"]:
        if set(output) != {"name", "enabled", "in_layout", "width", "height"}:
            raise RuntimeError(f"diagnostic output record is invalid: {output!r}")
    for window in payload["windows"]:
        if set(window) != {
            "protocol", "title", "mapped", "iconified", "focused",
            "x", "y", "width", "height",
        }:
            raise RuntimeError(f"diagnostic window record is invalid: {window!r}")
        if window["title"] != "overlay-native" or window["protocol"] != "xdg_shell":
            raise RuntimeError(f"diagnostic window identity is stale: {window!r}")


def run(compositor_binary: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m9-diagnostic-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        dump_path = temporary / "diagnostic.json"
        log_path = temporary / "compositor.log"
        socket_name = f"wtwm-m9-diagnostic-{os.getpid()}"
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        with log_path.open("w", encoding="utf-8") as compositor_log:
            compositor = subprocess.Popen(
                [
                    str(compositor_binary),
                    "--diagnostic-dump", str(dump_path),
                    "--test-control", str(control_path),
                    "--test-socket", socket_name,
                    "--test-backend", "headless",
                ],
                env=environment,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=compositor_log,
            )
            control: Control | None = None
            client: subprocess.Popen[str] | None = None
            try:
                control = Control(control_path, compositor)
                control.command("SET ANIMATION_MS 0")
                control.command("SET PLACEMENT_SEED 0")
                control.command("SET FONT DejaVu Sans 10")
                control.command("OUTPUT 640 480")

                client_environment = environment.copy()
                client_environment["WAYLAND_DISPLAY"] = socket_name
                client = subprocess.Popen(
                    [str(client_binary)],
                    env=client_environment,
                    text=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                )
                wait_client_line(client, "READY")
                client_command(client, "MAP_POPUP", "POPUP_MAPPED")
                state = wait_state(
                    control,
                    lambda item: len(item["windows"]) == 1 and
                    len(item["popups"]) == 1 and item["popups"][0]["mapped"],
                    "diagnostic client and popup map",
                )

                trigger_dump(compositor, control, log_path, "written", 1)
                validate_dump(dump_path, state)

                dump_path.unlink()
                os.mkfifo(dump_path, mode=0o600)
                trigger_dump(compositor, control, log_path, "failed", 1)
                if not stat.S_ISFIFO(dump_path.lstat().st_mode):
                    raise RuntimeError("diagnostic FIFO target was replaced or followed")

                dump_path.unlink()
                sentinel = temporary / "sentinel"
                sentinel_content = "diagnostic-symlink-sentinel\n"
                sentinel.write_text(sentinel_content, encoding="utf-8")
                sentinel.chmod(0o600)
                dump_path.symlink_to(sentinel)
                trigger_dump(compositor, control, log_path, "failed", 2)
                if not dump_path.is_symlink():
                    raise RuntimeError("diagnostic symlink target was replaced")
                if sentinel.read_text(encoding="utf-8") != sentinel_content:
                    raise RuntimeError("diagnostic dump followed and overwrote a symlink")

                client_command(client, "EXIT", "EXITING")
                client.wait(timeout=5)
                if client.returncode != 0:
                    raise RuntimeError(f"diagnostic client returned {client.returncode}")
                client = None
                wait_state(
                    control, lambda item: not item["windows"] and not item["popups"],
                    "diagnostic client teardown",
                )
                control.command("QUIT")
                compositor.wait(timeout=5)
                if compositor.returncode != 0:
                    raise RuntimeError(f"compositor returned {compositor.returncode}")
            except Exception as error:
                client_error = ""
                if client is not None and client.poll() is None:
                    client.terminate()
                if client is not None:
                    try:
                        _, client_error = client.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        client.kill()
                        _, client_error = client.communicate()
                if compositor.poll() is None:
                    compositor.terminate()
                try:
                    compositor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=5)
                compositor_log.flush()
                raise RuntimeError(
                    f"{error}\nclient stderr:\n{client_error}\n"
                    f"compositor log:\n{log_path.read_text(encoding='utf-8', errors='replace')}"
                ) from error
            finally:
                if client is not None and client.poll() is None:
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
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.client.resolve())


if __name__ == "__main__":
    main()
