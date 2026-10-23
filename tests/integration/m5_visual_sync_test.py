#!/usr/bin/env python3
"""Exercise delayed Xwayland paint without weakening the exact pixel check."""

from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_m5_visual_differential as visual


ROOT = Path(__file__).resolve().parents[2]
PAINTED = gzip.decompress((ROOT / (
    "reference/captures/twm-1.0.13.1/baseline/phase-bravo.ppm.gz"
)).read_bytes())


def unpainted() -> bytes:
    width, height, payload = visual.parse_ppm(PAINTED)
    result = bytearray(payload)
    for offset in range(0, len(result), 3):
        for role in ("alpha", "bravo"):
            if result[offset:offset + 3] == bytes(visual.REFERENCE_COLORS[role + "_accent"]):
                result[offset:offset + 3] = bytes(visual.REFERENCE_COLORS[role + "_client"])
    return f"P6\n{width} {height}\n255\n".encode() + result


class Control:
    def __init__(self, captures: list[bytes], delayed_state: bool = False,
                 phase: str = "bravo"):
        self.captures = iter(captures)
        self.last = captures[-1]
        self.captured = 0
        self.states = 0
        self.delayed_state = delayed_state
        self.phase = phase

    def state(self):
        self.states += 1
        ready = not self.delayed_state or self.states > 2
        alpha_on_top = (self.phase == "alpha") == ready
        return {
            # The client sets X input focus, not wtwm's focus-root/active state.
            "active": "Reference Bravo",
            "focus": None,
            "windows": [
                {"title": "Reference Alpha", "mapped": True, "stack": 0 if alpha_on_top else 1,
                 "x": 30, "y": 28, "content_x": 3, "content_y": 23},
                {"title": "Reference Bravo", "mapped": True, "stack": 1 if alpha_on_top else 0,
                 "x": 88, "y": 58, "content_x": 3, "content_y": 23},
            ],
        }

    def command(self, command: str):
        if command.startswith("CAPTURE "):
            self.captured += 1
            Path(command.removeprefix("CAPTURE ")).write_bytes(
                next(self.captures, self.last)
            )
        elif command != "WAIT 3":
            raise AssertionError(command)
        return "OK"


class VisualSyncTests(unittest.TestCase):
    def test_identical_unpainted_frames_do_not_count_as_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.ppm", Path(directory) / "second.ppm"
            control = Control([unpainted(), unpainted(), PAINTED, PAINTED, PAINTED])
            actual = visual.capture_stable(control, first, second, "bravo")
            self.assertEqual(actual, PAINTED)
            self.assertEqual(control.captured, 5)
            self.assertEqual(visual.comparison(PAINTED, actual)["mismatch_pixels"], 0)

    def test_phase_stacking_must_arrive(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Control([PAINTED], delayed_state=True)
            visual.wait_phase_ready(control, "bravo", Path(directory) / "ready.ppm")
            self.assertGreaterEqual(control.states, 3)

    def test_paint_probes_are_visible_with_alpha_on_top(self):
        alpha = gzip.decompress((ROOT / (
            "reference/captures/twm-1.0.13.1/baseline/phase-alpha.ppm.gz"
        )).read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            visual.wait_phase_ready(
                Control([alpha], phase="alpha"), "alpha", Path(directory) / "ready.ppm"
            )

    def test_missing_paint_times_out_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "ready.ppm"
            # Advance a virtual clock so loaded CI hosts cannot exhaust the
            # test deadline before the first diagnostic capture is written.
            with patch.object(visual.time, "monotonic", side_effect=[0, 0, 1]), \
                    patch.object(visual.time, "sleep"), \
                    self.assertRaisesRegex(RuntimeError, "timed out.*paint"):
                visual.wait_phase_ready(Control([unpainted()]), "bravo", ready, timeout=1)
            self.assertEqual(ready.read_bytes(), unpainted())

    def test_stable_rendering_regression_is_still_compared_exactly(self):
        wrong = PAINTED[:-3] + b"\xff\x00\xff"
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.ppm", Path(directory) / "second.ppm"
            actual = visual.capture_stable(Control([wrong]), first, second, "bravo")
            self.assertEqual(visual.comparison(PAINTED, actual)["mismatch_pixels"], 1)

    def test_instability_after_ready_fails_and_preserves_both_captures(self):
        changed = PAINTED[:-3] + b"\xff\x00\xff"
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.ppm", Path(directory) / "second.ppm"
            with self.assertRaisesRegex(RuntimeError, "consecutive compositor captures differ"):
                visual.capture_stable(Control([PAINTED, PAINTED, changed]), first, second, "bravo")
            self.assertEqual(first.read_bytes(), PAINTED)
            self.assertEqual(second.read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
