#!/usr/bin/env python3
"""Verify Milestone 8 startup, logout, recovery, and state-file behavior."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-session-native"
X11_TITLE = "wtwm-session-x11"
MALFORMED_STATE = b"not-a-wtwm-session-state\x00preserve-me"
PRESERVED_STATE = b"existing-explicit-save-must-survive"


def environment(runtime: Path, state_home: Path) -> dict[str, str]:
    result = os.environ.copy()
    result.update({
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_STATE_HOME": str(state_home),
        "HOME": str(state_home.parent),
        "WLR_RENDERER": "pixman",
    })
    return result


def config_text(*, restore: bool = False) -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        + ("RestartPreviousState\n" if restore else "")
        + "Button1 = : root : f.quit\n"
    )


def compositor_command(
    compositor: Path,
    config: Path,
    control_path: Path,
    display_name: str,
    startup: str,
) -> list[str]:
    return [
        str(compositor),
        "-f", str(config),
        "-s", startup,
        "--test-control", str(control_path),
        "--test-socket", display_name,
        "--test-backend", "headless",
    ]


def run_failed_startups(compositor: Path, temporary: Path) -> Path:
    runtime = temporary / "failure-runtime"
    state_home = temporary / "failure-state"
    runtime.mkdir(mode=0o700)
    state_path = state_home / "wtwm" / "state"
    state_path.parent.mkdir(parents=True, mode=0o700)
    state_path.write_bytes(PRESERVED_STATE)
    marker = temporary / "failed-startup-command"
    control_path = temporary / "failed-control.sock"
    display_name = f"wm8-lifecycle-fail-{os.getpid()}"
    invalid = temporary / "invalid.twmrc"
    invalid.write_text('Button1 = : root : f.quit\n"unterminated\n',
                       encoding="utf-8")
    process = subprocess.run(
        compositor_command(
            compositor,
            invalid,
            control_path,
            display_name,
            f"touch {shlex.quote(str(marker))}",
        ),
        env=environment(runtime, state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if process.returncode != 1 or "wtwm:" not in process.stderr:
        raise RuntimeError(
            "invalid configuration did not fail deterministically: "
            f"status={process.returncode}, stderr={process.stderr!r}"
        )
    if marker.exists() or control_path.exists() or (runtime / display_name).exists():
        raise RuntimeError("invalid configuration published runtime state")
    if state_path.read_bytes() != PRESERVED_STATE:
        raise RuntimeError("invalid configuration changed the explicit state file")

    valid = temporary / "runtime-failure.twmrc"
    valid.write_text(config_text(), encoding="utf-8")
    runtime_marker = temporary / "runtime-failure-startup-command"
    runtime_control = temporary / "runtime-failure-control.sock"
    # A socket name longer than sockaddr_un.sun_path cannot be published on
    # any supported platform.  This reaches the compositor's bounded runtime
    # initialization failure path without depending on advisory-lock flavor.
    runtime_display = "w" * 200
    process = subprocess.run(
        compositor_command(
            compositor,
            valid,
            runtime_control,
            runtime_display,
            f"touch {shlex.quote(str(runtime_marker))}",
        ),
        env=environment(runtime, state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if process.returncode != 1:
        raise RuntimeError(
            "runtime initialization failure did not return 1: "
            f"status={process.returncode}, stderr={process.stderr!r}"
        )
    if runtime_marker.exists() or runtime_control.exists():
        raise RuntimeError("runtime initialization failure ran the startup command")
    if state_path.read_bytes() != PRESERVED_STATE:
        raise RuntimeError("runtime initialization failure changed saved state")
    return state_home


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {window["title"] for window in windows} == {NATIVE_TITLE, X11_TITLE}
        and all(window["mapped"] for window in windows)
    )


def run_f_quit_mixed_clients(
    compositor: Path,
    wayland_client: Path,
    x11_client: Path,
    temporary: Path,
) -> None:
    runtime = temporary / "quit-runtime"
    state_home = temporary / "quit-state"
    runtime.mkdir(mode=0o700)
    config = temporary / "quit.twmrc"
    config.write_text(config_text(), encoding="utf-8")
    control_path = temporary / "quit-control.sock"
    display_marker = temporary / "quit-environment"
    display_name = f"wm8-lifecycle-quit-{os.getpid()}"
    startup = (
        f'printf "%s|%s\\n" "$WAYLAND_DISPLAY" "$DISPLAY" > '
        f'{shlex.quote(str(display_marker))}; exit 71'
    )
    process = subprocess.Popen(
        compositor_command(
            compositor, config, control_path, display_name, startup
        ),
        env=environment(runtime, state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    control: Control | None = None
    clients: list[subprocess.Popen[bytes]] = []
    try:
        control = Control(control_path, process)
        control.socket.settimeout(10)
        control.command("SET ANIMATION_MS 0")
        control.command("OUTPUT 800 600")
        control.command("WAIT 2")
        published = wait_path(display_marker)
        fields = published.split("|", 1)
        if len(fields) != 2 or fields[0] != display_name or not fields[1]:
            raise RuntimeError(
                "startup command did not observe the published displays: "
                f"{published!r}"
            )
        # The startup command deliberately exited 71.  It is a best-effort
        # child, so the compositor and its control socket must remain live.
        if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
            raise RuntimeError("startup command failure ended the compositor")

        native_environment = environment(runtime, state_home)
        native_environment["WAYLAND_DISPLAY"] = display_name
        native_process = subprocess.Popen(
            [str(wayland_client), NATIVE_TITLE, "org.wtwm.SessionLifecycle"],
            env=native_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        clients.append(native_process)
        native = ClientChannel(native_process, NATIVE_TITLE)
        native.expect(f"OK READY {NATIVE_TITLE}")

        x11_environment = environment(runtime, state_home)
        x11_environment["DISPLAY"] = fields[1]
        x11_process = subprocess.Popen(
            [str(x11_client), X11_TITLE, "lifecycle", "WtwmLifecycle"],
            env=x11_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        clients.append(x11_process)
        x11 = ClientChannel(x11_process, X11_TITLE)
        x11.expect_prefix(f"OK READY {X11_TITLE} ")
        state = wait_state(control, mapped_pair, "f.quit mixed clients")
        types = {window["title"]: window["type"] for window in state["windows"]}
        if types != {NATIVE_TITLE: "wayland", X11_TITLE: "x11"}:
            raise RuntimeError(f"f.quit fixtures used wrong protocols: {state!r}")
        if native_process.poll() is not None or x11_process.poll() is not None:
            raise RuntimeError("a mixed client exited before f.quit")

        control.command("POINTER 790 590")
        wait_state(
            control,
            lambda item: item["pointer_context"] == "root",
            "f.quit root binding",
        )
        control.command("BUTTON 272 press")
        control.command("BUTTON 272 release")
        if process.wait(timeout=10) != 0:
            raise RuntimeError("f.quit did not exit successfully")
        if wait_process(native_process, NATIVE_TITLE) == 0:
            raise RuntimeError("native client reported a clean self-exit after logout")
        if wait_process(x11_process, X11_TITLE) == 0:
            raise RuntimeError("Xwayland client reported a clean self-exit after logout")
        if control_path.exists() or (runtime / display_name).exists():
            raise RuntimeError("f.quit left a compositor socket behind")
        if (state_home / "wtwm" / "state").exists():
            raise RuntimeError("f.quit implicitly created a saved-state file")
    finally:
        if control is not None:
            control.close()
        for client in clients:
            if client.poll() is None:
                client.kill()
                client.wait(timeout=10)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process.returncode not in (0, -9):
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(
                f"f.quit mixed clients compositor exited {process.returncode}: "
                f"{stderr}"
            )


def run_signal_logout(
    compositor: Path,
    temporary: Path,
    signal_number: signal.Signals,
    state_home: Path,
    malformed: bool,
) -> None:
    label = signal_number.name.lower()
    runtime = temporary / f"{label}-runtime"
    runtime.mkdir(mode=0o700)
    config = temporary / f"{label}.twmrc"
    config.write_text(config_text(restore=malformed), encoding="utf-8")
    state_path = state_home / "wtwm" / "state"
    if malformed:
        state_path.parent.mkdir(parents=True, mode=0o700)
        state_path.write_bytes(MALFORMED_STATE)
    control_path = temporary / f"{label}-control.sock"
    display_name = f"wm8-lifecycle-{label}-{os.getpid()}"
    process = subprocess.Popen(
        compositor_command(
            compositor, config, control_path, display_name, "exit 0"
        ),
        env=environment(runtime, state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    control: Control | None = None
    try:
        control = Control(control_path, process)
        control.socket.settimeout(10)
        if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
            raise RuntimeError(f"{signal_number.name} session was not ready")
        os.kill(process.pid, signal_number)
        if process.wait(timeout=10) != 0:
            raise RuntimeError(f"{signal_number.name} did not exit successfully")
        stderr = process.stderr.read() if process.stderr is not None else ""
        if f"received signal {signal_number.value}; ending the session" not in stderr:
            raise RuntimeError(
                f"{signal_number.name} did not reach orderly cleanup: {stderr!r}"
            )
        if control_path.exists() or (runtime / display_name).exists():
            raise RuntimeError(f"{signal_number.name} left a compositor socket behind")
        if malformed:
            if state_path.read_bytes() != MALFORMED_STATE:
                raise RuntimeError("malformed state changed during signal logout")
            if "RestartPreviousState rejected saved state" not in stderr:
                raise RuntimeError("malformed state was not diagnosed")
        elif state_path.exists():
            raise RuntimeError(f"{signal_number.name} implicitly saved state")
    finally:
        if control is not None:
            control.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if process.returncode not in (0, -9):
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(
                f"{signal_number.name} compositor exited {process.returncode}: "
                f"{stderr}"
            )


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-session-lifecycle-") as value:
        temporary = Path(value)
        recovery_state_home = run_failed_startups(compositor, temporary)
        run_f_quit_mixed_clients(
            compositor, wayland_client, x11_client, temporary
        )
        for signal_number in (
            signal.SIGINT,
            signal.SIGHUP,
            signal.SIGQUIT,
            signal.SIGTERM,
        ):
            state_home = recovery_state_home if signal_number == signal.SIGTERM \
                else temporary / f"{signal_number.name.lower()}-state"
            run_signal_logout(
                compositor,
                temporary,
                signal_number,
                state_home,
                malformed=signal_number == signal.SIGTERM,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", required=True, type=Path)
    parser.add_argument("--wayland-client", required=True, type=Path)
    parser.add_argument("--x11-client", required=True, type=Path)
    args = parser.parse_args()
    run(
        args.compositor.resolve(),
        args.wayland_client.resolve(),
        args.x11_client.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
