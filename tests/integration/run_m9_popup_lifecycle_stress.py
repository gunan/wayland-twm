#!/usr/bin/env python3
"""Rapidly churn native xdg-popup and parent toplevel lifecycles."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

from run_compositor import Control


DEFAULT_ITERATIONS = 128
MAX_ITERATIONS = 4096
TITLE = "overlay-native"


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
        raise RuntimeError(f"unexpected popup-stress client event: {line!r}")
    raise RuntimeError(f"timed out waiting for popup-stress event {expected!r}")


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


def assert_bounded_state(
    state: dict[str, object], *, mapped: bool, popup_mapped: bool
) -> None:
    windows = state["windows"]
    popups = state["popups"]
    expected_windows = 1 if mapped else 0
    expected_popups = 1 if popup_mapped else 0
    if len(windows) != expected_windows or len(popups) != expected_popups:
        raise RuntimeError(f"lifecycle state is not bounded: {state!r}")
    if state["override_redirect"] or state["icons"] or state["menu"] is not None:
        raise RuntimeError(f"unrelated scene state appeared during popup churn: {state!r}")
    if state["interactive"]:
        raise RuntimeError(f"popup churn leaked an interactive grab: {state!r}")

    if mapped:
        window = windows[0]
        if window["title"] != TITLE or not window["mapped"] or window["iconified"]:
            raise RuntimeError(f"toplevel scene state changed during popup churn: {state!r}")
        if state["focus"] not in (None, TITLE) or state["active"] not in (None, TITLE):
            raise RuntimeError(f"focus escaped the only live toplevel: {state!r}")
    else:
        if state["focus"] is not None or state["active"] is not None:
            raise RuntimeError(f"focus survived parent unmap: {state!r}")
        if state["pointer_window"] == TITLE:
            raise RuntimeError(f"pointer target survived parent unmap: {state!r}")

    if popup_mapped:
        popup = popups[0]
        if popup["depth"] != 1 or not popup["mapped"] or not popup["visible"]:
            raise RuntimeError(f"popup is absent from the live scene: {state!r}")
        if not (0 < popup["width"] <= 640 and 0 < popup["height"] <= 480):
            raise RuntimeError(f"popup geometry is unbounded: {state!r}")
        if (popup["x"] < 0 or popup["y"] < 0 or
                popup["x"] + popup["width"] > 640 or
                popup["y"] + popup["height"] > 480):
            raise RuntimeError(f"popup escaped its output: {state!r}")


def run(compositor_binary: Path, client_binary: Path, iterations: int) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m9-popup-stress-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        socket_name = f"wtwm-m9-popup-{os.getpid()}"
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
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
            state = wait_state(
                control, lambda item: len(item["windows"]) == 1,
                "initial native toplevel map",
            )
            assert_bounded_state(state, mapped=True, popup_mapped=False)

            for iteration in range(1, iterations + 1):
                client_command(client, "MAP_POPUP", "POPUP_MAPPED")
                state = wait_state(
                    control,
                    lambda item: len(item["popups"]) == 1 and
                    item["popups"][0]["mapped"],
                    f"popup map {iteration}",
                )
                assert_bounded_state(state, mapped=True, popup_mapped=True)

                if iteration % 2 == 0:
                    client_command(client, "DESTROY_POPUP", "POPUP_DESTROYED")
                    state = wait_state(
                        control, lambda item: not item["popups"],
                        f"explicit popup destroy {iteration}",
                    )
                    assert_bounded_state(state, mapped=True, popup_mapped=False)
                else:
                    client_command(client, "UNMAP_TOPLEVEL", "TOPLEVEL_UNMAPPED")
                    state = wait_state(
                        control,
                        lambda item: not item["windows"] and not item["popups"],
                        f"parent unmap cleanup {iteration}",
                    )
                    assert_bounded_state(state, mapped=False, popup_mapped=False)
                    client_command(
                        client, "DROP_DISMISSED_POPUP", "DISMISSED_POPUP_DROPPED"
                    )
                    client_command(client, "REMAP_TOPLEVEL", "TOPLEVEL_REMAPPED")
                    state = wait_state(
                        control, lambda item: len(item["windows"]) == 1,
                        f"parent remap {iteration}",
                    )
                    assert_bounded_state(state, mapped=True, popup_mapped=False)

                if iteration % 8 == 0:
                    if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                        raise RuntimeError("compositor liveness probe failed")

            client_command(client, "EXIT", "EXITING")
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"popup-stress client returned {client.returncode}")
            client = None
            state = wait_state(
                control, lambda item: not item["windows"] and not item["popups"],
                "final client teardown",
            )
            assert_bounded_state(state, mapped=False, popup_mapped=False)
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
                _, compositor_error = compositor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
                _, compositor_error = compositor.communicate()
            raise RuntimeError(
                f"{error}\nclient stderr:\n{client_error}\n"
                f"compositor stderr:\n{compositor_error}"
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
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    arguments = parser.parse_args()
    if not 1 <= arguments.iterations <= MAX_ITERATIONS:
        parser.error(f"--iterations must be between 1 and {MAX_ITERATIONS}")
    run(
        arguments.compositor.resolve(),
        arguments.client.resolve(),
        arguments.iterations,
    )


if __name__ == "__main__":
    main()
