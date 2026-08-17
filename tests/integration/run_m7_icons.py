#!/usr/bin/env python3
"""Exercise Milestone 7 icon windows, regions, and icon managers."""

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


def wait_line(process: subprocess.Popen[str], expected: str) -> None:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 10)
    if not ready or process.stdout.readline().rstrip("\n") != expected:
        raise RuntimeError(f"timed out waiting for {expected!r}")


def wait_display(control: Control, path: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            display = path.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("startup command did not publish DISPLAY")


def wait_windows(control: Control) -> dict[str, object]:
    expected = {"xwm-parent-initial", "xwm-transient", "Reference Alpha",
                "Reference Bravo"}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = control.state()
        titles = {item["title"] for item in state["windows"]}
        if expected <= titles:
            return state
        time.sleep(0.01)
    raise RuntimeError(f"Milestone 7 clients did not map: {control.state()!r}")


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"missing window {title!r}: {state!r}")
    return matches[0]


def manager(state: dict[str, object], identity: int) -> dict[str, object]:
    matches = [item for item in state["icon_managers"]
               if int(item["id"]) == identity]
    if len(matches) != 1:
        raise RuntimeError(f"missing icon manager {identity}: {state!r}")
    return matches[0]


def click(control: Control, x: int, y: int) -> None:
    control.command(f"POINTER {x} {y}")
    control.command("BUTTON 272 press")
    control.command("BUTTON 272 release")


