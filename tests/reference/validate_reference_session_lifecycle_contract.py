#!/usr/bin/env python3
"""Validate the frozen twm session lifecycle and wtwm translation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(
    "reference/lifecycle/twm-1.0.13.1/session-lifecycle-contract.json"
)
INVENTORY_PATH = Path("reference/inventory/twm-1.0.13.1.json")
UPSTREAM = {
    "name": "X.Org twm",
    "version": "1.0.13.1",
    "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
    "sha256": "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5",
    "inventory": "reference/inventory/twm-1.0.13.1.json",
}
SOURCE_MEMBERS = {
    "twm-1.0.13.1/man/twm.man":
        "a1743a47770bd63a2ff5e63b8c6e86d72ee02ddd126813951833fb33b8a56674",
    "twm-1.0.13.1/src/menus.c":
        "f8192e767d40207e931a180415c97689f107fb1e330416f8d68bca9a68919a83",
    "twm-1.0.13.1/src/parse.c":
        "d36e01520616b98a02a399462f5aef62e16147288c7818d99eb22ca85cd02b7c",
    "twm-1.0.13.1/src/session.c":
        "0dbc830242b74e8194e86a8a1600cd185c15e603f444ba4ca695e107ae3008a4",
    "twm-1.0.13.1/src/twm.c":
        "6a8c95df4df186a970e56ed7da4013f6305823c4a9b99cbebfe08f076f01ab3d",
}
EVIDENCE = {
    "manual.foreground-owner": ("twm-1.0.13.1/man/twm.man", 73,
        "as the last client."),
    "manual.exit-logs-out": ("twm-1.0.13.1/man/twm.man", 74,
        "When run this way, exiting \\fItwm\\fP causes the"),
    "manual.client-id": ("twm-1.0.13.1/man/twm.man", 128,
        ".B \\-clientId \\fIID\\fP"),
    "manual.restore": ("twm-1.0.13.1/man/twm.man", 151,
        ".B \\-restore \\fIfilename\\fP"),
    "manual.quit": ("twm-1.0.13.1/man/twm.man", 1357,
        "This function causes \\fItwm\\fP to restore the window's borders and exit."),
    "parse.quit": ("twm-1.0.13.1/src/parse.c", 456,
        '    { "f.quit",                 FKEYWORD, F_QUIT },'),
    "menu.quit": ("twm-1.0.13.1/src/menus.c", 2173, "    case F_QUIT:"),
    "menu.quit-done": ("twm-1.0.13.1/src/menus.c", 2174,
        "        Done(NULL, NULL);"),
    "startup.sigint": ("twm-1.0.13.1/src/twm.c", 285,
        "    newhandler(SIGINT);"),
    "startup.sighup": ("twm-1.0.13.1/src/twm.c", 286,
        "    newhandler(SIGHUP);"),
    "startup.sigquit": ("twm-1.0.13.1/src/twm.c", 287,
        "    newhandler(SIGQUIT);"),
    "startup.sigterm": ("twm-1.0.13.1/src/twm.c", 288,
        "    newhandler(SIGTERM);"),
    "startup.signal-dispatch": ("twm-1.0.13.1/src/twm.c", 317,
        "    si = XtAppAddSignal(appContext, Done, NULL);"),
    "startup.restore-read": ("twm-1.0.13.1/src/twm.c", 329,
        "        ReadWinConfigFile(restore_filename);"),
    "startup.session-connect": ("twm-1.0.13.1/src/twm.c", 643,
        "    (void) ConnectToSessionManager(client_id, appContext);"),
    "exit.reborder": ("twm-1.0.13.1/src/twm.c", 925,
        "        Reborder(CurrentTime);"),
    "exit.session-destroy": ("twm-1.0.13.1/src/twm.c", 930,
        "    DestroySession();"),
    "exit.success": ("twm-1.0.13.1/src/twm.c", 931,
        "    exit(EXIT_SUCCESS);"),
    "xsm.restart-style": ("twm-1.0.13.1/src/session.c", 711,
        "        hint[0] = SmRestartIfRunning;"),
    "xsm.save-directory": ("twm-1.0.13.1/src/session.c", 725,
        '    path = getenv("SM_SAVE_DIR");'),
    "xsm.restart-command": ("twm-1.0.13.1/src/session.c", 775,
        "    props[3]->name = strdup(SmRestartCommand);"),
    "xsm.discard-command": ("twm-1.0.13.1/src/session.c", 814,
        "    props[4]->name = strdup(SmDiscardCommand);"),
    "xsm.save-result": ("twm-1.0.13.1/src/session.c", 824,
        "    SmcSaveYourselfDone(smcConn2, success);"),
    "xsm.die": ("twm-1.0.13.1/src/session.c", 854,
        "    Done(NULL, NULL);"),
    "xsm.cancelled": ("twm-1.0.13.1/src/session.c", 867,
        "        SmcSaveYourselfDone(smcConn2, False);"),
}
REQUIREMENTS = {
    "session.foreground-owner",
    "session.startup-order",
    "session.startup-failure",
    "session.quit-orderly",
    "session.signal-orderly",
    "session.startup-child-isolation",
    "session.no-automatic-restart",
    "session.explicit-state",
    "session.state-load-failure",
    "session.xsm-boundary",
}
SCENARIOS = {
    "invalid-command-line",
    "invalid-configuration",
    "runtime-initialization-failure",
    "startup-command-environment",
    "startup-command-failure",
    "f-quit-mixed-clients",
    "signal-int",
    "signal-hup",
    "signal-quit",
    "signal-term",
    "launcher-forward-and-reap",
    "launcher-failed-child",
    "missing-state",
    "malformed-state",
    "failed-explicit-save",
    "logout-without-save",
    "failure-then-new-login",
}
CURRENT_MARKERS = {
    "data/wtwm.desktop": ["Exec=wtwm-session"],
    "scripts/platform/wtwm-session": [
        "trap forward_signal HUP INT QUIT TERM",
        "wait_for_child",
        "last_wait_status=127",
        "final_wait_status",
        'printf \'wtwm-session: compositor exit=%s',
    ],
    "src/wtwm.c": [
        "static int session_signal",
        "wl_event_loop_add_signal",
        "finish_session_signals(&server);",
        "case WTWM_ACTION_QUIT: wl_display_terminate(server->display); break;",
        "if (startup != NULL) spawn_command(startup);",
        "initialize_session_state(&server);",
    ],
    "src/session_state.c": [
        'suffix = "/wtwm/state";',
        "if (fchmod(descriptor, 0600) != 0)",
        "if (rename(temporary, path) != 0)",
        "if (errno == ENOENT)",
    ],
    "tests/integration/run_m8_session_lifecycle.py": [
        "invalid configuration",
        "runtime initialization failure",
        "startup command failure",
        "f.quit mixed clients",
        "except (BrokenPipeError, ConnectionResetError):",
        "malformed state",
        "signal.SIGTERM",
    ],
    "tests/platform/session-launcher-test.sh": [
        "forwarded child was not reaped",
        "forwarded child status was not preserved",
        'while test "$iteration" -lt 50',
    ],
}


def load_json(path: Path) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)


def records(value: Any, label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append(f"{label}[{index}] must have a string id")
            continue
        identifier = item["id"]
        if identifier in result:
            errors.append(f"duplicate {label} id {identifier}")
        result[identifier] = item
    return result


def validate_current_sources(source_root: Path,
                             replacements: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    replacements = replacements or {}
    for relative, markers in CURRENT_MARKERS.items():
        path = source_root / relative
        if not path.is_file():
            errors.append(f"current source is missing: {relative}")
            continue
        text = replacements.get(relative, path.read_text(encoding="utf-8"))
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative} is missing lifecycle marker: {marker}")
    launcher = source_root / "scripts/platform/wtwm-session"
    if launcher.is_file():
        text = replacements.get(str(launcher.relative_to(source_root)),
                                launcher.read_text(encoding="utf-8"))
        if "while :" not in text:
            errors.append("session launcher must use a bounded-by-child wait loop")
        if "wtwm_bin" in text and text.count('"$wtwm_bin" "$@" &') != 1:
            errors.append("session launcher must start exactly one compositor child")
    return errors


def validate(contract: dict[str, Any], inventory: dict[str, Any],
             source_root: Path, check_current: bool = True) -> list[str]:
    errors: list[str] = []
    expected_fields = {
        "schema_version", "contract", "upstream", "source_members", "evidence",
        "reference_behavior", "wayland_translation", "requirements",
        "verification_scenarios", "deferred",
    }
    if set(contract) != expected_fields:
        errors.append("contract top-level fields differ")
    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if contract.get("upstream") != UPSTREAM:
        errors.append("upstream identity differs from the frozen source")
    if contract.get("source_members") != SOURCE_MEMBERS:
        errors.append("source member hashes differ from the frozen source")

    archive_path = source_root / UPSTREAM["archive"]
    if not archive_path.is_file():
        errors.append("frozen upstream archive is missing")
        return errors
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != UPSTREAM["sha256"]:
        errors.append("frozen upstream archive hash differs")
        return errors
    evidence = contract.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE):
        errors.append("evidence IDs differ from the frozen set")
        evidence = {}
    with tarfile.open(archive_path, "r:xz") as archive:
        for member, expected_hash in SOURCE_MEMBERS.items():
            extracted = archive.extractfile(member)
            if extracted is None:
                errors.append(f"archive member is missing: {member}")
                continue
            if hashlib.sha256(extracted.read()).hexdigest() != expected_hash:
                errors.append(f"archive member hash differs: {member}")
        for identifier, (member, line_number, text) in EVIDENCE.items():
            if evidence.get(identifier) != {
                "member": member, "line": line_number, "text": text,
            }:
                errors.append(f"evidence record differs: {identifier}")
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            lines = extracted.read().decode("utf-8").splitlines()
            if line_number > len(lines) or lines[line_number - 1] != text:
                errors.append(f"archive evidence line differs: {identifier}")

    keyword = next((item for item in inventory.get("keywords", [])
                    if item.get("id") == "keyword.f.quit"), None)
    if keyword != {
        "id": "keyword.f.quit",
        "spelling": "f.quit",
        "parser_token": "FKEYWORD",
        "parser_value": "F_QUIT",
        "categories": ["built-in-action"],
        "evidence": {
            "archive_member": "twm-1.0.13.1/src/parse.c",
            "line": 456,
            "text": '    { "f.quit",                 FKEYWORD, F_QUIT },',
        },
    }:
        errors.append("inventory f.quit identity differs")

    reference = contract.get("reference_behavior", {})
    if reference.get("orderly_exit_sources") != [
        "f.quit", "SIGINT", "SIGHUP", "SIGQUIT", "SIGTERM", "XSM Die",
    ] or reference.get("orderly_exit_status") != 0:
        errors.append("reference orderly-exit semantics differ")
    xsm = reference.get("xsm", {})
    if xsm.get("restart_style") != "SmRestartIfRunning" or \
            xsm.get("discard_command_removes_state") is not True:
        errors.append("reference XSM lifecycle differs")

    translation = contract.get("wayland_translation", {})
    owner = translation.get("session_owner", {})
    if owner.get("entrypoint") != "wtwm-session" or \
            owner.get("restart_loop") is not False or \
            owner.get("child_status_preserved") is not True:
        errors.append("Wayland session ownership differs")
    startup = translation.get("startup", {})
    if startup.get("order") != [
        "validate command line",
        "parse and validate the complete configuration",
        "resolve and optionally load compositor-owned saved state",
        "create display, backend, protocols, and input state",
        "publish the Wayland socket and start the backend",
        "allocate Xwayland and export WAYLAND_DISPLAY and DISPLAY",
        "launch the optional startup command",
        "enter the event loop",
    ]:
        errors.append("Wayland startup order differs")
    logout = translation.get("logout", {})
    if logout.get("sources") != ["f.quit", "SIGINT", "SIGHUP", "SIGQUIT", "SIGTERM"] or \
            logout.get("status") != 0 or \
            logout.get("automatic_state_save") is not False or \
            logout.get("automatic_restart") is not False:
        errors.append("Wayland logout semantics differ")
    recovery = translation.get("failure_recovery", {})
    expected_statuses = (1, 2, 127)
    actual_statuses = (
        recovery.get("configuration_or_initialization_failure_status"),
        recovery.get("invalid_option_status"),
        recovery.get("missing_compositor_status_from_launcher"),
    )
    if actual_statuses != expected_statuses or \
            recovery.get("launcher_restarts_compositor") is not False or \
            recovery.get("existing_saved_state_is_never_replaced_by_startup_or_runtime_failure") is not True:
        errors.append("Wayland failure-recovery semantics differ")
    state = translation.get("state_file", {})
    if state.get("writer") != "f.saveyourself only" or \
            state.get("reader_gate") != "RestartPreviousState" or \
            state.get("xsm_client_id_option") is not False or \
            state.get("xsm_restore_option") is not False or \
            state.get("xsm_discard_command") is not False or \
            state.get("restores_client_processes_or_documents") is not False:
        errors.append("Wayland state-file boundary differs")

    requirements = records(contract.get("requirements"), "requirements", errors)
    if set(requirements) != REQUIREMENTS:
        errors.append("requirement IDs differ from the frozen set")
    for identifier, requirement in requirements.items():
        if requirement.get("level") != "MUST" or not requirement.get("rule"):
            errors.append(f"requirement is not a nonempty MUST: {identifier}")
        refs = requirement.get("evidence")
        if not isinstance(refs, list) or not refs or any(ref not in EVIDENCE for ref in refs):
            errors.append(f"requirement evidence is invalid: {identifier}")
    scenarios = records(contract.get("verification_scenarios"),
                        "verification_scenarios", errors)
    if set(scenarios) != SCENARIOS:
        errors.append("scenario IDs differ from the frozen set")
    for identifier, scenario in scenarios.items():
        if not isinstance(scenario.get("oracle"), str) or not scenario["oracle"]:
            errors.append(f"scenario oracle is empty: {identifier}")
    mixed = scenarios.get("f-quit-mixed-clients", {})
    if mixed.get("protocols") != ["native-wayland", "xwayland"]:
        errors.append("f.quit mixed-client protocols differ")
    deferred = contract.get("deferred")
    if not isinstance(deferred, list) or deferred != sorted(deferred) or len(deferred) != 5:
        errors.append("deferred scope must be the frozen sorted five-item set")

    if check_current:
        errors.extend(validate_current_sources(source_root))
    return errors


def self_test(contract: dict[str, Any], inventory: dict[str, Any],
              source_root: Path) -> list[str]:
    mutations: list[tuple[str, dict[str, Any]]] = []
    changed = copy.deepcopy(contract)
    changed["upstream"]["version"] = "future"
    mutations.append(("upstream-version", changed))
    changed = copy.deepcopy(contract)
    changed["source_members"].pop("twm-1.0.13.1/src/session.c")
    mutations.append(("missing-session-source", changed))
    changed = copy.deepcopy(contract)
    changed["evidence"]["exit.success"]["line"] += 1
    mutations.append(("wrong-exit-line", changed))
    changed = copy.deepcopy(contract)
    changed["reference_behavior"]["orderly_exit_status"] = 1
    mutations.append(("wrong-reference-status", changed))
    changed = copy.deepcopy(contract)
    changed["reference_behavior"]["orderly_exit_sources"].remove("SIGQUIT")
    mutations.append(("missing-reference-signal", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["session_owner"]["restart_loop"] = True
    mutations.append(("automatic-restart", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["startup"]["order"].reverse()
    mutations.append(("startup-order", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["logout"]["automatic_state_save"] = True
    mutations.append(("implicit-logout-save", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["logout"]["sources"].remove("SIGHUP")
    mutations.append(("missing-wayland-signal", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["failure_recovery"]["launcher_restarts_compositor"] = True
    mutations.append(("launcher-restart-loop", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["state_file"]["writer"] = "every logout"
    mutations.append(("wrong-state-writer", changed))
    changed = copy.deepcopy(contract)
    changed["wayland_translation"]["state_file"]["xsm_restore_option"] = True
    mutations.append(("invented-xsm-option", changed))
    changed = copy.deepcopy(contract)
    changed["requirements"][0]["level"] = "SHOULD"
    mutations.append(("weakened-requirement", changed))
    changed = copy.deepcopy(contract)
    changed["verification_scenarios"].pop()
    mutations.append(("missing-scenario", changed))
    changed = copy.deepcopy(contract)
    changed["verification_scenarios"][5]["protocols"].pop()
    mutations.append(("missing-protocol", changed))
    changed = copy.deepcopy(contract)
    changed["deferred"].pop()
    mutations.append(("expanded-scope", changed))

    failures: list[str] = []
    for label, mutation in mutations:
        if not validate(mutation, inventory, source_root, check_current=False):
            failures.append(f"tamper was accepted: {label}")
    for relative, markers in CURRENT_MARKERS.items():
        path = source_root / relative
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        for marker in markers[:1]:
            replacement = original.replace(marker, "TAMPERED")
            errors = validate_current_sources(source_root, {relative: replacement})
            if not errors:
                failures.append(f"current-source tamper was accepted: {relative}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        contract = load_json(source_root / CONTRACT_PATH)
        inventory = load_json(source_root / INVENTORY_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"session lifecycle contract: {error}", file=sys.stderr)
        return 1
    errors = validate(contract, inventory, source_root)
    if errors:
        for error in errors:
            print(f"session lifecycle contract: {error}", file=sys.stderr)
        return 1
    if args.self_test_tamper:
        failures = self_test(contract, inventory, source_root)
        if failures:
            for failure in failures:
                print(f"session lifecycle contract: {failure}", file=sys.stderr)
            return 1
        print("session lifecycle contract tamper self-test: 22 mutations rejected")
    print(
        "session lifecycle contract: 25 archive anchors, 10 requirements, "
        "17 scenarios"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
