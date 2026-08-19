#!/usr/bin/env python3
"""Exercise hostile public Wayland requests without losing the session."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

from run_compositor import Control


SURVIVOR_TITLE = "m9-protocol-survivor"


def wait_line(
    process: subprocess.Popen[str], expected: str, *, prefix: bool = False
) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    observed: list[str] = []
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        observed.append(line)
        if (prefix and line.startswith(expected)) or (not prefix and line == expected):
            return line
        if process.poll() is not None and line == "":
            break
    raise RuntimeError(
        f"timed out waiting for {expected!r}; observed={observed!r}, "
        f"returncode={process.poll()}"
    )


def wait_one_of(process: subprocess.Popen[str], expected: set[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    observed: list[str] = []
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        observed.append(line)
        if line in expected:
            return line
        if process.poll() is not None and line == "":
            break
    raise RuntimeError(
        f"timed out waiting for one of {sorted(expected)!r}; "
        f"observed={observed!r}, returncode={process.poll()}"
    )


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def find_window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {title!r} window: {state!r}")
    return matches[0]


def launch(client: Path, mode: str, environment: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(client), mode],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )


def finish_client(process: subprocess.Popen[str], label: str) -> None:
    try:
        _, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate()
        raise RuntimeError(f"{label} hung; stderr:\n{stderr}")
    if process.returncode != 0:
        raise RuntimeError(f"{label} returned {process.returncode}; stderr:\n{stderr}")


def stop_client(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
    try:
        _, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate()
    return stderr


def assert_responsive(control: Control, *, expected_windows: int | None = None) -> None:
    if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
        raise RuntimeError("test-control PING stopped responding")
    state = control.state()
    if expected_windows is not None and len(state["windows"]) != expected_windows:
        raise RuntimeError(f"unexpected live window count: {state!r}")
    find_window(state, SURVIVOR_TITLE)
    if state["interactive"] or state["menu"] is not None:
        raise RuntimeError(f"rejected request changed interactive state: {state!r}")


def assert_log_evidence(log: str) -> None:
    required = (
        "event=client_request protocol=xdg_shell action=move outcome=rejected",
        "event=client_request protocol=xdg_shell action=resize outcome=rejected",
        "event=client_request protocol=xdg_shell action=show_window_menu outcome=rejected",
        "event=client_request protocol=wl_pointer action=set_cursor outcome=rejected",
        "event=client_size protocol=xdg_shell boundary=xdg_commit outcome=adjusted",
        "event=client_size protocol=xdg_shell role=popup boundary=popup_create outcome=rejected",
    )
    missing = [marker for marker in required if marker not in log]
    if missing:
        raise RuntimeError(
            "missing structured hostile-request evidence: " + ", ".join(missing)
            + f"\ncompositor log:\n{log}"
        )
    forbidden = ("ERROR: AddressSanitizer", "runtime error:", "deadlock", "assertion failed")
    found = [marker for marker in forbidden if marker in log]
    if found:
        raise RuntimeError(f"fatal diagnostic in compositor log: {found!r}\n{log}")


def run(compositor: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m9-protocol-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_name = f"wtwm-m9-protocol-{os.getpid()}"
        config = temporary / "protocol-fuzz.twmrc"
        config.write_text("NoDefaults\nRandomPlacement\n", encoding="utf-8")
        log_path = temporary / "compositor.log"
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        client_environment = environment.copy()
        client_environment["WAYLAND_DISPLAY"] = display_name

        clients: list[subprocess.Popen[str]] = []
        with log_path.open("w", encoding="utf-8") as log_file:
            compositor_process = subprocess.Popen(
                [
                    str(compositor),
                    "-d",
                    "-f",
                    str(config),
                    "--test-control",
                    str(control_path),
                    "--test-socket",
                    display_name,
                    "--test-backend",
                    "headless",
                ],
                env=environment,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
            )
            control: Control | None = None
            try:
                control = Control(control_path, compositor_process)
                control.command("SET ANIMATION_MS 0")
                control.command("SET PLACEMENT_SEED 9")
                control.command("SET FONT DejaVu Sans 10")
                control.command("OUTPUT 800 600")
                control.command("POINTER 790 590")

                survivor = launch(client_binary, "survivor", client_environment)
                clients.append(survivor)
                wait_line(survivor, "MAPPED")
                wait_state(
                    control,
                    lambda state: any(
                        item["title"] == SURVIVOR_TITLE for item in state["windows"]
                    ),
                    "survivor map",
                )
                assert_responsive(control, expected_windows=1)

                geometry = launch(client_binary, "geometry", client_environment)
                clients.append(geometry)
                wait_line(geometry, "MAPPED")
                wait_line(geometry, "GEOMETRY_SENT")
                wait_line(geometry, "SURVIVED")
                finish_client(geometry, "oversized geometry client")
                clients.remove(geometry)
                wait_state(control, lambda state: len(state["windows"]) == 1,
                           "geometry client cleanup")
                assert_responsive(control, expected_windows=1)

                positioner = launch(client_binary, "positioner", client_environment)
                clients.append(positioner)
                wait_line(positioner, "MAPPED")
                wait_line(positioner, "POSITIONER_SENT")
                # A compositor may close only the malformed popup client's
                # connection. The client reports that as success itself.
                wait_one_of(positioner, {"SURVIVED", "DISCONNECTED"})
                finish_client(positioner, "oversized positioner client")
                clients.remove(positioner)
                wait_state(control, lambda state: len(state["windows"]) == 1,
                           "positioner client cleanup")
                assert_responsive(control, expected_windows=1)

                serials = launch(client_binary, "serials", client_environment)
                clients.append(serials)
                wait_line(serials, "MAPPED")
                state = wait_state(
                    control,
                    lambda item: any(
                        window["title"] == "m9-protocol-serials"
                        for window in item["windows"]
                    ),
                    "serial client map",
                )
                target = find_window(state, "m9-protocol-serials")
                pointer_x = int(target["x"]) + int(target["width"]) // 2
                pointer_y = (
                    int(target["y"])
                    + int(target["title_height"])
                    + int(target["height"]) // 2
                )
                control.command(f"POINTER {pointer_x} {pointer_y}")
                pointed = control.state()
                if (
                    pointed["pointer_window"] != "m9-protocol-serials"
                    or pointed["pointer_context"] != "window"
                ):
                    raise RuntimeError(
                        f"serial client did not receive content focus: {pointed!r}"
                    )
                wait_line(serials, "POINTER_ENTER ", prefix=True)
                control.command("BUTTON 272 press")
                pressed = wait_line(serials, "POINTER_BUTTON ", prefix=True)
                if not pressed.endswith(" 272 press"):
                    raise RuntimeError(f"unexpected pointer press event: {pressed!r}")
                control.command("BUTTON 272 release")
                released = wait_line(serials, "POINTER_BUTTON ", prefix=True)
                if not released.endswith(" 272 release"):
                    raise RuntimeError(f"unexpected pointer release event: {released!r}")
                wait_line(serials, "FUZZ_SENT stale=", prefix=True)
                wait_line(serials, "SURVIVED")
                finish_client(serials, "serial fuzz client")
                clients.remove(serials)
                wait_state(control, lambda item: len(item["windows"]) == 1,
                           "serial client cleanup")
                assert_responsive(control, expected_windows=1)

                survivor_error = stop_client(survivor)
                if survivor_error:
                    raise RuntimeError(
                        f"survivor emitted stderr during cleanup:\n{survivor_error}"
                    )
                clients.remove(survivor)
                wait_state(control, lambda state: not state["windows"],
                           "survivor cleanup")
                if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                    raise RuntimeError("compositor stopped responding after cleanup")
                control.command("QUIT")
                compositor_process.wait(timeout=10)
                if compositor_process.returncode != 0:
                    raise RuntimeError(
                        f"compositor returned {compositor_process.returncode}"
                    )
            except Exception:
                for client in clients:
                    stop_client(client)
                if compositor_process.poll() is None:
                    compositor_process.terminate()
                try:
                    compositor_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    compositor_process.kill()
                    compositor_process.wait()
                raise
        assert_log_evidence(log_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    args = parser.parse_args()
    run(args.compositor, args.client)


if __name__ == "__main__":
    main()
