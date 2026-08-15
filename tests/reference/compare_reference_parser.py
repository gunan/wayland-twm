#!/usr/bin/env python3
"""Compare normalized wtwm-config results with the real twm 1.0.13.1 parser."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from validate_parser_fixture_coverage import CoverageError, build_coverage, load_json


MANIFEST_PATH = Path("reference/grammar/manifest.json")
COMMON_FIELDS = {
    "border_width": "border-width",
    "button_indent": "button-indent",
    "frame_padding": "frame-padding",
    "move_delta": "move-delta",
    "no_defaults": "no-defaults",
    "no_grab_server": "no-grab-server",
    "no_icon_managers": "no-icon-managers",
    "title_button_border_width": "title-button-border-width",
    "title_focus": "title-focus",
    "title_padding": "title-padding",
}
REFERENCE_FIELDS = tuple(COMMON_FIELDS)


class ComparisonError(RuntimeError):
    """The executable differential contract or an observation failed."""


def canonical(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def diagnostic_classes(text: str, rejected: bool) -> list[str]:
    lowered = text.lower()
    classes: set[str] = set()
    if rejected:
        classes.add("parse-error")
    if "unknown keyword" in lowered or "unknown directive" in lowered:
        classes.add("unknown-keyword")
    if "unterminated" in lowered or "unexpected end" in lowered:
        classes.add("truncated-input")
    if "ignoring character" in lowered or "invalid character" in lowered:
        classes.add("invalid-character")
    if "bad modifier" in lowered or "invalid modifier" in lowered:
        classes.add("invalid-modifier")
    if "bad button" in lowered or "button number" in lowered:
        classes.add("invalid-button")
    return sorted(classes)


def diagnostic_lines(text: str, fixture: Path) -> list[str]:
    interesting = (
        "error", "unknown", "unterminated", "invalid", "ignoring character",
        "bad modifier", "bad button",
    )
    result: list[str] = []
    for raw_line in text.splitlines():
        if not any(marker in raw_line.lower() for marker in interesting):
            continue
        line = raw_line.replace(str(fixture), "<fixture>")
        line = re.sub(r"/tmp/[^ :\t]+", "<tmp>", line)
        line = re.sub(r"/private/tmp/[^ :\t]+", "<tmp>", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in result:
            result.append(line)
    return result


def parse_scalar(value: str) -> object:
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def normalize_wtwm(
    returncode: int, stdout: str, stderr: str, fixture: Path
) -> dict[str, Any]:
    lines = [
        line.replace(str(fixture), "<fixture>").rstrip()
        for line in stdout.splitlines() if line.strip()
    ]
    fields: dict[str, object] = {}
    for line in lines:
        if line.startswith((" ", "\t")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[a-z][a-z0-9-]*", key):
            fields[key] = parse_scalar(value)
    rejected = returncode != 0
    return {
        "accepted": not rejected,
        "diagnostic_classes": diagnostic_classes(stderr, rejected),
        "diagnostics": diagnostic_lines(stderr, fixture),
        "dump_fields": fields,
        "ordered_dump": lines,
    }


def normalize_reference(
    gdb_text: str,
    parser_text: str,
    fixture: Path,
    grammar_by_line: dict[int, str],
) -> dict[str, Any]:
    effective: dict[str, int] = {}
    parse_error: int | None = None
    for line in gdb_text.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        if fields[:2] == ["parser", "parse_error"]:
            parse_error = int(fields[2])
        elif fields[0] == "effective" and fields[1] in REFERENCE_FIELDS:
            if fields[1] in effective:
                raise ComparisonError(f"duplicate reference field {fields[1]}")
            effective[fields[1]] = int(fields[2])
    if parse_error is None:
        raise ComparisonError("GDB observer did not report ParseError")
    missing = set(REFERENCE_FIELDS) - set(effective)
    if missing:
        raise ComparisonError(
            "GDB observer omitted effective fields: " + ", ".join(sorted(missing))
        )
    reductions = [
        {"rule": int(rule), "source_line": int(line)}
        for rule, line in re.findall(
            r"Reducing stack by rule ([0-9]+) \(line ([0-9]+)\):", parser_text
        )
    ]
    if not reductions:
        raise ComparisonError(
            "reference parser emitted no yydebug reductions; rebuild it with YYDEBUG=1"
        )
    rejected = parse_error != 0
    grammar_trace = [
        grammar_by_line.get(reduction["source_line"], f"gram.y:{reduction['source_line']}")
        for reduction in reductions
    ]
    return {
        "accepted": not rejected,
        "diagnostic_classes": diagnostic_classes(parser_text, rejected),
        "diagnostics": diagnostic_lines(parser_text, fixture),
        "effective_fields": effective,
        "grammar_trace": grammar_trace,
        "reduction_count": len(reductions),
        "reductions": reductions,
    }


def compare_fixture(
    fixture: dict[str, Any], wtwm: dict[str, Any], reference: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_accept = fixture["expected"] == "accept"
    for implementation, result in (("wtwm-config", wtwm), ("reference twm", reference)):
        if result["accepted"] != expected_accept:
            errors.append(
                f"{fixture['id']}: {implementation} accepted={result['accepted']}, "
                f"expected {expected_accept}"
            )
    if wtwm["accepted"] != reference["accepted"]:
        errors.append(f"{fixture['id']}: implementations disagree on acceptance")
    if not expected_accept:
        expected_class = fixture["diagnostic_class"]
        for implementation, result in (("wtwm-config", wtwm), ("reference twm", reference)):
            if expected_class not in result["diagnostic_classes"]:
                errors.append(
                    f"{fixture['id']}: {implementation} lacks normalized "
                    f"diagnostic class {expected_class}"
                )
        return errors

    required = set(COMMON_FIELDS.values())
    available = set(wtwm["dump_fields"]) & required
    if not required.issubset(available):
        errors.append(
            f"{fixture['id']}: wtwm-config dump lacks required reference fields "
            + ", ".join(sorted(required - available))
        )
    inverse = {wtwm_name: reference_name for reference_name, wtwm_name in COMMON_FIELDS.items()}
    comparisons: dict[str, dict[str, object]] = {}
    for wtwm_name in sorted(available):
        reference_name = inverse[wtwm_name]
        wtwm_value = wtwm["dump_fields"][wtwm_name]
        reference_value = reference["effective_fields"][reference_name]
        comparisons[wtwm_name] = {"reference": reference_value, "wtwm": wtwm_value}
        if wtwm_value != reference_value:
            errors.append(
                f"{fixture['id']}: {wtwm_name} is {wtwm_value!r} in wtwm-config "
                f"and {reference_value!r} in reference twm"
            )
    wtwm["common_effective_comparison"] = comparisons
    return errors


def evaluate_grammar_trace_coverage(
    manifest: dict[str, Any],
    inventory: dict[str, Any],
    results: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    policy = manifest["coverage_policy"]
    trace_policy = policy["grammar_trace"]
    grammar_ids = {str(row["id"]) for row in inventory["grammar"]}
    rejected_requirements = {
        str(row_id): str(fixture_id)
        for row_id, fixture_id in trace_policy["rejected_rows"].items()
    }
    required_accepted = grammar_ids - set(rejected_requirements)
    by_fixture = {str(result["fixture_id"]): result for result in results}
    observed_accepted: set[str] = set()
    for result in results:
        if result["expected"] == "accept":
            observed_accepted.update(
                row_id for row_id in result["reference"]["grammar_trace"]
                if row_id in grammar_ids
            )
    missing_accepted = sorted(required_accepted - observed_accepted)
    observed_rejected: dict[str, str] = {}
    missing_rejected: list[str] = []
    for row_id, fixture_id in sorted(rejected_requirements.items()):
        result = by_fixture.get(fixture_id)
        if (
            result is None
            or result["expected"] != "reject"
            or row_id not in result["reference"]["grammar_trace"]
        ):
            missing_rejected.append(row_id)
        else:
            observed_rejected[row_id] = fixture_id
    errors: list[str] = []
    if missing_accepted:
        errors.append(
            "accepted fixture traces omit frozen grammar rows: "
            + ", ".join(missing_accepted)
        )
    if missing_rejected:
        errors.append(
            "rejection fixture traces omit deliberate error rows: "
            + ", ".join(missing_rejected)
        )
    artifact = {
        "required": bool(trace_policy["required"]),
        "source": trace_policy["source"],
        "aggregation": trace_policy["aggregation"],
        "required_accepted_rows": sorted(required_accepted),
        "observed_accepted_rows": sorted(observed_accepted & required_accepted),
        "required_rejected_rows": rejected_requirements,
        "observed_rejected_rows": observed_rejected,
        "missing_accepted_rows": missing_accepted,
        "missing_rejected_rows": missing_rejected,
        "complete": not errors,
    }
    return artifact, errors


def wait_for_x11(display: str, xvfb: subprocess.Popen[bytes], log: Path) -> None:
    for _ in range(50):
        probe = subprocess.run(
            ["xdpyinfo", "-display", display],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            return
        if xvfb.poll() is not None:
            raise ComparisonError(f"Xvfb exited during startup: {log.read_text(errors='replace')}")
        time.sleep(0.1)
    raise ComparisonError(f"Xvfb did not become ready on {display}")


def gdb_commands(display: str, fixture: Path, parser_log: Path) -> str:
    lines = [
        "set pagination off",
        "set confirm off",
        "break ParseTwmrc",
        "commands",
        "silent",
        "set variable yydebug=1",
        "continue",
        "end",
        "break assign_var_savecolor",
        "commands",
        "silent",
        "disable 2",
        'printf "parser\\tparse_error\\t%d\\n", ParseError',
    ]
    for field in REFERENCE_FIELDS:
        expression = {
            "border_width": "Scr->BorderWidth",
            "button_indent": "Scr->ButtonIndent",
            "frame_padding": "Scr->FramePadding",
            "move_delta": "Scr->MoveDelta",
            "no_defaults": "Scr->NoDefaults",
            "no_grab_server": "Scr->NoGrabServer",
            "no_icon_managers": "Scr->NoIconManagers",
            "title_button_border_width": "Scr->TBInfo.border",
            "title_focus": "Scr->TitleFocus",
            "title_padding": "Scr->TitlePadding",
        }[field]
        lines.append(f'printf "effective\\t{field}\\t%d\\n", {expression}')
    lines += [
        "info inferiors",
        "detach",
        "quit",
        "end",
        (
            f"run -display {shlex.quote(display)} -single "
            f"-f {shlex.quote(str(fixture))} "
            f"> {shlex.quote(str(parser_log))} 2>&1"
        ),
    ]
    return "\n".join(lines) + "\n"


def run_reference(
    reference_twm: Path,
    display: str,
    fixture: Path,
    work: Path,
    grammar_by_line: dict[int, str],
) -> dict[str, Any]:
    parser_log = work / "twm.log"
    commands = work / "observe.gdb"
    commands.write_text(gdb_commands(display, fixture, parser_log), encoding="utf-8")
    try:
        result = subprocess.run(
            ["gdb", "--quiet", "--batch", f"--command={commands}", str(reference_twm)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ComparisonError(f"reference observer timed out for {fixture}") from error
    if result.returncode != 0:
        raise ComparisonError(
            f"reference observer failed for {fixture}:\n{result.stdout}"
        )
    process_matches = re.findall(r"process ([0-9]+)", result.stdout)
    if process_matches:
        try:
            os.kill(int(process_matches[-1]), signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        parser_text = parser_log.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ComparisonError(f"reference parser log is missing for {fixture}") from error
    return normalize_reference(result.stdout, parser_text, fixture, grammar_by_line)


def run_wtwm(config_tool: Path, fixture: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [str(config_tool), str(fixture)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ComparisonError(f"wtwm-config timed out for {fixture}") from error
    return normalize_wtwm(result.returncode, result.stdout, result.stderr, fixture)


def validate_executable_contract(source_root: Path) -> dict[str, int]:
    _, counts = build_coverage(source_root)
    sample_wtwm = normalize_wtwm(
        0,
        (
            "border-width=2\nbutton-indent=1\nframe-padding=2\n"
            "move-delta=1\nno-defaults=0\nno-grab-server=0\n"
            "no-icon-managers=0\ntitle-button-border-width=1\n"
            "title-focus=1\ntitle-padding=8\n  ordered item\n"
        ),
        "",
        Path("fixture.twmrc"),
    )
    if sample_wtwm["dump_fields"] != {
        "border-width": 2,
        "button-indent": 1,
        "frame-padding": 2,
        "move-delta": 1,
        "no-defaults": 0,
        "no-grab-server": 0,
        "no-icon-managers": 0,
        "title-button-border-width": 1,
        "title-focus": 1,
        "title-padding": 8,
    }:
        raise ComparisonError("wtwm-config normalization self-test failed")
    reference_values = {
        "border_width": 2,
        "button_indent": 1,
        "frame_padding": 2,
        "move_delta": 1,
        "no_defaults": 0,
        "no_grab_server": 0,
        "no_icon_managers": 0,
        "title_button_border_width": 1,
        "title_focus": 1,
        "title_padding": 8,
    }
    fields = "\n".join(
        ["parser\tparse_error\t0"]
        + [
            f"effective\t{name}\t{reference_values[name]}"
            for name in REFERENCE_FIELDS
        ]
    )
    sample_reference = normalize_reference(
        fields,
        "Reducing stack by rule 1 (line 138):\n",
        Path("fixture.twmrc"),
        {138: "grammar.twmrc.1"},
    )
    if (
        not sample_reference["accepted"]
        or sample_reference["reduction_count"] != 1
        or sample_reference["grammar_trace"] != ["grammar.twmrc.1"]
    ):
        raise ComparisonError("reference normalization self-test failed")
    comparison_errors = compare_fixture(
        {"id": "normalization-self-test", "expected": "accept"},
        sample_wtwm,
        sample_reference,
    )
    if comparison_errors or set(sample_wtwm["common_effective_comparison"]) != set(
        COMMON_FIELDS.values()
    ):
        raise ComparisonError("ten-field effective-state comparison self-test failed")
    rejected = diagnostic_classes("ignoring unknown keyword", True)
    if rejected != ["parse-error", "unknown-keyword"]:
        raise ComparisonError("diagnostic normalization self-test failed")
    trace_manifest = {
        "coverage_policy": {"grammar_trace": {
            "required": True,
            "source": "twm-1.0.13.1-yydebug",
            "aggregation": "union-of-accepted-fixtures",
            "rejected_rows": {"grammar.stmt.1": "reject-error"},
        }}
    }
    trace_inventory = {
        "grammar": [{"id": "grammar.stmt.1"}, {"id": "grammar.stmt.2"}]
    }
    trace_results = [
        {
            "fixture_id": "accept",
            "expected": "accept",
            "reference": {"grammar_trace": ["grammar.stmt.2"]},
        },
        {
            "fixture_id": "reject-error",
            "expected": "reject",
            "reference": {"grammar_trace": ["grammar.stmt.1"]},
        },
    ]
    trace_coverage, trace_errors = evaluate_grammar_trace_coverage(
        trace_manifest, trace_inventory, trace_results
    )
    if trace_errors or not trace_coverage["complete"]:
        raise ComparisonError("grammar trace aggregation self-test failed")
    trace_results[0]["reference"]["grammar_trace"] = []
    trace_coverage, trace_errors = evaluate_grammar_trace_coverage(
        trace_manifest, trace_inventory, trace_results
    )
    if not trace_errors or trace_coverage["complete"]:
        raise ComparisonError("grammar trace omission self-test failed")
    return counts


def full_comparison(args: argparse.Namespace, source_root: Path) -> dict[str, Any]:
    if args.config_tool is None or args.reference_twm is None:
        raise ComparisonError("full comparison requires --config-tool and --reference-twm")
    config_tool = args.config_tool.resolve()
    reference_twm = args.reference_twm.resolve()
    for label, executable in (("wtwm-config", config_tool), ("reference twm", reference_twm)):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ComparisonError(f"{label} is not executable: {executable}")
    for program in ("Xvfb", "xdpyinfo", "gdb"):
        if shutil.which(program) is None:
            raise ComparisonError(f"full comparison requires {program}")
    version = subprocess.run(
        [str(reference_twm), "-V"], capture_output=True, text=True, check=False
    )
    if version.returncode != 0 or version.stdout.strip() != "twm 1.0.13.1":
        raise ComparisonError("reference binary does not report twm 1.0.13.1")

    manifest = load_json(source_root / MANIFEST_PATH)
    inventory = load_json(source_root / manifest["reference"]["inventory"])
    grammar_by_line = {
        int(row["evidence"]["line"]): str(row["id"])
        for row in inventory["grammar"]
    }
    selected = set(args.fixture or [])
    fixtures = [
        fixture for fixture in manifest["fixtures"]
        if not selected or fixture["id"] in selected
    ]
    missing = selected - {fixture["id"] for fixture in fixtures}
    if missing:
        raise ComparisonError("unknown fixture ids: " + ", ".join(sorted(missing)))

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="wtwm-parser-differential-") as temporary:
        work = Path(temporary)
        xvfb_log = work / "xvfb.log"
        with xvfb_log.open("wb") as log_stream:
            xvfb = subprocess.Popen(
                ["Xvfb", args.display, "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
                stdout=log_stream,
                stderr=subprocess.STDOUT,
            )
        try:
            wait_for_x11(args.display, xvfb, xvfb_log)
            for index, fixture in enumerate(fixtures):
                fixture_path = (source_root / fixture["path"]).resolve()
                case_work = work / f"case-{index}"
                case_work.mkdir()
                wtwm = run_wtwm(config_tool, fixture_path)
                reference = run_reference(
                    reference_twm,
                    args.display,
                    fixture_path,
                    case_work,
                    grammar_by_line,
                )
                errors.extend(compare_fixture(fixture, wtwm, reference))
                results.append({
                    "fixture_id": fixture["id"],
                    "path": fixture["path"],
                    "expected": fixture["expected"],
                    "reference": reference,
                    "wtwm": wtwm,
                })
        finally:
            xvfb.terminate()
            try:
                xvfb.wait(timeout=5)
            except subprocess.TimeoutExpired:
                xvfb.kill()
                xvfb.wait(timeout=5)
    trace_coverage, trace_errors = evaluate_grammar_trace_coverage(
        manifest, inventory, results
    )
    errors.extend(trace_errors)
    artifact = {
        "schema_version": 1,
        "reference": "twm 1.0.13.1",
        "normalization": {
            "acceptance": "reference ParseError compared with wtwm-config exit status",
            "diagnostics": "implementation text reduced to stable semantic classes",
            "effective_state": "all ten normalized GDB-observed ScreenInfo fields compared with required wtwm-config dump fields (title-focus is the NoTitleFocus inverse)",
            "grammar_order": "ordered upstream yydebug reductions mapped to frozen grammar IDs (mid-rule semantic actions retain gram.y line IDs)",
            "wtwm_output": "ordered non-empty wtwm-config dump lines plus scalar field map",
        },
        "fixtures": results,
        "grammar_trace_coverage": trace_coverage,
        "comparison_errors": errors,
    }
    return artifact


def wtwm_only(args: argparse.Namespace, source_root: Path) -> dict[str, Any]:
    if args.config_tool is None:
        raise ComparisonError("--wtwm-only requires --config-tool")
    config_tool = args.config_tool.resolve()
    if not config_tool.is_file() or not os.access(config_tool, os.X_OK):
        raise ComparisonError(f"wtwm-config is not executable: {config_tool}")
    manifest = load_json(source_root / MANIFEST_PATH)
    selected = set(args.fixture or [])
    fixtures = [
        fixture for fixture in manifest["fixtures"]
        if not selected or fixture["id"] in selected
    ]
    missing = selected - {fixture["id"] for fixture in fixtures}
    if missing:
        raise ComparisonError("unknown fixture ids: " + ", ".join(sorted(missing)))
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        result = run_wtwm(config_tool, (source_root / fixture["path"]).resolve())
        expected_accept = fixture["expected"] == "accept"
        if result["accepted"] != expected_accept:
            errors.append(
                f"{fixture['id']}: wtwm-config accepted={result['accepted']}, "
                f"expected {expected_accept}"
            )
        if not expected_accept and fixture["diagnostic_class"] not in result["diagnostic_classes"]:
            errors.append(
                f"{fixture['id']}: wtwm-config lacks normalized diagnostic "
                f"class {fixture['diagnostic_class']}"
            )
        results.append({
            "fixture_id": fixture["id"],
            "path": fixture["path"],
            "expected": fixture["expected"],
            "wtwm": result,
        })
    return {
        "schema_version": 1,
        "mode": "wtwm-only",
        "fixtures": results,
        "comparison_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--config-tool", type=Path)
    parser.add_argument("--reference-twm", type=Path)
    parser.add_argument("--display", default=":119")
    parser.add_argument("--fixture", action="append")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--wtwm-only", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        counts = validate_executable_contract(source_root)
        if args.validate_only and args.wtwm_only:
            raise ComparisonError("--validate-only and --wtwm-only are mutually exclusive")
        if args.validate_only:
            print(
                "reference parser comparison contract valid: "
                f"{counts['rows']} mapped inventory rows"
            )
            return 0
        artifact = (
            wtwm_only(args, source_root) if args.wtwm_only
            else full_comparison(args, source_root)
        )
    except (CoverageError, ComparisonError, OSError, ValueError) as error:
        print(f"reference parser comparison error: {error}", file=sys.stderr)
        return 1
    output = canonical(artifact)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    if artifact["comparison_errors"]:
        for error in artifact["comparison_errors"]:
            print(f"parser difference: {error}", file=sys.stderr)
        return 1
    print(
        f"parser comparison passed: {len(artifact['fixtures'])} fixtures",
        file=sys.stderr if not args.output else sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
