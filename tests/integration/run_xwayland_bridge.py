#!/usr/bin/env python3
"""Exercise Xwayland window-manager lifecycle, metadata, hints, and actions."""

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


def wait_line(client: subprocess.Popen[str], expected: str) -> str:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([client.stdout], [], [], deadline - time.monotonic())
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected X11 client event: {line!r}")
    raise RuntimeError(f"timed out waiting for X11 client event {expected!r}")


def command(client: subprocess.Popen[str], text: str, expected: str) -> str:
    assert client.stdin is not None
    client.stdin.write(text + "\n")
    client.stdin.flush()
    return wait_line(client, expected)


def wait_state(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {title!r} window: {state!r}")
    return matches[0]


def click_title(control: Control, item: dict[str, object], button: int) -> None:
    x = int(item["x"]) + int(item["width"]) // 2
    y = int(item["y"]) + 8
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")


def assert_initial_metadata(parent: dict[str, object], transient: dict[str, object]) -> None:
    if (parent["type"], parent["instance"], parent["class"]) != (
        "x11", "xwm-instance-initial", "XwmClassInitial"
    ):
        raise RuntimeError(f"initial WM_CLASS bridge is stale: {parent!r}")
    if transient["parent"] != parent["xid"]:
        raise RuntimeError(f"WM_TRANSIENT_FOR relationship is missing: {transient!r}")
    if not parent["supports_delete"] or not parent["urgent"] or parent["input"]:
        raise RuntimeError(f"WM_PROTOCOLS/WM_HINTS bridge is wrong: {parent!r}")
    if not parent["icon_pixmap"] or not parent["icon_mask"] or not parent["icon_window"]:
        raise RuntimeError(f"supplied WM_HINTS icon evidence is missing: {parent!r}")
    if parent["icon_name"] != "xwm-icon-initial":
        raise RuntimeError(f"WM_ICON_NAME bridge is stale: {parent!r}")
    icon = parent["net_wm_icon"]
    if (icon["count"], icon["width"], icon["height"], icon["truncated"]) != (
        1, 2, 2, False
    ) or icon["checksum"] == 0:
        raise RuntimeError(f"_NET_WM_ICON evidence is wrong: {parent!r}")
    hints = parent["size_hints"]
    expected = (80, 60, 320, 240, 40, 30, 20, 10)
    actual = tuple(hints[key] for key in (
        "min_width", "min_height", "max_width", "max_height",
        "base_width", "base_height", "width_inc", "height_inc",
    ))
    if actual != expected:
        raise RuntimeError(f"WM_NORMAL_HINTS bridge is wrong: {parent!r}")


def run(compositor: Path, client_binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-xwayland-bridge-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "bridge.twmrc"
        config.write_text(
            "Button1 = : title : f.delete\n"
            "Button2 = : title : f.destroy\n",
            encoding="utf-8",
        )
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", f"wtwm-xwm-{os.getpid()}",
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
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            display = wait_path(display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            state = wait_state(
                control,
                lambda item: len(item["windows"]) == 2 and
                len(item["override_redirect"]) == 1,
                "managed, transient, and override-redirect maps",
            )
            parent = window(state, "xwm-parent-initial")
            transient = window(state, "xwm-transient")
            assert_initial_metadata(parent, transient)
            override = state["override_redirect"][0]
            if override["title"] != "xwm-override-redirect" or not override["mapped"]:
                raise RuntimeError(f"override-redirect window is not visible: {state!r}")

            command(client, "UPDATE", "UPDATED")
            state = wait_state(
                control,
                lambda item: any(entry["title"] == "xwm-parent-updated" and
                    entry["instance"] == "xwm-instance-updated" and
                    entry["class"] == "XwmClassUpdated" and
                    entry["icon_name"] == "xwm-icon-updated" and
                    not entry["urgent"] and entry["input"] and
                    entry["net_wm_icon"]["width"] == 3
                    for entry in item["windows"]),
                "live X11 metadata and hint updates",
            )
            parent = window(state, "xwm-parent-updated")
            if parent["net_wm_icon"]["height"] != 2:
                raise RuntimeError(f"updated supplied icon is stale: {parent!r}")

            command(client, "TRUNCATE_ICON", "TRUNCATED_ICON_SET")
            state = wait_state(
                control,
                lambda item: window(item, "xwm-parent-updated")["net_wm_icon"]["truncated"],
                "bounded oversized _NET_WM_ICON handling",
            )
            icon = window(state, "xwm-parent-updated")["net_wm_icon"]
            if icon["count"] != 0:
                raise RuntimeError(f"partial icon was accepted as complete: {icon!r}")
            command(client, "RESTORE_ICON", "ICON_RESTORED")
            wait_state(
                control,
                lambda item: not window(item, "xwm-parent-updated")["net_wm_icon"]["truncated"],
                "restored bounded _NET_WM_ICON",
            )

            command(client, "CLEAR_TRANSIENT", "TRANSIENT_CLEARED")
            wait_state(
                control,
                lambda item: window(item, "xwm-transient")["parent"] == 0,
                "live WM_TRANSIENT_FOR removal",
            )
            command(client, "RESTORE_TRANSIENT", "TRANSIENT_RESTORED")
            state = wait_state(
                control,
                lambda item: window(item, "xwm-transient")["parent"] ==
                window(item, "xwm-parent-updated")["xid"],
                "live WM_TRANSIENT_FOR restoration",
            )

            command(client, "CONFIGURE", "CONFIGURE_REQUESTED")
            state = wait_state(
                control,
                lambda item: any(entry["title"] == "xwm-parent-updated" and
                    entry["client_x"] == 120 and entry["client_y"] == 100 and
                    entry["width"] == 275 and entry["height"] == 190
                    for entry in item["windows"]),
                "hint-constrained configure request",
            )
            parent = window(state, "xwm-parent-updated")
            command(client, "RESTACK", "RESTACK_REQUESTED")
            state = wait_state(
                control,
                lambda item: window(item, "xwm-transient")["stack"] <
                window(item, "xwm-parent-updated")["stack"],
                "transient restack above parent",
            )

            command(client, "UNMAP_OR", "OR_UNMAPPED")
            wait_state(control, lambda item: not item["override_redirect"],
                       "override-redirect unmap cleanup")
            command(client, "REMAP_OR", "OR_REMAPPED")
            wait_state(control, lambda item: len(item["override_redirect"]) == 1,
                       "override-redirect remap")

            command(client, "UNMAP_PARENT", "PARENT_UNMAPPED")
            state = wait_state(
                control,
                lambda item: not any(entry["title"] == "xwm-parent-updated"
                                     for entry in item["windows"]),
                "managed X11 unmap cleanup",
            )
            if state["interactive"] or state["menu"] is not None:
                raise RuntimeError(f"unmapped X11 target retained UI state: {state!r}")
            command(client, "REMAP_PARENT", "PARENT_REMAPPED")
            state = wait_state(
                control,
                lambda item: any(entry["title"] == "xwm-parent-updated"
                                 for entry in item["windows"]),
                "managed X11 remap",
            )
            parent = window(state, "xwm-parent-updated")
            click_title(control, parent, 272)
            wait_line(client, "DELETE_RECEIVED")
            wait_state(
                control,
                lambda item: not any(entry["title"] == "xwm-parent-updated"
                                     for entry in item["windows"]),
                "cooperative WM_DELETE teardown",
            )

            command(client, "CREATE_STUBBORN", "STUBBORN_MAPPED")
            state = wait_state(
                control,
                lambda item: any(entry["title"] == "xwm-stubborn"
                                 for entry in item["windows"]),
                "non-cooperating X11 client map",
            )
            stubborn = window(state, "xwm-stubborn")
            if stubborn["supports_delete"]:
                raise RuntimeError(f"stubborn window unexpectedly supports delete: {stubborn!r}")
            click_title(control, stubborn, 272)
            time.sleep(0.2)
            stubborn = window(control.state(), "xwm-stubborn")
            click_title(control, stubborn, 274)
            wait_line(client, "STUBBORN_KILLED")
            wait_state(
                control,
                lambda item: not any(entry["title"] == "xwm-stubborn"
                                     for entry in item["windows"]),
                "forced X client termination",
            )

            assert client.stdin is not None
            client.stdin.write("EXIT\n")
            client.stdin.flush()
            client.wait(timeout=5)
            if client.returncode != 0:
                raise RuntimeError(f"X11 bridge client returned {client.returncode}")
            client = None
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
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
            if process.poll() is None:
                process.terminate()
            try:
                _, compositor_error = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, compositor_error = process.communicate()
            raise RuntimeError(
                f"{error}\nX11 client stderr:\n{client_error}\n"
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
