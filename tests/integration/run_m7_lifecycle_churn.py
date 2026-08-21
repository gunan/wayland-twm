#!/usr/bin/env python3
"""Run deterministic 256-window, 2000-operation icon lifecycle churn."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import tempfile
import time

from run_compositor import Control


WINDOW_COUNT = 256
CYCLE_COUNT = 400
OPERATIONS_PER_CYCLE = 5
OPERATION_COUNT = CYCLE_COUNT * OPERATIONS_PER_CYCLE
OPERATION_KINDS = ("deiconify", "iconify", "rename", "destroy", "recreate")
INITIAL_ASSOCIATION_TIMEOUT_SECONDS = 360
INITIAL_ASSOCIATION_STALL_SECONDS = 60
# Exactly 16 by 16 allocation cells: all 256 icons must fill the region.
GRID = (76, 21)
REGION = (0, 192, 1216, 336)
OUTPUT = (1216, 528)


def base_title(index: int, generation: int) -> str:
    return f"M7-{index:03d}-g{generation:03d}"


def rename_title(index: int, cycle: int) -> str:
    return f"M7-{index:03d}-r{cycle:03d}"


def schedule() -> list[dict[str, object]]:
    operations: list[dict[str, object]] = []
    generations = [0] * WINDOW_COUNT
    for cycle in range(CYCLE_COUNT):
        index = (cycle * 73 + 19) % WINDOW_COUNT
        renamed = rename_title(index, cycle)
        generations[index] += 1
        recreated = base_title(index, generations[index])
        for kind in OPERATION_KINDS:
            item: dict[str, object] = {
                "number": len(operations) + 1,
                "cycle": cycle,
                "kind": kind,
                "index": index,
            }
            if kind == "rename":
                item["title"] = renamed
            elif kind == "recreate":
                item["title"] = recreated
            operations.append(item)
    return operations


def validate_schedule(operations: list[dict[str, object]]) -> None:
    if len(operations) != OPERATION_COUNT:
        raise RuntimeError(
            f"churn schedule has {len(operations)} operations, expected {OPERATION_COUNT}"
        )
    counts = Counter(str(item.get("kind")) for item in operations)
    if counts != Counter({kind: CYCLE_COUNT for kind in OPERATION_KINDS}):
        raise RuntimeError(f"churn operation counts changed: {counts!r}")
    for cycle in range(CYCLE_COUNT):
        group = operations[
            cycle * OPERATIONS_PER_CYCLE:(cycle + 1) * OPERATIONS_PER_CYCLE
        ]
        index = (cycle * 73 + 19) % WINDOW_COUNT
        if [item.get("kind") for item in group] != list(OPERATION_KINDS):
            raise RuntimeError(f"cycle {cycle} operation order changed: {group!r}")
        if any(item.get("cycle") != cycle or item.get("index") != index
               for item in group):
            raise RuntimeError(f"cycle {cycle} target changed: {group!r}")
        numbers = [int(item["number"]) for item in group]
        expected = list(range(cycle * OPERATIONS_PER_CYCLE + 1,
                              (cycle + 1) * OPERATIONS_PER_CYCLE + 1))
        if numbers != expected:
            raise RuntimeError(f"cycle {cycle} numbering changed: {numbers!r}")
    targets = Counter(int(item["index"]) for item in operations
                      if item["kind"] == "recreate")
    if len(targets) != WINDOW_COUNT or min(targets.values()) < 1:
        raise RuntimeError("the deterministic schedule no longer covers all 256 windows")


def schedule_sha256(operations: list[dict[str, object]]) -> str:
    data = json.dumps(operations, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def expected_final_model(
    operations: list[dict[str, object]],
) -> tuple[list[str], list[int], list[int]]:
    titles = [base_title(index, 0) for index in range(WINDOW_COUNT)]
    generations = [0] * WINDOW_COUNT
    manager_order = list(range(WINDOW_COUNT))
    for item in operations:
        index = int(item["index"])
        kind = str(item["kind"])
        if kind == "rename":
            titles[index] = str(item["title"])
        elif kind == "destroy":
            manager_order.remove(index)
        elif kind == "recreate":
            generations[index] += 1
            titles[index] = str(item["title"])
            manager_order.append(index)
    return titles, generations, manager_order


def self_test() -> None:
    operations = schedule()
    validate_schedule(operations)
    first = schedule_sha256(operations)
    second = schedule_sha256(schedule())
    if first != second:
        raise RuntimeError("churn schedule is not deterministic")
    titles, generations, manager_order = expected_final_model(operations)
    if len(set(titles)) != WINDOW_COUNT or sorted(manager_order) != list(range(WINDOW_COUNT)):
        raise RuntimeError("deterministic final model lost a window")
    if sum(generations) != CYCLE_COUNT:
        raise RuntimeError("deterministic final generation count is wrong")
    columns, extra_width = divmod(REGION[2], GRID[0])
    rows, extra_height = divmod(REGION[3], GRID[1])
    if (extra_width != 0 or extra_height != 0 or
            columns * rows != WINDOW_COUNT):
        raise RuntimeError("the live icon region is not exactly 256 cells")
    if REGION[0] + REGION[2] > OUTPUT[0] or REGION[1] + REGION[3] > OUTPUT[1]:
        raise RuntimeError("the live icon region escapes the headless output")
    tampered = operations[:-1]
    try:
        validate_schedule(tampered)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("truncated churn schedule passed tamper validation")
    print(
        f"Milestone 7 lifecycle self-test passed: {WINDOW_COUNT} windows, "
        f"{OPERATION_COUNT} operations, sha256={first}"
    )


def wait_line(process: subprocess.Popen[str], expected: str) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [process.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = process.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if process.poll() is not None:
            break
        raise RuntimeError(f"unexpected lifecycle client output: {line!r}")
    raise RuntimeError(f"timed out waiting for lifecycle client output {expected!r}")


def client_command(
    process: subprocess.Popen[str], command: str, expected: str
) -> str:
    assert process.stdin is not None
    process.stdin.write(command + "\n")
    process.stdin.flush()
    return wait_line(process, expected)


def wait_display(control: Control, marker: Path) -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if marker.exists():
            display = marker.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("Xwayland DISPLAY marker was not published")


def manager(state: dict[str, object]) -> dict[str, object]:
    managers = state["icon_managers"]
    if len(managers) != 1 or int(managers[0]["id"]) != 1:
        raise RuntimeError(f"large-set churn lost the default manager: {managers!r}")
    return managers[0]


def rectangles_overlap(left: dict[str, object], right: dict[str, object]) -> bool:
    return not (
        int(left["x"]) + int(left["width"]) <= int(right["x"]) or
        int(right["x"]) + int(right["width"]) <= int(left["x"]) or
        int(left["y"]) + int(left["height"]) <= int(right["y"]) or
        int(right["y"]) + int(right["height"]) <= int(left["y"])
    )


def normalized_signature(state: dict[str, object]) -> dict[str, object]:
    icons = sorted(
        ({key: item[key] for key in ("title", "x", "y", "width", "height",
                                      "region_allocated")}
         for item in state["icon_views"]),
        key=lambda item: str(item["title"]),
    )
    current_manager = manager(state)
    return {
        "windows": sorted(
            ({"title": item["title"], "iconified": item["iconified"]}
             for item in state["windows"]),
            key=lambda item: str(item["title"]),
        ),
        "icons": icons,
        "manager": {
            "columns": current_manager["columns"],
            "rows": current_manager["rows"],
            "entries": [
                {key: entry[key] for key in ("label", "row", "column")}
                for entry in current_manager["entries"]
            ],
        },
    }


def validate_state(
    state: dict[str, object], titles: list[str], manager_order: list[int],
) -> tuple[dict[int, tuple[int, int, int, int]], dict[str, int]]:
    if len(state["windows"]) != WINDOW_COUNT:
        raise RuntimeError(f"expected {WINDOW_COUNT} live windows: {len(state['windows'])}")
    windows_by_title = {str(item["title"]): item for item in state["windows"]}
    if len(windows_by_title) != WINDOW_COUNT or set(windows_by_title) != set(titles):
        raise RuntimeError("live window titles contain a duplicate, stale, or missing client")
    if not all(bool(item["iconified"]) for item in windows_by_title.values()):
        raise RuntimeError("a churn window did not return to IconicState")

    current_manager = manager(state)
    entries = current_manager["entries"]
    if len(entries) != WINDOW_COUNT:
        raise RuntimeError(f"manager entry count is stale: {len(entries)}")
    entry_ids = [int(item["id"]) for item in entries]
    if len(set(entry_ids)) != WINDOW_COUNT:
        raise RuntimeError("manager retained a duplicate entry identity")
    expected_labels = [titles[index] for index in manager_order]
    labels = [str(item["label"]) for item in entries]
    if labels != expected_labels:
        raise RuntimeError("manager entry order does not match deterministic lifecycle order")

    icons = state["icon_views"]
    if len(icons) != WINDOW_COUNT:
        raise RuntimeError(f"icon view count is stale: {len(icons)}")
    icons_by_title = {str(item["title"]): item for item in icons}
    if len(icons_by_title) != WINDOW_COUNT or set(icons_by_title) != set(titles):
        raise RuntimeError("icon views contain a duplicate, stale, or missing title")
    region_x, region_y, region_width, region_height = REGION
    values = list(icons_by_title.values())
    for icon in values:
        if not bool(icon["region_allocated"]):
            raise RuntimeError(f"icon lost its region reservation: {icon!r}")
        if (int(icon["x"]) < region_x or int(icon["y"]) < region_y or
                int(icon["x"]) + int(icon["width"]) > region_x + region_width or
                int(icon["y"]) + int(icon["height"]) > region_y + region_height):
            raise RuntimeError(f"icon escaped the configured region: {icon!r}")
    for left_index, left in enumerate(values):
        for right in values[left_index + 1:]:
            if rectangles_overlap(left, right):
                raise RuntimeError(f"live icon allocations overlap: {left!r}, {right!r}")

    rectangles: dict[int, tuple[int, int, int, int]] = {}
    for index, title in enumerate(titles):
        item = icons_by_title[title]
        rectangles[index] = tuple(
            int(item[key]) for key in ("x", "y", "width", "height")
        )
    return rectangles, {str(item["label"]): int(item["id"]) for item in entries}


def entry_point(current_manager: dict[str, object], label: str) -> tuple[int, int]:
    matches = [item for item in current_manager["entries"] if item["label"] == label]
    if len(matches) != 1:
        raise RuntimeError(f"cannot target unique manager entry {label!r}")
    entry = matches[0]
    columns = int(current_manager["columns"])
    rows = int(current_manager["rows"])
    cell_width = int(current_manager["width"]) // columns
    row_height = int(current_manager["height"]) // rows
    return (
        int(current_manager["x"]) + int(entry["column"]) * cell_width + cell_width // 2,
        int(current_manager["y"]) + int(entry["row"]) * row_height + row_height // 2,
    )


def click(control: Control, x: int, y: int) -> None:
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")


def wait_trace_kinds(
    control: Control, required: set[str], deadline_seconds: float = 5,
) -> dict[str, object]:
    deadline = time.monotonic() + deadline_seconds
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = control.trace()
        kinds = {str(item["event"]) for item in latest["events"]}
        if required <= kinds:
            return latest
        time.sleep(0.005)
    raise RuntimeError(f"trace omitted lifecycle operations {required!r}: {latest!r}")


def wait_final_state(
    control: Control, titles: list[str], deadline_seconds: float = 15,
    poll_seconds: float = 0.02,
) -> dict[str, object]:
    deadline = time.monotonic() + deadline_seconds
    latest: dict[str, object] = {}
    wanted = set(titles)
    while time.monotonic() < deadline:
        latest = control.state()
        window_titles = {str(item["title"]) for item in latest["windows"]}
        entry_labels = {str(item["label"]) for item in manager(latest)["entries"]}
        icon_titles = {str(item["title"]) for item in latest["icon_views"]}
        if window_titles == wanted and entry_labels == wanted and icon_titles == wanted:
            return latest
        time.sleep(poll_seconds)
    raise RuntimeError("compositor did not converge after recreate: " + repr(latest))


def wait_initial_association(
    control: Control, titles: list[str], state: dict[str, object],
    deadline_seconds: float = INITIAL_ASSOCIATION_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Wait until every logically managed X11 window has live surface content."""
    deadline = time.monotonic() + deadline_seconds
    latest = state
    last_ready = -1
    last_progress = time.monotonic()
    while time.monotonic() < deadline:
        lifecycle = latest["xwayland_lifecycle"]
        ready = sum(
            bool(item["associated"]) and bool(item["mapped"]) and
            bool(item["has_buffer"]) for item in lifecycle
        )
        if len(lifecycle) == WINDOW_COUNT and ready == WINDOW_COUNT:
            return latest
        if ready > last_ready:
            last_ready = ready
            last_progress = time.monotonic()
        elif time.monotonic() - last_progress > INITIAL_ASSOCIATION_STALL_SECONDS:
            raise RuntimeError(
                f"initial Xwayland association stalled: {ready}/{WINDOW_COUNT} ready"
            )
        # STATE is several hundred KiB at this scale; yield between snapshots so
        # the Xwayland association and frame-callback queues can make progress.
        time.sleep(0.25)
        latest = wait_final_state(control, titles, 15, 0.25)
    ready = sum(
        bool(item["associated"]) and bool(item["mapped"]) and
        bool(item["has_buffer"]) for item in latest["xwayland_lifecycle"]
    )
    raise RuntimeError(
        f"initial Xwayland surfaces did not converge: {ready}/{WINDOW_COUNT} ready"
    )


