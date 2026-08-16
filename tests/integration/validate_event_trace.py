#!/usr/bin/env python3
"""Validate the deterministic compositor event-trace protocol and wiring."""

from __future__ import annotations

import argparse
from pathlib import Path


EVENT_MINIMUMS = {
    '"map", "client"': 2,
    '"unmap", "client"': 1,
    '"focus", "client"': 1,
    '"unfocus", "client"': 2,
    '"configure", "client"': 4,
    '"move", "frame"': 1,
    '"resize", "frame"': 1,
    '"raise", "frame"': 2,
    '"lower", "frame"': 1,
    '"restack", "frame"': 2,
    '"title", "title"': 1,
    '"icon_name", "icon"': 1,
    '"destroy", "client"': 3,
}

SCHEMA_FRAGMENTS = (
    '"OK TRACE {\\"version\\":1,\\"first_seq\\":%" PRIu64',
    '\\"next_seq\\":%" PRIu64',
    '\\"dropped\\":%" PRIu64',
    '\\"window\\":{\\"id\\":%" PRIu64',
    '\\"geometry\\":{\\"client\\":{\\"x\\":%d,\\"y\\":%d,',
    '\\"frame\\":{\\"x\\":%d,\\"y\\":%d,',
    '\\"outer_width\\":%d,',
    '\\"border_width\\":%d,',
    '\\"title_bar_height\\":%d,\\"title_height\\":%d,',
    '\\"content_x\\":%d,\\"content_y\\":%d}},',
    '\\"state\\":{\\"mapped\\":%s,\\"iconified\\":%s,\\"focused\\":%s,',
    '\\"stack\\":',
)


def validate_protocol(header: str, parser: str, protocol_test: str) -> None:
    for fragment in (
        "WTWM_TEST_COMMAND_TRACE",
        'strcmp(verb, "TRACE") == 0',
        'strcmp(option, "CLEAR") == 0',
        '"usage: TRACE [CLEAR]"',
    ):
        if fragment not in header + parser:
            raise ValueError(f"test-control TRACE protocol lacks {fragment!r}")
    for fragment in (
        'parse("TRACE")',
        'parse("TRACE CLEAR")',
        'reject("TRACE RESET")',
        'reject("TRACE CLEAR now")',
    ):
        if fragment not in protocol_test:
            raise ValueError(f"TRACE parser regression coverage lacks {fragment!r}")


def validate_source(source: str) -> None:
    for fragment, minimum in EVENT_MINIMUMS.items():
        if source.count(fragment) < minimum:
            raise ValueError(
                f"event trace lacks {fragment!r}: expected at least {minimum} wiring points"
            )
    for event in ("pointer", "button", "key"):
        fragment = f'test_trace_input_snapshot(server, "{event}")'
        if source.count(fragment) != 1:
            raise ValueError(f"synthetic {event} lacks one post-dispatch trace snapshot")
    for fragment in SCHEMA_FRAGMENTS:
        if fragment not in source:
            raise ValueError(f"event trace JSON schema lacks {fragment!r}")
    for fragment in (
        "TEST_TRACE_MAX_EVENTS = 4096",
        "char test_title[TEST_TRACE_IDENTITY_MAX]",
        "static void test_trace_snapshot_identity(struct toplevel *toplevel)",
        'if (strcmp(event, "destroy") != 0) test_trace_snapshot_identity(toplevel);',
        "test_trace_copy(trace->title, toplevel->test_title);",
        "++control->trace_dropped",
        "toplevel->test_id = ++toplevel->server->test_control.trace_next_window_id",
        "control->trace_event_count = 0",
        "control->trace_next_sequence = 0",
        "control->trace_dropped = 0",
        "free(control->trace_events)",
        'test_write(control, "OK TRACE CLEAR\\n")',
    ):
        if fragment not in source:
            raise ValueError(f"event trace lifecycle contract lacks {fragment!r}")
    append_start = source.find("static struct test_trace_event *test_trace_append")
    append_end = source.find("#else", append_start)
    writer_start = source.find("static void test_write_trace")
    writer_end = source.find("static void test_write_state", writer_start)
    if min(append_start, append_end, writer_start, writer_end) < 0:
        raise ValueError("event trace implementation boundaries are missing")
    deterministic = source[append_start:append_end] + source[writer_start:writer_end]
    for forbidden in ("%p", "time_msec", "timestamp", '"xid"'):
        if forbidden in deterministic:
            raise ValueError(f"event trace exposes nondeterministic field {forbidden!r}")


