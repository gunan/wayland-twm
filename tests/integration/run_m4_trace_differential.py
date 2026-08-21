#!/usr/bin/env python3
"""Replay one exact M4 input trace under reference twm and wtwm/Xwayland."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time
from typing import Callable

from run_compositor import Control


ROLES = ("alpha", "bravo")
TITLES = {"alpha": "Reference Alpha", "bravo": "Reference Bravo"}
STABLE_SAMPLES = 3
MAX_SAMPLES = 24
BUTTON_CODES = {1: 272, 2: 274, 3: 273}
KEY_CODES = {"F1": 59, "F2": 60, "F3": 61}


def wait_line(process: subprocess.Popen[str], expected: str) -> None:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.01)
        if readable:
            actual = process.stdout.readline().rstrip("\n")
            if actual != expected:
                raise RuntimeError(f"unexpected client output: {actual!r}")
            return
        if process.poll() is not None:
            raise RuntimeError(f"client exited early with {process.returncode}")
    raise RuntimeError(f"timed out waiting for client output {expected!r}")


def wait_path(path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.01)
    raise RuntimeError(f"timed out waiting for {path}")


def xvfb_display(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], 0.01)
        if readable:
            value = process.stdout.readline().strip()
            if value.isdigit():
                return f":{value}"
            raise RuntimeError(f"Xvfb returned invalid display number {value!r}")
        if process.poll() is not None:
            raise RuntimeError(f"Xvfb exited early with {process.returncode}")
    raise RuntimeError("timed out waiting for Xvfb display number")


def stop_process(process: subprocess.Popen[str] | None) -> tuple[str, str]:
    if process is None:
        return "", ""
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def capture_reference(probe: Path, environment: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(
        [str(probe)], env=environment, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"reference observer failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("screenshot is not an un-commented 8-bit PPM P6 image")
    width, height = (int(value) for value in fields[1].split())
    if len(fields[3]) != width * height * 3:
        raise RuntimeError("screenshot has an invalid pixel payload")
    return width, height, fields[3]


def screenshot_name(backend: str, index: int, after: str) -> str:
    return f"{backend}-{index:02d}-{after}.ppm"


def capture_reference_screenshot(
    observer: Path,
    environment: dict[str, str],
    evidence: Path,
    index: int,
    after: str,
) -> bytes:
    output = evidence / screenshot_name("reference", index, after)
    repeat = evidence / ("." + screenshot_name("reference-repeat", index, after))
    for _ in range(12):
        subprocess.run(
            [str(observer), "capture", str(output)], env=environment,
            check=True, timeout=10,
        )
        time.sleep(0.03)
        subprocess.run(
            [str(observer), "capture", str(repeat)], env=environment,
            check=True, timeout=10,
        )
        data = output.read_bytes()
        if data == repeat.read_bytes():
            repeat.unlink()
            parse_ppm(data)
            return data
        time.sleep(0.03)
    raise RuntimeError(f"reference screenshot {index} ({after}) did not converge")


def normalize_wtwm(state: dict[str, object], screen: dict[str, int]) -> dict[str, object]:
    raw_windows = state["windows"]
    if not isinstance(raw_windows, list):
        raise RuntimeError(f"wtwm STATE has no window list: {state!r}")
    selected: dict[str, dict[str, object]] = {}
    for role in ROLES:
        matches = [item for item in raw_windows if item.get("title") == TITLES[role]]
        if len(matches) != 1:
            raise RuntimeError(f"wtwm role {role!r} is ambiguous: {state!r}")
        selected[role] = matches[0]
    focus_title = state.get("focus")
    focus = next((role for role in ROLES if focus_title == TITLES[role]), "root")
    raw_cursor = state.get("cursor")
    if not isinstance(raw_cursor, dict):
        raise RuntimeError(f"wtwm STATE has no cursor coordinates: {state!r}")
    pointer = {
        "x": int(float(raw_cursor["x"])),
        "y": int(float(raw_cursor["y"])),
    }
    stack = [
        role for role, _ in sorted(
            (
                pair for pair in selected.items()
                if bool(pair[1]["mapped"]) and not bool(pair[1]["iconified"])
            ),
            key=lambda pair: int(pair[1]["stack"]), reverse=True,
        )
    ]
    windows: list[dict[str, object]] = []
    for role in ROLES:
        item = selected[role]
        iconified = bool(item["iconified"])
        windows.append({
            "role": role,
            "client": {
                "x": int(item["client_x"]),
                "y": int(item["client_y"]),
                "width": int(item["width"]),
                "height": int(item["height"]),
                "border_width": 0,
            },
            "frame": {
                "x": int(item["x"]),
                "y": int(item["y"]),
                "width": int(item["frame_width"]),
                "height": int(item["frame_height"]),
                "outer_width": int(item["outer_width"]),
                "outer_height": int(item["outer_height"]),
                "border_width": int(item["border_width"]),
                "content_x": int(item["content_x"]),
                "content_y": int(item["content_y"]),
            },
            "mapped": bool(item["mapped"]) and not iconified,
            "iconified": iconified,
            "titled": bool(item["decorated"]) and int(item["title_bar_height"]) > 0,
        })
    return {
        "screen": screen,
        "pointer": pointer,
        "focus": focus,
        "stack": stack,
        "windows": windows,
    }


def converge(
    capture: Callable[[], dict[str, object]],
    evidence: Path,
    backend: str,
    index: int,
) -> dict[str, object]:
    samples: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    consecutive = 0
    deadline = time.monotonic() + 15
    latest_error = ""
    while len(samples) < MAX_SAMPLES and time.monotonic() < deadline:
        try:
            current = capture()
        except (RuntimeError, json.JSONDecodeError) as error:
            latest_error = str(error)
            time.sleep(0.01)
            continue
        samples.append(current)
        if current == previous:
            consecutive += 1
        else:
            previous = current
            consecutive = 1
        if consecutive >= STABLE_SAMPLES:
            (evidence / f"{backend}-{index:02d}-convergence.json").write_text(
                json.dumps({
                    "backend": backend,
                    "event_index": index,
                    "required_consecutive_equal": STABLE_SAMPLES,
                    "samples": samples,
                    "schema_version": 1,
                }, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return current
        time.sleep(0.01)
    raise RuntimeError(
        f"{backend} event {index} did not converge across {MAX_SAMPLES} captures; "
        f"latest observer error: {latest_error}"
    )


def oracle_windows(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict[str, object]] = []
    for item in value["windows"]:
        client = item["client"]
        frame = item["frame"]
        border = int(frame["border_width"])
        outer_x = int(frame["x"]) - border
        outer_y = int(frame["y"]) - border
        result.append({
            "role": item["role"],
            "client": {
                "x": int(client["x"]), "y": int(client["y"]),
                "width": int(client["width"]), "height": int(client["height"]),
                "border_width": int(client["border_width"]),
            },
            "frame": {
                "x": outer_x,
                "y": outer_y,
                "width": int(frame["width"]),
                "height": int(frame["height"]),
                "outer_width": int(frame["width"]) + 2 * border,
                "outer_height": int(frame["height"]) + 2 * border,
                "border_width": border,
                "content_x": int(client["x"]) - outer_x,
                "content_y": int(client["y"]) - outer_y,
            },
            "mapped": bool(client["mapped"]),
            "iconified": False,
            "titled": True,
        })
    return result


def reference_input(
    driver: Path, event: dict[str, object], environment: dict[str, str]
) -> None:
    kind = event["kind"]
    if kind == "pointer":
        command = [str(driver), "pointer", str(event["x"]), str(event["y"])]
    elif kind == "button":
        command = [str(driver), "button", str(event["button"]), str(event["state"])]
    elif kind == "key":
        command = [str(driver), "key", str(event["key"]), str(event["state"])]
    else:
        raise RuntimeError(f"unknown input event: {event!r}")
    subprocess.run(command, env=environment, check=True, timeout=10)


def wtwm_input(control: Control, event: dict[str, object]) -> None:
    kind = event["kind"]
    if kind == "pointer":
        control.command(f"POINTER {event['x']} {event['y']}")
    elif kind == "button":
        control.command(
            f"BUTTON {BUTTON_CODES[int(event['button'])]} {event['state']}"
        )
    elif kind == "key":
        control.command(f"KEY {KEY_CODES[str(event['key'])]} {event['state']}")
    else:
        raise RuntimeError(f"unknown input event: {event!r}")
    control.command("WAIT 2")


def tagged(index: int, event: dict[str, object] | None,
           state: dict[str, object]) -> dict[str, object]:
    return {
        "index": index,
        "after": "initial" if event is None else event["id"],
        "input": event,
        "state": state,
    }


def run_reference(
    xvfb_binary: Path,
    reference_twm: Path,
    client_binary: Path,
    probe: Path,
    screenshot_observer: Path,
    driver: Path,
    config: Path,
    events: list[dict[str, object]],
    oracle: list[dict[str, object]],
    evidence: Path,
) -> tuple[list[dict[str, object]], list[bytes]]:
    xvfb = subprocess.Popen(
        [str(xvfb_binary), "-displayfd", "1", "-screen", "0", "260x180x24",
         "-nolisten", "tcp"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    twm: subprocess.Popen[str] | None = None
    client: subprocess.Popen[str] | None = None
    logs: list[str] = []
    try:
        display = xvfb_display(xvfb)
        environment = os.environ.copy()
        environment.update({"DISPLAY": display, "LC_ALL": "C"})
        twm = subprocess.Popen(
            [str(reference_twm), "-display", display, "-single", "-f", str(config),
             "-quiet"], env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        readiness = subprocess.run(
            [str(client_binary), "wait-wm"], env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            check=False,
        )
        if readiness.returncode != 0:
            raise RuntimeError(
                f"reference twm readiness sentinel failed: {readiness.stderr.strip()}"
            )
        client = subprocess.Popen(
            [str(client_binary), "scenario"], env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        wait_line(client, "READY")
        reference_input(driver, events[0], environment)
        initial = converge(
            lambda: capture_reference(probe, environment), evidence, "reference", 0
        )
        if initial["windows"] != oracle:
            raise RuntimeError(
                "reference initial geometry differs from frozen alpha/bravo oracle:\n"
                + json.dumps({"expected": oracle, "actual": initial["windows"]}, indent=2)
            )
        trace = [tagged(0, None, initial)]
        screenshots = [capture_reference_screenshot(
            screenshot_observer, environment, evidence, 0, "initial"
        )]
        for index, event in enumerate(events, 1):
            print(f"reference trace input {index}/{len(events)}: {event['id']}",
                  flush=True)
            reference_input(driver, event, environment)
            state = converge(
                lambda: capture_reference(probe, environment),
                evidence, "reference", index,
            )
            trace.append(tagged(index, event, state))
            screenshots.append(capture_reference_screenshot(
                screenshot_observer, environment, evidence, index, str(event["id"])
            ))
        if twm.poll() is not None:
            raise RuntimeError(f"reference twm exited with {twm.returncode}")
        return trace, screenshots
    finally:
        stdout, stderr = stop_process(client)
        logs.append(f"client stdout:\n{stdout}\nstderr:\n{stderr}")
        stdout, stderr = stop_process(twm)
        logs.append(f"twm stdout:\n{stdout}\nstderr:\n{stderr}")
        stdout, stderr = stop_process(xvfb)
        logs.append(f"Xvfb stdout:\n{stdout}\nstderr:\n{stderr}")
        (evidence / "reference-session.log").write_text(
            "\n".join(logs), encoding="utf-8"
        )


def run_wtwm(
    compositor: Path,
    client_binary: Path,
    config: Path,
    events: list[dict[str, object]],
    screen: dict[str, int],
    evidence: Path,
) -> tuple[list[dict[str, object]], list[bytes]]:
    with tempfile.TemporaryDirectory(prefix="wtwm-m4-trace-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "display"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_path))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C",
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [str(compositor), "-f", str(config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-m4-trace-{os.getpid()}",
             "--test-backend", "headless"],
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        logs: list[str] = []
        try:
            control = Control(control_path, process)
            control.command(f"OUTPUT {screen['width']} {screen['height']}")
            display = wait_path(display_path)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(client_binary), "scenario"], env=client_environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            wait_line(client, "READY")
            wtwm_input(control, events[0])

            def capture() -> dict[str, object]:
                assert control is not None
                return normalize_wtwm(control.state(), screen)

            initial = converge(capture, evidence, "wtwm", 0)
            trace = [tagged(0, None, initial)]

            def screenshot(index: int, after: str) -> bytes:
                assert control is not None
                output = evidence / screenshot_name("wtwm", index, after)
                repeat = temporary / screenshot_name("wtwm-repeat", index, after)
                for _ in range(12):
                    control.command("WAIT 3")
                    control.command(f"CAPTURE {output}")
                    control.command("WAIT 3")
                    control.command(f"CAPTURE {repeat}")
                    data = output.read_bytes()
                    if data == repeat.read_bytes():
                        parse_ppm(data)
                        return data
                raise RuntimeError(
                    f"wtwm screenshot {index} ({after}) did not converge"
                )

            screenshots = [screenshot(0, "initial")]
            for index, event in enumerate(events, 1):
                print(f"wtwm trace input {index}/{len(events)}: {event['id']}",
                      flush=True)
                wtwm_input(control, event)
                trace.append(tagged(
                    index, event, converge(capture, evidence, "wtwm", index)
                ))
                screenshots.append(screenshot(index, str(event["id"])))
            return trace, screenshots
        finally:
            stdout, stderr = stop_process(client)
            logs.append(f"client stdout:\n{stdout}\nstderr:\n{stderr}")
            if control is not None and process.poll() is None:
                try:
                    control.command("QUIT")
                except (BrokenPipeError, ConnectionError, RuntimeError):
                    process.terminate()
                control.close()
            stdout, stderr = stop_process(process)
            logs.append(f"wtwm stdout:\n{stdout}\nstderr:\n{stderr}")
            (evidence / "wtwm-session.log").write_text(
                "\n".join(logs), encoding="utf-8"
            )


def compare_screenshots(
    reference: list[bytes],
    wtwm: list[bytes],
    events: list[dict[str, object]],
    screen: dict[str, int],
) -> list[dict[str, object]]:
    if len(reference) != len(events) + 1 or len(wtwm) != len(reference):
        raise RuntimeError("paired screenshot count does not cover every trace action")
    comparisons: list[dict[str, object]] = []
    labels = ["initial"] + [str(event["id"]) for event in events]
    for index, (after, reference_data, wtwm_data) in enumerate(
            zip(labels, reference, wtwm, strict=True)):
        ref_width, ref_height, ref_pixels = parse_ppm(reference_data)
        width, height, pixels = parse_ppm(wtwm_data)
        expected_size = (int(screen["width"]), int(screen["height"]))
        if (ref_width, ref_height) != expected_size or (width, height) != expected_size:
            raise RuntimeError(
                f"screenshot {index} ({after}) size differs from {expected_size}: "
                f"reference={(ref_width, ref_height)}, wtwm={(width, height)}"
            )
        mismatches = sum(
            ref_pixels[offset:offset + 3] != pixels[offset:offset + 3]
            for offset in range(0, len(ref_pixels), 3)
        )
        comparisons.append({
            "index": index,
            "after": after,
            "reference": screenshot_name("reference", index, after),
            "wtwm": screenshot_name("wtwm", index, after),
            "reference_sha256": hashlib.sha256(reference_data).hexdigest(),
            "wtwm_sha256": hashlib.sha256(wtwm_data).hexdigest(),
            "mismatch_pixels": mismatches,
            "exact": mismatches == 0,
        })
    return comparisons


def run(arguments: argparse.Namespace) -> None:
    contract = json.loads(arguments.contract.read_text(encoding="utf-8"))
    events = contract["events"]
    screen = contract["screen"]
    evidence = arguments.output.parent / "m4-trace-differential-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for path in evidence.iterdir():
        if path.is_file():
            path.unlink()
    result: dict[str, object] = {
        "schema_version": 1,
        "comparison": "reference-twm-1.0.13.1-vs-wtwm-xwayland",
        "normalization": contract["normalization"],
        "result": "failed",
    }
    try:
        version = subprocess.run(
            [str(arguments.reference_twm), "-V"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
        ).stdout.strip()
        if version != "twm 1.0.13.1":
            raise RuntimeError(f"unexpected reference version: {version!r}")
        oracle = oracle_windows(arguments.oracle)
        reference, reference_screenshots = run_reference(
            arguments.xvfb, arguments.reference_twm, arguments.client, arguments.probe,
            arguments.screenshot_observer, arguments.input_driver,
            arguments.config, events, oracle, evidence,
        )
        (evidence / "reference-trace.json").write_text(
            json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        wtwm, wtwm_screenshots = run_wtwm(
            arguments.compositor, arguments.client, arguments.config,
            events, screen, evidence,
        )
        (evidence / "wtwm-trace.json").write_text(
            json.dumps(wtwm, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result.update({
            "event_count": len(events),
            "reference_trace": "m4-trace-differential-evidence/reference-trace.json",
            "wtwm_trace": "m4-trace-differential-evidence/wtwm-trace.json",
        })
        screenshots = compare_screenshots(
            reference_screenshots, wtwm_screenshots, events, screen
        )
        unexplained = sum(int(item["mismatch_pixels"]) for item in screenshots)
        result.update({
            "screenshot_count": len(screenshots),
            "screenshots": screenshots,
            "screenshot_masks": [],
            "unexplained_pixel_differences": unexplained,
        })
        if reference != wtwm:
            raise RuntimeError(
                "normalized M4 event traces differ:\n"
                + json.dumps({"reference": reference, "wtwm": wtwm}, indent=2)
            )
        if unexplained != 0:
            differing = [
                f"{item['after']}={item['mismatch_pixels']}"
                for item in screenshots if not item["exact"]
            ]
            raise RuntimeError(
                "paired stable screenshots contain nonzero differences for review: "
                + ", ".join(differing)
            )
        result["result"] = "equivalent"
    except Exception as error:
        result["error"] = str(error)
        (evidence / "runner-error.log").write_text(str(error) + "\n", encoding="utf-8")
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("Milestone 4 traces and every paired stable screenshot match reference twm")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xvfb", type=Path, default=Path("/usr/bin/Xvfb"))
    parser.add_argument("--reference-twm", type=Path, required=True)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--screenshot-observer", type=Path, required=True)
    parser.add_argument("--input-driver", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments)


if __name__ == "__main__":
    main()
