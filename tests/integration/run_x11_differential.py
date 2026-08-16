#!/usr/bin/env python3
"""Compare one canonical X11 workload under reference twm and wtwm/Xwayland."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
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
class Role:
    name: str
    title: str
    instance: str | None
    class_name: str | None
    override_redirect: bool = False


@dataclass
class RunningApp:
    label: str
    process: subprocess.Popen[str]


ROLES = (
    Role("xterm", "WTWM Real Xterm", "wtwm-real-xterm", "WtwmRealXterm"),
    Role("xclock", "WTWM Real XClock", "wtwm-real-xclock", "XClock"),
    Role("xload", "WTWM Real XLoad", "wtwm-real-xload", "XLoad"),
    Role("emacs", "WTWM Real Emacs", "wtwm-real-emacs", "Emacs-gtk"),
    Role(
        "terminal-dialog",
        "WTWM Terminal Dialog",
        "wtwm-terminal-dialog",
        "WtwmTerminalDialog",
    ),
    Role(
        "icccm-normal",
        "xwm-parent-initial",
        "xwm-instance-initial",
        "XwmClassInitial",
    ),
    Role(
        "icccm-transient",
        "xwm-transient",
        "xwm-transient-instance",
        "XwmTransientClass",
    ),
    Role("icccm-override", "xwm-override-redirect", None, None, True),
)
ROLE_BY_NAME = {role.name: role for role in ROLES}
EXCLUDED_COMPARISONS = (
    "exact frame and client geometry (Milestone 4)",
    "pixel rendering and decoration appearance (Milestone 5)",
    "native-Wayland and cross-protocol semantics (later Milestone 3 testing)",
)
REQUIRED_STABLE_CAPTURES = 3
MAX_CONVERGENCE_CAPTURES = 24


def checked_program(path: Path, requested_name: str) -> Path:
    if not path.is_absolute() or path.name != requested_name:
        raise RuntimeError(f"{requested_name} must be passed as its absolute Debian path")
    resolved = path.resolve(strict=True)
    if resolved.parent != Path("/usr/bin") or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"{requested_name} is not a Debian /usr/bin executable: {resolved}")
    if requested_name == "emacs":
        if not resolved.name.startswith("emacs"):
            raise RuntimeError(f"emacs alternative resolves unexpectedly: {resolved}")
    elif resolved.name != requested_name:
        raise RuntimeError(f"{requested_name} resolves unexpectedly: {resolved}")
    return resolved


def canonical_commands(programs: dict[str, Path]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (
            "xterm",
            (
                str(programs["xterm"]), "-name", "wtwm-real-xterm", "-class",
                "WtwmRealXterm", "-title", "WTWM Real Xterm", "-geometry",
                "40x8+20+20", "-fn", "fixed", "+sb", "-hold", "-e", "/bin/true",
            ),
        ),
        (
            "xclock",
            (
                str(programs["xclock"]), "-name", "wtwm-real-xclock", "-title",
                "WTWM Real XClock", "-geometry", "180x180+460+20",
            ),
        ),
        (
            "xload",
            (
                str(programs["xload"]), "-name", "wtwm-real-xload", "-title",
                "WTWM Real XLoad", "-geometry", "260x120+660+20",
            ),
        ),
        (
            "emacs",
            (
                str(programs["emacs"]), "--quick", "--no-splash", "--name",
                "wtwm-real-emacs", "--title", "WTWM Real Emacs", "--geometry",
                "70x18+20+300",
            ),
        ),
        (
            "terminal-dialog",
            (
                str(programs["xterm"]), "-name", "wtwm-terminal-dialog", "-class",
                "WtwmTerminalDialog", "-title", "WTWM Terminal Dialog", "-geometry",
                "50x12+700+300", "-fn", "fixed", "+sb", "-e",
                str(programs["dialog"]), "--title", "WTWM terminal dialog", "--msgbox",
                "Real terminal dialog in the X11 differential", "8", "42",
            ),
        ),
    )


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
        raise RuntimeError(f"unexpected ICCCM client event: {line!r}")
    raise RuntimeError(f"timed out waiting for ICCCM client event {expected!r}")


def wait_xvfb_display(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], deadline - time.monotonic())
        if readable:
            value = process.stdout.readline().strip()
            if value.isdigit():
                return f":{value}"
            raise RuntimeError(f"Xvfb returned invalid display number {value!r}")
        if process.poll() is not None:
            break
    raise RuntimeError("Xvfb did not publish a display number")


def wait_command(command: list[str], environment: dict[str, str], description: str) -> None:
    deadline = time.monotonic() + 10
    latest = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        latest = result.stderr
        if result.returncode == 0:
            return
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {latest}")


def wait_capture(
    probe: Path,
    environment: dict[str, str],
    predicate: Callable[[dict[str, object]], bool],
    description: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 15
    latest = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [str(probe), "capture"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        latest = result.stderr
        if result.returncode == 0:
            observed = json.loads(result.stdout)
            if predicate(observed):
                return observed
        elif result.returncode != 3:
            raise RuntimeError(f"X11 capture failed ({result.returncode}): {latest}")
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {latest}")


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


def pid_is_running(pid: int) -> bool:
    try:
        suffix = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rpartition(")")[2]
    except (FileNotFoundError, ProcessLookupError):
        return False
    fields = suffix.split()
    return bool(fields) and fields[0] != "Z"


def wait_pid_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_is_running(pid):
            return True
        time.sleep(0.01)
    return not pid_is_running(pid)


def stop_dialog_child(parent: subprocess.Popen[str], dialog_pid: int) -> None:
    if parent.poll() is not None:
        return
    try:
        os.kill(dialog_pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if wait_pid_gone(dialog_pid, 2):
        return
    try:
        os.kill(dialog_pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    if not wait_pid_gone(dialog_pid, 3):
        raise RuntimeError("terminal xterm did not reap dialog after bounded SIGKILL")


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


def stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def launch_workload(
    commands: tuple[tuple[str, tuple[str, ...]], ...],
    icccm_client: Path,
    environment: dict[str, str],
) -> tuple[list[RunningApp], subprocess.Popen[str]]:
    apps = [
        RunningApp(
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
        for label, command in commands
    ]
    icccm = subprocess.Popen(
        [str(icccm_client)],
        env=environment,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        start_new_session=True,
    )
    wait_line(icccm, "READY")
    return apps, icccm


def verify_workload_alive(apps: list[RunningApp], icccm: subprocess.Popen[str]) -> None:
    exited = [app.label for app in apps if app.process.poll() is not None]
    if icccm.poll() is not None:
        exited.append("icccm-client")
    if exited:
        raise RuntimeError("canonical clients exited during comparison: " + ", ".join(exited))


def stop_workload(
    apps: list[RunningApp],
    icccm: subprocess.Popen[str] | None,
    dialog_pid: int | None,
) -> list[str]:
    logs: list[str] = []
    if icccm is not None and icccm.poll() is None:
        assert icccm.stdin is not None
        icccm.stdin.write("EXIT\n")
        icccm.stdin.flush()
        try:
            icccm.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logs.append(stop_group(RunningApp("icccm-client", icccm)))
    if icccm is not None and icccm.poll() not in (None, 0):
        logs.append(f"icccm-client exited with {icccm.returncode}")
    dialog_app = next((app for app in apps if app.label == "terminal-dialog"), None)
    if dialog_app is not None and dialog_pid is not None:
        stop_dialog_child(dialog_app.process, dialog_pid)
    for app in apps:
        logs.append(stop_group(app))
    apps.clear()
    return logs


def raw_clients(observed: dict[str, object]) -> list[dict[str, object]]:
    clients = observed.get("clients")
    if not isinstance(clients, list) or [item.get("role") for item in clients] != [
        role.name for role in ROLES
    ]:
        raise RuntimeError(f"observer returned an invalid role set: {observed!r}")
    return clients


def reference_ready(observed: dict[str, object]) -> bool:
    for item in raw_clients(observed):
        role = ROLE_BY_NAME[str(item["role"])]
        if not item["mapped"] or bool(item["override_redirect"]) != role.override_redirect:
            return False
        if bool(item["root_parent"]) == (not role.override_redirect):
            return False
    return True


def wtwm_control_ready(state: dict[str, object]) -> bool:
    for role in ROLES:
        collection = state["override_redirect"] if role.override_redirect else state["windows"]
        matches = [
            item
            for item in collection
            if item["title"] == role.title
            and (role.instance is None or item.get("instance") == role.instance)
            and (role.class_name is None or item.get("class") == role.class_name)
        ]
        if len(matches) != 1 or not matches[0]["mapped"]:
            return False
        xid = int(matches[0]["xid"])
        lifecycle = [
            entry
            for entry in state["xwayland_lifecycle"]
            if int(entry["xid"]) == xid
            and entry["associated"]
            and entry["mapped"]
            and bool(entry["override_redirect"]) == role.override_redirect
        ]
        if len(lifecycle) != 1:
            return False
    return True


def wait_control(control: Control) -> dict[str, object]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = control.state()
        if wtwm_control_ready(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for wtwm scene management: {control.state()!r}")


def normalized_common(item: dict[str, object], managed: bool) -> dict[str, object]:
    result = dict(item)
    result.pop("root_parent")
    result["managed"] = managed
    return result


def normalize_reference(observed: dict[str, object]) -> list[dict[str, object]]:
    if not reference_ready(observed):
        raise RuntimeError(f"reference twm did not reparent the managed workload: {observed!r}")
    return [
        normalized_common(item, not ROLE_BY_NAME[str(item["role"])].override_redirect)
        for item in raw_clients(observed)
    ]


def normalize_wtwm(
    observed: dict[str, object], state: dict[str, object]
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in raw_clients(observed):
        role = ROLE_BY_NAME[str(item["role"])]
        if not item["root_parent"]:
            raise RuntimeError(f"wtwm unexpectedly reparented an Xwayland client: {item!r}")
        collection = state["override_redirect"] if role.override_redirect else state["windows"]
        matches = [entry for entry in collection if entry["title"] == role.title]
        if len(matches) != 1:
            raise RuntimeError(f"wtwm scene role is ambiguous: {role.name}: {state!r}")
        scene = matches[0]
        managed = not role.override_redirect and bool(scene["mapped"])
        results.append(normalized_common(item, managed))
    return results


def write_convergence_history(
    evidence: Path,
    backend: str,
    samples: list[list[dict[str, object]]],
) -> None:
    (evidence / f"{backend}-convergence.json").write_text(
        json.dumps({
            "backend": backend,
            "required_consecutive_equal": REQUIRED_STABLE_CAPTURES,
            "samples": samples,
            "schema_version": 1,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def converge_reference(
    probe: Path,
    environment: dict[str, str],
    evidence: Path,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + 15
    samples: list[list[dict[str, object]]] = []
    previous: list[dict[str, object]] | None = None
    consecutive = 0
    write_convergence_history(evidence, "reference", samples)
    for _ in range(MAX_CONVERGENCE_CAPTURES):
        if time.monotonic() >= deadline:
            break
        wait_command(
            [str(probe), "ready"], environment,
            "reference twm convergence sentinel reparent",
        )
        observed = wait_capture(
            probe, environment, reference_ready,
            "reference twm reparented workload",
        )
        current = normalize_reference(observed)
        samples.append(current)
        write_convergence_history(evidence, "reference", samples)
        if current == previous:
            consecutive += 1
        else:
            previous = current
            consecutive = 1
        if consecutive >= REQUIRED_STABLE_CAPTURES:
            return current
    raise RuntimeError(
        "reference normalized X11 observations did not converge across "
        f"{len(samples)} sentinel reparent barriers"
    )


def converge_wtwm(
    control: Control,
    probe: Path,
    environment: dict[str, str],
    evidence: Path,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + 15
    samples: list[list[dict[str, object]]] = []
    previous: list[dict[str, object]] | None = None
    consecutive = 0
    write_convergence_history(evidence, "wtwm", samples)
    for _ in range(MAX_CONVERGENCE_CAPTURES):
        if time.monotonic() >= deadline:
            break
        control.command("WAIT 3")
        state = wait_control(control)
        observed = wait_capture(
            probe, environment, lambda item: True,
            "wtwm/Xwayland convergence capture",
        )
        current = normalize_wtwm(observed, state)
        samples.append(current)
        write_convergence_history(evidence, "wtwm", samples)
        if current == previous:
            consecutive += 1
        else:
            previous = current
            consecutive = 1
        if consecutive >= REQUIRED_STABLE_CAPTURES:
            return current
    raise RuntimeError(
        "wtwm normalized X11 observations did not converge across "
        f"{len(samples)} compositor frame barriers"
    )


def run_reference(
    reference_twm: Path,
    scenario: Path,
    commands: tuple[tuple[str, tuple[str, ...]], ...],
    icccm_client: Path,
    probe: Path,
    dialog: Path,
    evidence: Path,
) -> list[dict[str, object]]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    environment["GDK_BACKEND"] = "x11"
    xvfb = subprocess.Popen(
        ["/usr/bin/Xvfb", "-displayfd", "1", "-screen", "0", "1280x960x24",
         "-nolisten", "tcp"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    twm: subprocess.Popen[str] | None = None
    apps: list[RunningApp] = []
    icccm: subprocess.Popen[str] | None = None
    dialog_pid: int | None = None
    diagnostics: list[str] = []
    try:
        display = wait_xvfb_display(xvfb)
        environment["DISPLAY"] = display
        wait_command(["/usr/bin/xdpyinfo", "-display", display], environment,
                     "Xvfb readiness")
        twm = subprocess.Popen(
            [str(reference_twm), "-display", display, "-single", "-f", str(scenario),
             "-quiet"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_command(
            [str(probe), "ready"], environment,
            "reference twm sentinel reparent readiness",
        )
        apps, icccm = launch_workload(commands, icccm_client, environment)
        dialog_app = next(app for app in apps if app.label == "terminal-dialog")
        dialog_pid = wait_dialog_process(dialog_app.process.pid, dialog)
        verify_workload_alive(apps, icccm)
        stable = converge_reference(probe, environment, evidence)
        verify_workload_alive(apps, icccm)
        if twm.poll() is not None:
            raise RuntimeError(f"reference twm exited with {twm.returncode}")
        return stable
    except Exception as error:
        raise RuntimeError(f"reference session failed: {error}") from error
    finally:
        diagnostics.extend(stop_workload(apps, icccm, dialog_pid))
        if twm is not None:
            stdout, stderr = stop_process(twm)
            diagnostics.append(f"reference twm stdout:\n{stdout}\nstderr:\n{stderr}")
        stdout, stderr = stop_process(xvfb)
        diagnostics.append(f"Xvfb stdout:\n{stdout}\nstderr:\n{stderr}")
        (evidence / "reference-session.log").write_text(
            "\n".join(diagnostics), encoding="utf-8"
        )


def run_wtwm(
    compositor: Path,
    scenario: Path,
    commands: tuple[tuple[str, tuple[str, ...]], ...],
    icccm_client: Path,
    probe: Path,
    dialog: Path,
    temporary: Path,
    evidence: Path,
) -> list[dict[str, object]]:
    runtime = temporary / "runtime"
    runtime.mkdir(mode=0o700)
    control_path = temporary / "control.sock"
    display_marker = temporary / "display"
    startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
    environment = os.environ.copy()
    environment.update({
        "GDK_BACKEND": "x11",
        "LC_ALL": "C",
        "XDG_RUNTIME_DIR": str(runtime),
        "WLR_RENDERER": "pixman",
    })
    process = subprocess.Popen(
        [
            str(compositor), "-f", str(scenario), "-s", startup,
            "--test-control", str(control_path),
            "--test-socket", f"wtwm-differential-{os.getpid()}",
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
    dialog_pid: int | None = None
    diagnostics: list[str] = []
    try:
        control = Control(control_path, process)
        control.command("OUTPUT 1280 960")
        display = wait_path(display_marker)
        client_environment = environment.copy()
        client_environment["DISPLAY"] = display
        apps, icccm = launch_workload(commands, icccm_client, client_environment)
        wait_control(control)
        dialog_app = next(app for app in apps if app.label == "terminal-dialog")
        dialog_pid = wait_dialog_process(dialog_app.process.pid, dialog)
        verify_workload_alive(apps, icccm)
        stable = converge_wtwm(control, probe, client_environment, evidence)
        verify_workload_alive(apps, icccm)
        return stable
    except Exception as error:
        raise RuntimeError(f"wtwm session failed: {error}") from error
    finally:
        diagnostics.extend(stop_workload(apps, icccm, dialog_pid))
        if control is not None and process.poll() is None:
            try:
                control.command("QUIT")
            except (BrokenPipeError, ConnectionError, RuntimeError):
                process.terminate()
            control.close()
        stdout, stderr = stop_process(process)
        diagnostics.append(f"wtwm stdout:\n{stdout}\nstderr:\n{stderr}")
        (evidence / "wtwm-session.log").write_text(
            "\n".join(diagnostics), encoding="utf-8"
        )


def run(arguments: argparse.Namespace) -> None:
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    evidence = arguments.output.parent / "x11-differential-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for name in (
        "reference-convergence.json", "reference-session.log", "reference.json",
        "runner-error.log", "wtwm-convergence.json", "wtwm-session.log", "wtwm.json",
    ):
        (evidence / name).unlink(missing_ok=True)
    arguments.output.unlink(missing_ok=True)
    programs = {
        name: checked_program(getattr(arguments, name), name)
        for name in ("xterm", "xclock", "xload", "emacs", "dialog")
    }
    reference_twm = arguments.reference_twm.resolve(strict=True)
    compositor = arguments.compositor.resolve(strict=True)
    icccm_client = arguments.icccm_client.resolve(strict=True)
    probe = arguments.probe.resolve(strict=True)
    scenario = arguments.scenario.resolve(strict=True)
    version = subprocess.run(
        [str(reference_twm), "-V"], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=True
    ).stdout.strip()
    if version != "twm 1.0.13.1":
        raise RuntimeError(f"unexpected reference version: {version!r}")
    commands = canonical_commands(programs)
    try:
        with tempfile.TemporaryDirectory(prefix="wtwm-x11-differential-") as directory:
            temporary = Path(directory)
            reference = run_reference(
                reference_twm, scenario, commands, icccm_client, probe,
                programs["dialog"], evidence,
            )
            (evidence / "reference.json").write_text(
                json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            wtwm = run_wtwm(
                compositor, scenario, commands, icccm_client, probe,
                programs["dialog"], temporary, evidence,
            )
            (evidence / "wtwm.json").write_text(
                json.dumps(wtwm, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            if reference != wtwm:
                raise RuntimeError(
                    "normalized reference/wtwm X11 results differ:\n"
                    + json.dumps({"reference": reference, "wtwm": wtwm}, indent=2,
                                 sort_keys=True)
                )
            result = {
                "clients": reference,
                "comparison": "reference-twm-1.0.13.1-vs-wtwm-xwayland",
                "excluded": list(EXCLUDED_COMPARISONS),
                "management_translation": {
                    "reference": "managed client has a distinct reparent frame",
                    "wtwm": "managed client has a compositor scene decoration",
                },
                "result": "equivalent",
                "schema_version": 1,
            }
            arguments.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except Exception as error:
        (evidence / "runner-error.log").write_text(str(error) + "\n", encoding="utf-8")
        failure = {
            "comparison": "reference-twm-1.0.13.1-vs-wtwm-xwayland",
            "diagnostics": "see x11-differential-evidence",
            "result": "failed",
            "schema_version": 1,
        }
        arguments.output.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-twm", type=Path, required=True)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--icccm-client", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name in ("xterm", "xclock", "xload", "emacs", "dialog"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        run(arguments)
    except Exception as error:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        evidence = arguments.output.parent / "x11-differential-evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        error_path = evidence / "runner-error.log"
        if not error_path.exists():
            error_path.write_text(str(error) + "\n", encoding="utf-8")
        if not arguments.output.exists():
            arguments.output.write_text(
                json.dumps({
                    "comparison": "reference-twm-1.0.13.1-vs-wtwm-xwayland",
                    "diagnostics": "see x11-differential-evidence",
                    "result": "failed",
                    "schema_version": 1,
                }, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise
    print("canonical X11 clients match reference twm under wtwm/Xwayland")


if __name__ == "__main__":
    main()
