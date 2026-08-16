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


SIZE_HINT_KEYS = (
    "flags", "min_width", "min_height", "max_width", "max_height",
    "base_width", "base_height", "width_inc", "height_inc",
    "min_aspect_num", "min_aspect_den", "max_aspect_num", "max_aspect_den",
    "gravity",
)
INITIAL_SIZE_HINTS = (880, 80, 60, 320, 240, 40, 30, 20, 10, 0, 0, 0, 0, 1)
UPDATED_SIZE_HINTS = (880, 100, 70, 300, 220, 50, 40, 25, 15, 0, 0, 0, 0, 1)


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


def lifecycle_matches(
    state: dict[str, object], xid: int, *, associated: bool, mapped: bool,
    override_redirect: bool,
) -> bool:
    return any(
        entry["xid"] == xid and entry["associated"] == associated and
        entry["mapped"] == mapped and
        entry["override_redirect"] == override_redirect
        for entry in state["xwayland_lifecycle"]
    )


def click_title(control: Control, item: dict[str, object], button: int) -> None:
    x = int(item["x"]) + int(item["width"]) // 2
    y = int(item["y"]) + 8
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")


def size_hint_values(item: dict[str, object]) -> tuple[object, ...]:
    hints = item["size_hints"]
    assert isinstance(hints, dict)
    return tuple(hints[key] for key in SIZE_HINT_KEYS)


def hint_icon_ids(item: dict[str, object]) -> tuple[int, int, int]:
    return tuple(int(item[key]) for key in (
        "icon_pixmap", "icon_mask", "icon_window",
    ))


def net_icon_values(item: dict[str, object]) -> tuple[object, ...]:
    icon = item["net_wm_icon"]
    assert isinstance(icon, dict)
    return tuple(icon[key] for key in (
        "count", "width", "height", "checksum", "truncated",
    ))


def assert_frame_contract(
    item: dict[str, object], *, frame_x: int, frame_y: int,
    width: int, height: int,
) -> None:
    border = int(item["border_width"])
    title_extent = int(item["title_height"])
    expected = {
        "x": frame_x,
        "y": frame_y,
        "width": width,
        "height": height,
        "frame_width": width,
        "frame_height": height + title_extent,
        "outer_width": width + 2 * border,
        "outer_height": height + title_extent + 2 * border,
        "content_x": border,
        "content_y": border + title_extent,
        "client_x": frame_x + border,
        "client_y": frame_y + border + title_extent,
    }
    actual = {key: int(item[key]) for key in expected}
    if actual != expected:
        raise RuntimeError(
            f"reference frame/client extent contract is wrong: "
            f"expected={expected!r} actual={actual!r}"
        )


def assert_initial_metadata(
    parent: dict[str, object], transient: dict[str, object]
) -> tuple[tuple[int, int, int], tuple[object, ...]]:
    if (parent["title"], parent["type"], parent["instance"], parent["class"]) != (
        "xwm-parent-initial", "x11", "xwm-instance-initial", "XwmClassInitial"
    ):
        raise RuntimeError(f"initial WM_NAME/WM_CLASS bridge is stale: {parent!r}")
    if transient["parent"] != parent["xid"]:
        raise RuntimeError(f"WM_TRANSIENT_FOR relationship is missing: {transient!r}")
    if not parent["supports_delete"] or not parent["urgent"] or parent["input"]:
        raise RuntimeError(f"WM_PROTOCOLS/WM_HINTS bridge is wrong: {parent!r}")
    icon_ids = hint_icon_ids(parent)
    if any(value == 0 for value in icon_ids) or len(set(icon_ids)) != len(icon_ids):
        raise RuntimeError(f"supplied WM_HINTS icon evidence is missing: {parent!r}")
    if parent["icon_name"] != "xwm-icon-initial":
        raise RuntimeError(f"WM_ICON_NAME bridge is stale: {parent!r}")
    icon = net_icon_values(parent)
    if icon[:3] != (1, 2, 2) or icon[3] == 0 or icon[4] is not False:
        raise RuntimeError(f"_NET_WM_ICON evidence is wrong: {parent!r}")
    if size_hint_values(parent) != INITIAL_SIZE_HINTS:
        raise RuntimeError(f"WM_NORMAL_HINTS bridge is wrong: {parent!r}")
    return icon_ids, icon


