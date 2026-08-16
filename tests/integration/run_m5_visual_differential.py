#!/usr/bin/env python3
"""Compare wtwm's canonical decorations byte-for-byte with frozen twm pixels."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
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


REFERENCE_COLORS = {
    "root": (48, 48, 48),
    "border": (16, 16, 16),
    "title": (32, 64, 96),
    "title_text": (255, 255, 255),
    "alpha_client": (40, 96, 144),
    "alpha_accent": (120, 200, 255),
    "bravo_client": (144, 72, 40),
    "bravo_accent": (255, 192, 120),
}
STRUCTURAL_COLORS = {
    REFERENCE_COLORS[name] for name in (
        "root", "border", "title", "alpha_client", "bravo_client"
    )
}


def wait_display(control: Control, marker: Path) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            display = marker.read_text(encoding="utf-8").strip()
            if display.startswith(":"):
                return display
        control.state()
    raise RuntimeError("startup command did not publish Xwayland DISPLAY")


def wait_line(client: subprocess.Popen[str], expected: str) -> str:
    assert client.stdout is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [client.stdout], [], [], deadline - time.monotonic()
        )
        if not readable:
            break
        line = client.stdout.readline().rstrip("\n")
        if line == expected or line.startswith(expected + " "):
            return line
        if client.poll() is not None:
            break
        raise RuntimeError(f"unexpected visual client event: {line!r}")
    raise RuntimeError(f"timed out waiting for visual client event {expected!r}")


def client_command(client: subprocess.Popen[str], command: str, expected: str) -> str:
    assert client.stdin is not None
    client.stdin.write(command + "\n")
    client.stdin.flush()
    return wait_line(client, expected)


def wait_windows(control: Control) -> dict[str, object]:
    deadline = time.monotonic() + 10
    wanted = {"Reference Alpha", "Reference Bravo"}
    while time.monotonic() < deadline:
        state = control.state()
        mapped = {
            item["title"] for item in state["windows"] if item["mapped"]
        }
        if wanted.issubset(mapped):
            return state
        time.sleep(0.01)
    raise RuntimeError(f"canonical visual windows did not map: {control.state()!r}")


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    fields = data.split(b"\n", 3)
    if len(fields) != 4 or fields[0] != b"P6" or fields[2] != b"255":
        raise RuntimeError("capture is not an un-commented 8-bit PPM P6 image")
    width, height = (int(value) for value in fields[1].split())
    pixels = fields[3]
    if len(pixels) != width * height * 3:
        raise RuntimeError("capture pixel payload length is invalid")
    return width, height, pixels


def pixels(payload: bytes) -> list[tuple[int, int, int]]:
    return [tuple(payload[index:index + 3]) for index in range(0, len(payload), 3)]


def comparison(reference: bytes, actual: bytes) -> dict[str, object]:
    ref_width, ref_height, ref_payload = parse_ppm(reference)
    width, height, payload = parse_ppm(actual)
    if (width, height) != (ref_width, ref_height):
        return {
            "reference_size": [ref_width, ref_height],
            "actual_size": [width, height],
            "size_match": False,
            "mismatch_pixels": None,
        }
    expected = pixels(ref_payload)
    observed = pixels(payload)
    mismatch = sum(left != right for left, right in zip(expected, observed))
    structural = sum(
        (left in STRUCTURAL_COLORS) != (right in STRUCTURAL_COLORS)
        for left, right in zip(expected, observed)
    )
    white = REFERENCE_COLORS["title_text"]
    font = sum((left == white) != (right == white)
               for left, right in zip(expected, observed))
    reference_histogram = Counter(expected)
    actual_histogram = Counter(observed)
    expected_palette = {
        name: reference_histogram[color] for name, color in REFERENCE_COLORS.items()
    }
    actual_palette = {
        name: actual_histogram[color] for name, color in REFERENCE_COLORS.items()
    }
    return {
        "reference_size": [ref_width, ref_height],
        "actual_size": [width, height],
        "size_match": True,
        "mismatch_pixels": mismatch,
        "geometry_mask_mismatch_pixels": structural,
        "font_mask_mismatch_pixels": font,
        "configured_color_pixel_counts": {
            "reference": expected_palette,
            "actual": actual_palette,
            "match": expected_palette == actual_palette,
        },
        "reference_sha256": hashlib.sha256(reference).hexdigest(),
        "actual_sha256": hashlib.sha256(actual).hexdigest(),
    }


def diff_ppm(reference: bytes, actual: bytes) -> bytes:
    ref_width, ref_height, ref_payload = parse_ppm(reference)
    width, height, payload = parse_ppm(actual)
    if (width, height) != (ref_width, ref_height):
        return actual
    result = bytearray(len(payload))
    for offset in range(0, len(payload), 3):
        if payload[offset:offset + 3] == ref_payload[offset:offset + 3]:
            result[offset:offset + 3] = b"\x00\x00\x00"
        else:
            result[offset:offset + 3] = b"\xff\x00\xff"
    return f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(result)


def capture_stable(control: Control, first: Path, second: Path) -> bytes:
    control.command("WAIT 3")
    control.command(f"CAPTURE {first}")
    control.command("WAIT 3")
    control.command(f"CAPTURE {second}")
    first_data = first.read_bytes()
    second_data = second.read_bytes()
    if first_data != second_data:
        raise RuntimeError(f"consecutive compositor captures differ: {first.name}")
    return first_data


def run(arguments: argparse.Namespace) -> None:
    arguments.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wtwm-m5-visual-") as directory:
        temporary = Path(directory)
        runtime = temporary / "runtime"
        runtime.mkdir(mode=0o700)
        control_path = temporary / "control.sock"
        display_marker = temporary / "display"
        socket_name = f"wtwm-m5-visual-{os.getpid()}"
        startup = f'printf "%s\\n" "$DISPLAY" > {shlex.quote(str(display_marker))}'
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C",
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_RENDERER": "pixman",
        })
        compositor = subprocess.Popen(
            [
                str(arguments.compositor), "-f", str(arguments.config),
                "-s", startup, "--test-control", str(control_path),
                "--test-socket", socket_name, "--test-backend", "headless",
            ],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        control: Control | None = None
        client: subprocess.Popen[str] | None = None
        results: dict[str, object] = {"schema_version": 1, "phases": {}}
        try:
            control = Control(control_path, compositor)
            control.command("SET ANIMATION_MS 0")
            control.command("SET PLACEMENT_SEED 0")
            control.command("OUTPUT 260 180")
            display = wait_display(control, display_marker)
            client_environment = environment.copy()
            client_environment["DISPLAY"] = display
            client = subprocess.Popen(
                [str(arguments.client)],
                env=client_environment,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            wait_line(client, "READY")
            wait_windows(control)
            failures: list[str] = []
            for phase in ("bravo", "alpha"):
                client_command(client, f"PHASE {phase}", f"PHASE {phase}")
                wait_windows(control)
                first = arguments.evidence / f"phase-{phase}.actual.ppm"
                second = temporary / f"phase-{phase}.repeat.ppm"
                actual = capture_stable(control, first, second)
                reference = gzip.decompress(
                    (arguments.baseline / f"phase-{phase}.ppm.gz").read_bytes()
                )
                (arguments.evidence / f"phase-{phase}.reference.ppm").write_bytes(
                    reference
                )
                (arguments.evidence / f"phase-{phase}.diff.ppm").write_bytes(
                    diff_ppm(reference, actual)
                )
                phase_result = comparison(reference, actual)
                results["phases"][phase] = phase_result
                if phase_result.get("mismatch_pixels") != 0:
                    failures.append(
                        f"{phase}: {phase_result.get('mismatch_pixels')} mismatched pixels"
                    )
            results["exact"] = not failures
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if failures:
                raise RuntimeError("; ".join(failures))
            client_command(client, "QUIT", "QUITTING")
            client.wait(timeout=5)
            client = None
            control.command("QUIT")
            compositor.wait(timeout=5)
            if compositor.returncode != 0:
                raise RuntimeError(f"compositor exited with {compositor.returncode}")
        except Exception as error:
            if compositor.poll() is None:
                compositor.terminate()
            try:
                stdout, stderr = compositor.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                compositor.kill()
                stdout, stderr = compositor.communicate()
            (arguments.evidence / "session.log").write_text(
                f"error: {error}\nstdout:\n{stdout}\nstderr:\n{stderr}\n",
                encoding="utf-8",
            )
            raise
        finally:
            if client is not None and client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
            if control is not None:
                control.close()
            if compositor.poll() is None:
                compositor.terminate()
                compositor.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.compositor = arguments.compositor.resolve(strict=True)
    arguments.client = arguments.client.resolve(strict=True)
    arguments.config = arguments.config.resolve(strict=True)
    arguments.baseline = arguments.baseline.resolve(strict=True)
    run(arguments)


if __name__ == "__main__":
    main()