def wait_destroyed_state(
    control: Control, titles: list[str], destroyed_title: str,
    deadline_seconds: float = 15,
) -> dict[str, object]:
    deadline = time.monotonic() + deadline_seconds
    latest: dict[str, object] = {}
    wanted = set(titles)
    wanted.remove(destroyed_title)
    while time.monotonic() < deadline:
        latest = control.state()
        window_titles = {str(item["title"]) for item in latest["windows"]}
        entry_labels = {str(item["label"]) for item in manager(latest)["entries"]}
        icon_titles = {str(item["title"]) for item in latest["icon_views"]}
        if window_titles == wanted and entry_labels == wanted and icon_titles == wanted:
            return latest
        time.sleep(0.005)
    raise RuntimeError("compositor retained destroyed lifecycle state: " + repr(latest))


def config_text() -> str:
    return (
        "NoDefaults\n"
        "NoGrabServer\n"
        "NoTitle\n"
        "ShowIconManager\n"
        f"IconManagerGeometry \"{OUTPUT[0]}x5+0+0\" 32\n"
        "StartIconified { \"M7Churn\" }\n"
        f"IconRegion \"{REGION[2]}x{REGION[3]}+{REGION[0]}+{REGION[1]}\" "
        f"North West {GRID[0]} {GRID[1]}\n"
        "IconFont \"fixed\"\n"
        "IconManagerFont \"fixed\"\n"
        "IconBorderWidth 1\n"
        "Button1 = : iconmgr : f.iconify\n"
        "Color {\n"
        "  DefaultForeground \"#ffffff\"\n"
        "  DefaultBackground \"#202020\"\n"
        "  IconForeground \"#ffffff\"\n"
        "  IconBackground \"#304050\"\n"
        "  IconBorderColor \"#708090\"\n"
        "  IconManagerForeground \"#ffffff\"\n"
        "  IconManagerBackground \"#203040\"\n"
        "  IconManagerHighlight \"#ff00ff\"\n"
        "}\n"
    )