def updated_metadata_matches(
    parent: dict[str, object], initial_icon_ids: tuple[int, int, int],
    initial_net_icon: tuple[object, ...],
) -> bool:
    icon_ids = hint_icon_ids(parent)
    icon = net_icon_values(parent)
    return (
        (parent["title"], parent["type"], parent["instance"], parent["class"]) ==
        ("xwm-parent-updated", "x11", "xwm-instance-updated", "XwmClassUpdated")
        and parent["icon_name"] == "xwm-icon-updated"
        and parent["supports_delete"] and not parent["urgent"] and parent["input"]
        and all(value != 0 for value in icon_ids)
        and len(set(icon_ids)) == len(icon_ids)
        and all(after != before for before, after in zip(initial_icon_ids, icon_ids))
        and size_hint_values(parent) == UPDATED_SIZE_HINTS
        and icon[:3] == (1, 3, 2) and icon[3] != 0 and icon[4] is False
        and icon[3] != initial_net_icon[3]
    )


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
            control.command("SET CURSOR 44 55")
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
            initial_icon_ids, initial_net_icon = assert_initial_metadata(parent, transient)
            assert_frame_contract(parent, frame_x=44, frame_y=55,
                                  width=221, height=151)
            parent_xid = int(parent["xid"])
            override = state["override_redirect"][0]
            override_xid = int(override["xid"])
            if override["title"] != "xwm-override-redirect" or not override["mapped"]:
                raise RuntimeError(f"override-redirect window is not visible: {state!r}")
            if not lifecycle_matches(
                state, parent_xid, associated=True, mapped=True,
                override_redirect=False,
            ) or not lifecycle_matches(
                state, override_xid, associated=True, mapped=True,
                override_redirect=True,
            ):
                raise RuntimeError(f"initial Xwayland lifecycle is stale: {state!r}")

            command(client, "UPDATE", "UPDATED")
            state = wait_state(
                control,
                lambda item: any(updated_metadata_matches(
                    entry, initial_icon_ids, initial_net_icon,
                ) for entry in item["windows"]),
                "live X11 metadata and hint updates",
            )
            parent = window(state, "xwm-parent-updated")
            assert_frame_contract(parent, frame_x=44, frame_y=55,
                                  width=221, height=151)
            updated_icon_ids = hint_icon_ids(parent)
            updated_net_icon = net_icon_values(parent)

            command(client, "TRUNCATE_ICON", "TRUNCATED_ICON_SET")
            state = wait_state(
                control,
                lambda item: net_icon_values(window(item, "xwm-parent-updated")) ==
                (0, 0, 0, 0, True),
                "bounded oversized _NET_WM_ICON handling",
            )
            command(client, "RESTORE_ICON", "ICON_RESTORED")
            state = wait_state(
                control,
                lambda item: net_icon_values(window(item, "xwm-parent-updated")) ==
                updated_net_icon,
                "restored bounded _NET_WM_ICON",
            )
            if hint_icon_ids(window(state, "xwm-parent-updated")) != updated_icon_ids:
                raise RuntimeError(f"WM_HINTS icon identifiers regressed: {state!r}")

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
                    entry["client_x"] == 120 and
                    entry["client_y"] == 100 + entry["title_height"] and
                    entry["width"] == 277 and entry["height"] == 199 and
                    size_hint_values(entry) == UPDATED_SIZE_HINTS
                    for entry in item["windows"]),
                "reference ConfigureRequest geometry",
            )
            parent = window(state, "xwm-parent-updated")
            assert_frame_contract(
                parent,
                frame_x=120 - int(parent["border_width"]),
                frame_y=100 - int(parent["border_width"]),
                width=277,
                height=199,
            )
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
            wait_state(
                control,
                lambda item: lifecycle_matches(
                    item, override_xid, associated=False, mapped=False,
                    override_redirect=True,
                ),
                "override-redirect dissociation",
            )
            command(client, "REMAP_OR", "OR_REMAPPED")
            wait_state(
                control,
                lambda item: len(item["override_redirect"]) == 1 and
                lifecycle_matches(
                    item, override_xid, associated=True, mapped=True,
                    override_redirect=True,
                ),
                "override-redirect remap",
            )

            command(client, "UNMAP_PARENT", "PARENT_UNMAPPED")
            state = wait_state(
                control,
                lambda item: not any(entry["title"] == "xwm-parent-updated"
                                     for entry in item["windows"]),
                "managed X11 unmap cleanup",
            )
            if state["interactive"] or state["menu"] is not None:
                raise RuntimeError(f"unmapped X11 target retained UI state: {state!r}")
            wait_state(
                control,
                lambda item: lifecycle_matches(
                    item, parent_xid, associated=False, mapped=False,
                    override_redirect=False,
                ),
                "managed X11 dissociation",
            )
            command(client, "REMAP_PARENT", "PARENT_REMAPPED")
            state = wait_state(
                control,
                lambda item: any(entry["title"] == "xwm-parent-updated"
                                 for entry in item["windows"]) and
                lifecycle_matches(
                    item, parent_xid, associated=True, mapped=True,
                    override_redirect=False,
                ),
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
            control.command("WAIT 1")
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
