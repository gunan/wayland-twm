#!/usr/bin/env python3
"""Verify in-place f.restart/f.twmrc with native and Xwayland clients."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-restart-native"
X11_TITLE = "wtwm-restart-x11"


def config_text(*, no_title: bool) -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        + ("NoTitle\n" if no_title else "")
        + "Button1 = : root : f.restart\n"
        + "Button2 = : root : f.twmrc\n"
    )


def restart(control: Control, button: int) -> None:
    control.command("POINTER 790 590")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")
    control.command("WAIT 2")


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {item["title"] for item in windows} == {NATIVE_TITLE, X11_TITLE}
        and all(item["mapped"] for item in windows)
    )


def snapshot(state: dict[str, object]) -> dict[str, tuple[int, str, int | None]]:
    result: dict[str, tuple[int, str, int | None]] = {}
    for item in state["windows"]:
        result[str(item["title"])] = (
            int(item["id"]),
            str(item["type"]),
            int(item["xid"]) if item["type"] == "x11" else None,
        )
    return result


def session_snapshot(state: dict[str, object]) -> dict[str, object]:
    return {
        "focus": state["focus"],
        "active": state["active"],
        "focus_root": state["focus_root"],
        "windows": {
            str(item["title"]): {
                key: item[key]
                for key in ("stack", "x", "y", "width", "height", "iconified")
            }
            for item in state["windows"]
        },
    }


def send_prefix(channel: ClientChannel, command: str, prefix: str) -> None:
    channel.stdin.write((command + "\n").encode("utf-8"))
    channel.stdin.flush()
    channel.expect_prefix(prefix)


def assert_preserved(
    control: Control,
    expected: dict[str, tuple[int, str, int | None]],
    expected_session: dict[str, object],
    decorated: bool,
    native_process: subprocess.Popen[bytes],
    native: ClientChannel,
    x11_process: subprocess.Popen[bytes],
    x11: ClientChannel,
) -> dict[str, object]:
    state = wait_state(control, mapped_pair, "preserved restart clients")
    if snapshot(state) != expected:
        raise RuntimeError(
            f"restart replaced or changed client identities: {state!r}"
        )
    observed_session = session_snapshot(state)
    if observed_session != expected_session:
        raise RuntimeError(
            "restart changed focus, stacking, geometry, or iconic state: "
            f"expected={expected_session!r}, observed={observed_session!r}, "
            f"state={state!r}"
        )
    if any(bool(item["decorated"]) != decorated for item in state["windows"]):
        raise RuntimeError(
            f"restart did not apply the active decoration policy: {state!r}"
        )
    if native_process.poll() is not None or x11_process.poll() is not None:
        raise RuntimeError("restart disconnected a client process")
    send_prefix(native, "REPORT preserved", "OK REPORT preserved ")
    send_prefix(x11, "REPORT", "OK REPORT close=0 mapped=1 cycle=0")
    if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
        raise RuntimeError("restart replaced the compositor control connection")
    return state


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-restart-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "restart.twmrc"
        config.write_text(config_text(no_title=False), encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        display_name = f"wtwm-m8-restart-{os.getpid()}"
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
        native: ClientChannel | None = None
        x11: ClientChannel | None = None
        try:
            control = Control(control_path, process)
            control.socket.settimeout(10)
            control.command("SET ANIMATION_MS 0")
            control.command("OUTPUT 800 600")
            control.command("WAIT 2")

            wayland_environment = environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = display_name
            native_process = subprocess.Popen(
                [str(wayland_client), NATIVE_TITLE, "org.wtwm.Restart"],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((NATIVE_TITLE, native_process))
            native = ClientChannel(native_process, NATIVE_TITLE)
            native.expect(f"OK READY {NATIVE_TITLE}")
            native.command("ARM preserved", "OK ARMED preserved")

            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = wait_path(display_marker)
            x11_process = subprocess.Popen(
                [str(x11_client), X11_TITLE, "restart", "WtwmRestart"],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((X11_TITLE, x11_process))
            x11 = ClientChannel(x11_process, X11_TITLE)
            x11.expect_prefix(f"OK READY {X11_TITLE} ")

            initial = wait_state(control, mapped_pair, "initial restart clients")
            identities = snapshot(initial)
            session = session_snapshot(initial)
            if identities[NATIVE_TITLE][1] != "wayland" or \
                    identities[X11_TITLE][1] != "x11":
                raise RuntimeError(f"restart fixtures used wrong protocols: {initial!r}")
            if not all(item["decorated"] for item in initial["windows"]):
                raise RuntimeError(f"initial configuration was not active: {initial!r}")

            # f.restart reparses and applies the valid replacement in-process.
            config.write_text(config_text(no_title=True), encoding="utf-8")
            restart(control, 272)
            assert_preserved(
                control, identities, session, False, native_process, native,
                x11_process, x11,
            )

            # f.twmrc is the same action.  A malformed replacement is rejected
            # atomically, leaving both the active configuration and clients live.
            config.write_text('Button1 = : root : f.restart\n"unterminated\n',
                              encoding="utf-8")
            restart(control, 273)
            assert_preserved(
                control, identities, session, False, native_process, native,
                x11_process, x11,
            )

            # The alias remains usable after rejection and applies the next
            # valid replacement without reconnecting either protocol client.
            config.write_text(config_text(no_title=False), encoding="utf-8")
            restart(control, 273)
            assert_preserved(
                control, identities, session, True, native_process, native,
                x11_process, x11,
            )

            native.command("EXIT", "OK EXIT")
            x11.command("EXIT", "OK EXIT")
            if wait_process(native_process, NATIVE_TITLE) != 0:
                raise RuntimeError("native restart fixture did not exit cleanly")
            if wait_process(x11_process, X11_TITLE) != 0:
                raise RuntimeError("X11 restart fixture did not exit cleanly")
            control.command("QUIT")
            if process.wait(timeout=10) != 0:
                raise RuntimeError("compositor did not exit cleanly")
        finally:
            if control is not None:
                control.close()
            for _, client in clients:
                if client.poll() is None:
                    client.kill()
                    client.wait(timeout=10)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if process.returncode not in (0, -9):
                stderr = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(
                    f"compositor exited with {process.returncode}: {stderr}"
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
