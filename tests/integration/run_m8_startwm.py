#!/usr/bin/env python3
"""Verify safe and rejected f.startwm handoffs with live clients."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-startwm-native"
X11_TITLE = "wtwm-startwm-x11"


def config_text(
    program: str,
    alternate: Path,
    invalid: Path,
    marker: Path,
    *,
    no_title: bool,
) -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        + ("NoTitle\n" if no_title else "")
        + f'Button1 = : root : f.startwm "{program} -f {alternate}"\n'
        + f'Button2 = : root : f.startwm "touch {marker}"\n'
        + f'Button3 = : root : f.startwm "{program} -f {invalid}"\n'
        + f'Button4 = : root : f.startwm "{program}"\n'
    )


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {item["title"] for item in windows} == {NATIVE_TITLE, X11_TITLE}
        and all(item["mapped"] for item in windows)
    )


def identities(state: dict[str, object]) -> dict[str, tuple[int, str, int | None]]:
    return {
        str(item["title"]): (
            int(item["id"]),
            str(item["type"]),
            int(item["xid"]) if item["type"] == "x11" else None,
        )
        for item in state["windows"]
    }


def session(state: dict[str, object]) -> dict[str, object]:
    return {
        "focus_root": state["focus_root"],
        "active": state["active"],
        "focus": state["focus"],
        "windows": {
            str(item["title"]): {
                key: item[key]
                for key in ("stack", "x", "y", "width", "height", "iconified")
            }
            for item in state["windows"]
        },
    }


def invoke(control: Control, raw_button: int) -> None:
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 2")


def send_prefix(channel: ClientChannel, command: str, prefix: str) -> None:
    channel.stdin.write((command + "\n").encode("utf-8"))
    channel.stdin.flush()
    channel.expect_prefix(prefix)


def assert_preserved(
    control: Control,
    expected_identities: dict[str, tuple[int, str, int | None]],
    expected_session: dict[str, object],
    decorated: bool,
    native_process: subprocess.Popen[bytes],
    native: ClientChannel,
    x11_process: subprocess.Popen[bytes],
    x11: ClientChannel,
) -> dict[str, object]:
    state = wait_state(control, mapped_pair, "preserved startwm clients")
    if identities(state) != expected_identities:
        raise RuntimeError(f"f.startwm replaced client identities: {state!r}")
    observed_session = session(state)
    if observed_session != expected_session:
        raise RuntimeError(
            "f.startwm changed session state: "
            f"expected={expected_session!r}, observed={observed_session!r}"
        )
    if any(bool(item["decorated"]) != decorated for item in state["windows"]):
        raise RuntimeError(f"f.startwm applied the wrong configuration: {state!r}")
    if native_process.poll() is not None or x11_process.poll() is not None:
        raise RuntimeError("f.startwm disconnected a client process")
    send_prefix(native, "REPORT handoff", "OK REPORT handoff ")
    send_prefix(x11, "REPORT", "OK REPORT close=0 mapped=1 cycle=0")
    if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
        raise RuntimeError("f.startwm replaced the compositor control connection")
    return state


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-startwm-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "initial.twmrc"
        alternate = temporary / "alternate.twmrc"
        invalid = temporary / "invalid.twmrc"
        marker = temporary / "unsupported-command-ran"
        program = compositor.name
        config.write_text(
            config_text(program, alternate, invalid, marker, no_title=False),
            encoding="utf-8",
        )
        alternate.write_text(
            config_text(program, alternate, invalid, marker, no_title=True),
            encoding="utf-8",
        )
        invalid.write_text('NoTitle\n"unterminated\n', encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {display_marker}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        display_name = f"wtwm-m8-startwm-{os.getpid()}"
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
                [str(wayland_client), NATIVE_TITLE, "org.wtwm.Startwm"],
                env=wayland_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((NATIVE_TITLE, native_process))
            native = ClientChannel(native_process, NATIVE_TITLE)
            native.expect(f"OK READY {NATIVE_TITLE}")
            native.command("ARM handoff", "OK ARMED handoff")

            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = wait_path(display_marker)
            x11_process = subprocess.Popen(
                [str(x11_client), X11_TITLE, "startwm", "WtwmStartwm"],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append((X11_TITLE, x11_process))
            x11 = ClientChannel(x11_process, X11_TITLE)
            x11.expect_prefix(f"OK READY {X11_TITLE} ")

            state = wait_state(control, mapped_pair, "initial startwm clients")
            expected_identities = identities(state)
            if expected_identities[NATIVE_TITLE][1] != "wayland" or \
                    expected_identities[X11_TITLE][1] != "x11":
                raise RuntimeError(f"startwm fixtures used wrong protocols: {state!r}")
            if not all(item["decorated"] for item in state["windows"]):
                raise RuntimeError(f"initial startwm config was not active: {state!r}")
            control.command("POINTER 790 590")
            state = wait_state(
                control,
                lambda item: item["pointer_context"] == "root",
                "startwm root binding",
            )
            expected_session = session(state)

            # A direct invocation of this compositor with -f is a safe
            # in-process handoff and adopts the replacement config path.
            invoke(control, 272)
            assert_preserved(
                control, expected_identities, expected_session, False,
                native_process, native, x11_process, x11,
            )

            # A different executable has no transferable Wayland state.  It
            # must not run and must not destroy the active session.
            invoke(control, 274)
            assert_preserved(
                control, expected_identities, expected_session, False,
                native_process, native, x11_process, x11,
            )
            if marker.exists():
                raise RuntimeError("unsupported f.startwm command was executed")

            # A supported self-handoff whose replacement config is invalid is
            # rejected atomically with the adopted valid config still active.
            invoke(control, 273)
            assert_preserved(
                control, expected_identities, expected_session, False,
                native_process, native, x11_process, x11,
            )

            # The no-argument self target reloads the path adopted by the first
            # handoff rather than silently reverting to the startup config.
            alternate.write_text(
                config_text(program, alternate, invalid, marker, no_title=False),
                encoding="utf-8",
            )
            invoke(control, 275)
            assert_preserved(
                control, expected_identities, expected_session, True,
                native_process, native, x11_process, x11,
            )

            native.command("EXIT", "OK EXIT")
            x11.command("EXIT", "OK EXIT")
            if wait_process(native_process, NATIVE_TITLE) != 0:
                raise RuntimeError("native startwm fixture did not exit cleanly")
            if wait_process(x11_process, X11_TITLE) != 0:
                raise RuntimeError("X11 startwm fixture did not exit cleanly")
            control.command("QUIT")
            if process.wait(timeout=10) != 0:
                raise RuntimeError("startwm compositor did not exit cleanly")
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
                    f"startwm compositor exited with {process.returncode}: {stderr}"
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
