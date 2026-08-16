#!/usr/bin/env python3
"""Drive deterministic randomized lifecycle and stack actions under wtwm."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import time

from run_client_stress import ClientChannel, wait_path, wait_state
from run_compositor import Control


RUNTIME_RUNS = 2
RUNTIME_STEPS = 96
RUNTIME_SEED = 1279870533
RUNTIME_ACTIONS = (
    "create", "unmap", "remap", "title", "icon_cycle", "raise", "lower",
    "raiselower", "circle_up", "circle_down", "destroy",
)


@dataclass
class RuntimeClient:
    serial: int
    title: str
    protocol: str
    process: subprocess.Popen[bytes]
    channel: ClientChannel
    xid: int | None
    mapped: bool = True
    cycle: int = 0
    title_revision: int = 0
    identifier: int | None = None


def wait_for_title(control: Control, title: str, present: bool) -> dict[str, object]:
    return wait_state(
        control,
        lambda state: any(item["title"] == title for item in state["windows"])
        == present,
        f"{title} {'map' if present else 'unmap'}",
    )


def assert_runtime_invariants(
    control: Control,
    clients: list[RuntimeClient],
    ids_by_title: dict[str, int],
    owners_by_id: dict[int, int],
) -> dict[str, object]:
    state = control.state()
    windows = state["windows"]
    titles = [str(item["title"]) for item in windows]
    ids = [int(item["id"]) for item in windows]
    if len(titles) != len(set(titles)) or len(ids) != len(set(ids)):
        raise RuntimeError(f"duplicate managed window/list state: {state!r}")
    expected = {item.title for item in clients if item.mapped}
    if set(titles) != expected or not all(item["mapped"] for item in windows):
        raise RuntimeError(f"mapped/list state disagrees with clients: {state!r}")
    if {int(item["stack"]) for item in windows} != set(range(len(windows))):
        raise RuntimeError(f"managed stack is not unique and contiguous: {state!r}")

    for item in windows:
        title = str(item["title"])
        identifier = int(item["id"])
        matches = [
            client for client in clients
            if client.mapped and client.title == title
        ]
        if len(matches) != 1:
            raise RuntimeError(f"window lacks one client owner: {state!r}")
        client = matches[0]
        if client.identifier is None:
            client.identifier = identifier
        elif client.identifier != identifier:
            raise RuntimeError(f"remap changed creation identity: {state!r}")
        previous_id = ids_by_title.setdefault(title, identifier)
        previous_owner = owners_by_id.setdefault(identifier, client.serial)
        if previous_id != identifier or previous_owner != client.serial or identifier <= 0:
            raise RuntimeError(f"creation identity was reused or changed: {state!r}")
    focus = state["focus"]
    if focus is not None:
        focused = [item for item in windows if item["title"] == focus]
        if len(focused) != 1 or focused[0]["iconified"]:
            raise RuntimeError(f"focus names a stale or hidden client: {state!r}")
    icons = state["icons"]
    expected_icons = [item["title"] for item in windows if item["iconified"]]
    if len(icons) != len(set(icons)) or set(icons) != set(expected_icons):
        raise RuntimeError(f"icon/list state is duplicated or stale: {state!r}")
    if state["interactive"] or state["menu"] is not None:
        raise RuntimeError(f"lifecycle action leaked transient UI state: {state!r}")
    if state["popups"] or state["override_redirect"]:
        raise RuntimeError(f"fixture created an unmanaged surface: {state!r}")

    x11_clients = {item.xid: item for item in clients if item.protocol == "x11"}
    lifecycle = state["xwayland_lifecycle"]
    lifecycle_xids = [int(item["xid"]) for item in lifecycle]
    if len(lifecycle_xids) != len(set(lifecycle_xids)):
        raise RuntimeError(f"duplicate Xwayland lifecycle entry: {state!r}")
    if set(lifecycle_xids) != set(x11_clients):
        raise RuntimeError(f"stale or missing Xwayland lifecycle entry: {state!r}")
    for entry in lifecycle:
        client = x11_clients[int(entry["xid"])]
        if bool(entry["associated"]) != client.mapped:
            raise RuntimeError(f"Xwayland association disagrees with map state: {state!r}")
        if bool(entry["mapped"]) != client.mapped:
            raise RuntimeError(f"Xwayland lifecycle map flag is stale: {state!r}")
    for item in windows:
        if item["type"] == "x11":
            matches = [entry for entry in lifecycle if entry["xid"] == item["xid"]]
            if len(matches) != 1 or not matches[0]["associated"]:
                raise RuntimeError(f"managed X11 window lacks one association: {state!r}")

    trace = control.trace()
    if trace["version"] != 1 or trace["dropped"] != 0:
        raise RuntimeError(f"event ledger is incomplete: {trace!r}")
    events = trace["events"]
    sequences = [int(event["seq"]) for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise RuntimeError(f"event sequence is stale or duplicated: {trace!r}")
    if trace["first_seq"] != 1 or trace["next_seq"] != len(events):
        raise RuntimeError(f"event bounds disagree with entries: {trace!r}")
    for event in events:
        identifier = int(event["window"]["id"])
        title = str(event["window"]["title"])
        if identifier <= 0:
            raise RuntimeError(f"event lost stable client identity: {event!r}")
        # Native clients can emit a creation/title event before both xdg
        # metadata strings arrive.  The monotonic ID is the stable identity;
        # once a non-empty title exists it must remain bound to that same ID.
        if title:
            previous_id = ids_by_title.setdefault(title, identifier)
            if previous_id != identifier:
                raise RuntimeError(f"event identity is stale or reused: {event!r}")
    return state


def title_action(control: Control, state: dict[str, object], button: int) -> bool:
    windows = sorted(state["windows"], key=lambda item: int(item["stack"]))
    if not windows:
        return False
    target = windows[0]
    x = int(target["x"]) + int(target["border_width"]) + int(target["width"]) // 2
    y = int(target["y"]) + int(target["border_width"]) + max(
        1, int(target["title_bar_height"]) // 2
    )
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")
    return True


def root_action(control: Control, button: int) -> None:
    control.command("POINTER 630 470")
    control.command(f"BUTTON {button} press")
    control.command(f"BUTTON {button} release")


def run_once(
    compositor: Path,
    wayland_binary: Path,
    x11_binary: Path,
    iteration: int,
) -> tuple[tuple[object, ...], ...]:
    with tempfile.TemporaryDirectory(prefix="wtwm-random-lifecycle-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "random-lifecycle.twmrc"
        config.write_text(
            "NoDefaults\nRandomPlacement\nNoGrabServer\nNoIconManagers\n"
            "Button1 = : title : f.raise\n"
            "Button2 = : title : f.lower\n"
            "Button3 = : title : f.raiselower\n"
            "Button4 = : root : f.circleup\n"
            "Button5 = : root : f.circledown\n"
            "Function \"icon-cycle\" { f.iconify f.deiconify }\n"
            "Button6 = : title : f.function \"icon-cycle\"\n",
            encoding="utf-8",
        )
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        display_name = f"wtwm-random-lifecycle-{os.getpid()}-{iteration}"
        compositor_process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", display_name,
                "--test-backend", "headless",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        control: Control | None = None
        clients: list[RuntimeClient] = []
        all_processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        history: list[tuple[object, ...]] = []
        ids_by_title: dict[str, int] = {}
        owners_by_id: dict[int, int] = {}
        serial = 0
        rng = random.Random(RUNTIME_SEED)

        wayland_environment = environment.copy()
        wayland_environment["WAYLAND_DISPLAY"] = display_name
        x11_environment = environment.copy()

        def launch() -> RuntimeClient:
            nonlocal serial
            serial += 1
            protocol = "wayland" if serial % 2 else "x11"
            title = f"wtwm-random-{serial:03d}-{protocol}"
            if protocol == "wayland":
                child = subprocess.Popen(
                    [str(wayland_binary), title, f"org.wtwm.Random{serial}"],
                    env=wayland_environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                channel = ClientChannel(child, title)
                channel.expect(f"OK READY {title}")
                xid = None
            else:
                child = subprocess.Popen(
                    [str(x11_binary), title, title, "WtwmRandomLifecycle"],
                    env=x11_environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                channel = ClientChannel(child, title)
                ready = channel.expect_prefix(f"OK READY {title} ")
                xid = int(ready.rsplit(" ", 1)[1])
            item = RuntimeClient(serial, title, protocol, child, channel, xid)
            clients.append(item)
            all_processes.append((title, child))
            wait_for_title(control, title, True)
            return item

        try:
            control = Control(control_path, compositor_process)
            control.socket.settimeout(10)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            x11_environment["DISPLAY"] = wait_path(display_marker)
            control.command("TRACE CLEAR")
            for _ in range(3):
                launch()
                assert_runtime_invariants(
                    control, clients, ids_by_title, owners_by_id
                )

            for step in range(RUNTIME_STEPS):
                action = (
                    RUNTIME_ACTIONS[step]
                    if step < len(RUNTIME_ACTIONS)
                    else rng.choice(RUNTIME_ACTIONS)
                )
                mapped = [item for item in clients if item.mapped]
                unmapped = [item for item in clients if not item.mapped]
                actual = action
                if action == "create" and len(clients) < 5:
                    launch()
                elif action == "unmap" and len(mapped) > 1:
                    target = rng.choice(mapped)
                    target.cycle += 1
                    target.channel.command(
                        f"UNMAP {target.cycle}", f"OK UNMAPPED {target.cycle}"
                    )
                    target.mapped = False
                    wait_for_title(control, target.title, False)
                elif action == "remap" and unmapped:
                    target = rng.choice(unmapped)
                    target.channel.command(
                        f"REMAP {target.cycle}", f"OK REMAPPED {target.cycle}"
                    )
                    target.mapped = True
                    wait_for_title(control, target.title, True)
                elif action == "title" and mapped:
                    target = rng.choice(mapped)
                    old_title = target.title
                    target.title_revision += 1
                    new_title = (
                        f"wtwm-random-{target.serial:03d}-{target.protocol}-"
                        f"title-{target.title_revision:03d}"
                    )
                    target.channel.command(
                        f"TITLE {new_title}", f"OK TITLE {new_title}"
                    )
                    target.title = new_title
                    if target.identifier is None:
                        raise RuntimeError("mapped client lacks a stable identity")
                    ids_by_title[new_title] = target.identifier
                    wait_for_title(control, old_title, False)
                    wait_for_title(control, new_title, True)
                elif action == "icon_cycle" and mapped:
                    if not title_action(control, control.state(), 277):
                        actual = "no_window"
                elif action == "destroy" and len(clients) > 1:
                    target = rng.choice(clients)
                    target.channel.command("EXIT", "OK EXIT")
                    if target.process.wait(timeout=10) != 0:
                        raise RuntimeError(f"{target.title} did not exit cleanly")
                    clients.remove(target)
                    wait_for_title(control, target.title, False)
                elif action in {"raise", "lower", "raiselower"} and mapped:
                    button = {"raise": 272, "lower": 273, "raiselower": 274}[action]
                    if not title_action(control, control.state(), button):
                        actual = "no_window"
                elif action in {"circle_up", "circle_down"}:
                    root_action(control, 275 if action == "circle_up" else 276)
                elif len(clients) < 5:
                    actual = "create"
                    launch()
                else:
                    actual = "circle_up"
                    root_action(control, 275)

                control.command("WAIT 1")
                state = assert_runtime_invariants(
                    control, clients, ids_by_title, owners_by_id
                )
                ordered = tuple(
                    item["title"]
                    for item in sorted(state["windows"], key=lambda entry: entry["stack"])
                )
                history.append((
                    actual,
                    ordered,
                    state["focus"],
                    tuple(sorted(item.title for item in clients if not item.mapped)),
                ))

            for item in list(clients):
                item.channel.command("EXIT", "OK EXIT")
                if item.process.wait(timeout=10) != 0:
                    raise RuntimeError(f"{item.title} teardown failed")
                clients.remove(item)
            wait_state(
                control,
                lambda state: not state["windows"]
                and not state["xwayland_lifecycle"]
                and state["focus"] is None,
                "empty final lifecycle state",
            )
            assert_runtime_invariants(control, clients, ids_by_title, owners_by_id)
            control.command("QUIT")
            compositor_process.wait(timeout=10)
            if compositor_process.returncode != 0:
                raise RuntimeError(
                    f"compositor returned {compositor_process.returncode}"
                )
            return tuple(history)
        except Exception as error:
            diagnostics: list[str] = []
            for label, child in all_processes:
                if child.poll() is None:
                    child.kill()
                try:
                    _, stderr = child.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    _, stderr = child.communicate()
                diagnostics.append(
                    f"{label} status={child.returncode} stderr:\n"
                    f"{stderr.decode('utf-8', errors='replace')}"
                )
            if compositor_process.poll() is None:
                compositor_process.terminate()
            try:
                _, compositor_error = compositor_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor_process.kill()
                _, compositor_error = compositor_process.communicate()
            raise RuntimeError(
                f"run {iteration}: {error}\n" + "\n".join(diagnostics)
                + f"\ncompositor stderr:\n{compositor_error}"
            ) from error
        finally:
            for _, child in all_processes:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor_process.poll() is None:
                compositor_process.terminate()
                compositor_process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--wayland-client", type=Path, required=True)
    parser.add_argument("--x11-client", type=Path, required=True)
    arguments = parser.parse_args()
    histories = [
        run_once(
            arguments.compositor.resolve(),
            arguments.wayland_client.resolve(),
            arguments.x11_client.resolve(),
            iteration,
        )
        for iteration in range(RUNTIME_RUNS)
    ]
    if any(history != histories[0] for history in histories[1:]):
        raise RuntimeError("seeded lifecycle runtime was not repeatable")


if __name__ == "__main__":
    main()
