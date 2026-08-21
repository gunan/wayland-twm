#!/usr/bin/env python3
"""Compare live frozen-twm and wtwm menu state and pixels exactly."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time

from run_compositor import Control


SCREEN = (260, 180)
PHASES = ("normal", "title", "highlight", "pull-right", "child")
EXPECTED_STATES = {
    "normal": {
        "name": "cert-root", "parent": None, "depth": 1, "selected": -1,
        "pull_right": False, "submenu_open": False,
    },
    "title": {
        "name": "cert-root", "parent": None, "depth": 1, "selected": -1,
        "pull_right": False, "submenu_open": False,
    },
    "highlight": {
        "name": "cert-root", "parent": None, "depth": 1, "selected": 1,
        "pull_right": False, "submenu_open": False,
    },
    "pull-right": {
        "name": "cert-root", "parent": None, "depth": 1, "selected": 3,
        "pull_right": True, "submenu_open": False,
    },
    "child": {
        "name": "cert-child", "parent": "cert-root", "depth": 2,
        "selected": -1, "pull_right": False, "submenu_open": True,
    },
}


def wait_xvfb(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        line = process.stdout.readline().strip()
        if line.isdigit():
            return f":{line}"
        if process.poll() is not None:
            break
    raise RuntimeError("Xvfb did not publish a display number")


def stop(process: subprocess.Popen[str] | None) -> tuple[str, str]:
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


def stop_process_group(process: subprocess.Popen[object] | None) -> None:
    if process is None or process.poll() is not None:
        return
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


def input_event(driver: Path, environment: dict[str, str], *values: str) -> None:
    subprocess.run(
        [str(driver), *values], env=environment, check=True, timeout=10,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("capture is not an un-commented 8-bit PPM P6 image")
    width, height = (int(value) for value in fields[1].split())
    if len(fields[3]) != width * height * 3:
        raise RuntimeError("capture has an invalid pixel payload")
    return width, height, fields[3]


def screenshot_comparison(reference: bytes, wtwm: bytes) -> dict[str, object]:
    ref_width, ref_height, ref_pixels = parse_ppm(reference)
    width, height, pixels = parse_ppm(wtwm)
    mismatch = None
    if (width, height) == (ref_width, ref_height):
        mismatch = sum(
            ref_pixels[offset:offset + 3] != pixels[offset:offset + 3]
            for offset in range(0, len(ref_pixels), 3)
        )
    return {
        "reference_size": [ref_width, ref_height],
        "wtwm_size": [width, height],
        "reference_sha256": hashlib.sha256(reference).hexdigest(),
        "wtwm_sha256": hashlib.sha256(wtwm).hexdigest(),
        "mismatch_pixels": mismatch,
        "exact": mismatch == 0,
    }


def require_menu_pixels(data: bytes, phase: str) -> None:
    width, height, pixels = parse_ppm(data)
    if (width, height) != SCREEN:
        raise RuntimeError(f"{phase} capture is {width}x{height}, expected 260x180")
    triples = [pixels[index:index + 3] for index in range(0, len(pixels), 3)]
    for color, label in ((bytes((32, 48, 64)), "menu background"),
                         (bytes((224, 224, 224)), "menu border")):
        if color not in triples:
            raise RuntimeError(f"{phase} capture lacks configured {label} pixels")


def gdb_script(path: Path, display: str, config: Path) -> None:
    arguments = " ".join(
        shlex.quote(value) for value in (
            "-display", display, "-single", "-f", str(config), "-quiet",
        )
    )
    path.write_text(
        "set pagination off\n"
        "set confirm off\n"
        "set debuginfod enabled off\n"
        "break PopUpMenu\n"
        "commands\n"
        "silent\n"
        "printf \"WTWM_MENU_POP\\t%s\\t%d\\t%s\\t%d\\t%d\\t%d\\t%d\\t%d\\t%d\\t%d\\n\", menu->name, MenuDepth + 1, ActiveMenu == 0 ? \"-\" : ActiveMenu->name, x, y, center, menu->width, menu->height, Scr->EntryHeight, Scr->MenuBorderWidth\n"
        "continue\n"
        "end\n"
        "break menus.c:561\n"
        "commands\n"
        "silent\n"
        "printf \"WTWM_MENU_MOTION\\t%s\\t%d\\t%d\\t%d\\t%d\\n\", ActiveMenu->name, MenuDepth, ActiveItem == 0 ? -1 : ActiveItem->item_num, ActiveItem == 0 ? 0 : ActiveItem->state, ActiveItem == 0 ? 0 : ActiveItem->sub != 0\n"
        "continue\n"
        "end\n"
        f"run {arguments}\n",
        encoding="utf-8",
    )


def parse_gdb_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split("\t")
        try:
            if fields[0] == "WTWM_MENU_POP" and len(fields) == 11:
                records.append({
                    "kind": "pop", "name": fields[1], "depth": int(fields[2]),
                    "parent": None if fields[3] == "-" else fields[3],
                    "anchor_x": int(fields[4]), "anchor_y": int(fields[5]),
                    "center": bool(int(fields[6])), "width": int(fields[7]),
                    "height": int(fields[8]), "row_height": int(fields[9]),
                    "border": int(fields[10]),
                })
            elif fields[0] == "WTWM_MENU_MOTION" and len(fields) == 6:
                records.append({
                    "kind": "motion", "name": fields[1],
                    "depth": int(fields[2]), "item": int(fields[3]),
                    "state": int(fields[4]), "has_submenu": bool(int(fields[5])),
                })
        except ValueError:
            continue
    return records


def wait_record(path: Path, start: int, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        records = parse_gdb_records(path)
        for record in records[start:]:
            if predicate(record):
                return record
        time.sleep(0.01)
    raise RuntimeError(
        f"reference observer timed out waiting for {description}: "
        f"{parse_gdb_records(path)!r}"
    )


def reference_origin(record: dict[str, object]) -> tuple[int, int]:
    x = int(record["anchor_x"])
    y = int(record["anchor_y"])
    if record["center"]:
        x -= int(record["width"]) // 2
        y -= int(record["row_height"]) // 2
    x = min(max(x, 0), SCREEN[0] - int(record["width"]))
    y = min(max(y, 0), SCREEN[1] - int(record["height"]))
    return x, y


def reference_state(record: dict[str, object], selected: int = -1,
                    pull_right: bool = False) -> dict[str, object]:
    return {
        "name": record["name"], "parent": record.get("parent"),
        "depth": record["depth"], "selected": selected,
        "pull_right": pull_right, "submenu_open": int(record["depth"]) > 1,
    }


def capture_reference_stable(observer: Path, environment: dict[str, str],
                             evidence: Path, phase: str) -> bytes:
    first = evidence / f"{phase}.reference.ppm"
    repeat = evidence / f".{phase}.reference-repeat.ppm"
    time.sleep(0.05)
    for _ in range(12):
        subprocess.run([str(observer), "capture", str(first)], env=environment,
                       check=True, timeout=10)
        time.sleep(0.03)
        subprocess.run([str(observer), "capture", str(repeat)], env=environment,
                       check=True, timeout=10)
        data = first.read_bytes()
        if data == repeat.read_bytes():
            repeat.unlink()
            require_menu_pixels(data, phase)
            return data
        time.sleep(0.03)
    raise RuntimeError(f"reference {phase} pixels did not converge")


def run_reference(arguments: argparse.Namespace, evidence: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "GDK_BACKEND": "x11"})
    xvfb = subprocess.Popen(
        ["/usr/bin/Xvfb", "-displayfd", "1", "-screen", "0", "260x180x24",
         "-nolisten", "tcp"], cwd=arguments.source_root, env=environment,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    gdb: subprocess.Popen[object] | None = None
    log_handle = None
    try:
        environment["DISPLAY"] = wait_xvfb(xvfb)
        script = evidence / "reference-menu.gdb"
        log = evidence / "reference-gdb.log"
        gdb_script(script, environment["DISPLAY"], arguments.config)
        log_handle = log.open("w", encoding="utf-8")
        gdb = subprocess.Popen(
            ["gdb", "--quiet", "--batch", f"--command={script}",
             str(arguments.reference_twm)], cwd=arguments.source_root,
            env=environment, stdout=log_handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        subprocess.run([str(arguments.observer), "ready"], env=environment,
                       check=True, timeout=20)

        input_event(arguments.input_driver, environment, "pointer", "130", "90")
        before = len(parse_gdb_records(log))
        input_event(arguments.input_driver, environment, "button", "3", "press")
        root = wait_record(
            log, before,
            lambda item: item["kind"] == "pop" and item["name"] == "cert-root",
            "root menu pop",
        )
        root_x, root_y = reference_origin(root)
        border = int(root["border"])
        width = int(root["width"])
        row = int(root["row_height"])
        states: dict[str, dict[str, object]] = {
            "normal": reference_state(root),
        }
        captures = {
            "normal": capture_reference_stable(
                arguments.observer, environment, evidence, "normal"
            )
        }

        def move_and_observe(phase: str, item: int, fraction: int,
                             has_submenu: bool) -> dict[str, object]:
            start = len(parse_gdb_records(log))
            x = root_x + border + width * fraction // 4
            y = root_y + border + item * row + row // 2
            input_event(arguments.input_driver, environment, "pointer", str(x), str(y))
            return wait_record(
                log, start,
                lambda value: value["kind"] == "motion" and
                value["name"] == "cert-root" and value["item"] == item and
                value["has_submenu"] == has_submenu,
                f"{phase} motion",
            )

        title = move_and_observe("title", 0, 1, False)
        states["title"] = reference_state(title)
        captures["title"] = capture_reference_stable(
            arguments.observer, environment, evidence, "title"
        )
        highlighted = move_and_observe("highlight", 1, 1, False)
        states["highlight"] = reference_state(highlighted, selected=1)
        captures["highlight"] = capture_reference_stable(
            arguments.observer, environment, evidence, "highlight"
        )
        pull = move_and_observe("pull-right", 3, 1, True)
        states["pull-right"] = reference_state(pull, selected=3, pull_right=True)
        captures["pull-right"] = capture_reference_stable(
            arguments.observer, environment, evidence, "pull-right"
        )
        before = len(parse_gdb_records(log))
        input_event(
            arguments.input_driver, environment, "pointer",
            str(root_x + border + width * 3 // 4),
            str(root_y + border + 3 * row + row // 2),
        )
        child = wait_record(
            log, before,
            lambda item: item["kind"] == "pop" and item["name"] == "cert-child",
            "child menu pop",
        )
        states["child"] = reference_state(child)
        captures["child"] = capture_reference_stable(
            arguments.observer, environment, evidence, "child"
        )
        input_event(arguments.input_driver, environment, "button", "3", "release")
        if gdb.poll() is not None:
            raise RuntimeError(f"reference gdb/twm exited with {gdb.returncode}")
        return {"states": states, "captures": captures}
    finally:
        stop_process_group(gdb)
        if log_handle is not None:
            log_handle.close()
        stdout, stderr = stop(xvfb)
        (evidence / "reference-xvfb.log").write_text(
            f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
        )


def wait_display(control: Control, marker: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            display = marker.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("Xwayland did not publish DISPLAY")


def wait_menu(control: Control, predicate, description: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = control.state()["menu"]
        if isinstance(value, dict) and predicate(value):
            return value
        time.sleep(0.01)
    raise RuntimeError(f"wtwm timed out waiting for {description}: {control.state()!r}")


def normalize_wtwm_menu(menu: dict[str, object]) -> dict[str, object]:
    return {
        key: menu[key] for key in (
            "name", "parent", "depth", "selected", "pull_right", "submenu_open",
        )
    }


def capture_wtwm_stable(control: Control, evidence: Path, temporary: Path,
                        phase: str) -> bytes:
    first = evidence / f"{phase}.wtwm.ppm"
    repeat = temporary / f"{phase}.wtwm-repeat.ppm"
    for _ in range(12):
        control.command("WAIT 3")
        control.command(f"CAPTURE {first}")
        control.command("WAIT 3")
        control.command(f"CAPTURE {repeat}")
        data = first.read_bytes()
        if data == repeat.read_bytes():
            require_menu_pixels(data, phase)
            return data
    raise RuntimeError(f"wtwm {phase} pixels did not converge")


def run_wtwm(arguments: argparse.Namespace, evidence: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="wtwm-m10-menu-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        marker = temporary / "display"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        process = subprocess.Popen(
            [str(arguments.compositor), "-f", str(arguments.config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-m10-menu-{os.getpid()}",
             "--test-backend", "headless"], cwd=arguments.source_root,
            env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        try:
            control = Control(control_path, process)
            control.command("SET ANIMATION_MS 0")
            control.command("OUTPUT 260 180")
            wait_display(control, marker)
            control.command("POINTER 130 90")
            control.command("BUTTON 273 press")
            root = wait_menu(control, lambda value: value["name"] == "cert-root",
                             "root menu")
            states: dict[str, dict[str, object]] = {
                "normal": normalize_wtwm_menu(root),
            }
            captures = {
                "normal": capture_wtwm_stable(
                    control, evidence, temporary, "normal"
                )
            }
            root_x = int(root["x"])
            root_y = int(root["y"])
            width = int(root["width"])
            row = int(root["row_height"])
            border = 2

            def move(phase: str, item: int, fraction: int,
                     selected: int) -> dict[str, object]:
                control.command(
                    f"POINTER {root_x + border + width * fraction // 4} "
                    f"{root_y + border + item * row + row // 2}"
                )
                return wait_menu(
                    control,
                    lambda value: value["name"] == "cert-root" and
                    int(value["selected"]) == selected,
                    phase,
                )

            title = move("title", 0, 1, -1)
            states["title"] = normalize_wtwm_menu(title)
            captures["title"] = capture_wtwm_stable(
                control, evidence, temporary, "title"
            )
            highlighted = move("highlight", 1, 1, 1)
            states["highlight"] = normalize_wtwm_menu(highlighted)
            captures["highlight"] = capture_wtwm_stable(
                control, evidence, temporary, "highlight"
            )
            pull = move("pull-right", 3, 1, 3)
            states["pull-right"] = normalize_wtwm_menu(pull)
            captures["pull-right"] = capture_wtwm_stable(
                control, evidence, temporary, "pull-right"
            )
            control.command(
                f"POINTER {root_x + border + width * 3 // 4} "
                f"{root_y + border + 3 * row + row // 2}"
            )
            child = wait_menu(
                control,
                lambda value: value["name"] == "cert-child" and
                int(value["depth"]) == 2,
                "child menu",
            )
            states["child"] = normalize_wtwm_menu(child)
            captures["child"] = capture_wtwm_stable(
                control, evidence, temporary, "child"
            )
            control.command("BUTTON 273 release")
            if control.state()["menu"] is not None:
                raise RuntimeError("wtwm menu did not close on invoking-button release")
            return {"states": states, "captures": captures}
        finally:
            if control is not None and process.poll() is None:
                try:
                    control.command("QUIT")
                except (BrokenPipeError, ConnectionError, RuntimeError):
                    process.terminate()
                control.close()
            stdout, stderr = stop(process)
            (evidence / "wtwm-session.log").write_text(
                f"stdout:\n{stdout}\nstderr:\n{stderr}", encoding="utf-8"
            )


def compare_states(reference: dict[str, dict[str, object]],
                   wtwm: dict[str, dict[str, object]]) -> None:
    if tuple(reference) != PHASES or tuple(wtwm) != PHASES:
        raise RuntimeError(
            f"menu phases differ: reference={tuple(reference)!r}, wtwm={tuple(wtwm)!r}"
        )
    for phase in PHASES:
        expected = EXPECTED_STATES[phase]
        if reference[phase] != expected or wtwm[phase] != expected:
            raise RuntimeError(
                f"{phase} state differs: expected={expected!r}, "
                f"reference={reference[phase]!r}, wtwm={wtwm[phase]!r}"
            )


def synthetic_ppm(change: bool = False) -> bytes:
    pixels = bytearray(bytes((48, 48, 48)) * 16)
    pixels[0:3] = bytes((224, 224, 224) if not change else (255, 0, 255))
    return b"P6\n4 4\n255\n" + bytes(pixels)


def self_test() -> None:
    left = {phase: dict(EXPECTED_STATES[phase]) for phase in PHASES}
    right = {phase: dict(EXPECTED_STATES[phase]) for phase in PHASES}
    compare_states(left, right)
    exact = screenshot_comparison(synthetic_ppm(), synthetic_ppm())
    if exact["mismatch_pixels"] != 0:
        raise RuntimeError("identical synthetic menu images differed")
    tampered = screenshot_comparison(synthetic_ppm(), synthetic_ppm(change=True))
    if tampered["mismatch_pixels"] != 1:
        raise RuntimeError("synthetic menu pixel tamper was not detected")
    right["pull-right"]["pull_right"] = False
    try:
        compare_states(left, right)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("synthetic pull-right state tamper was accepted")
    print("Milestone 10 live menu differential self-test passed")


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    for path in arguments.evidence.iterdir():
        if path.is_file():
            path.unlink()
    result: dict[str, object] = {
        "schema_version": 1,
        "comparison": "live-twm-1.0.13.1-vs-wtwm-menu-state-and-pixels",
        "result": "failed",
    }
    try:
        version = subprocess.run(
            [str(arguments.reference_twm), "-V"], cwd=arguments.source_root,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True, timeout=10,
        ).stdout.strip()
        if version != "twm 1.0.13.1":
            raise RuntimeError(f"unexpected reference version: {version!r}")
        reference = run_reference(arguments, arguments.evidence)
        wtwm = run_wtwm(arguments, arguments.evidence)
        compare_states(reference["states"], wtwm["states"])
        comparisons = {
            phase: screenshot_comparison(
                reference["captures"][phase], wtwm["captures"][phase]
            )
            for phase in PHASES
        }
        differences = [
            f"{phase}: {value['mismatch_pixels']} mismatched pixels"
            for phase, value in comparisons.items() if not value["exact"]
        ]
        if differences:
            raise RuntimeError("; ".join(differences))
        result.update({
            "reference_version": version,
            "phases": list(PHASES),
            "reference_states": reference["states"],
            "wtwm_states": wtwm["states"],
            "screenshots": comparisons,
            "unexplained_pixel_differences": 0,
            "result": "equivalent",
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
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--reference-twm", type=Path)
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--input-driver", type=Path)
    parser.add_argument("--observer", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    required = (
        "source_root", "reference_twm", "compositor", "input_driver",
        "observer", "config", "output", "evidence",
    )
    missing = [name for name in required if getattr(arguments, name) is None]
    if missing:
        parser.error("missing live arguments: " + ", ".join(missing))
    for name in (
        "source_root", "reference_twm", "compositor", "input_driver",
        "observer", "config",
    ):
        setattr(arguments, name, getattr(arguments, name).resolve(strict=True))
    arguments.output = arguments.output.resolve()
    arguments.evidence = arguments.evidence.resolve()
    run(arguments)


if __name__ == "__main__":
    main()