def validate_runner(runner: str) -> None:
    for fragment in (
        'self.command("TRACE")',
        'control.command("TRACE CLEAR")',
        '"version": 1, "first_seq": 1, "next_seq": 0,',
        'required = {',
        '"pointer", "button", "key",',
        'client["x"] != frame["x"] + frame["content_x"]',
        'frame["outer_height"] != frame["height"] + 2 * frame["border_width"]',
        'if "unmap" not in final_kinds or "destroy" not in final_kinds:',
    ):
        if fragment not in runner:
            raise ValueError(f"headless trace integration lacks {fragment!r}")


def validate_documentation(readme: str) -> None:
    for fragment in (
        "`TRACE` returns",
        "`TRACE CLEAR` resets",
        "creation-order window ID",
        "border/title extents",
        "pointer, button, and key",
        "last pre-destroy identity snapshot",
        "4096",
        "`dropped`",
    ):
        if fragment not in readme:
            raise ValueError(f"event trace documentation lacks {fragment!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    root = arguments.source_root
    header = (root / "src/test_control.h").read_text(encoding="utf-8")
    protocol = (root / "src/test_control.c").read_text(encoding="utf-8")
    protocol_test = (
        root / "tests/integration/test_control_protocol_test.c"
    ).read_text(encoding="utf-8")
    source = (root / "src/wtwm.c").read_text(encoding="utf-8")
    runner = (root / "tests/integration/run_compositor.py").read_text(encoding="utf-8")
    readme = (root / "tests/integration/README.md").read_text(encoding="utf-8")
    validate_protocol(header, protocol, protocol_test)
    validate_source(source)
    validate_runner(runner)
    validate_documentation(readme)
    if arguments.self_test_tamper:
        tampered_source = source.replace(
            'test_trace_toplevel_event(toplevel, "lower", "frame");', "", 1
        )
        try:
            validate_source(tampered_source)
        except ValueError:
            pass
        else:
            raise ValueError("event trace contract accepted missing lower event")
        tampered_clear = source.replace("control->trace_next_sequence = 0;", "", 1)
        try:
            validate_source(tampered_clear)
        except ValueError:
            pass
        else:
            raise ValueError("event trace contract accepted nondeterministic clear")
        tampered_identity = source.replace(
            'if (strcmp(event, "destroy") != 0) test_trace_snapshot_identity(toplevel);',
            "test_trace_snapshot_identity(toplevel);",
            1,
        )
        try:
            validate_source(tampered_identity)
        except ValueError:
            pass
        else:
            raise ValueError("event trace contract accepted destroy-time identity loss")
        tampered_runner = runner.replace('"pointer", "button", "key",', '"button", "key",', 1)
        try:
            validate_runner(tampered_runner)
        except ValueError:
            pass
        else:
            raise ValueError("event trace contract accepted a missing pointer snapshot")
        tampered_protocol = protocol.replace('strcmp(verb, "TRACE") == 0', "false", 1)
        try:
            validate_protocol(header, tampered_protocol, protocol_test)
        except ValueError:
            pass
        else:
            raise ValueError("event trace contract accepted missing TRACE parsing")
        print("event trace source, reset, input-snapshot, and parser tampers rejected")
    print("deterministic event trace contract valid")


if __name__ == "__main__":
    main()
