#!/usr/bin/env python3
"""Check causal X11 input delivery before hotplug counter snapshots."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from run_client_stress import ClientChannel
from run_m8_input_hotplug import x11_key_report


TOKEN = "x-key"
PRESS = f"EVENT KEY {TOKEN} x11-a 30 press"
RELEASE = f"EVENT KEY {TOKEN} x11-a 30 release"
REPORT = f"OK REPORT {TOKEN} x11-a=2 x11-b=0 focus=x11-a"


class DelayedX11Channel(ClientChannel):
    """Deliver pending input on reads, or an early counter snapshot on REPORT.

    Xwayland can service an X11 roundtrip before reading its Wayland input.
    This schedule keeps both events pending until the runner reads them, so
    an immediate REPORT deterministically observes zero without using sleeps.
    """

    def __init__(self, events: list[str], report: str = REPORT) -> None:
        self.label = "delayed X11 fixture"
        self.stdin = self
        self.lines = events.copy()
        self.delivered: list[str] = []
        self.commands: list[bytes] = []
        self.report = report
        self.deadlines: list[float] = []

    def write(self, command: bytes) -> None:
        self.commands.append(command)
        if PRESS not in self.delivered or RELEASE not in self.delivered:
            self.lines.insert(
                0, f"OK REPORT {TOKEN} x11-a=0 x11-b=0 focus=x11-a"
            )
        else:
            self.lines.append(self.report)

    def flush(self) -> None:
        pass

    def line(self, deadline: float) -> str:
        self.deadlines.append(deadline)
        if not self.lines:
            raise RuntimeError("timed out waiting for delayed X11 fixture output")
        line = self.lines.pop(0)
        self.delivered.append(line)
        return line


class X11KeyReportTests(unittest.TestCase):
    def test_delayed_pair_precedes_report(self) -> None:
        channel = DelayedX11Channel([PRESS, RELEASE])
        with patch("run_m8_input_hotplug.time.monotonic", return_value=42):
            x11_key_report(channel, TOKEN)
        self.assertEqual(channel.commands, [b"REPORT x-key\n"])
        self.assertEqual(channel.delivered, [PRESS, RELEASE, REPORT])
        self.assertEqual(set(channel.deadlines), {52})

    def test_focus_notifications_do_not_replace_key_delivery(self) -> None:
        channel = DelayedX11Channel([
            f"EVENT LEAVE {TOKEN} x11-b",
            f"EVENT ENTER {TOKEN} x11-a",
            PRESS,
            RELEASE,
        ])
        x11_key_report(channel, TOKEN)
        self.assertEqual(channel.commands, [b"REPORT x-key\n"])

    def test_rejects_bad_pair_before_report(self) -> None:
        cases = [
            [f"EVENT KEY {TOKEN} x11-b 30 press", RELEASE],
            [f"EVENT KEY {TOKEN} x11-a 31 press", RELEASE],
            ["EVENT KEY other x11-a 30 press", RELEASE],
            [PRESS, PRESS, RELEASE],
            [RELEASE, PRESS],
            [PRESS, f"EVENT ENTER other x11-a", RELEASE],
            [PRESS, "OK unexpected", RELEASE],
            [PRESS],
            [],
        ]
        for events in cases:
            with self.subTest(events=events):
                channel = DelayedX11Channel(events)
                with self.assertRaises(RuntimeError):
                    x11_key_report(channel, TOKEN)
                self.assertEqual(channel.commands, [])

    def test_rejects_extra_keys_before_report_reply(self) -> None:
        for extra in [PRESS, RELEASE, f"EVENT KEY {TOKEN} x11-b 30 press"]:
            with self.subTest(extra=extra):
                channel = DelayedX11Channel([PRESS, RELEASE, extra])
                with self.assertRaises(RuntimeError):
                    x11_key_report(channel, TOKEN)

    def test_report_counts_and_focus_remain_exact(self) -> None:
        for report in [
            f"OK REPORT {TOKEN} x11-a=0 x11-b=0 focus=x11-a",
            f"OK REPORT {TOKEN} x11-a=3 x11-b=0 focus=x11-a",
            f"OK REPORT {TOKEN} x11-a=2 x11-b=1 focus=x11-a",
            f"OK REPORT {TOKEN} x11-a=2 x11-b=0 focus=x11-b",
            "OK REPORT other x11-a=2 x11-b=0 focus=x11-a",
        ]:
            with self.subTest(report=report):
                with self.assertRaises(RuntimeError):
                    x11_key_report(DelayedX11Channel([PRESS, RELEASE], report), TOKEN)


if __name__ == "__main__":
    unittest.main()