def click_frame(control: Control, item: dict[str, object]) -> None:
    click(control, int(item["x"]) + 1,
          int(item["y"]) + int(item["outer_height"]) // 2)


def entry_point(item: dict[str, object], label: str) -> tuple[int, int]:
    entries = [entry for entry in item["entries"] if entry["label"] == label]
    if len(entries) != 1:
        raise RuntimeError(f"missing manager entry {label!r}: {item!r}")
    entry = entries[0]
    columns = max(1, int(item["columns"]))
    cell_width = int(item["width"]) // columns
    rows = max(1, int(item["rows"]))
    row_height = int(item["height"]) // rows
    return (int(item["x"]) + int(entry["column"]) * cell_width + cell_width // 2,
            int(item["y"]) + int(entry["row"]) * row_height + row_height // 2)


def key(control: Control, code: int) -> None:
    control.command(f"KEY {code} press")
    control.command(f"KEY {code} release")


def ppm_color_count(path: Path) -> int:
    data = path.read_bytes()
    if not data.startswith(b"P6\n"):
        raise RuntimeError("icon screenshot is not a binary PPM")
    _, payload = data.split(b"\n255\n", 1)
    return len({payload[index:index + 3] for index in range(0, len(payload), 3)})


def run(compositor_binary: Path, bridge_binary: Path,
        visual_binary: Path) -> None:
    compositor_binary = compositor_binary.resolve()
    bridge_binary = bridge_binary.resolve()
    visual_binary = visual_binary.resolve()
    with tempfile.TemporaryDirectory(prefix="wtwm-m7-icons-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_path = temporary / "display"
        bitmap = temporary / "configured.xbm"
        bitmap.write_text(
            "#define configured_width 8\n#define configured_height 8\n"
            "static unsigned char configured_bits[] = {"
            "0x81,0x42,0x24,0x18,0x18,0x24,0x42,0x81};\n",
            encoding="utf-8",
        )
        config = temporary / "icons.twmrc"
        config.write_text(
            "NoDefaults\n"
            "ShowIconManager\n"
            "SortIconManager\n"
            "ForceIcons\n"
            "Zoom 4\n"
            "IconManagerGeometry \"300x5+0+0\" 2\n"
            "IconManagers { \"XwmClassInitial\" \"Bridge\" "
            "\"180x5-0+0\" 1 }\n"
            "IconManagerDontShow { \"xwm-transient\" \"Reference Alpha\" }\n"
            "IconManagerShow { \"Reference Alpha\" }\n"
            "IconifyByUnmapping { \"Reference Alpha\" }\n"
            "StartIconified { \"Reference Bravo\" }\n"
            f"UnknownIcon \"{bitmap}\"\n"
            f"Icons {{ \"Reference Bravo\" \"{bitmap}\" }}\n"
            "IconRegion \"200x200+380+220\" South East 50 50\n"
            "Button1 = : frame : f.iconify\n"
            "Button1 = : icon : f.iconify\n"
            "Button1 = : iconmgr : f.iconify\n"
            "\"F2\" = : iconmgr : f.forwiconmgr\n"
            "\"F3\" = : iconmgr : f.hideiconmgr\n"
            "\"F4\" = : root : f.showiconmgr\n"
            "\"F5\" = : root : f.sorticonmgr\n"
            "\"F6\" = : root : f.warptoiconmgr \"Reference Bravo\"\n"
            "\"F7\" = : iconmgr : f.nexticonmgr\n"
            "\"F8\" = : iconmgr : f.previconmgr\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update({"XDG_RUNTIME_DIR": str(runtime),
                            "WLR_RENDERER": "pixman"})
        socket_name = f"wtwm-m7-icons-{os.getpid()}"
        startup = "printf '%s\\n' \"$DISPLAY\" > " + shlex.quote(str(display_path))
        compositor = subprocess.Popen(
            [str(compositor_binary), "-f", str(config), "-s", startup,
             "--test-control", str(control_path), "--test-socket", socket_name,
             "--test-backend", "headless"],
            env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        bridge: subprocess.Popen[str] | None = None
        visual: subprocess.Popen[str] | None = None
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 12")
            control.command("SET FONT DejaVu Sans 10")
            control.command("OUTPUT 640 480")
            control.command("OUTPUT 320 480")
            display = wait_display(control, display_path)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            bridge = subprocess.Popen(
                [str(bridge_binary)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=1,
            )
            visual = subprocess.Popen(
                [str(visual_binary)], env=client_environment, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=1,
            )
            wait_line(bridge, "READY")
            wait_line(visual, "READY")
            state = wait_windows(control)

            default = manager(state, 1)
            custom = manager(state, 2)
            default_labels = [entry["label"] for entry in default["entries"]]
            if default_labels != ["Reference Alpha", "Reference Bravo"]:
                raise RuntimeError(f"default manager filtering/sort is wrong: {default!r}")
            if [entry["label"] for entry in custom["entries"]] != ["xwm-icon-initial"]:
                raise RuntimeError(f"custom manager matching is wrong: {custom!r}")
            if int(custom["x"]) < 640:
                raise RuntimeError(f"custom manager did not use the second output: {custom!r}")

            bravo = window(state, "Reference Bravo")
            if not bravo["iconified"]:
                raise RuntimeError("StartIconified did not iconify Reference Bravo")
            bravo_icons = [item for item in state["icon_views"]
                           if item["title"] == "Reference Bravo"]
            if len(bravo_icons) != 1 or bravo_icons[0]["source"] != "configured" \
                    or not bravo_icons[0]["region_allocated"]:
                raise RuntimeError(f"configured ForceIcons icon is wrong: {bravo_icons!r}")

            parent = window(state, "xwm-parent-initial")
            click_frame(control, parent)
            state = control.state()
            parent_icons = [item for item in state["icon_views"]
                            if item["title"] == "xwm-parent-initial"]
            if len(parent_icons) != 1 or parent_icons[0]["source"] != "wm_hints" \
                    or not parent_icons[0]["region_allocated"]:
                raise RuntimeError(f"WM_HINTS client icon is wrong: {parent_icons!r}")
            bravo_icon = next(item for item in state["icon_views"]
                              if item["title"] == "Reference Bravo")
            occupied = {(item["x"], item["y"]) for item in (parent_icons[0], bravo_icon)}
            if len(occupied) != 2:
                raise RuntimeError(f"IconRegion collision was not avoided: {occupied!r}")

            alpha = window(state, "Reference Alpha")
            click_frame(control, alpha)
            state = control.state()
            alpha = window(state, "Reference Alpha")
            if not alpha["iconified"] or not alpha["iconify_by_unmapping"]:
                raise RuntimeError(f"IconifyByUnmapping rule is wrong: {alpha!r}")
            if any(item["title"] == "Reference Alpha" for item in state["icon_views"]):
                raise RuntimeError("unmapping-only iconification created an icon window")
            if "Reference Alpha" not in [entry["label"]
                                           for entry in manager(state, 1)["entries"]]:
                raise RuntimeError("icon manager lost an unmapping-only window")

            default = manager(state, 1)
            click(control, *entry_point(default, "Reference Alpha"))
            if window(control.state(), "Reference Alpha")["iconified"]:
                raise RuntimeError("icon-manager row did not deiconify its window")

            default = manager(control.state(), 1)
            control.command(f"POINTER {entry_point(default, 'Reference Alpha')[0]} "
                            f"{entry_point(default, 'Reference Alpha')[1]}")
            key(control, 60)  # F2: f.forwiconmgr
            selected = manager(control.state(), 1)["active_entry"]
            bravo_entry = next(entry for entry in default["entries"]
                               if entry["label"] == "Reference Bravo")
            if int(selected) != int(bravo_entry["id"]):
                raise RuntimeError("forward icon-manager navigation selected the wrong row")

            control.command("POINTER 630 470")
            key(control, 64)  # F6: named f.warptoiconmgr from root
            warped = control.state()["cursor"]
            default = manager(control.state(), 1)
            if not (int(default["x"]) <= float(warped["x"]) <
                    int(default["x"]) + int(default["width"])):
                raise RuntimeError("named f.warptoiconmgr did not reach its row")
            key(control, 65)  # F7: next visible non-empty manager
            state = control.state()
            cursor = state["cursor"]
            custom = manager(state, 2)
            if not (int(custom["x"]) <= float(cursor["x"]) <
                    int(custom["x"]) + int(custom["width"])):
                raise RuntimeError(f"next icon manager did not warp to custom manager: {state!r}")
            key(control, 66)  # F8: previous manager

            default = manager(control.state(), 1)
            control.command(f"POINTER {entry_point(default, 'Reference Alpha')[0]} "
                            f"{entry_point(default, 'Reference Alpha')[1]}")
            key(control, 61)  # F3: hide manager
            if manager(control.state(), 1)["visible"]:
                raise RuntimeError("f.hideiconmgr did not hide the active manager")
            control.command("POINTER 630 470")
            key(control, 62)  # F4: show active manager from root
            if not manager(control.state(), 1)["visible"]:
                raise RuntimeError("f.showiconmgr did not restore the active manager")

            assert visual.stdin is not None
            visual.stdin.write("TITLE bravo Aardvark\n")
            visual.stdin.flush()
            wait_line(visual, "TITLE bravo")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                labels = [entry["label"] for entry in
                          manager(control.state(), 1)["entries"]]
                if labels == ["Aardvark", "Reference Alpha"]:
                    break
                time.sleep(0.01)
            else:
                raise RuntimeError("automatic icon-manager sorting did not follow icon names")

            capture = temporary / "icons.ppm"
            control.command("WAIT 2")
            control.command(f"CAPTURE {capture}")
            if ppm_color_count(capture) < 4:
                raise RuntimeError("icon/manager screenshot lacks expected visual structure")
            events = control.trace()["events"]
            if not any(event["event"] == "animation" for event in events):
                raise RuntimeError("Zoom iconification did not emit an animation transition")
        finally:
            for process in (bridge, visual):
                if process is not None and process.poll() is None:
                    assert process.stdin is not None
                    process.stdin.write("EXIT\n" if process is bridge else "QUIT\n")
                    process.stdin.flush()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
            if control is not None:
                try:
                    control.command("QUIT")
                except (BrokenPipeError, ConnectionError, RuntimeError):
                    pass
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
            try:
                compositor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
            if compositor.returncode not in (0, -15):
                stderr = compositor.stderr.read() if compositor.stderr else ""
                raise RuntimeError(f"compositor failed ({compositor.returncode}): {stderr}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", required=True, type=Path)
    parser.add_argument("--bridge-client", required=True, type=Path)
    parser.add_argument("--visual-client", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.compositor, arguments.bridge_client, arguments.visual_client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
