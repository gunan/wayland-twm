#!/usr/bin/env python3
"""Verify reference f.colormap rotation and the native no-op boundary."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


X11_TITLE = "wtwm-colormap-x11"
NATIVE_TITLE = "wtwm-colormap-native"


def reference_install_requests(
    windows: list[str], rotation: int, capacity: int,
) -> list[str]:
    """Model BumpWindowColormap selection plus reverse install requests."""
    rotated = windows[rotation:] + windows[:rotation]
    selected = rotated[:capacity]
    return list(reversed(selected))


def validate_reference_model() -> None:
    valid = [
        window_name for window_name in ["top", "invalid", "three", "two"]
        if window_name != "invalid"
    ]
    if valid != ["top", "three", "two"]:
        raise RuntimeError("colormap invalid-entry compaction model failed")
    if reference_install_requests(valid, 1, 2) != ["two", "three"]:
        raise RuntimeError("multi-capacity reverse colormap request model failed")
    if reference_install_requests(valid, 0, 1) != ["top"]:
        raise RuntimeError("colormap default request model failed")


def config_text() -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        "NoIconManagers\n"
        'Button1 = : window : f.colormap "next"\n'
        'Button2 = : window : f.colormap "prev"\n'
        'Button3 = : window : f.colormap "default"\n'
    )


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one mapped {title!r}: {state!r}")
    return matches[0]


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {item["title"] for item in windows} == {X11_TITLE, NATIVE_TITLE}
        and all(item["mapped"] for item in windows)
        and len(state["xwayland_lifecycle"]) == 1
        and state["xwayland_lifecycle"][0]["associated"]
        and state["xwayland_lifecycle"][0]["mapped"]
    )


def pointer_inside(control: Control, title: str) -> None:
    item = window(control.state(), title)
    x = int(item["x"]) + int(item["content_x"]) + 20
    y = int(item["y"]) + int(item["content_y"]) + 20
    control.command(f"POINTER {x} {y}")
    control.command("WAIT 2")
    state = control.state()
    if state["pointer_window"] != title or state["pointer_context"] != "window":
        raise RuntimeError(f"pointer did not enter {title!r} client: {state!r}")


def click(control: Control, title: str, raw_button: int) -> None:
    pointer_inside(control, title)
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 2")


def client_line(channel: ClientChannel, command: str, prefix: str) -> str:
    channel.stdin.write((command + "\n").encode("utf-8"))
    channel.stdin.flush()
    return channel.expect_prefix(prefix)


def expect_colormap(channel: ClientChannel, name: str) -> None:
    client_line(channel, f"EXPECT {name}", f"OK EXPECT {name} count=")


def snapshot(channel: ClientChannel, label: str) -> str:
    prefix = f"OK SNAPSHOT {label}"
    line = client_line(channel, f"SNAPSHOT {label}", prefix)
    return line[len(prefix):]


def property_snapshot(channel: ClientChannel, label: str) -> str:
    prefix = f"OK PROPERTY {label}"
    line = client_line(channel, f"PROPERTY {label}", prefix)
    return line[len(prefix):]


def assert_trace(control: Control) -> None:
    events = [
        event for event in control.trace()["events"]
        if event["event"] == "colormap"
    ]
    x11 = [
        event["context"] for event in events
        if event["window"]["type"] == "x11"
    ]
    native = [
        event["context"] for event in events
        if event["window"]["type"] == "wayland"
    ]
    expected_x11 = [
        "x11-next",
        "x11-next",
        "x11-prev",
        "x11-default",
        "x11-next",
        "x11-next",
        "x11-prev",
        "x11-default",
    ]
    if x11 != expected_x11:
        raise RuntimeError(f"unexpected X11 colormap trace: {x11!r}")
    if native != ["native-noop", "native-noop", "native-noop"]:
        raise RuntimeError(f"unexpected native colormap trace: {native!r}")


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    validate_reference_model()
    with tempfile.TemporaryDirectory(prefix="wm8c-", dir="/tmp") as directory:
        root = Path(directory)
        runtime = root / "r"
        runtime.mkdir(mode=0o700)
        control_path = root / "c"
        display_marker = root / "display"
        display_name = f"wm8c-{os.getpid()}"
        config = root / "colormap.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        startup = (
            f'printf "%s\\n" "$DISPLAY" > '
            f"{shlex.quote(str(display_marker))}"
        )
        process = subprocess.Popen(
            [
                str(compositor), "-d", "-f", str(config), "-s", startup,
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
        native_process: subprocess.Popen[bytes] | None = None
        x11_process: subprocess.Popen[bytes] | None = None
        try:
            control = Control(control_path, process)
            control.socket.settimeout(10)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("OUTPUT 640 480")

            native_environment = environment.copy()
            native_environment["WAYLAND_DISPLAY"] = display_name
            native_process = subprocess.Popen(
                [
                    str(wayland_client), NATIVE_TITLE,
                    "org.wtwm.ColormapNative",
                ],
                env=native_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            native = ClientChannel(native_process, "native colormap client")
            native.expect(f"OK READY {NATIVE_TITLE}")

            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = wait_path(display_marker)
            x11_process = subprocess.Popen(
                [str(x11_client)],
                env=x11_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            x11 = ClientChannel(x11_process, "X11 colormap client")
            ready = x11.expect_prefix(f"OK READY {X11_TITLE} max=")
            maximum = re.search(r"\bmax=([0-9]+)\b", ready)
            if maximum is None or int(maximum.group(1)) != 1:
                raise RuntimeError(
                    "live colormap fixture requires the one-map Xwayland "
                    f"profile for unambiguous observations: {ready}"
                )

            wait_state(control, mapped_pair, "native/X11 colormap client pair")
            control.command("TRACE CLEAR")
            initial_property = property_snapshot(x11, "initial")

            click(control, X11_TITLE, 272)  # Button1: next
            expect_colormap(x11, "one")
            click(control, X11_TITLE, 272)
            expect_colormap(x11, "two")
            click(control, X11_TITLE, 274)  # Button2: prev
            expect_colormap(x11, "one")
            click(control, X11_TITLE, 273)  # Button3: default/refetch
            expect_colormap(x11, "top")
            if property_snapshot(x11, "after-default") != initial_property:
                raise RuntimeError(
                    "f.colormap rewrote the client's initial "
                    "WM_COLORMAP_WINDOWS property"
                )

            # Leave the old four-entry cache at rotation one. The replacement
            # property is [invalid,three,two] (with top inserted first and the
            # dead XID compacted away); next must therefore choose three after
            # the PropertyNotify reset, not old two.
            click(control, X11_TITLE, 272)
            expect_colormap(x11, "one")
            x11.command("MUTATE", "OK MUTATED three two")
            control.command("WAIT 3")
            mutated_property = property_snapshot(x11, "mutated")
            if mutated_property == initial_property:
                raise RuntimeError("client property mutation was not observable")
            click(control, X11_TITLE, 272)
            expect_colormap(x11, "three")
            click(control, X11_TITLE, 274)
            expect_colormap(x11, "top")
            click(control, X11_TITLE, 273)
            expect_colormap(x11, "top")
            if property_snapshot(x11, "after-mutated-default") != mutated_property:
                raise RuntimeError(
                    "f.colormap rewrote the client's replacement "
                    "WM_COLORMAP_WINDOWS property"
                )

            # Move onto native content before taking the baseline. Pointer
            # transitions are therefore outside the no-request observation.
            pointer_inside(control, NATIVE_TITLE)
            installed_before = snapshot(x11, "native-before")
            click(control, NATIVE_TITLE, 272)
            click(control, NATIVE_TITLE, 274)
            click(control, NATIVE_TITLE, 273)
            installed_after = snapshot(x11, "native-after")
            if installed_after != installed_before:
                raise RuntimeError(
                    "native f.colormap changed the X installed-colormap set: "
                    f"before={installed_before!r} after={installed_after!r}"
                )

            assert_trace(control)
            x11.command("PING", "OK PONG")
            native.command("ARM alive", "OK ARMED alive")
            client_line(native, "REPORT alive", "OK REPORT alive ")
            if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("test-control connection stopped responding")

            native.command("EXIT", "OK EXIT")
            x11.command("EXIT", "OK EXIT")
            if wait_process(native_process, "native colormap client") != 0:
                raise RuntimeError("native colormap client did not exit cleanly")
            if wait_process(x11_process, "X11 colormap client") != 0:
                raise RuntimeError("X11 colormap client did not exit cleanly")
            control.command("QUIT")
            control.close()
            control = None
            if process.wait(timeout=10) != 0:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"colormap compositor failed: {stderr}")
            stderr = process.stderr.read() if process.stderr else ""
            if "no-op for native true-color Wayland; no X11 request issued" not in stderr:
                raise RuntimeError("native no-request compatibility log is absent")
            if "f.colormap next selected X11 colormap" not in stderr:
                raise RuntimeError("X11 selected-colormap log is absent")
        finally:
            if control is not None:
                control.close()
            for client_process in (native_process, x11_process):
                if client_process is not None and client_process.poll() is None:
                    client_process.kill()
                    client_process.wait(timeout=10)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--wayland-client", type=Path)
    parser.add_argument("--x11-client", type=Path)
    args = parser.parse_args()
    if args.self_test_model:
        validate_reference_model()
        print("Milestone 8 colormap model self-test passed")
        return 0
    paths = (args.compositor, args.wayland_client, args.x11_client)
    if any(path is None for path in paths):
        parser.error("--compositor, --wayland-client, and --x11-client are required")
    for path in paths:
        assert path is not None
        if not path.is_file():
            parser.error(f"missing executable: {path}")
    assert args.compositor is not None
    assert args.wayland_client is not None
    assert args.x11_client is not None
    run(args.compositor.resolve(), args.wayland_client.resolve(),
        args.x11_client.resolve())
    print("Milestone 8 Xwayland/native colormap integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
