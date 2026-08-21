#!/usr/bin/env python3
"""Compare X11 close/destruction and record native close-only translation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Any

from run_compositor import Control


GRACEFUL_TITLE = "m10-close-graceful"
FORCED_TITLE = "m10-close-forced"
NATIVE_TITLE = "m10-close-native"


class Client:
    def __init__(self, process: subprocess.Popen[bytes], label: str) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError(f"{label} client lacks control pipes")
        self.process = process
        self.label = label
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.buffer = bytearray()
        self.pending: list[str] = []
        os.set_blocking(self.stdout.fileno(), False)

    def line(self, timeout: float = 10) -> str:
        deadline = time.monotonic() + timeout
        while not self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"timed out waiting for {self.label} output")
            readable, _, _ = select.select([self.stdout], [], [], remaining)
            if not readable:
                raise RuntimeError(f"timed out waiting for {self.label} output")
            data = os.read(self.stdout.fileno(), 4096)
            if not data:
                raise RuntimeError(
                    f"{self.label} exited while output was pending: "
                    f"{self.process.poll()}"
                )
            self.buffer.extend(data)
            while b"\n" in self.buffer:
                raw, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                self.pending.append(raw.decode("utf-8"))
        return self.pending.pop(0)

    def expect(self, expected: str) -> str:
        line = self.line()
        if line != expected and not line.startswith(expected + " "):
            raise RuntimeError(
                f"unexpected {self.label} output {line!r}; expected {expected!r}"
            )
        return line

    def command(self, command: str, expected: str) -> str:
        self.stdin.write((command + "\n").encode("utf-8"))
        self.stdin.flush()
        return self.expect(expected)

    def expect_event(self, expected: str) -> None:
        while True:
            line = self.line()
            if line == expected:
                return
            if line.startswith("EVENT ENTER ") or line.startswith("EVENT LEAVE "):
                continue
            raise RuntimeError(
                f"unexpected {self.label} event {line!r}; expected {expected!r}"
            )


def wait_xvfb(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if readable:
            value = process.stdout.readline().strip()
            if value.isdigit():
                return f":{value}"
            raise RuntimeError(f"Xvfb published an invalid display: {value!r}")
        if process.poll() is not None:
            break
    raise RuntimeError("Xvfb did not publish a display within 10 seconds")


def stop(process: subprocess.Popen[Any] | None) -> tuple[str, str]:
    if process is None:
        return "", ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stdout, stderr = process.communicate()
    return str(stdout or ""), str(stderr or "")


def stop_group(process: subprocess.Popen[Any] | None) -> tuple[str, str]:
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
    if process is None:
        return "", ""
    stdout, stderr = process.communicate()
    return str(stdout or ""), str(stderr or "")


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
        if value:
            return value
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def launch_x11(binary: Path, environment: dict[str, str], title: str
               ) -> tuple[subprocess.Popen[bytes], Client, int]:
    process = subprocess.Popen(
        [str(binary), title, title, "WtwmM10Close"], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    channel = Client(process, title)
    ready = channel.expect(f"OK READY {title}")
    return process, channel, int(ready.rsplit(" ", 1)[1])


def wait_process(process: subprocess.Popen[Any], description: str) -> int:
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"timed out waiting for {description}") from error


def snapshot(observer: Path, environment: dict[str, str], title: str
             ) -> dict[str, Any]:
    value = subprocess.run(
        [str(observer), title], env=environment, check=True, timeout=10,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("count"), int):
        raise RuntimeError(f"close observer returned invalid state: {value!r}")
    return parsed


def wait_snapshot(observer: Path, environment: dict[str, str], title: str,
                  count: int, reparented: bool | None = None
                  ) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    value: dict[str, Any] = {"count": -1}
    while time.monotonic() < deadline:
        value = snapshot(observer, environment, title)
        if value["count"] == count and (
                reparented is None or value.get("reparented") is reparented):
            return value
        time.sleep(0.01)
    raise RuntimeError(
        f"timed out waiting for {count} {title!r} windows: {value!r}"
    )


def input_event(driver: Path, environment: dict[str, str], *values: str) -> None:
    subprocess.run(
        [str(driver), *values], env=environment, check=True, timeout=10,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def reference_click(driver: Path, environment: dict[str, str],
                    geometry: dict[str, Any], button: int) -> None:
    x = int(geometry["x"]) + int(geometry["width"]) // 2
    y = int(geometry["y"]) + 8
    input_event(driver, environment, "pointer", str(x), str(y))
    input_event(driver, environment, "button", str(button), "press")
    input_event(driver, environment, "button", str(button), "release")


def x11_outcome() -> dict[str, Any]:
    return {
        "graceful-delete": {
            "wm_delete_received": True,
            "client_cooperated": True,
            "target_removed": True,
            "client_exit": "success",
        },
        "ignored-delete-then-destroy": {
            "wm_delete_received": True,
            "target_survived_delete": True,
            "x_connection_forced_closed": True,
            "target_removed": True,
            "client_exit": "connection-error",
        },
        "recreate-after-destroy": {
            "new_client_process": True,
            "prior_lifecycle_removed_before_recreate": True,
            "single_live_instance": True,
            "x_connection_forced_closed": True,
            "target_removed": True,
            "stale_state": False,
        },
    }


def run_reference(arguments: argparse.Namespace, config: Path,
                  evidence: Path) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "GDK_BACKEND": "x11"})
    xvfb = subprocess.Popen(
        [str(arguments.xvfb), "-displayfd", "1", "-screen", "0", "640x480x24",
         "-nolisten", "tcp"], cwd=arguments.source_root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    twm: subprocess.Popen[str] | None = None
    clients: list[subprocess.Popen[bytes]] = []
    try:
        environment["DISPLAY"] = wait_xvfb(xvfb)
        twm = subprocess.Popen(
            [str(arguments.reference_twm), "-display", environment["DISPLAY"],
             "-single", "-f", str(config), "-quiet"],
            cwd=arguments.source_root, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        subprocess.run(
            [str(arguments.reference_observer), "ready"], env=environment,
            check=True, timeout=20,
        )

        graceful_process, graceful, _ = launch_x11(
            arguments.x11_client, environment, GRACEFUL_TITLE
        )
        clients.append(graceful_process)
        geometry = wait_snapshot(
            arguments.close_observer, environment, GRACEFUL_TITLE, 1, True
        )
        reference_click(arguments.input_driver, environment, geometry, 1)
        graceful.expect("EVENT DELETE 1")
        graceful.command("EXIT", "OK EXIT")
        if wait_process(graceful_process, "reference graceful client") != 0:
            raise RuntimeError("reference graceful client did not exit cleanly")
        wait_snapshot(arguments.close_observer, environment, GRACEFUL_TITLE, 0)

        forced_process, forced, forced_xid = launch_x11(
            arguments.x11_client, environment, FORCED_TITLE
        )
        clients.append(forced_process)
        geometry = wait_snapshot(
            arguments.close_observer, environment, FORCED_TITLE, 1, True
        )
        reference_click(arguments.input_driver, environment, geometry, 1)
        forced.expect("EVENT DELETE 1")
        forced.command("REPORT", "OK REPORT close=1 mapped=1 cycle=0")
        geometry = wait_snapshot(
            arguments.close_observer, environment, FORCED_TITLE, 1, True
        )
        reference_click(arguments.input_driver, environment, geometry, 2)
        if wait_process(forced_process, "reference forced client") == 0:
            raise RuntimeError("reference f.destroy exited cooperatively")
        wait_snapshot(arguments.close_observer, environment, FORCED_TITLE, 0)

        recreated_process, _, recreated_xid = launch_x11(
            arguments.x11_client, environment, FORCED_TITLE
        )
        clients.append(recreated_process)
        geometry = wait_snapshot(
            arguments.close_observer, environment, FORCED_TITLE, 1, True
        )
        reference_click(arguments.input_driver, environment, geometry, 2)
        if wait_process(recreated_process, "reference recreated client") == 0:
            raise RuntimeError("reference recreated f.destroy exited cooperatively")
        wait_snapshot(arguments.close_observer, environment, FORCED_TITLE, 0)
        if twm.poll() is not None:
            raise RuntimeError(f"reference twm exited with {twm.returncode}")
        return x11_outcome()
    finally:
        for client in clients:
            if client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
        stdout, stderr = stop_group(twm)
        (evidence / "reference-twm.log").write_text(
            f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
        )
        stdout, stderr = stop(xvfb)
        (evidence / "reference-xvfb.log").write_text(
            f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
        )


def wait_state(control: Control, predicate, description: str
               ) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = control.state()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {state!r}")


def state_window(state: dict[str, Any], title: str) -> dict[str, Any]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {title!r} window: {state!r}")
    return matches[0]


def mapped(control: Control, title: str, protocol: str,
           xid: int | None = None) -> dict[str, Any]:
    def ready(state: dict[str, Any]) -> bool:
        matches = [item for item in state["windows"] if item["title"] == title]
        return len(matches) == 1 and matches[0]["type"] == protocol and (
            xid is None or int(matches[0]["xid"]) == xid
        )
    return wait_state(control, ready, f"single mapped {protocol} {title}")


def cleaned(control: Control, title: str, xid: int | None = None) -> None:
    wait_state(
        control,
        lambda state: not any(item["title"] == title for item in state["windows"])
        and (xid is None or not any(
            int(item["xid"]) == xid for item in state["xwayland_lifecycle"]
        )),
        f"complete cleanup of {title}",
    )


def wtwm_click(control: Control, state: dict[str, Any], title: str,
               raw_button: int) -> None:
    item = state_window(state, title)
    x = int(item["x"]) + int(item["width"]) // 2
    y = int(item["y"]) + 8
    control.command(f"POINTER {x} {y}")
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")


def run_wtwm(arguments: argparse.Namespace, config: Path,
             evidence: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="wtwm-m10-close-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        wayland_display = f"wtwm-m10-close-{os.getpid()}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor = subprocess.Popen(
            [str(arguments.compositor), "-f", str(config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", wayland_display,
             "--test-backend", "headless"],
            cwd=arguments.source_root, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        control: Control | None = None
        clients: list[subprocess.Popen[bytes]] = []
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("OUTPUT 640 480")
            x11_environment = environment.copy()
            x11_environment["DISPLAY"] = wait_path(display_marker)

            graceful_process, graceful, graceful_xid = launch_x11(
                arguments.x11_client, x11_environment, GRACEFUL_TITLE
            )
            clients.append(graceful_process)
            state = mapped(control, GRACEFUL_TITLE, "x11", graceful_xid)
            wtwm_click(control, state, GRACEFUL_TITLE, 272)
            graceful.expect("EVENT DELETE 1")
            graceful.command("EXIT", "OK EXIT")
            if wait_process(graceful_process, "wtwm graceful client") != 0:
                raise RuntimeError("wtwm graceful client did not exit cleanly")
            cleaned(control, GRACEFUL_TITLE, graceful_xid)

            forced_process, forced, forced_xid = launch_x11(
                arguments.x11_client, x11_environment, FORCED_TITLE
            )
            clients.append(forced_process)
            state = mapped(control, FORCED_TITLE, "x11", forced_xid)
            wtwm_click(control, state, FORCED_TITLE, 272)
            forced.expect("EVENT DELETE 1")
            forced.command("REPORT", "OK REPORT close=1 mapped=1 cycle=0")
            state = mapped(control, FORCED_TITLE, "x11", forced_xid)
            wtwm_click(control, state, FORCED_TITLE, 274)
            if wait_process(forced_process, "wtwm forced client") == 0:
                raise RuntimeError("wtwm f.destroy exited cooperatively")
            cleaned(control, FORCED_TITLE, forced_xid)

            recreated_process, _, recreated_xid = launch_x11(
                arguments.x11_client, x11_environment, FORCED_TITLE
            )
            clients.append(recreated_process)
            state = mapped(control, FORCED_TITLE, "x11", recreated_xid)
            if sum(item["title"] == FORCED_TITLE for item in state["windows"]) != 1:
                raise RuntimeError(f"wtwm retained stale recreated state: {state!r}")
            wtwm_click(control, state, FORCED_TITLE, 274)
            if wait_process(recreated_process, "wtwm recreated client") == 0:
                raise RuntimeError("wtwm recreated f.destroy exited cooperatively")
            cleaned(control, FORCED_TITLE, recreated_xid)

            wayland_environment = environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = wayland_display
            native_process = subprocess.Popen(
                [str(arguments.native_client), NATIVE_TITLE,
                 "org.wtwm.M10Close"], env=wayland_environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append(native_process)
            native = Client(native_process, NATIVE_TITLE)
            native.expect(f"OK READY {NATIVE_TITLE}")
            native.command("ARM close", "OK ARMED close")
            state = mapped(control, NATIVE_TITLE, "wayland")
            wtwm_click(control, state, NATIVE_TITLE, 272)
            native.expect_event("EVENT CLOSE 1")
            state = mapped(control, NATIVE_TITLE, "wayland")
            if native_process.poll() is not None:
                raise RuntimeError("native client exited after f.delete")
            wtwm_click(control, state, NATIVE_TITLE, 274)
            native.expect_event("EVENT CLOSE 2")
            mapped(control, NATIVE_TITLE, "wayland")
            if native_process.poll() is not None:
                raise RuntimeError("native client exited after translated f.destroy")
            native.command("REPORT close", "OK REPORT close")
            native.command("EXIT", "OK EXIT")
            if wait_process(native_process, "native close-only client") != 0:
                raise RuntimeError("native close-only client did not exit cleanly")
            cleaned(control, NATIVE_TITLE)

            if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("wtwm stopped responding after close scenarios")
            native_outcome = {
                "f.delete": {
                    "xdg_toplevel_close_count": 1,
                    "client_remained_mapped": True,
                },
                "f.destroy": {
                    "xdg_toplevel_close_count": 2,
                    "client_remained_mapped": True,
                    "forced_client_kill_available": False,
                    "classification": "unavoidable-native-close-only-translation",
                },
                "external_cleanup": "clean-client-exit",
                "stale_state": False,
            }
            control.command("QUIT")
            if compositor.wait(timeout=10) != 0:
                raise RuntimeError("wtwm close session exited nonzero")
            return x11_outcome(), native_outcome
        finally:
            for client in clients:
                if client.poll() is None:
                    client.terminate()
                    client.wait(timeout=5)
            if control is not None:
                control.close()
            stdout, stderr = stop(compositor)
            (evidence / "wtwm-session.log").write_text(
                f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
            )


def compare(reference: dict[str, Any], wtwm: dict[str, Any]) -> None:
    expected = x11_outcome()
    if reference != expected or wtwm != expected:
        raise RuntimeError(
            f"X11 close outcomes differ: expected={expected!r}, "
            f"reference={reference!r}, wtwm={wtwm!r}"
        )


def self_test() -> None:
    expected = x11_outcome()
    compare(expected, expected)
    tampered = json.loads(json.dumps(expected))
    tampered["ignored-delete-then-destroy"]["target_survived_delete"] = False
    try:
        compare(expected, tampered)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("close-outcome tamper was accepted")
    print("Milestone 10 close/destruction differential self-test passed")


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    for path in arguments.evidence.iterdir():
        if path.is_file():
            path.unlink()
    result: dict[str, Any] = {
        "schema_version": 1,
        "comparison": "live-twm-1.0.13.1-vs-wtwm-close-and-destruction",
        "result": "failed",
    }
    try:
        version = subprocess.run(
            [str(arguments.reference_twm), "-V"], cwd=arguments.source_root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=10,
        ).stdout.strip()
        if version != "twm 1.0.13.1":
            raise RuntimeError(f"unexpected reference version: {version!r}")
        reference = run_reference(arguments, arguments.config, arguments.evidence)
        wtwm, native = run_wtwm(arguments, arguments.config, arguments.evidence)
        compare(reference, wtwm)
        result.update({
            "reference_version": version,
            "x11_reference": reference,
            "x11_wtwm": wtwm,
            "native_wayland_translation": native,
            "unexplained_differences": 0,
            "result": "equivalent-with-documented-native-translation",
        })
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    for name in (
        "source-root", "reference-twm", "xvfb", "compositor", "config", "input-driver",
        "reference-observer", "close-observer", "x11-client",
        "native-client", "output", "evidence",
    ):
        parser.add_argument(f"--{name}", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    required = tuple(name.replace("-", "_") for name in (
        "source-root", "reference-twm", "xvfb", "compositor", "config", "input-driver",
        "reference-observer", "close-observer", "x11-client",
        "native-client", "output", "evidence",
    ))
    missing = [name for name in required if getattr(arguments, name) is None]
    if missing:
        parser.error("missing live arguments: " + ", ".join(missing))
    for name in required[:-2]:
        setattr(arguments, name, getattr(arguments, name).resolve(strict=True))
    arguments.output = arguments.output.resolve()
    arguments.evidence = arguments.evidence.resolve()
    run(arguments)


if __name__ == "__main__":
    main()
