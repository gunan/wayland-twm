#!/usr/bin/env python3
"""Verify the legacy cut-buffer translation across Wayland and Xwayland."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time

from run_client_stress import ClientChannel, wait_path, wait_process, wait_state
from run_compositor import Control


NATIVE_TITLE = "wtwm-selection-wayland"
X11_TITLE = "wtwm-selection-x11"
FILE_LIMIT = 4095


def cut_bytes(argument: bytes) -> bytes:
    return argument + b"\n"


def file_bytes(contents: bytes | None) -> bytes | None:
    if not contents:
        return None
    return contents[:FILE_LIMIT]


def first_filename(buffer: bytes) -> bytes | None:
    fields = buffer.split()
    return fields[0] if fields else None


def validate_model() -> None:
    if cut_bytes(b"exact") != b"exact\n":
        raise RuntimeError("f.cut newline model failed")
    if cut_bytes(b"") != b"\n":
        raise RuntimeError("empty f.cut model failed")
    contents = bytes(range(256)) * 17
    bounded = file_bytes(contents)
    if bounded != contents[:FILE_LIMIT] or len(bounded) != FILE_LIMIT:
        raise RuntimeError("file capacity model failed")
    if b"\x00" not in bounded:
        raise RuntimeError("file model lost embedded NUL bytes")
    if first_filename(b"/tmp/first\tignored\nlast") != b"/tmp/first":
        raise RuntimeError("f.cutfile first-token model failed")
    state = b"previous"
    for replacement in (file_bytes(b""), file_bytes(None)):
        if replacement is not None:
            state = replacement
    if state != b"previous":
        raise RuntimeError("empty/error preservation model failed")
    foreign_clipboard = b"foreign"
    if foreign_clipboard == state or state != b"previous":
        raise RuntimeError("foreign CLIPBOARD independence model failed")
    restarted = state
    if restarted != b"previous":
        raise RuntimeError("restart preservation model failed")


def config_text(large: Path, empty: Path, missing: Path) -> str:
    return (
        "NoDefaults\n"
        "RandomPlacement\n"
        "NoIconManagers\n"
        'Button1 = : window : f.cut "native-cut"\n'
        f'Button2 = : window : f.file "{large}"\n'
        "Button3 = : window : f.cutfile\n"
        f'Button4 = : window : f.file "{empty}"\n'
        f'Button5 = : window : f.file "{missing}"\n'
        "Button6 = : root : f.restart\n"
        'Button7 = : window : ^ "alias-cut"\n'
        'Button8 = : window : f.cut ""\n'
    )


def request(channel: ClientChannel, command: str) -> str:
    channel.stdin.write((command + "\n").encode("utf-8"))
    channel.stdin.flush()
    return channel.line(time.monotonic() + 10)


def parse_datahex(line: str, selection: str) -> bytes | None:
    match = re.fullmatch(
        rf"DATAHEX {selection} len=([0-9]+) hex=([0-9a-f]*)", line
    )
    if match is None:
        return None
    payload = bytes.fromhex(match.group(2))
    if len(payload) != int(match.group(1)):
        raise RuntimeError(f"invalid length in client response: {line!r}")
    return payload


def wait_selection(
    channel: ClientChannel, selection: str, expected: bytes, label: str,
) -> None:
    deadline = time.monotonic() + 10
    last = ""
    while time.monotonic() < deadline:
        last = request(channel, f"GETHEX {selection}")
        if parse_datahex(last, selection) == expected:
            return
        time.sleep(0.01)
    raise RuntimeError(
        f"timed out waiting for {label} {selection} bytes; last={last!r}, "
        f"expected_len={len(expected)} expected_hex={expected.hex()}"
    )


def parse_cut_buffer(line: str) -> tuple[str, int, bytes] | None:
    match = re.fullmatch(
        r"CUTBUFFER type=(STRING|NONE|OTHER) format=([0-9]+) "
        r"len=([0-9]+) hex=([0-9a-f]*)",
        line,
    )
    if match is None:
        return None
    payload = bytes.fromhex(match.group(4))
    if len(payload) != int(match.group(3)):
        raise RuntimeError(f"invalid CUT_BUFFER0 response length: {line!r}")
    return match.group(1), int(match.group(2)), payload


def wait_cut_buffer(channel: ClientChannel, expected: bytes, label: str) -> None:
    deadline = time.monotonic() + 10
    last = ""
    while time.monotonic() < deadline:
        last = request(channel, "GET CUTBUFFER")
        if parse_cut_buffer(last) == ("STRING", 8, expected):
            return
        time.sleep(0.01)
    raise RuntimeError(
        f"timed out waiting for {label} CUT_BUFFER0 STRING/8 bytes; "
        f"last={last!r}, expected_len={len(expected)}"
    )


def set_cut_buffer(channel: ClientChannel, payload: bytes) -> None:
    expected = f"CUTBUFFER SET len={len(payload)}"
    observed = request(channel, f"SET CUTBUFFER {payload.hex()}")
    if observed != expected:
        raise RuntimeError(
            f"setting foreign CUT_BUFFER0 expected {expected!r}, got {observed!r}"
        )


def window(state: dict[str, object], title: str) -> dict[str, object]:
    matches = [item for item in state["windows"] if item["title"] == title]
    if len(matches) != 1:
        raise RuntimeError(f"expected one mapped {title!r}: {state!r}")
    return matches[0]


def mapped_pair(state: dict[str, object]) -> bool:
    windows = state["windows"]
    return (
        len(windows) == 2
        and {item["title"] for item in windows} == {NATIVE_TITLE, X11_TITLE}
        and all(item["mapped"] for item in windows)
        and {item["type"] for item in windows} == {"wayland", "x11"}
    )


def visible_content_point(
    state: dict[str, object], title: str,
) -> tuple[int, int]:
    target = window(state, title)
    above = [
        item for item in state["windows"]
        if int(item["stack"]) < int(target["stack"])
    ]
    left = int(target["x"]) + int(target["content_x"])
    top = int(target["y"]) + int(target["content_y"])
    right = left + int(target["width"])
    bottom = top + int(target["height"])
    for y in (top + 12, bottom - 12, (top + bottom) // 2):
        for x in (left + 12, right - 12, (left + right) // 2):
            if not any(
                int(other["x"]) <= x
                < int(other["x"]) + int(other["outer_width"])
                and int(other["y"]) <= y
                < int(other["y"]) + int(other["outer_height"])
                for other in above
            ):
                return x, y
    raise RuntimeError(f"no visible content point for {title!r}: {state!r}")


def pointer_inside(control: Control, title: str) -> None:
    x, y = visible_content_point(control.state(), title)
    control.command(f"POINTER {x} {y}")
    control.command("WAIT 2")
    state = control.state()
    if state["pointer_window"] != title or state["pointer_context"] != "window":
        raise RuntimeError(f"pointer did not enter {title!r} content: {state!r}")


def click(control: Control, title: str, raw_button: int) -> None:
    pointer_inside(control, title)
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 2")


def click_root(control: Control, raw_button: int) -> None:
    control.command("POINTER 790 470")
    control.command("WAIT 2")
    state = control.state()
    if state["pointer_context"] != "root":
        raise RuntimeError(f"pointer did not enter root context: {state!r}")
    control.command(f"BUTTON {raw_button} press")
    control.command(f"BUTTON {raw_button} release")
    control.command("WAIT 3")


def assert_payloads(
    control: Control,
    native: ClientChannel,
    x11: ClientChannel,
    expected: bytes,
    label: str,
) -> None:
    pointer_inside(control, NATIVE_TITLE)
    wait_selection(native, "CLIPBOARD", expected, f"native {label}")
    pointer_inside(control, X11_TITLE)
    if request(x11, "WAIT FOCUS") != "FOCUS 1":
        raise RuntimeError(f"X11 fixture did not focus for {label}")
    wait_selection(x11, "CLIPBOARD", expected, f"Xwayland {label}")
    wait_cut_buffer(x11, expected, label)


def run(compositor: Path, wayland_client: Path, x11_client: Path) -> None:
    validate_model()
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-cut-", dir="/tmp") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control"
        display_marker = temporary / "display"
        config = temporary / "cut-buffer.twmrc"
        large_path = temporary / "large.bin"
        token_path = temporary / "token.bin"
        empty_path = temporary / "empty.bin"
        missing_path = temporary / "missing.bin"
        large_contents = bytes(range(256)) * 20
        token_contents = b"from-cutfile\x00with-newline\n"
        large_path.write_bytes(large_contents)
        token_path.write_bytes(token_contents)
        empty_path.write_bytes(b"")
        config.write_text(
            config_text(large_path, empty_path, missing_path), encoding="utf-8"
        )

        runtime_environment = os.environ.copy()
        runtime_environment.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        socket_name = f"wtwm-m8-cut-{os.getpid()}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        process = subprocess.Popen(
            [
                str(compositor), "-f", str(config), "-s", startup,
                "--test-control", str(control_path),
                "--test-socket", socket_name,
                "--test-backend", "headless",
            ],
            env=runtime_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        clients: list[tuple[str, subprocess.Popen[bytes]]] = []
        try:
            control = Control(control_path, process)
            control.socket.settimeout(10)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("OUTPUT 800 480")

            wayland_environment = runtime_environment.copy()
            wayland_environment["WAYLAND_DISPLAY"] = socket_name
            native_process = subprocess.Popen(
                [str(wayland_client)], env=wayland_environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append(("native", native_process))
            native = ClientChannel(native_process, "native cut-buffer client")
            native.expect("READY")

            x11_environment = runtime_environment.copy()
            x11_environment["DISPLAY"] = wait_path(display_marker)
            x11_process = subprocess.Popen(
                [str(x11_client)], env=x11_environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            clients.append(("X11", x11_process))
            x11 = ClientChannel(x11_process, "X11 cut-buffer client")
            x11.expect_prefix("READY ")

            wait_state(control, mapped_pair, "native/Xwayland cut-buffer clients")

            # Establish an unrelated PRIMARY selection. An unbound Button9
            # supplies the native client with a valid serial without executing
            # one of the cut-buffer bindings.
            pointer_inside(control, NATIVE_TITLE)
            control.command("BUTTON 280 press")
            control.command("BUTTON 280 release")
            serial = request(native, "WAIT SERIAL")
            if not serial.startswith("SERIAL ") or serial == "SERIAL 0":
                raise RuntimeError(f"native fixture did not receive a serial: {serial!r}")
            if request(native, "SET PRIMARY") != "SET PRIMARY native-primary":
                raise RuntimeError("native fixture could not establish PRIMARY")

            # f.cut is useful on a native target: it appends exactly one newline,
            # becomes ordinary CLIPBOARD data for both protocols, and is mirrored
            # into Xwayland's root CUT_BUFFER0 as STRING/8.
            click(control, NATIVE_TITLE, 272)
            assert_payloads(
                control, native, x11, cut_bytes(b"native-cut"), "f.cut"
            )

            click(control, X11_TITLE, 279)
            assert_payloads(control, native, x11, b"\n", "empty f.cut")

            # The lexical ^ shorthand reaches the same action, including when
            # dispatched on a managed Xwayland window, and replaces all views.
            click(control, X11_TITLE, 278)
            assert_payloads(
                control, native, x11, cut_bytes(b"alias-cut"), "^ alias"
            )

            # f.file retains arbitrary bytes (including NUL), caps the read at
            # 4095 bytes, and again publishes identical native/X11 observations.
            click(control, X11_TITLE, 274)
            large_expected = large_contents[:FILE_LIMIT]
            if b"\x00" not in large_expected:
                raise RuntimeError("large fixture unexpectedly lacks an embedded NUL")
            assert_payloads(control, native, x11, large_expected, "f.file")

            # A foreign CLIPBOARD owner must not rewrite the persistent legacy
            # buffer. f.cutfile instead obtains the first whitespace token from
            # the independently supplied root CUT_BUFFER0 filename.
            pointer_inside(control, X11_TITLE)
            if request(x11, "WAIT FOCUS") != "FOCUS 1":
                raise RuntimeError("X11 fixture did not receive input focus")
            if request(x11, "OWN CLIPBOARD") != "OWN CLIPBOARD 1":
                raise RuntimeError("X11 fixture could not own foreign CLIPBOARD")
            wait_selection(x11, "CLIPBOARD", b"x11-clipboard", "foreign owner")
            wait_cut_buffer(x11, large_expected, "foreign CLIPBOARD independence")
            whitespace_buffer = b" \t\n"
            set_cut_buffer(x11, whitespace_buffer)
            click(control, X11_TITLE, 273)
            wait_selection(
                x11, "CLIPBOARD", b"x11-clipboard", "empty filename preservation"
            )
            wait_cut_buffer(x11, whitespace_buffer, "empty filename preservation")
            filename_buffer = str(token_path).encode() + b"\tignored-token\n"
            set_cut_buffer(x11, filename_buffer)
            wait_cut_buffer(x11, filename_buffer, "foreign filename")
            click(control, X11_TITLE, 273)
            assert_payloads(control, native, x11, token_contents, "f.cutfile")

            # Empty and failed file loads are atomic: neither the clipboard
            # source nor the mirrored cut buffer changes.
            click(control, NATIVE_TITLE, 275)
            assert_payloads(
                control, native, x11, token_contents, "empty-file preservation"
            )
            click(control, X11_TITLE, 276)
            assert_payloads(
                control, native, x11, token_contents, "missing-file preservation"
            )

            # Cut/file actions never claim or replace PRIMARY.
            wait_selection(x11, "PRIMARY", b"native-primary", "PRIMARY invariance")

            # The in-place restart retains the persistent buffer, both protocol
            # clients, CLIPBOARD publication, and the unrelated PRIMARY owner.
            click_root(control, 277)
            wait_state(control, mapped_pair, "clients preserved across restart")
            assert_payloads(
                control, native, x11, token_contents, "restart preservation"
            )
            wait_selection(x11, "PRIMARY", b"native-primary", "restart PRIMARY")
            if request(native, "CANCELS").startswith("CANCELS ") is False:
                raise RuntimeError("native client stopped responding after restart")
            if request(x11, "STATUS").startswith("STATUS ") is False:
                raise RuntimeError("X11 client stopped responding after restart")
            if control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("test-control stopped responding after restart")

            native.command("EXIT", "EXITING")
            x11.command("EXIT", "EXITING")
            if wait_process(native_process, "native cut-buffer client") != 0:
                raise RuntimeError("native cut-buffer client did not exit cleanly")
            if wait_process(x11_process, "X11 cut-buffer client") != 0:
                raise RuntimeError("X11 cut-buffer client did not exit cleanly")
            clients.clear()
            control.command("QUIT")
            control.close()
            control = None
            if process.wait(timeout=10) != 0:
                stderr = process.stderr.read().decode() if process.stderr else ""
                raise RuntimeError(f"cut-buffer compositor failed: {stderr}")
        except Exception as error:
            diagnostics: list[str] = []
            for label, client_process in clients:
                if client_process.poll() is None:
                    client_process.kill()
                _, stderr = client_process.communicate(timeout=10)
                if stderr:
                    diagnostics.append(f"{label}:\n{stderr.decode(errors='replace')}")
            if process.poll() is None:
                process.kill()
            _, stderr = process.communicate(timeout=10)
            raise RuntimeError(
                f"{error}\nclient stderr:\n{''.join(diagnostics)}"
                f"compositor stderr:\n{stderr.decode(errors='replace')}"
            ) from error
        finally:
            if control is not None:
                control.close()
            for _, client_process in clients:
                if client_process.poll() is None:
                    client_process.kill()
                    client_process.wait(timeout=10)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    parser.add_argument("--wayland-client", type=Path)
    parser.add_argument("--x11-client", type=Path)
    args = parser.parse_args()
    if args.self_test_model:
        validate_model()
        print("Milestone 8 cut-buffer model self-test passed")
        return 0
    paths = (args.compositor, args.wayland_client, args.x11_client)
    if any(path is None for path in paths):
        parser.error("--compositor, --wayland-client, and --x11-client are required")
    for path in paths:
        assert path is not None
        if not path.is_file():
            parser.error(f"missing executable: {path}")
    assert args.compositor is not None
    assert args.wayland_client is not None
    assert args.x11_client is not None
    run(
        args.compositor.resolve(), args.wayland_client.resolve(),
        args.x11_client.resolve(),
    )
    print("Milestone 8 Wayland/Xwayland cut-buffer integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
