#!/usr/bin/env python3
"""Exercise native xdg-shell toplevel, remap, popup, and destroy lifecycles."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_client_line(client: subprocess.Popen[str], expected: str) -> None:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([client.stdout], [], [], deadline - time.monotonic())
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected:
            return
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected lifecycle client event: {line!r}")
    raise RuntimeError(f"timed out waiting for lifecycle client event {expected!r}")


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
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def assert_clean_state(state: dict[str, object]) -> None:
    if state["windows"] or state["popups"]:
        raise RuntimeError(f"destroyed surfaces remain in compositor state: {state!r}")
    if state["focus"] is not None or state["menu"] is not None or state["interactive"]:
        raise RuntimeError(f"focus, menu, or interaction survived unmap/destroy: {state!r}")


def assert_popups_constrained(state: dict[str, object]) -> None:
    popups = state["popups"]
    if len(popups) != 2 or {popup["depth"] for popup in popups} != {1, 2}:
        raise RuntimeError(f"parent and nested popup were not both managed: {state!r}")
    for popup in popups:
        if not popup["mapped"] or not popup["visible"]:
            raise RuntimeError(f"mapped popup is absent from the scene: {popup!r}")
        if popup["width"] <= 0 or popup["height"] <= 0:
            raise RuntimeError(f"popup has invalid configured geometry: {popup!r}")
        if (popup["x"] < 0 or popup["y"] < 0 or
                popup["x"] + popup["width"] > 640 or
                popup["y"] + popup["height"] > 480):
            raise RuntimeError(f"popup escaped the usable output area: {popup!r}")


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("capture is not an 8-bit PPM P6 image")
    width, height = (int(value) for value in fields[1].split())
    if len(fields[3]) != width * height * 3:
        raise RuntimeError("capture has a truncated pixel payload")
    return width, height, fields[3]


def capture(control: Control, path: Path) -> bytes:
    control.command("WAIT 3")
    control.command(f"CAPTURE {path}")
    first = path.read_bytes()
    control.command("WAIT 3")
    control.command(f"CAPTURE {path}")
    second = path.read_bytes()
    if first != second:
        raise RuntimeError("title lifecycle capture was not stable")
    return second


def titlebar_pixels(data: bytes, window: dict[str, object]) -> bytes:
    width, height, pixels = parse_ppm(data)
    border = int(window["border_width"])
    left = int(window["x"]) + border
    top = int(window["y"]) + border
    right = left + int(window["width"])
    bottom = top + int(window["title_bar_height"])
    if left < 0 or top < 0 or right > width or bottom > height:
        raise RuntimeError(f"titlebar lies outside capture: {window!r}")
    row_bytes = width * 3
    return b"".join(
        pixels[y * row_bytes + left * 3:y * row_bytes + right * 3]
        for y in range(top, bottom)
    )


def exercise_dynamic_title_rendering(
    control: Control, client: subprocess.Popen[str], temporary: Path,
) -> dict[str, object]:
    client_command(client, "TITLE_FOOT", "TITLE_FOOT_UPDATED")
    state = wait_state(
        control,
        lambda item: item["windows"] and
        item["windows"][0]["title"] == "foot" and
        item["windows"][0]["app_id"] == "org.wtwm.LifecycleInitial",
        "foot title without app_id mutation",
    )
    window = state["windows"][0]
    foot_pixels = titlebar_pixels(
        capture(control, temporary / "title-foot.ppm"), window,
    )

    client_command(client, "TITLE_DYNAMIC", "TITLE_DYNAMIC_UPDATED")
    state = wait_state(
        control,
        lambda item: item["windows"] and
        item["windows"][0]["title"] == "project-shell-title" and
        item["windows"][0]["app_id"] == "org.wtwm.LifecycleInitial",
        "dynamic title without app_id mutation",
    )
    window = state["windows"][0]
    dynamic_pixels = titlebar_pixels(
        capture(control, temporary / "title-dynamic.ppm"), window,
    )
    if dynamic_pixels == foot_pixels:
        raise RuntimeError(
            "xdg title metadata changed but the visible titlebar stayed at foot"
        )

    client_command(client, "APP_ID_DYNAMIC", "APP_ID_DYNAMIC_UPDATED")
    state = wait_state(
        control,
        lambda item: item["windows"] and
        item["windows"][0]["title"] == "project-shell-title" and
        item["windows"][0]["app_id"] == "org.wtwm.DynamicIdentity",
        "app_id mutation without title mutation",
    )
    window = state["windows"][0]
    app_id_pixels = titlebar_pixels(
        capture(control, temporary / "app-id-dynamic.ppm"), window,
    )
    if app_id_pixels != dynamic_pixels:
        raise RuntimeError("app_id text replaced the visible xdg title")
    return state


def exercise_target_cleanup(control: Control, state: dict[str, object]) -> None:
    window = state["windows"][0]
    control.command(f"POINTER {window['x'] + 100} {window['y'] + 8}")
    control.command("BUTTON 272 press")
    if not control.state()["interactive"]:
        raise RuntimeError("title press did not begin an interactive operation")
    control.command("BUTTON 273 press")
    control.command("BUTTON 273 release")
    # An aborted move can leave the cursor at a constrained-move warp point.
    # Re-establish the title hit target before exercising its Button3 binding.
    state = control.state()
    window = state["windows"][0]
    control.command(f"POINTER {window['x'] + 100} {window['y'] + 8}")
    control.command("BUTTON 273 press")
    target_state = control.state()
    if target_state["menu"] is None:
        raise RuntimeError("title binding did not open a target-owned menu")


def run(compositor: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-xdg-lifecycle-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_name = f"wtwm-lifecycle-{os.getpid()}"
        config = temporary / "lifecycle.twmrc"
        config.write_text(
            'Button3 = : title : f.menu "lifecycle"\n'
            'Menu "lifecycle" { "Lifecycle" f.title "Nothing" f.nop }\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config),
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
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            client_environment = environment.copy()
            client_environment["WAYLAND_DISPLAY"] = display_name
            client = subprocess.Popen(
                [str(client_binary)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )

            wait_client_line(client, "MAPPED 1")
            state = wait_state(control, lambda item: len(item["windows"]) == 1,
                               "initial toplevel map")
            window = state["windows"][0]
            initial_coordinates = (window["x"], window["y"])
            if (window["title"], window["app_id"]) != (
                    "wtwm-lifecycle-initial", "org.wtwm.LifecycleInitial"):
                raise RuntimeError(f"initial metadata is stale: {window!r}")

            state = exercise_dynamic_title_rendering(control, client, temporary)

            client_command(client, "METADATA", "METADATA_UPDATED")
            state = wait_state(
                control,
                lambda item: item["windows"] and
                item["windows"][0]["title"] == "wtwm-lifecycle-updated" and
                item["windows"][0]["app_id"] == "org.wtwm.LifecycleUpdated",
                "title and app_id update",
            )
            exercise_target_cleanup(control, state)
            client_command(client, "UNMAP", "UNMAPPED")
            state = wait_state(control, lambda item: not item["windows"],
                               "toplevel unmap cleanup")
            assert_clean_state(state)
            control.command("BUTTON 272 release")
            control.command("BUTTON 273 release")

            client_command(client, "REMAP", "MAPPED 2")
            state = wait_state(control, lambda item: len(item["windows"]) == 1,
                               "toplevel remap")
            remap_coordinates = (state["windows"][0]["x"],
                                 state["windows"][0]["y"])
            if remap_coordinates != initial_coordinates:
                raise RuntimeError(f"first remap changed placement: {state!r}")
            if (state["windows"][0]["title"], state["windows"][0]["app_id"]) != (
                    "wtwm-lifecycle-updated", "org.wtwm.LifecycleUpdated"):
                raise RuntimeError(f"remapped metadata is stale: {state!r}")

            client_command(client, "CREATE_POPUPS", "POPUPS_MAPPED")
            state = wait_state(control, lambda item: len(item["popups"]) == 2,
                               "nested popup map")
            assert_popups_constrained(state)

            client_command(client, "UNMAP", "UNMAPPED")
            state = wait_state(control, lambda item: not item["popups"],
                               "rooted popup dismissal on parent unmap")
            assert_clean_state(state)
            client_command(client, "DROP_DISMISSED_POPUPS",
                           "DISMISSED_POPUPS_DROPPED")

            client_command(client, "REMAP", "MAPPED 3")
            state = wait_state(control, lambda item: len(item["windows"]) == 1,
                               "second toplevel remap")
            remap_coordinates = (state["windows"][0]["x"],
                                 state["windows"][0]["y"])
            if remap_coordinates != initial_coordinates:
                raise RuntimeError(f"second remap changed placement: {state!r}")
            client_command(client, "CREATE_POPUPS", "POPUPS_MAPPED")
            state = wait_state(control, lambda item: len(item["popups"]) == 2,
                               "second nested popup map")
            assert_popups_constrained(state)
            client_command(client, "DESTROY_POPUPS", "POPUPS_DESTROYED")
            state = wait_state(control, lambda item: not item["popups"],
                               "explicit popup destroy")
            if len(state["windows"]) != 1:
                raise RuntimeError(f"popup destroy damaged its toplevel: {state!r}")

            exercise_target_cleanup(control, state)
            client_command(client, "DESTROY_TOPLEVEL", "TOPLEVEL_DESTROYED")
            state = wait_state(control, lambda item: not item["windows"],
                               "mapped toplevel destroy cleanup")
            assert_clean_state(state)
            control.command("BUTTON 272 release")
            control.command("BUTTON 273 release")
            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"lifecycle client returned {client.returncode}")
            client = None

            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
        except Exception as error:
            if client is not None and client.poll() is None:
                client.terminate()
            client_error = ""
            if client is not None:
                try:
                    _, client_error = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    _, client_error = client.communicate()
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
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
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.compositor.resolve(), arguments.client.resolve())


if __name__ == "__main__":
    main()
