#!/usr/bin/env python3
"""Compare frozen-twm and wtwm command dispatch at the libc boundary."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
from typing import Any

from run_compositor import Control


ENV_VALUE = "expanded-by-command-shell"
PHASES = ("explicit", "alias", "shell", "empty", "startwm")


def twm_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def scenario(observer: Path, result_log: Path) -> dict[str, dict[str, Any]]:
    prefix = f"{observer} {result_log}"
    return {
        "explicit": {
            "spelling": "f.exec", "canonical": "f.exec",
            "command": f'{prefix} explicit "two words" literal',
            "argv": [str(observer), str(result_log), "explicit", "two words", "literal"],
        },
        "alias": {
            "spelling": "!", "canonical": "f.exec",
            "command": f'{prefix} alias "alias value"',
            "argv": [str(observer), str(result_log), "alias", "alias value"],
        },
        "shell": {
            "spelling": "f.exec", "canonical": "f.exec",
            "command": f'{prefix} shell "$WTWM_CERT_COMMAND"',
            "argv": [str(observer), str(result_log), "shell", ENV_VALUE],
        },
        "empty": {
            "spelling": "f.exec", "canonical": "f.exec",
            "command": "", "argv": None,
        },
        "startwm": {
            "spelling": "f.startwm", "canonical": "f.startwm",
            "command": f'{prefix} startwm "handoff value"',
            "argv": [str(observer), str(result_log), "startwm", "handoff value"],
        },
    }


def config_text(cases: dict[str, dict[str, Any]]) -> str:
    return "".join((
        "NoDefaults\nNoGrabServer\nNoIconManagers\n",
        f'Button1 = : root : f.exec {twm_string(cases["explicit"]["command"])}\n',
        f'Button2 = : root : ! {twm_string(cases["alias"]["command"])}\n',
        f'Button3 = : root : f.exec {twm_string(cases["shell"]["command"])}\n',
        'Button4 = : root : f.exec ""\n',
        f'Button5 = : root : f.startwm {twm_string(cases["startwm"]["command"])}\n',
    ))


def wait_xvfb(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.1)
        if readable:
            line = process.stdout.readline().strip()
            if line.isdigit():
                return f":{line}"
            raise RuntimeError(f"Xvfb published an invalid display: {line!r}")
        if process.poll() is not None:
            break
    raise RuntimeError("Xvfb did not publish a display within 10 seconds")


def stop_process(process: subprocess.Popen[str] | None) -> tuple[str, str]:
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
    return stdout or "", stderr or ""


def stop_group(process: subprocess.Popen[str] | None) -> tuple[str, str]:
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
    return stdout or "", stderr or ""


def decode_hex(value: str) -> str | None:
    if value == "-":
        return None
    return bytes.fromhex(value).decode("utf-8")


def parse_calls(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="ascii").splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        argc = int(fields[2])
        if len(fields) != 3 + argc:
            continue
        result.append({
            "pid": int(fields[0]), "operation": fields[1],
            "argv": [decode_hex(value) for value in fields[3:]],
        })
    return result


def parse_observers(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    result: list[list[str]] = []
    for line in path.read_text(encoding="ascii").splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        argc = int(fields[0])
        if len(fields) != 1 + argc:
            continue
        values = [decode_hex(value) for value in fields[1:]]
        if any(value is None for value in values):
            raise RuntimeError("observer emitted a null argument")
        result.append([str(value) for value in values])
    return result


def wait_count(loader, path: Path, count: int, description: str) -> list[Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            values = loader(path)
        except (OSError, UnicodeDecodeError, ValueError):
            values = []
        if len(values) >= count:
            return values
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {description}: {loader(path)!r}")


def input_button(driver: Path, environment: dict[str, str], number: int) -> None:
    clean = environment.copy()
    clean.pop("LD_PRELOAD", None)
    clean.pop("WTWM_COMMAND_CALL_LOG", None)
    for state in ("press", "release"):
        subprocess.run(
            [str(driver), "button", str(number), state], env=clean,
            check=True, timeout=10, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )


def validate_config_dump(config_check: Path, config: Path,
                         cases: dict[str, dict[str, Any]]) -> str:
    dump = subprocess.run(
        [str(config_check), str(config)], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    ).stdout
    binding_lines = [line for line in dump.splitlines() if line.startswith("  button=")]
    if len(binding_lines) != len(PHASES):
        raise RuntimeError(f"config dump omitted command bindings: {binding_lines!r}")
    for phase in ("explicit", "alias", "shell", "startwm"):
        if str(cases[phase]["command"]) not in dump:
            raise RuntimeError(f"config dump changed decoded {phase} command")
    if sum("action=f.exec" in line for line in binding_lines) != 4:
        raise RuntimeError(f"f.exec/! canonicalization changed: {binding_lines!r}")
    if sum("action=f.startwm" in line for line in binding_lines) != 1:
        raise RuntimeError(f"f.startwm decoding changed: {binding_lines!r}")
    return dump


def run_reference(arguments: argparse.Namespace, config: Path, calls: Path,
                  result_log: Path) -> tuple[list[dict[str, Any]], list[list[str]]]:
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C", "GDK_BACKEND": "x11", "LD_PRELOAD": str(arguments.interposer),
        "WTWM_COMMAND_CALL_LOG": str(calls), "WTWM_CERT_COMMAND": ENV_VALUE,
    })
    xvfb = subprocess.Popen(
        ["/usr/bin/Xvfb", "-displayfd", "1", "-screen", "0", "260x180x24",
         "-nolisten", "tcp"], cwd=arguments.source_root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    twm: subprocess.Popen[str] | None = None
    try:
        environment["DISPLAY"] = wait_xvfb(xvfb)
        twm = subprocess.Popen(
            [str(arguments.reference_twm), "-display", environment["DISPLAY"],
             "-single", "-f", str(config), "-quiet"],
            cwd=arguments.source_root, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        driver_environment = environment.copy()
        driver_environment.pop("LD_PRELOAD", None)
        driver_environment.pop("WTWM_COMMAND_CALL_LOG", None)
        subprocess.run([str(arguments.observer), "ready"], env=driver_environment,
                       check=True, timeout=20)
        for button, expected in ((1, 1), (2, 2), (3, 3)):
            input_button(arguments.input_driver, environment, button)
            wait_count(parse_observers, result_log, expected, f"reference Button{button}")
        input_button(arguments.input_driver, environment, 4)
        wait_count(parse_calls, calls, 4, "reference empty system call")
        if len(parse_observers(result_log)) != 3:
            raise RuntimeError("empty reference f.exec ran the observer")
        input_button(arguments.input_driver, environment, 5)
        wait_count(parse_observers, result_log, 4, "reference f.startwm observer")
        if twm.wait(timeout=10) != 0:
            raise RuntimeError("reference f.startwm replacement exited nonzero")
        return parse_calls(calls), parse_observers(result_log)
    finally:
        stdout, stderr = stop_group(twm)
        (arguments.evidence / "reference-session.log").write_text(
            f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
        )
        stdout, stderr = stop_process(xvfb)
        (arguments.evidence / "reference-xvfb.log").write_text(
            f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
        )


def invoke_control(control: Control, raw_button: int) -> None:
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 2")


def run_wtwm(arguments: argparse.Namespace, config: Path, calls: Path,
             result_log: Path) -> tuple[list[dict[str, Any]], list[list[str]]]:
    with tempfile.TemporaryDirectory(prefix="wtwm-m10-command-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman", "LD_PRELOAD": str(arguments.interposer),
            "WTWM_COMMAND_CALL_LOG": str(calls), "WTWM_CERT_COMMAND": ENV_VALUE,
        })
        process = subprocess.Popen(
            [str(arguments.compositor), "-f", str(config),
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-m10-command-{os.getpid()}",
             "--test-backend", "headless"], cwd=arguments.source_root,
            env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        try:
            control = Control(control_path, process)
            control.command("SET ANIMATION_MS 0")
            control.command("OUTPUT 260 180")
            control.command("POINTER 250 170")
            # Linux input codes keep middle/right opposite X Button2/Button3.
            for raw_button, expected in ((272, 1), (274, 2), (273, 3)):
                invoke_control(control, raw_button)
                wait_count(parse_observers, result_log, expected,
                           f"wtwm button {raw_button}")
            invoke_control(control, 275)
            if len(parse_observers(result_log)) != 3:
                raise RuntimeError("empty wtwm f.exec ran the observer")
            invoke_control(control, 276)
            if len(parse_observers(result_log)) != 3:
                raise RuntimeError("unsupported wtwm f.startwm ran the observer")
            if process.poll() is not None or control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("unsupported wtwm f.startwm replaced the compositor")
            control.command("QUIT")
            if process.wait(timeout=10) != 0:
                raise RuntimeError("wtwm command session exited nonzero")
            return parse_calls(calls), parse_observers(result_log)
        finally:
            if control is not None:
                control.close()
            stdout, stderr = stop_process(process)
            (arguments.evidence / "wtwm-session.log").write_text(
                f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
            )


def normalized_calls(records: list[dict[str, Any]], observer: Path,
                     cases: dict[str, dict[str, Any]], reference: bool) -> list[dict[str, Any]]:
    commands = {str(value["command"]) for value in cases.values()}
    selected = []
    for record in records:
        operation = record["operation"]
        argv = record["argv"]
        relevant = False
        if reference:
            relevant = operation == "system" and argv and argv[0] in commands
            relevant = relevant or (
                operation == "execlp" and len(argv) == 3 and
                argv[2] == cases["startwm"]["command"]
            )
        else:
            relevant = operation == "execvp" and argv and argv[0] == str(observer)
            relevant = relevant or (
                operation == "execl" and len(argv) == 3 and
                argv[2] == cases["shell"]["command"]
            )
        if relevant:
            selected.append({"operation": operation, "argv": argv})
    return selected


def compare(cases: dict[str, dict[str, Any]], observer: Path,
            reference_calls: list[dict[str, Any]], wtwm_calls: list[dict[str, Any]],
            reference_observers: list[list[str]],
            wtwm_observers: list[list[str]]) -> dict[str, Any]:
    expected_reference_calls = [
        {"operation": "system", "argv": [cases[phase]["command"]]}
        for phase in ("explicit", "alias", "shell", "empty")
    ] + [{
        "operation": "execlp",
        "argv": ["sh", "-c", cases["startwm"]["command"]],
    }]
    expected_wtwm_calls = [
        {"operation": "execvp", "argv": cases["explicit"]["argv"]},
        {"operation": "execvp", "argv": cases["alias"]["argv"]},
        {"operation": "execl",
         "argv": ["/bin/sh", "-c", cases["shell"]["command"]]},
    ]
    if reference_calls != expected_reference_calls:
        raise RuntimeError(f"reference command calls differ: {reference_calls!r}")
    if wtwm_calls != expected_wtwm_calls:
        raise RuntimeError(f"wtwm command calls differ: {wtwm_calls!r}")
    expected_reference_observers = [
        cases[phase]["argv"] for phase in ("explicit", "alias", "shell", "startwm")
    ]
    expected_wtwm_observers = [
        cases[phase]["argv"] for phase in ("explicit", "alias", "shell")
    ]
    if reference_observers != expected_reference_observers:
        raise RuntimeError(f"reference observer argv differ: {reference_observers!r}")
    if wtwm_observers != expected_wtwm_observers:
        raise RuntimeError(f"wtwm observer argv differ: {wtwm_observers!r}")

    result: dict[str, Any] = {}
    for phase in PHASES:
        item = cases[phase]
        reference_executed = phase != "empty"
        wtwm_executed = phase not in {"empty", "startwm"}
        result[phase] = {
            "action_spelling": item["spelling"],
            "canonical_action": item["canonical"],
            "decoded_command": item["command"],
            "reference": {
                "dispatch": "execlp" if phase == "startwm" else "system",
                "unchanged_shell_text": item["command"],
                "observer_argv": item["argv"] if reference_executed else None,
                "executed": reference_executed,
            },
            "wtwm": {
                "dispatch": (
                    "execvp" if phase in {"explicit", "alias"} else
                    "execl" if phase == "shell" else "none"
                ),
                "direct_argv": item["argv"] if phase in {"explicit", "alias"} else None,
                "unchanged_shell_text": item["command"] if phase == "shell" else None,
                "observer_argv": item["argv"] if wtwm_executed else None,
                "executed": wtwm_executed,
                "intentional_non_execution": phase in {"empty", "startwm"},
            },
            "classification": (
                "unavoidable-wayland-handoff-translation"
                if phase == "startwm" else "observable-equivalent"
            ),
        }
    return result


def self_test() -> None:
    observer = Path("/tmp/observer")
    result_log = Path("/tmp/result")
    cases = scenario(observer, result_log)
    ref_calls = [
        {"operation": "system", "argv": [cases[phase]["command"]]}
        for phase in ("explicit", "alias", "shell", "empty")
    ] + [{"operation": "execlp",
          "argv": ["sh", "-c", cases["startwm"]["command"]]}]
    wtwm_calls = [
        {"operation": "execvp", "argv": cases["explicit"]["argv"]},
        {"operation": "execvp", "argv": cases["alias"]["argv"]},
        {"operation": "execl", "argv": ["/bin/sh", "-c", cases["shell"]["command"]]},
    ]
    ref_observers = [cases[phase]["argv"] for phase in
                     ("explicit", "alias", "shell", "startwm")]
    wtwm_observers = [cases[phase]["argv"] for phase in
                      ("explicit", "alias", "shell")]
    compare(cases, observer, ref_calls, wtwm_calls, ref_observers, wtwm_observers)
    tampered = [dict(record) for record in wtwm_calls]
    tampered[2] = {"operation": "execl", "argv": ["/bin/sh", "-c", "changed"]}
    try:
        compare(cases, observer, ref_calls, tampered, ref_observers, wtwm_observers)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("shell-text tamper was accepted")
    print("Milestone 10 command differential self-test passed")


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    for path in arguments.evidence.iterdir():
        if path.is_file():
            path.unlink()
    result: dict[str, Any] = {
        "schema_version": 1,
        "comparison": "live-twm-1.0.13.1-vs-wtwm-command-dispatch",
        "result": "failed",
    }
    try:
        version = subprocess.run(
            [str(arguments.reference_twm), "-V"], cwd=arguments.source_root,
            check=True, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=10,
        ).stdout.strip()
        if version != "twm 1.0.13.1":
            raise RuntimeError(f"unexpected reference version: {version!r}")
        with tempfile.TemporaryDirectory(
                prefix="wtwm-m10-command-files-") as directory:
            temporary = Path(directory)
            config = temporary / "commands.twmrc"
            result_log = temporary / "observer.log"
            reference_calls_path = arguments.evidence / "reference-calls.tsv"
            wtwm_calls_path = arguments.evidence / "wtwm-calls.tsv"
            cases = scenario(arguments.command_observer, result_log)
            config.write_text(config_text(cases), encoding="utf-8")
            dump = validate_config_dump(arguments.config_check, config, cases)
            (arguments.evidence / "wtwm-config.dump").write_text(
                dump, encoding="utf-8"
            )
            reference_raw, reference_observers = run_reference(
                arguments, config, reference_calls_path, result_log
            )
            reference_calls = normalized_calls(
                reference_raw, arguments.command_observer, cases, True
            )
            result_log.unlink()
            wtwm_raw, wtwm_observers = run_wtwm(
                arguments, config, wtwm_calls_path, result_log
            )
            wtwm_calls = normalized_calls(
                wtwm_raw, arguments.command_observer, cases, False
            )
            scenarios = compare(
                cases, arguments.command_observer, reference_calls, wtwm_calls,
                reference_observers, wtwm_observers,
            )
            result.update({
                "reference_version": version,
                "phases": list(PHASES),
                "scenarios": scenarios,
                "unexplained_differences": 0,
                "result": "equivalent-with-documented-startwm-translation",
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
        "source-root", "reference-twm", "compositor", "config-check",
        "input-driver", "observer", "command-observer", "interposer",
        "output", "evidence",
    ):
        parser.add_argument(f"--{name}", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    required = tuple(name.replace("-", "_") for name in (
        "source-root", "reference-twm", "compositor", "config-check",
        "input-driver", "observer", "command-observer", "interposer",
        "output", "evidence",
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
