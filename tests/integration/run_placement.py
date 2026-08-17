#!/usr/bin/env python3
"""Exercise twm placement policy through Xwayland and native test state."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_line(process: subprocess.Popen[str], expected: str) -> None:
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], 10)
    if not readable or process.stdout.readline().rstrip("\n") != expected:
        raise RuntimeError(f"client did not report {expected}")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    for item in state["windows"]:
        if item["title"] == title:
            return item
    raise KeyError(title)


def wait_windows(control: Control, titles: set[str]) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if titles <= {item["title"] for item in state["windows"]}:
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {sorted(titles)}: {control.state()!r}")


def wait_mapped_window(control: Control, title: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        try:
            item = window(state, title)
        except KeyError:
            pass
        else:
            if item["mapped"] and not item["placement_pending"]:
                return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for mapped {title!r}: {control.state()!r}")


def map_serial_windows(control: Control, client: subprocess.Popen[str],
                       scenario: str) -> None:
    if scenario not in ("random", "edge"):
        return
    titles = ["placement-random-1", "placement-random-2"]
    titles.append(
        "placement-random-3" if scenario == "random"
        else "placement-random-oversized"
    )
    wait_mapped_window(control, titles[0])
    assert client.stdin is not None
    for title in titles[1:]:
        client.stdin.write("NEXT\n")
        client.stdin.flush()
        wait_line(client, "MAPPED")
        wait_mapped_window(control, title)


def wait_xwayland_unmapped(
    control: Control, xid: int, title: str
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        lifecycle = [
            item for item in state["xwayland_lifecycle"] if int(item["xid"]) == xid
        ]
        if (
            not any(item["title"] == title for item in state["windows"])
            and len(lifecycle) == 1
            and not lifecycle[0]["associated"]
            and not lifecycle[0]["mapped"]
            and not lifecycle[0]["has_buffer"]
        ):
            return state
        time.sleep(0.01)
    raise RuntimeError(
        f"timed out waiting for Xwayland to unmap {title!r}: {control.state()!r}"
    )


def wait_interaction(control: Control, title: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        interaction = state["interaction"]
        if isinstance(interaction, dict) and interaction.get("window") == title:
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for placement of {title!r}: {control.state()!r}")


def perform_interactive_placements(
    control: Control,
    steps: list[tuple[str, tuple[int, int], str]],
) -> dict[str, tuple[int, int, int, int, str]]:
    dynamic: dict[str, tuple[int, int, int, int, str]] = {}
    buttons = {"confirm": 272, "resize": 274, "fill": 273}
    for title, point, action in steps:
        state = wait_interaction(control, title)
        item = window(state, title)
        if item["mapped"] or not item["placement_pending"]:
            raise RuntimeError(f"pending placement became visible: {state!r}")
        interaction = state["interaction"]
        if interaction["intent"] != "placement":
            raise RuntimeError(f"wrong placement intent: {interaction!r}")
        control.command(f"POINTER {point[0]} {point[1]}")
        preview = control.state()["interaction"]["preview"]
        button = buttons[action]
        control.command(f"BUTTON {button} press")
        if action == "confirm":
            pressed = control.state()
            if pressed["interaction"]["intent"] != "placement-confirm":
                raise RuntimeError(f"Button1 did not enter confirm phase: {pressed!r}")
            if window(pressed, title)["mapped"]:
                raise RuntimeError(f"Button1 press exposed the client early: {pressed!r}")
            control.command(f"BUTTON {button} release")
        elif action == "resize":
            resizing = control.state()
            if resizing["interaction"]["intent"] != "placement-resize":
                raise RuntimeError(f"Button2 did not enter placement resize: {resizing!r}")
            original = resizing["interaction"]["preview"]
            control.command(
                f"POINTER {int(original['x']) + int(item['outer_width']) + 31} "
                f"{int(original['y']) + int(item['outer_height']) + 21}"
            )
            resized = control.state()["interaction"]["preview"]
            if (int(resized["width"]), int(resized["height"])) == (
                int(original["width"]), int(original["height"])
            ):
                raise RuntimeError(f"Button2 placement resize did not change size: {resized!r}")
            control.command(f"BUTTON {button} release")
        else:
            # Reference Button3 fills and completes on press; its release is ordinary input.
            control.command(f"BUTTON {button} release")
        state = wait_windows(control, {title})
        placed = window(state, title)
        deadline = time.monotonic() + 10
        while (not placed["mapped"] or placed["placement_pending"]) and time.monotonic() < deadline:
            time.sleep(0.01)
            placed = window(control.state(), title)
        if not placed["mapped"] or placed["placement_pending"]:
            raise RuntimeError(f"placement did not expose {title!r}: {control.state()!r}")
        dynamic[title] = (
            int(placed["x"]), int(placed["y"]), int(placed["width"]),
            int(placed["height"]), str(placed["placement"]),
        )
        if action == "confirm" and dynamic[title][:2] != (
            int(preview["x"]), int(preview["y"])
        ):
            raise RuntimeError(f"confirmed outline did not become the frame: {placed!r}")
    return dynamic


def run_case(compositor: Path, client_binary: Path, scenario: str,
             config_text: str, output: tuple[int, int], cursor: tuple[int, int],
             expected: dict[str, tuple[int, int, int, int, str]],
             remap: bool = False,
             interactive: list[tuple[str, tuple[int, int], str]] | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix=f"wtwm-placement-{scenario}-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "placement.twmrc"
        config.write_text(config_text, encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        process = subprocess.Popen(
            [str(compositor), "-f", str(config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-placement-{os.getpid()}-{scenario}",
             "--test-backend", "headless"],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command(f"OUTPUT {output[0]} {output[1]}")
            control.command(f"SET CURSOR {cursor[0]} {cursor[1]}")
            control.command("SET PLACEMENT_SEED 0")
            control.command("TRACE CLEAR")
            display = wait_path(display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary), scenario], env=client_environment,
                text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=1,
            )
            wait_line(client, "READY")
            map_serial_windows(control, client, scenario)
            dynamic = perform_interactive_placements(control, interactive or [])
            expected = {**dynamic, **expected}
            state = wait_windows(control, set(expected))
            for title, values in expected.items():
                item = window(state, title)
                actual = (int(item["x"]), int(item["y"]), int(item["width"]),
                          int(item["height"]), str(item["placement"]))
                if actual != values:
                    raise RuntimeError(
                        f"{scenario} placement mismatch for {title}: "
                        f"expected={values!r} actual={actual!r} state={state!r}"
                    )
            trace = control.trace()
            trace_placements = {
                event["window"]["title"]: event["state"]["placement"]
                for event in trace["events"] if event["event"] == "map"
            }
            for title, values in expected.items():
                if trace_placements.get(title) != values[4]:
                    raise RuntimeError(f"TRACE omitted placement decision: {trace!r}")
            if interactive:
                events = trace["events"]
                for title, _, action in interactive:
                    window_events = [event for event in events
                                     if event["window"]["title"] == title]
                    if not any(event["event"] == "outline" and
                               event["context"] == "move"
                               for event in window_events):
                        raise RuntimeError(f"placement outline missing for {title}: {trace!r}")
                    if not any(event["event"] == "commit" and
                               event["context"] == "placement"
                               for event in window_events):
                        raise RuntimeError(f"placement commit missing for {title}: {trace!r}")
                    if action == "confirm" and not any(
                        event["event"] == "confirm" for event in window_events
                    ):
                        raise RuntimeError(f"placement confirm missing for {title}: {trace!r}")
            if remap:
                for cycle in range(3):
                    before = window(state, "placement-remap")
                    assert client.stdin is not None
                    client.stdin.write("UNMAP\n")
                    client.stdin.flush()
                    wait_line(client, "UNMAPPED")
                    wait_xwayland_unmapped(
                        control, int(before["xid"]), "placement-remap"
                    )
                    client.stdin.write("REMAP\n")
                    client.stdin.flush()
                    wait_line(client, "REMAPPED")
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        state = control.state()
                        try:
                            after = window(state, "placement-remap")
                        except KeyError:
                            pass
                        else:
                            if after["placement"] == "remapped":
                                break
                        time.sleep(0.01)
                    else:
                        raise RuntimeError(
                            f"remap cycle {cycle + 1} never stabilized: {state!r}"
                        )
                    if (after["x"], after["y"]) != (before["x"], before["y"]):
                        raise RuntimeError(
                            f"remap cycle {cycle + 1} moved the frame: "
                            f"before={before!r} after={after!r}"
                        )
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                try:
                    client.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.returncode not in (0, -15):
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"compositor failed ({process.returncode}): {stderr}")


def run_native_translation(compositor: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-placement-native-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display = f"wtwm-placement-native-{os.getpid()}"
        config = temporary / "placement.twmrc"
        config.write_text("NoTitle\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime), "WLR_RENDERER": "pixman"})
        process = subprocess.Popen(
            [str(compositor), "-f", str(config), "--test-control", str(control_path),
             "--test-socket", display, "--test-backend", "headless"],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, process)
            control.command("OUTPUT 640 480")
            control.command("SET CURSOR 70 80")
            control.command("SET PLACEMENT_SEED 13")
            client_environment = environment.copy()
            client_environment["WAYLAND_DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "MAPPED 1")
            state = wait_windows(control, {"wtwm-lifecycle-initial"})
            item = window(state, "wtwm-lifecycle-initial")
            if (item["x"], item["y"], item["placement"]) != (70, 80, "pointer"):
                raise RuntimeError(f"native pointer translation drifted: {state!r}")
            if state["interactive"] or item["placement_pending"]:
                raise RuntimeError(f"native map incorrectly blocked on X11 placement: {state!r}")
            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"native placement client failed: {client.returncode}")
            client = None
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"native placement compositor failed: {process.returncode}")
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def run(compositor: Path, client: Path, native_client: Path) -> None:
    run_case(compositor, client, "us", 'UsePPosition "off"\n', (640, 480),
             (17, 19), {"placement-us": (11, 13, 100, 80, "requested")})
    run_case(compositor, client, "nohint", 'UsePPosition "off"\n', (640, 480),
             (17, 19), {"placement-nohint": (17, 19, 100, 80, "interactive")}, interactive=[
                 ("placement-nohint", (17, 19), "confirm"),
             ])
    run_case(compositor, client, "p", 'UsePPosition "on"\n', (640, 480),
             (17, 19), {
                 "placement-p-zero": (0, 0, 100, 80, "requested"),
                 "placement-p-nonzero": (40, 50, 100, 80, "requested"),
             })
    run_case(compositor, client, "p", 'UsePPosition "off"\n', (640, 480),
             (17, 19), {
                 "placement-p-zero": (17, 19, 100, 80, "interactive"),
                 "placement-p-nonzero": (41, 43, 100, 80, "interactive"),
             }, interactive=[
                 ("placement-p-zero", (17, 19), "confirm"),
                 ("placement-p-nonzero", (41, 43), "confirm"),
             ])
    run_case(compositor, client, "p", 'UsePPosition "non-zero"\n', (640, 480),
             (17, 19), {
                 "placement-p-zero": (17, 19, 100, 80, "interactive"),
                 "placement-p-nonzero": (40, 50, 100, 80, "requested"),
             }, interactive=[
                 ("placement-p-zero", (17, 19), "confirm"),
             ])
    run_case(compositor, client, "transient", 'UsePPosition "off"\n',
             (640, 480), (17, 19), {
                 "placement-owner": (10, 12, 100, 80, "requested"),
                 "placement-transient": (77, 88, 90, 60, "requested"),
             })
    run_case(compositor, client, "random", "RandomPlacement\n", (640, 480),
             (17, 19), {
                 "placement-random-1": (50, 50, 100, 80, "random"),
                 "placement-random-2": (80, 80, 100, 80, "random"),
                 "placement-random-3": (110, 110, 100, 80, "random"),
             })
    run_case(compositor, client, "edge", "RandomPlacement\n", (120, 100),
             (17, 19), {
                 "placement-random-1": (20, 20, 100, 80, "random"),
                 "placement-random-2": (20, 20, 100, 80, "random"),
                 "placement-random-oversized": (0, 0, 200, 180, "random"),
             })
    run_case(compositor, client, "max", 'MaxWindowSize "800x600"\n',
             (1000, 800), (17, 19), {
                 "placement-max": (10, 12, 800, 600, "requested"),
             })
    run_case(compositor, client, "defaultmax", "", (640, 480), (17, 19), {
        "placement-default-max-width": (10, 12, 32127, 16, "requested"),
        "placement-default-max-height": (10, 12, 16, 32287, "requested"),
    })
    run_case(compositor, client, "remap", "", (640, 480), (17, 19), {
        "placement-remap": (66, 77, 100, 80, "requested"),
    }, remap=True)
    run_case(compositor, client, "nohint", "DontMoveOff\nNoTitle\n", (120, 100),
             (110, 95), {"placement-nohint": (16, 16, 100, 80, "interactive")}, interactive=[
                 ("placement-nohint", (110, 95), "confirm"),
             ])
    run_case(compositor, client, "buttons", "NoTitle\nBorderWidth 2\n",
             (320, 240), (20, 25), {}, interactive=[
                 ("placement-confirm", (20, 25), "confirm"),
                 ("placement-resize", (50, 55), "resize"),
                 ("placement-fill", (40, 45), "fill"),
             ])
    run_native_translation(compositor, native_client)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--native-client", type=Path, required=True)
    args = parser.parse_args()
    run(args.compositor.resolve(), args.client.resolve(), args.native_client.resolve())
    print("placement integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
