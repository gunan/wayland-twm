#!/usr/bin/env python3
"""Ensure an event read into XCB during native focus changes is dispatched."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from run_client_stress import wait_state
from run_m8_input_hotplug import client_point
import run_m8_output_topology as topology
from run_m8_output_topology import NATIVE_TITLE, Session, X11_TITLE, expect_command


def run(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-xcb-queue-") as directory:
        root = Path(directory)
        marker = root / "queue-event"
        wrapper = root / "compositor"
        # GCC's dynamic ASan runtime must precede preloaded libraries. Clang's
        # statically linked runtime needs no entry; inspect the built binary
        # so the fixture uses exactly the runtime selected by the build.
        dependencies = subprocess.run(
            ["ldd", str(args.compositor.resolve())], check=True,
            capture_output=True, text=True,
        ).stdout
        runtimes = re.findall(r"\blibasan[^ ]* => (\S+)", dependencies)
        preload = ":".join([*runtimes, str(args.fixture.resolve())])
        wrapper.write_text(
            "#!/bin/sh\n"
            f"export LD_PRELOAD={shlex.quote(preload)}\n"
            f"export WTWM_TEST_XCB_QUEUE={shlex.quote(str(marker))}\n"
            f"exec {shlex.quote(str(args.compositor.resolve()))} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        original_config = topology.config_text
        topology.config_text = lambda: original_config().replace(
            'Button3 = : all : f.warptoscreen "2"', 'Button3 = : all : f.focus'
        )
        session = Session(root, wrapper, args.config_tool.resolve(),
                          args.wayland_client.resolve(), args.x11_client.resolve())
        control = session.control
        assert control is not None
        try:
            expect_command(control, "OUTPUT 1000 800", "OK OUTPUT HEADLESS-1 1000 800")
            assert session.native is not None and session.x11 is not None
            session.native.expect(f"OK READY {NATIVE_TITLE}")
            session.x11.expect_prefix(f"OK READY {X11_TITLE} ")
            session.x11.command("FREEZE", "OK FROZEN 0x007030a0")
            wait_state(control, topology.state_windows_ready, "both mapped clients")
            # A zero-output MapRequest can create its placement frame before
            # Xwayland's surface is associated. Wait for actual client content.
            wait_state(control, lambda s: any(
                item.get("associated") and item.get("has_buffer")
                for item in s.get("xwayland_lifecycle", [])
            ), "associated X11 client buffer")
            control.command("POINTER 0 0")
            control.command("BUTTON 273 press")
            control.command("BUTTON 273 release")
            state = wait_state(control, lambda s: s.get("focus_root") is True,
                               "initial root focus")
            # The X11 client is frozen and sends no further protocol requests.
            # Only native focus and STATE queries follow the injected event.
            lifecycle = state["xwayland_lifecycle"]
            assert len(lifecycle) == 1, lifecycle
            marker.write_text(str(lifecycle[0]["xid"]), encoding="ascii")
            x, y = client_point(state, NATIVE_TITLE)
            control.command(f"POINTER {x} {y}")
            control.command("BUTTON 273 press")
            control.command("BUTTON 273 release")
            state = wait_state(
                control,
                lambda s: s.get("focus") == NATIVE_TITLE and any(
                    item.get("title") == "wtwm-queued-x11"
                    for item in s.get("windows", [])
                ),
                "queued X11 PropertyNotify after native focus",
            )
            if marker.exists():
                raise RuntimeError("XCB queue fixture did not execute")
            assert session.native is not None and session.x11 is not None
            session.native.command("EXIT", "OK EXIT")
            session.x11.command("EXIT", "OK EXIT")
            assert session.native_process is not None and session.x11_process is not None
            if session.native_process.wait(timeout=10) or session.x11_process.wait(timeout=10):
                raise RuntimeError("queue regression client failed")
            expect_command(control, "QUIT", "OK QUIT")
            control.close()
            if session.process.wait(timeout=10):
                raise RuntimeError("queue regression compositor failed")
        except Exception as error:
            stderr = session.abort()
            raise RuntimeError(f"{error}\ncompositor log:\n{stderr}") from error
    print("Xwayland queued-event regression passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("compositor", "config-tool", "wayland-client", "x11-client", "fixture"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
