#!/usr/bin/env python3
"""Verify the Milestone 8 X-screen to Wayland-output mapping."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from run_compositor import Control


WIDTH = 320
HEIGHT = 240
LEFT = (41.0, 37.0)
RIGHT = (WIDTH + LEFT[0], LEFT[1])
INT_MAX = 2_147_483_647


def select_config_source(
    explicit: str | None,
    available: set[str],
) -> str:
    """Portable model for the user-visible part of startup-file selection."""
    if explicit is not None:
        candidates = (explicit, "system", "builtin")
    else:
        candidates = (".twmrc.0", ".twmrc", "system", "builtin")
    for candidate in candidates:
        if candidate in available:
            return candidate
    return "builtin"


def canonical_identities(
    identities: list[tuple[str | None, str | None, str | None, str | None, int]],
) -> list[tuple[str | None, str | None, str | None, str | None, int]]:
    def key(
        identity: tuple[str | None, str | None, str | None, str | None, int],
    ) -> tuple[bytes, bytes, bytes, bytes, int]:
        strings = tuple((value or "").encode("utf-8") for value in identity[:4])
        return strings[0], strings[1], strings[2], strings[3], identity[4]

    return sorted(identities, key=key)


def numeric_target(argument: str | None, output_count: int) -> int | None:
    if argument is None or re.fullmatch(r"[0-9]+", argument) is None:
        return None
    value = int(argument, 10)
    if value > INT_MAX or value >= output_count:
        return None
    return value


def translated_coordinate(
    source: tuple[int, int, int, int],
    target: tuple[int, int, int, int],
    point: tuple[float, float],
) -> tuple[float, float]:
    relative_x = point[0] - source[0]
    relative_y = point[1] - source[1]
    return (
        target[0] + min(max(relative_x, 0), target[2] - 1),
        target[1] + min(max(relative_y, 0), target[3] - 1),
    )


def validate_model() -> None:
    available = {
        ".twmrc.0", ".twmrc.1", ".twmrc", "explicit.twmrc", "system",
        "builtin",
    }
    if select_config_source(None, available) != ".twmrc.0":
        raise RuntimeError("screen-zero configuration did not win implicit search")
    if select_config_source(None, {".twmrc.1", ".twmrc"}) != ".twmrc":
        raise RuntimeError("higher screen suffix incorrectly entered implicit search")
    if select_config_source(None, {".twmrc.1", "system", "builtin"}) != "system":
        raise RuntimeError("implicit search did not reach the system fallback")
    if select_config_source(None, {".twmrc.1", "builtin"}) != "builtin":
        raise RuntimeError("implicit search did not reach built-in defaults")
    if select_config_source("explicit.twmrc", available) != "explicit.twmrc":
        raise RuntimeError("explicit unsuffixed configuration did not win")
    if select_config_source(
        "missing", {".twmrc.0", ".twmrc", "system", "builtin"},
    ) != "system":
        raise RuntimeError("missing explicit file did not ignore HOME fallbacks")

    reverse_announcement = [
        ("HEADLESS-2", None, None, None, 2),
        ("HEADLESS-1", None, None, None, 1),
    ]
    if [item[0] for item in canonical_identities(reverse_announcement)] != [
        "HEADLESS-1", "HEADLESS-2",
    ]:
        raise RuntimeError("output identity order followed insertion order")
    colliding = [
        ("same", "make", "model", "serial", 9),
        ("same", "make", "model", "serial", 4),
        ("same", "make", "alpha", "serial", 8),
    ]
    if [item[4] for item in canonical_identities(colliding)] != [8, 4, 9]:
        raise RuntimeError("identity fields or announcement tie-break are unstable")

    for argument, expected in (("0", 0), ("00", 0), ("1", 1)):
        if numeric_target(argument, 2) != expected:
            raise RuntimeError(f"valid numeric output form rejected: {argument!r}")
    for argument in (
        None, "", "-1", "+1", " 1", "1 ", "1x", "١",
        str(INT_MAX + 1), "2",
    ):
        if numeric_target(argument, 2) is not None:
            raise RuntimeError(f"unsafe numeric output form accepted: {argument!r}")

    source = (0, 0, WIDTH, HEIGHT)
    target = (WIDTH, 0, WIDTH, HEIGHT)
    if translated_coordinate(source, target, LEFT) != RIGHT:
        raise RuntimeError("same-sized output warp lost output-relative coordinates")
    if translated_coordinate(source, (WIDTH, 0, 20, 10), (319, 239)) != (
        WIDTH + 19, 9,
    ):
        raise RuntimeError("smaller target did not clamp the relative coordinate")


def config_text() -> str:
    return (
        "NoDefaults\n"
        'Button1 = : root : f.warptoscreen "1"\n'
        'Button2 = : root : f.warptoscreen "0"\n'
        'Button3 = : root : f.warptoscreen "2"\n'
        "Button4 = : root : f.restart\n"
    )


def conflict_text(button: int) -> str:
    return (
        "NoDefaults\n"
        f'Button{button} = : root : f.warptoscreen "0"\n'
        'Button1 = : root : f.warptoscreen "0"\n'
        'Button2 = : root : f.warptoscreen "1"\n'
    )


def wait_cursor(
    control: Control,
    expected: tuple[float, float],
    label: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = control.state()
        cursor = last["cursor"]
        if (
            abs(float(cursor["x"]) - expected[0]) <= 0.001
            and abs(float(cursor["y"]) - expected[1]) <= 0.001
            and last["pointer_context"] == "root"
        ):
            return last
        time.sleep(0.01)
    raise RuntimeError(
        f"timed out waiting for {label} cursor {expected!r}: {last!r}"
    )


def point(control: Control, expected: tuple[float, float], label: str) -> None:
    control.command(f"POINTER {expected[0]} {expected[1]}")
    wait_cursor(control, expected, label)


def click(control: Control, button: int) -> None:
    raw = 271 + button
    control.command(f"BUTTON {raw} press")
    control.command(f"BUTTON {raw} release")


def expect_after_click(
    control: Control,
    button: int,
    expected: tuple[float, float],
    label: str,
) -> None:
    click(control, button)
    control.command("WAIT 2")
    wait_cursor(control, expected, label)


class Session:
    def __init__(
        self,
        root: Path,
        label: str,
        compositor: Path,
        home: Path,
        explicit: Path | None,
    ) -> None:
        runtime = root / f"runtime-{label}"
        runtime.mkdir(mode=0o700)
        self.control_path = root / f"control-{label}.sock"
        self.process = subprocess.Popen(
            [
                str(compositor),
                *([] if explicit is None else ["-f", str(explicit)]),
                "--test-control", str(self.control_path),
                "--test-socket", f"wtwm-m8-screen-{label}-{os.getpid()}",
                "--test-backend", "headless",
            ],
            env={
                **os.environ,
                "HOME": str(home),
                "XDG_RUNTIME_DIR": str(runtime),
                "WLR_RENDERER": "pixman",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.control = Control(self.control_path, self.process)
        self.control.socket.settimeout(10)
        self.control.command("SET ANIMATION_MS 0")

    def add_output(self) -> str:
        response = self.control.command(f"OUTPUT {WIDTH} {HEIGHT}")
        match = re.fullmatch(rf"OK OUTPUT (\S+) {WIDTH} {HEIGHT}", response)
        if match is None:
            raise RuntimeError(f"unexpected output response: {response!r}")
        self.control.command("WAIT 2")
        return match.group(1)

    def stop(self) -> str:
        self.control.command("QUIT")
        self.control.close()
        if self.process.wait(timeout=10) != 0:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"screen/output compositor failed: {stderr}")
        return self.process.stderr.read() if self.process.stderr else ""

    def abort(self) -> str:
        try:
            self.control.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.kill()
        _, stderr = self.process.communicate(timeout=10)
        return stderr


def verify_zero_and_outputs(session: Session, *, check_ignored: bool) -> None:
    if session.control.command("PING") != "OK WTWM_TEST_CONTROL 1":
        raise RuntimeError("zero-output compositor control did not survive startup")
    zero = session.control.state()
    if zero["windows"] or zero["pointer_context"] != "root":
        raise RuntimeError(f"unexpected zero-output state: {zero!r}")

    first = session.add_output()
    if first != "HEADLESS-1":
        raise RuntimeError(f"unexpected first output identity: {first!r}")
    point(session.control, LEFT, "one-output screen-zero binding")
    expect_after_click(
        session.control, 1, LEFT,
        "out-of-range target while only canonical output zero exists",
    )
    expect_after_click(
        session.control, 2, LEFT,
        "canonical output-zero binding on the sole output",
    )

    second = session.add_output()
    if second != "HEADLESS-2":
        raise RuntimeError(f"unexpected second output identity: {second!r}")
    if canonical_identities([
        (second, None, None, None, 2),
        (first, None, None, None, 1),
    ])[0][0] != first:
        raise RuntimeError("headless identities do not expose reverse-list ordering")

    point(session.control, LEFT, "canonical output zero")
    expect_after_click(
        session.control, 1, RIGHT,
        "screen-zero Button1 mapping on canonical output zero",
    )
    expect_after_click(
        session.control, 2, LEFT,
        "same screen-zero Button2 mapping on canonical output one",
    )
    point(session.control, RIGHT, "canonical output one before numeric rejection")
    expect_after_click(
        session.control, 3, RIGHT,
        "out-of-range numeric target preserves coordinates",
    )

    if check_ignored:
        expect_after_click(
            session.control, 5, RIGHT,
            "ignored .twmrc.1 binding does not merge",
        )
        expect_after_click(
            session.control, 6, RIGHT,
            "ignored unsuffixed HOME binding does not merge",
        )


def run(compositor: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wtwm-m8-screen-") as directory:
        root = Path(directory)

        implicit_home = root / "implicit-home"
        implicit_home.mkdir()
        screen_zero = implicit_home / ".twmrc.0"
        screen_zero.write_text(config_text(), encoding="utf-8")
        (implicit_home / ".twmrc.1").write_text(
            conflict_text(5), encoding="utf-8",
        )
        (implicit_home / ".twmrc").write_text(
            conflict_text(6), encoding="utf-8",
        )
        implicit = Session(root, "implicit", compositor, implicit_home, None)
        try:
            verify_zero_and_outputs(implicit, check_ignored=True)

            # Make both ignored candidates conflict again before a root restart.
            # The active source and output mapping must remain screen zero.
            (implicit_home / ".twmrc.1").write_text(
                conflict_text(5) + 'Button3 = : root : f.warptoscreen "0"\n',
                encoding="utf-8",
            )
            (implicit_home / ".twmrc").write_text(
                conflict_text(6) + 'Button4 = : root : f.warptoscreen "0"\n',
                encoding="utf-8",
            )
            expect_after_click(
                implicit.control, 4, RIGHT,
                "in-place restart retains cursor and screen-zero source",
            )
            if implicit.control.command("PING") != "OK WTWM_TEST_CONTROL 1":
                raise RuntimeError("root f.restart replaced the control connection")
            expect_after_click(
                implicit.control, 2, LEFT,
                "screen-zero mapping after in-place restart",
            )
            expect_after_click(
                implicit.control, 1, RIGHT,
                "global mapping on both outputs after in-place restart",
            )
            expect_after_click(
                implicit.control, 5, RIGHT,
                "restart did not merge .twmrc.1",
            )
            expect_after_click(
                implicit.control, 6, RIGHT,
                "restart did not merge HOME .twmrc",
            )
            implicit.stop()
        except Exception as error:
            stderr = implicit.abort()
            raise RuntimeError(
                f"implicit screen/output session failed: {error}\n"
                f"compositor stderr:\n{stderr}"
            ) from error

        explicit_home = root / "explicit-home"
        explicit_home.mkdir()
        (explicit_home / ".twmrc.0").write_text(
            conflict_text(5), encoding="utf-8",
        )
        (explicit_home / ".twmrc.1").write_text(
            conflict_text(5), encoding="utf-8",
        )
        (explicit_home / ".twmrc").write_text(
            conflict_text(6), encoding="utf-8",
        )
        explicit_config = root / "explicit-global.twmrc"
        explicit_config.write_text(config_text(), encoding="utf-8")
        explicit = Session(
            root, "explicit", compositor, explicit_home, explicit_config,
        )
        try:
            verify_zero_and_outputs(explicit, check_ignored=True)
            explicit.stop()
        except Exception as error:
            stderr = explicit.abort()
            raise RuntimeError(
                f"explicit screen/output session failed: {error}\n"
                f"compositor stderr:\n{stderr}"
            ) from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test-model", action="store_true")
    parser.add_argument("--compositor", type=Path)
    args = parser.parse_args()
    if args.self_test_model:
        validate_model()
        print("Milestone 8 screen/output mapping model self-test passed")
        return 0
    if args.compositor is None:
        parser.error("--compositor is required")
    if not args.compositor.is_file():
        parser.error(f"missing executable: {args.compositor}")
    run(args.compositor.resolve())
    print("Milestone 8 X screen/Wayland output mapping integration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
