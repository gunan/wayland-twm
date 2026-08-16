#!/usr/bin/env python3
"""Keep synthetic test-control input aligned with advertised seat resources."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


CAPABILITY_CALL = re.compile(
    r"new_keyboard\(&server, &server\.test_control\.keyboard\.base\);\s*"
    r"(?:/\*.*?\*/\s*)?"
    r"wlr_seat_set_capabilities\(server\.seat,\s*"
    r"WL_SEAT_CAPABILITY_KEYBOARD\s*\|\s*WL_SEAT_CAPABILITY_POINTER\);",
    re.DOTALL,
)


def validate(source: str) -> None:
    anchor = source.find("static const struct wlr_keyboard_impl test_keyboard_impl")
    if anchor < 0:
        raise ValueError("synthetic test keyboard setup is missing")
    branch_start = source.rfind("#ifdef WTWM_TEST_CONTROL", 0, anchor)
    branch_end = source.find("#else", anchor)
    if branch_start < 0 or branch_end < 0:
        raise ValueError("synthetic input setup escaped the test-control branch")
    branch = source[branch_start:branch_end]
    if CAPABILITY_CALL.search(branch) is None:
        raise ValueError(
            "test control must advertise POINTER|KEYBOARD after installing "
            "its synthetic keyboard"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    arguments = parser.parse_args()
    source = (arguments.source_root / "src/wtwm.c").read_text(encoding="utf-8")
    validate(source)
    if arguments.self_test_tamper:
        tampered = source.replace(
            "WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_POINTER",
            "WL_SEAT_CAPABILITY_KEYBOARD",
            1,
        )
        try:
            validate(tampered)
        except ValueError:
            pass
        else:
            raise ValueError("synthetic seat contract accepted missing POINTER")
        print("synthetic seat tamper rejected")
    print("test control synthetic seat contract valid")


if __name__ == "__main__":
    main()
