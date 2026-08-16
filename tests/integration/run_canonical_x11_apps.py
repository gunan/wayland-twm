#!/usr/bin/env python3
"""Run canonical real X11 applications and ICCCM fixtures under wtwm."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Callable

from run_compositor import Control


@dataclass(frozen=True)
class ExpectedWindow:
    label: str
    title: str
    instance: str
    class_name: str


@dataclass
class RunningApp:
    label: str
    process: subprocess.Popen[str]


@dataclass(frozen=True)
class ObservedXids:
    real: frozenset[int]
    icccm: frozenset[int]


REAL_WINDOWS = (
    ExpectedWindow("xterm", "WTWM Real Xterm", "wtwm-real-xterm", "WtwmRealXterm"),
    ExpectedWindow("xclock", "WTWM Real XClock", "wtwm-real-xclock", "XClock"),
    ExpectedWindow("xload", "WTWM Real XLoad", "wtwm-real-xload", "XLoad"),
    ExpectedWindow("emacs", "WTWM Real Emacs", "wtwm-real-emacs", "Emacs"),
    ExpectedWindow(
        "terminal-dialog",
        "WTWM Terminal Dialog",
        "wtwm-terminal-dialog",
        "WtwmTerminalDialog",
    ),
)


def checked_program(path: Path, requested_name: str) -> Path:
    if not path.is_absolute() or path.name != requested_name:
        raise RuntimeError(f"{requested_name} must be passed as its absolute Debian path")
    resolved = path.resolve(strict=True)
    if resolved.parent != Path("/usr/bin") or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"{requested_name} is not a Debian /usr/bin executable: {resolved}")
    if requested_name == "emacs":
        if not resolved.name.startswith("emacs"):
            raise RuntimeError(f"emacs alternative resolves to an unexpected binary: {resolved}")
    elif resolved.name != requested_name:
        raise RuntimeError(f"{requested_name} resolves to an unexpected binary: {resolved}")
    return resolved


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def wait_line(process: subprocess.Popen[str], expected: str) -> None:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], deadline - time.monotonic())
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        if line == expected:
            return
        if process.poll() is not None:
            break
        raise RuntimeError(f"unexpected ICCCM client event: {line!r}")
    raise RuntimeError(f"timed out waiting for ICCCM client event {expected!r}")


def wait_state(
    control: Control,
    predicate: Callable[[dict[str, object]], bool],
    description: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {control.state()!r}")


def matching_windows(
    state: dict[str, object], expected: ExpectedWindow
) -> list[dict[str, object]]:
    return [
        window
        for window in state["windows"]
        if window["type"] == "x11"
        and window["title"] == expected.title
        and window["instance"] == expected.instance
        and window["class"] == expected.class_name
    ]


def all_real_windows_mapped(state: dict[str, object]) -> bool:
    return all(
        len(matches := matching_windows(state, expected)) == 1
        and matches[0]["mapped"]
        for expected in REAL_WINDOWS
    )


def lifecycle_is_managed(state: dict[str, object], xid: int) -> bool:
    return any(
        entry["xid"] == xid
        and entry["associated"]
        and entry["mapped"]
        and not entry["override_redirect"]
        for entry in state["xwayland_lifecycle"]
    )


def lifecycle_is_override(state: dict[str, object], xid: int) -> bool:
    return any(
        entry["xid"] == xid
        and entry["associated"]
        and entry["mapped"]
        and entry["override_redirect"]
        for entry in state["xwayland_lifecycle"]
    )


def xids_absent(state: dict[str, object], xids: frozenset[int]) -> bool:
    return (
        not any(int(window.get("xid", 0)) in xids for window in state["windows"])
        and not any(int(window.get("xid", 0)) in xids
                    for window in state["override_redirect"])
        and not any(entry["xid"] in xids and (entry["associated"] or entry["mapped"])
                    for entry in state["xwayland_lifecycle"])
    )


def assert_runtime_state(state: dict[str, object]) -> ObservedXids:
    real_xids: set[int] = set()
    for expected in REAL_WINDOWS:
        matches = matching_windows(state, expected)
        if len(matches) != 1:
            raise RuntimeError(f"{expected.label} identity is ambiguous or absent: {state!r}")
        window = matches[0]
        xid = int(window["xid"])
        if not window["mapped"] or not window["decorated"]:
            raise RuntimeError(f"{expected.label} is not mapped and managed: {window!r}")
        if not lifecycle_is_managed(state, xid):
            raise RuntimeError(f"{expected.label} lacks an associated Xwayland surface: {state!r}")
        real_xids.add(xid)

    purpose = [
        window for window in state["windows"]
        if window["title"] in {"xwm-parent-initial", "xwm-transient"}
    ]
    if len(purpose) != 2:
        raise RuntimeError(f"purpose-built ICCCM windows are incomplete: {state!r}")
    parent = next(window for window in purpose if window["title"] == "xwm-parent-initial")
    transient = next(window for window in purpose if window["title"] == "xwm-transient")
    if (parent["instance"], parent["class"]) != (
        "xwm-instance-initial", "XwmClassInitial"
    ):
        raise RuntimeError(f"purpose-built normal-window identity is stale: {parent!r}")
    if transient["parent"] != parent["xid"]:
        raise RuntimeError(f"purpose-built transient role is missing: {transient!r}")
    if not parent["supports_delete"] or not parent["urgent"] or parent["input"]:
        raise RuntimeError(f"purpose-built ICCCM protocol/hint state is missing: {parent!r}")
    hints = parent["size_hints"]
    if tuple(
        hints[key] for key in (
            "min_width", "min_height", "max_width", "max_height",
            "base_width", "base_height", "width_inc", "height_inc",
        )
    ) != (80, 60, 320, 240, 40, 30, 20, 10):
        raise RuntimeError(f"purpose-built WM_NORMAL_HINTS are missing: {parent!r}")
    overrides = [
        item for item in state["override_redirect"]
        if item["title"] == "xwm-override-redirect" and item["mapped"]
    ]
    if len(overrides) != 1:
        raise RuntimeError(f"purpose-built override-redirect role is missing: {state!r}")
    override_xid = int(overrides[0]["xid"])
    if not lifecycle_is_override(state, override_xid):
        raise RuntimeError(f"override-redirect surface lacks association: {state!r}")
    icccm_xids = {override_xid}
    for window in purpose:
        xid = int(window["xid"])
        if not lifecycle_is_managed(state, xid):
            raise RuntimeError(f"purpose-built window lacks association: {window!r}")
        icccm_xids.add(xid)
    return ObservedXids(frozenset(real_xids), frozenset(icccm_xids))


def descendants(pid: int) -> set[int]:
    found: set[int] = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        children_path = Path(f"/proc/{parent}/task/{parent}/children")
        try:
            children = children_path.read_text(encoding="ascii").split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        for child_text in children:
            child = int(child_text)
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def wait_dialog_process(xterm_pid: int, dialog: Path) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for pid in descendants(xterm_pid):
            try:
                executable = Path(f"/proc/{pid}/exe").resolve(strict=True)
            except (FileNotFoundError, ProcessLookupError):
                continue
            if executable == dialog:
                return pid
        time.sleep(0.01)
    raise RuntimeError("real dialog process did not remain alive beneath terminal xterm")


def ensure_alive(apps: list[RunningApp], dialog_pid: int) -> None:
    exited = [f"{app.label}={app.process.returncode}" for app in apps
              if app.process.poll() is not None]
    if exited:
        raise RuntimeError("canonical client exited during observation: " + ", ".join(exited))
    if not Path(f"/proc/{dialog_pid}/exe").exists():
        raise RuntimeError("terminal dialog exited during observation")


def wait_process_gone(pid: int, description: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return
        time.sleep(0.01)
    raise RuntimeError(f"{description} remained after bounded cleanup")


def stop_group(app: RunningApp) -> str:
    try:
        os.killpg(app.process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        stdout, stderr = app.process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(app.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = app.process.communicate(timeout=5)
    return f"{app.label} stdout:\n{stdout}\n{app.label} stderr:\n{stderr}"


def launch(label: str, command: list[str], environment: dict[str, str]) -> RunningApp:
    return RunningApp(
        label,
        subprocess.Popen(
            command,
            env=environment,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ),
    )


def run(arguments: argparse.Namespace) -> None:
    programs = {
        name: checked_program(getattr(arguments, name), name)
        for name in ("xterm", "xclock", "xload", "emacs", "dialog")
    }
    compositor = arguments.compositor.resolve(strict=True)
    icccm_client = arguments.icccm_client.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="wtwm-canonical-apps-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "canonical.twmrc"
        config.write_text("RandomPlacement\n", encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C",
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", f"wtwm-canonical-{os.getpid()}",
                "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        apps: list[RunningApp] = []
        icccm: subprocess.Popen[str] | None = None
        diagnostic_logs: list[str] = []
        successful = False
        try:
            control = Control(control_path, process)
            control.command("SET FONT DejaVu Sans 10")
            control.command("SET PLACEMENT_SEED 0")
            control.command("OUTPUT 1280 960")
            display = wait_path(display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display

            apps.extend([
                launch("xterm", [
                    str(programs["xterm"]), "-display", display,
                    "-name", "wtwm-real-xterm", "-class", "WtwmRealXterm",
                    "-title", "WTWM Real Xterm", "-geometry", "40x8+20+20",
                    "-fn", "fixed", "+sb", "-hold", "-e", "/bin/true",
                ], client_environment),
                launch("xclock", [
                    str(programs["xclock"]), "-display", display,
                    "-name", "wtwm-real-xclock", "-title", "WTWM Real XClock",
                    "-geometry", "180x180+460+20",
                ], client_environment),
                launch("xload", [
                    str(programs["xload"]), "-display", display,
                    "-name", "wtwm-real-xload", "-title", "WTWM Real XLoad",
                    "-geometry", "260x120+660+20",
                ], client_environment),
                launch("emacs", [
                    str(programs["emacs"]), "--display", display, "--quick",
                    "--no-splash", "--name", "wtwm-real-emacs",
                    "--title", "WTWM Real Emacs", "--geometry", "70x18+20+300",
                ], client_environment),
                launch("terminal-dialog", [
                    str(programs["xterm"]), "-display", display,
                    "-name", "wtwm-terminal-dialog", "-class", "WtwmTerminalDialog",
                    "-title", "WTWM Terminal Dialog", "-geometry", "50x12+700+300",
                    "-fn", "fixed", "+sb", "-e", str(programs["dialog"]),
                    "--title", "WTWM terminal dialog", "--msgbox",
                    "Real terminal dialog under Xwayland", "8", "42",
                ], client_environment),
            ])
            icccm = subprocess.Popen(
                [str(icccm_client)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                start_new_session=True,
            )
            wait_line(icccm, "READY")
            state = wait_state(
                control,
                lambda item: all_real_windows_mapped(item)
                and len([window for window in item["windows"]
                         if window["title"] in {"xwm-parent-initial", "xwm-transient"}]) == 2
                and any(window["title"] == "xwm-override-redirect"
                        for window in item["override_redirect"]),
                "real canonical applications and purpose-built ICCCM maps",
            )
            observed_xids = assert_runtime_state(state)
            dialog_app = next(app for app in apps if app.label == "terminal-dialog")
            dialog_pid = wait_dialog_process(dialog_app.process.pid, programs["dialog"])
            ensure_alive(apps + [RunningApp("icccm-client", icccm)], dialog_pid)

            control.command("WAIT 3")
            stable_state = control.state()
            if assert_runtime_state(stable_state) != observed_xids:
                raise RuntimeError("canonical application XIDs changed during observation")
            ensure_alive(apps + [RunningApp("icccm-client", icccm)], dialog_pid)

            assert icccm.stdin is not None
            icccm.stdin.write("EXIT\n")
            icccm.stdin.flush()
            icccm.wait(timeout=5)
            if icccm.returncode != 0:
                raise RuntimeError(f"purpose-built ICCCM client returned {icccm.returncode}")
            icccm = None
            wait_state(
                control,
                lambda item: xids_absent(item, observed_xids.icccm),
                "purpose-built ICCCM managed and override-redirect cleanup",
            )

            for app in apps:
                diagnostic_logs.append(stop_group(app))
            apps.clear()
            wait_state(
                control,
                lambda item: xids_absent(item, observed_xids.real),
                "real canonical application cleanup",
            )
            wait_process_gone(dialog_pid, "terminal dialog")
            control.command("QUIT")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError(f"compositor returned {process.returncode}")
            successful = True
        except Exception as error:
            if icccm is not None:
                diagnostic_logs.append(stop_group(RunningApp("icccm-client", icccm)))
                icccm = None
            for app in apps:
                diagnostic_logs.append(stop_group(app))
            apps.clear()
            if process.poll() is None:
                process.terminate()
            try:
                compositor_stdout, compositor_stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                compositor_stdout, compositor_stderr = process.communicate(timeout=5)
            raise RuntimeError(
                f"{error}\n" + "\n".join(diagnostic_logs)
                + f"\ncompositor stdout:\n{compositor_stdout}"
                + f"\ncompositor stderr:\n{compositor_stderr}"
            ) from error
        finally:
            if icccm is not None:
                stop_group(RunningApp("icccm-client", icccm))
            for app in apps:
                stop_group(app)
            if control is not None:
                control.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        if not successful:
            raise RuntimeError("canonical application run did not complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--icccm-client", type=Path, required=True)
    for name in ("xterm", "xclock", "xload", "emacs", "dialog"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    run(parser.parse_args())
    print("canonical real X11 applications verified under wtwm/Xwayland")


if __name__ == "__main__":
    main()