def run(arguments: argparse.Namespace) -> None:
    operations = schedule()
    validate_schedule(operations)
    expected_titles, generations, expected_order = expected_final_model(operations)
    result: dict[str, object] = {
        "schema_version": 1,
        "window_count": WINDOW_COUNT,
        "operation_count": OPERATION_COUNT,
        "operation_counts": dict(Counter(item["kind"] for item in operations)),
        "cycle_count": CYCLE_COUNT,
        "schedule_sha256": schedule_sha256(operations),
        "result": "failed",
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wtwm-m7-lifecycle-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        config = temporary / "churn.twmrc"
        config.write_text(config_text(), encoding="utf-8")
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C", "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        # The compositor emits enough lifecycle diagnostics during 2,000
        # operations to fill an unread pipe and block its event loop.  Keep the
        # complete logs in seekable files and collect them after shutdown.
        compositor_stdout_file = tempfile.TemporaryFile(
            mode="w+", encoding="utf-8"
        )
        compositor_stderr_file = tempfile.TemporaryFile(
            mode="w+", encoding="utf-8"
        )
        compositor = subprocess.Popen(
            [str(arguments.compositor), "-f", str(config), "-s", startup,
             "--test-control", str(control_path),
             "--test-socket", f"wtwm-m7-churn-{os.getpid()}",
             "--test-backend", "headless"],
            env=environment, text=True, stdout=compositor_stdout_file,
            stderr=compositor_stderr_file,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command(f"OUTPUT {OUTPUT[0]} {OUTPUT[1]}")
            display = wait_display(control, display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(arguments.client)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=1,
            )
            wait_line(client, f"READY {WINDOW_COUNT}")
            titles = [base_title(index, 0) for index in range(WINDOW_COUNT)]
            live_generations = [0] * WINDOW_COUNT
            manager_order = list(range(WINDOW_COUNT))
            # A full STATE response grows to hundreds of kilobytes.  Polling it
            # continuously can starve the Xwayland association event stream.
            state = wait_final_state(control, titles, 120, 0.25)
            state = wait_initial_association(control, titles, state)
            rectangles, entry_ids = validate_state(state, titles, manager_order)
            completed = 0
            for cycle in range(CYCLE_COUNT):
                index = (cycle * 73 + 19) % WINDOW_COUNT
                old_title = titles[index]
                old_entry_id = entry_ids[old_title]
                released_rectangle = rectangles[index]
                point = entry_point(manager(state), old_title)
                control.command("TRACE CLEAR")
                click(control, *point)
                click(control, *point)
                wait_trace_kinds(control, {"deiconify", "iconify"})
                completed += 2

                renamed = rename_title(index, cycle)
                client_command(client, f"RENAME {index} {renamed}", "OK RENAME")
                titles[index] = renamed
                wait_trace_kinds(control, {"deiconify", "iconify", "title"})
                completed += 1

                client_command(client, f"DESTROY {index}", "OK DESTROY")
                wait_destroyed_state(control, titles, renamed)
                manager_order.remove(index)
                completed += 1
                live_generations[index] += 1
                recreated = base_title(index, live_generations[index])
                client_command(
                    client, f"RECREATE {index} {recreated}", "OK RECREATE"
                )
                titles[index] = recreated
                manager_order.append(index)
                completed += 1

                state = wait_final_state(control, titles)
                rectangles, entry_ids = validate_state(
                    state, titles, manager_order
                )
                if rectangles[index] != released_rectangle:
                    raise RuntimeError(f"cycle {cycle} did not reuse target icon cell")
                if old_entry_id in entry_ids.values() or entry_ids[recreated] == old_entry_id:
                    raise RuntimeError(f"cycle {cycle} retained stale manager identity")
                trace = wait_trace_kinds(
                    control, {"deiconify", "iconify", "title", "unmap", "destroy", "map"}
                )
                if int(trace["dropped"]) != 0:
                    raise RuntimeError(f"cycle {cycle} overflowed deterministic trace")
                if cycle % 25 == 24:
                    print(
                        f"Milestone 7 churn: {cycle + 1}/{CYCLE_COUNT} cycles, "
                        f"{completed}/{OPERATION_COUNT} operations",
                        flush=True,
                    )
            if completed != OPERATION_COUNT:
                raise RuntimeError(f"executed {completed}, expected {OPERATION_COUNT} operations")
            if (titles != expected_titles or manager_order != expected_order or
                    live_generations != generations):
                raise RuntimeError("live final model differs from deterministic schedule model")
            signature = normalized_signature(state)
            signature_bytes = json.dumps(
                signature, sort_keys=True, separators=(",", ":")
            ).encode()
            result.update({
                "completed_operations": completed,
                "all_window_indices_exercised": True,
                "final_generation_sum": sum(live_generations),
                "final_state_sha256": hashlib.sha256(signature_bytes).hexdigest(),
                "final_manager_order": manager_order,
                "result": "passed",
            })
            control.command("QUIT")
            compositor.wait(timeout=10)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor returned {compositor.returncode}")
        except Exception as error:
            result["error"] = str(error)
            raise
        finally:
            if client is not None and client.poll() is None:
                try:
                    client_command(client, "QUIT", "OK QUIT")
                except (BrokenPipeError, RuntimeError):
                    client.terminate()
            client_stdout = ""
            client_stderr = ""
            if client is not None:
                try:
                    client_stdout, client_stderr = client.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    client.kill()
                    client_stdout, client_stderr = client.communicate(timeout=5)
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
            try:
                compositor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                compositor.kill()
                compositor.wait(timeout=5)
            compositor_stdout_file.seek(0)
            compositor_stdout = compositor_stdout_file.read()
            compositor_stdout_file.close()
            compositor_stderr_file.seek(0)
            compositor_stderr = compositor_stderr_file.read()
            compositor_stderr_file.close()
            arguments.log.write_text(
                f"client stdout:\n{client_stdout}\nclient stderr:\n{client_stderr}\n"
                f"compositor stdout:\n{compositor_stdout}\n"
                f"compositor stderr:\n{compositor_stderr}\n",
                encoding="utf-8",
            )
            arguments.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log", type=Path)
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return
    missing = [name for name in ("compositor", "client", "output", "log")
               if getattr(arguments, name) is None]
    if missing:
        parser.error("missing live arguments: " + ", ".join(missing))
    arguments.compositor = arguments.compositor.resolve(strict=True)
    arguments.client = arguments.client.resolve(strict=True)
    arguments.output = arguments.output.resolve()
    arguments.log = arguments.log.resolve()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.log.parent.mkdir(parents=True, exist_ok=True)
    run(arguments)


if __name__ == "__main__":
    main()
