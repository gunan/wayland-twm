#!/usr/bin/env python3
"""Map the frozen upstream inventory to the audited wtwm implementation.

This is an intentionally conservative, offline migration helper.  It does not
discover features by guessing from the upstream inventory.  Exact current-tree
items come from current-implementation.json; the tables below only describe
which frozen rows those already-audited items cover.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


AUDIT_PATH = "reference/audits/current-implementation.json"
CROSSWALK_PATH = "reference/audits/current-to-ledger.json"
LEDGER_PATH = "reference/ledger/twm-1.0.13.1.json"
SUMMARY_PATH = "docs/audits/compatibility-ledger.md"
SCHEMA_PATH = "reference/ledger/schema-1.1.json"


def canonical(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def add_existing(targets: set[str], identifiers: set[str], *values: str) -> None:
    targets.update(value for value in values if value in identifiers)


def prefix(targets: set[str], identifiers: set[str], *values: str) -> None:
    targets.update(
        identifier
        for identifier in identifiers
        if any(identifier.startswith(value) for value in values)
    )


def construct_targets(current_id: str, identifiers: set[str]) -> set[str]:
    targets: set[str] = set()
    if current_id == "construct.bare-or-list-directives":
        add_existing(targets, identifiers, "grammar.noarg.1", "grammar.sarg.1", "grammar.narg.1")
        targets.update(
            f"grammar.stmt.{number}"
            for number in list(range(13, 15)) + list(range(21, 37)) + list(range(47, 50))
            if f"grammar.stmt.{number}" in identifiers
        )
    elif current_id == "construct.base-0-numbers":
        add_existing(targets, identifiers, "grammar.number.1", "lexical.number")
    elif current_id == "construct.binding-context-alternatives":
        prefix(targets, identifiers, "grammar.contexts.", "grammar.context.", "grammar.contextkeys.", "grammar.contextkey.")
        add_existing(targets, identifiers, "lexical.or", *(f"keyword.{name}" for name in ("all", "frame", "i", "icon", "iconmgr", "m", "meta", "r", "root", "t", "title", "w", "window")))
    elif current_id == "construct.braces-and-nested-balanced-blocks":
        add_existing(targets, identifiers, "lexical.left-brace", "lexical.right-brace")
        prefix(targets, identifiers, "grammar.pixmap_", "grammar.cursor_", "grammar.color_", "grammar.save_color_", "grammar.s_color_", "grammar.win_color_", "grammar.iconm_", "grammar.win_", "grammar.icon_", "grammar.function.", "grammar.menu.")
    elif current_id == "construct.button-range-1-through-32":
        add_existing(targets, identifiers, "grammar.button.1")
    elif current_id == "construct.case-insensitive-keywords-and-actions":
        add_existing(targets, identifiers, "lexical.keyword")
    elif current_id == "construct.comments":
        add_existing(targets, identifiers, "lexical.comment")
    elif current_id == "construct.function-action-sequences":
        prefix(targets, identifiers, "grammar.function.", "grammar.function_entries.", "grammar.function_entry.")
    elif current_id == "construct.menu-definitions-and-items":
        prefix(targets, identifiers, "grammar.menu.", "grammar.menu_entries.", "grammar.menu_entry.")
    elif current_id == "construct.modifier-alternatives":
        prefix(targets, identifiers, "grammar.keys.", "grammar.key.")
        add_existing(targets, identifiers, "lexical.or", *(f"keyword.{name}" for name in ("c", "control", "l", "lock", "m", "meta", "mod", "s", "shift")))
    elif current_id == "construct.named-window-binding-context":
        add_existing(targets, identifiers, "grammar.contextkey.10")
    elif current_id == "construct.newlines":
        add_existing(targets, identifiers, "lexical.whitespace")
    elif current_id == "construct.parenthesized-menu-colors":
        add_existing(targets, identifiers, "grammar.stmt.37", "grammar.menu_entry.2", "lexical.left-parenthesis", "lexical.right-parenthesis", "lexical.colon")
    elif current_id == "construct.quoted-strings-and-backslash-escapes":
        add_existing(targets, identifiers, "grammar.string.1", "lexical.string")
    elif current_id == "construct.signed-integer-option":
        prefix(targets, identifiers, "grammar.signed_number.")
        add_existing(targets, identifiers, "lexical.plus", "lexical.minus")
    elif current_id == "construct.title-button-bitmap-action-assignment":
        add_existing(targets, identifiers, "grammar.stmt.15", "grammar.stmt.16", "lexical.equals")
    elif current_id == "construct.unknown-statement-skipping":
        add_existing(targets, identifiers, "grammar.stmt.1")
    elif current_id == "construct.window-name-lists":
        prefix(targets, identifiers, "grammar.win_list.", "grammar.win_entries.", "grammar.win_entry.")
    elif current_id == "construct.word-tokens":
        add_existing(targets, identifiers, "grammar.twmrc.1", "grammar.stmts.1", "grammar.stmts.2", "lexical.keyword")
    return targets


STATEMENT_TARGETS = {
    "directive.autoraise": ["grammar.stmt.36"],
    "directive.color": ["grammar.stmt.41"],
    "directive.cursors": ["grammar.stmt.12"],
    "directive.donticonifybyunmapping": ["grammar.stmt.21"],
    "directive.dontsqueezetitle": ["grammar.squeeze.3", "grammar.squeeze.4"],
    "directive.function": ["grammar.stmt.39"],
    "directive.grayscale": ["grammar.stmt.42"],
    "directive.greyscale": ["grammar.stmt.42"],
    "directive.iconifybyunmapping": ["grammar.stmt.13", "grammar.stmt.14"],
    "directive.iconmanagerdontshow": ["grammar.stmt.22", "grammar.stmt.23"],
    "directive.iconmanagers": ["grammar.stmt.24"],
    "directive.iconmanagershow": ["grammar.stmt.25"],
    "directive.icons": ["grammar.stmt.40"],
    "directive.lefttitlebutton": ["grammar.stmt.15"],
    "directive.maketitle": ["grammar.stmt.34"],
    "directive.menu": ["grammar.stmt.37", "grammar.stmt.38"],
    "directive.monochrome": ["grammar.stmt.44"],
    "directive.nohighlight": ["grammar.stmt.28", "grammar.stmt.29"],
    "directive.nostackmode": ["grammar.stmt.30", "grammar.stmt.31"],
    "directive.notitle": ["grammar.stmt.32", "grammar.stmt.33"],
    "directive.notitlehighlight": ["grammar.stmt.26", "grammar.stmt.27"],
    "directive.pixmaps": ["grammar.stmt.11"],
    "directive.righttitlebutton": ["grammar.stmt.16"],
    "directive.savecolor": ["grammar.stmt.43"],
    "directive.squeezetitle": ["grammar.stmt.5", "grammar.squeeze.1", "grammar.squeeze.2"],
    "directive.starticonified": ["grammar.stmt.35"],
    "directive.warpcursor": ["grammar.stmt.47", "grammar.stmt.48"],
    "directive.windowring": ["grammar.stmt.49"],
}

BOOL_DIRECTIVES = {
    "autorelativeresize", "clientborderwidth", "decoratetransients", "dontmoveoff",
    "nocasesensitive", "nomenushadows", "noraiseondeiconify", "noraiseonmove",
    "noraiseonresize", "notitlefocus", "opaquemove", "randomplacement", "showiconmanager",
}
INT_DIRECTIVES = {
    "borderwidth", "buttonindent", "constrainedmovetime", "framepadding",
    "menuborderwidth", "movedelta", "titlebuttonborderwidth", "titlepadding",
}
STRING_DIRECTIVES = {"iconfont", "iconmanagerfont", "menufont", "resizefont", "titlefont"}
ARGUMENT_ACTIONS = {"f.exec", "f.function", "f.menu", "f.warpto"}


def direct_targets(entry: dict[str, object], keyword_by_name: dict[str, str], identifiers: set[str]) -> set[str]:
    current_id = str(entry["id"])
    category = str(entry["category"])
    name = str(entry["name"])
    targets: set[str] = set()
    if category == "action":
        if current_id == "action.f-exec-alias":
            add_existing(targets, identifiers, "lexical.exec-shorthand")
        elif current_id == "action.f-cut-alias":
            add_existing(targets, identifiers, "lexical.cut-shorthand")
        elif current_id != "action.unrecognized-f-action":
            spelling = name.split()[0]
            target = keyword_by_name.get(normalize(spelling))
            if target:
                targets.add(target)
            add_existing(
                targets,
                identifiers,
                "grammar.action.2" if spelling.lower() in ARGUMENT_ACTIONS else "grammar.action.1",
            )
        else:
            add_existing(targets, identifiers, "grammar.action.1", "grammar.action.2")
    elif category == "directive":
        if current_id == "directive.buttonn-binding":
            add_existing(targets, identifiers, "grammar.stmt.20", "grammar.full.1", "grammar.button.1")
            prefix(targets, identifiers, "grammar.keys.", "grammar.key.", "grammar.contexts.", "grammar.context.")
            add_existing(targets, identifiers, *(f"keyword.{value}" for value in ("all", "c", "control", "frame", "i", "icon", "iconmgr", "l", "lock", "m", "meta", "mod", "r", "root", "s", "shift", "t", "title", "w", "window")))
        elif current_id == "directive.quoted-key-binding":
            add_existing(targets, identifiers, "grammar.stmt.19", "grammar.fullkey.1")
            prefix(targets, identifiers, "grammar.keys.", "grammar.key.", "grammar.contextkeys.", "grammar.contextkey.")
            add_existing(targets, identifiers, *(f"keyword.{value}" for value in ("all", "c", "control", "frame", "i", "icon", "iconmgr", "l", "lock", "m", "meta", "mod", "r", "root", "s", "shift", "t", "title", "w", "window")))
        elif current_id != "directive.unrecognized-statement-fallback":
            target = keyword_by_name.get(normalize(name))
            if target:
                targets.add(target)
        add_existing(targets, identifiers, *STATEMENT_TARGETS.get(current_id, []))
        if current_id in {"directive.color", "directive.grayscale", "directive.greyscale", "directive.monochrome"}:
            prefix(targets, identifiers, "grammar.color_", "grammar.win_color_")
        elif current_id == "directive.cursors":
            prefix(targets, identifiers, "grammar.cursor_")
        elif current_id == "directive.iconmanagers":
            prefix(targets, identifiers, "grammar.iconm_")
        elif current_id == "directive.icons":
            prefix(targets, identifiers, "grammar.icon_")
        elif current_id == "directive.function":
            prefix(targets, identifiers, "grammar.function.", "grammar.function_entries.", "grammar.function_entry.")
        elif current_id == "directive.menu":
            prefix(targets, identifiers, "grammar.menu.", "grammar.menu_entries.", "grammar.menu_entry.")
        elif current_id == "directive.pixmaps":
            prefix(targets, identifiers, "grammar.pixmap_")
        elif current_id == "directive.savecolor":
            prefix(targets, identifiers, "grammar.save_color_", "grammar.s_color_")
        elif current_id in {"directive.squeezetitle", "directive.dontsqueezetitle"}:
            prefix(targets, identifiers, "grammar.squeeze.", "grammar.win_sqz_")
        elif current_id in {"directive.autoraise", "directive.maketitle", "directive.notitle", "directive.starticonified"}:
            prefix(targets, identifiers, "grammar.win_list.", "grammar.win_entries.", "grammar.win_entry.")
        suffix = current_id.removeprefix("directive.")
        if suffix in BOOL_DIRECTIVES:
            add_existing(targets, identifiers, "grammar.stmt.2", "grammar.noarg.1")
        elif suffix in INT_DIRECTIVES:
            add_existing(targets, identifiers, "grammar.stmt.4", "grammar.narg.1")
        elif suffix in STRING_DIRECTIVES:
            add_existing(targets, identifiers, "grammar.stmt.3", "grammar.sarg.1")
    elif category == "construct":
        targets.update(construct_targets(current_id, identifiers))
    return targets


def test_mapping(location: str) -> dict[str, object] | None:
    path, line_text = location.rsplit(":", 1)
    if path != "tests/config_test.c":
        return None
    line = int(line_text)
    cases = [
        (8, 49, "parse_defaults"),
        (50, 70, "parse_rules_and_title_buttons"),
        (71, 80, "rejects_invalid_binding"),
        (81, 101, "accepts_legacy_syntax"),
        (102, 115, "applies_global_and_exception_rules"),
    ]
    case = next((name for first, last, name in cases if first <= line <= last), None)
    if case is None:
        return None
    return {
        "test_id": f"test.config.{case.replace('_', '-')}",
        "path": path,
        "case": case,
        "dimensions": ["syntax"],
        "assertions": ["The parser accepts or rejects the case input and checks the resulting configuration state."],
    }


def evidence_for(entries: list[dict[str, object]]) -> list[str]:
    values = {
        str(location)
        for entry in entries
        for location in entry["evidence"]  # type: ignore[index]
        if not str(location).startswith("docs/COMPATIBILITY.md:")
    }
    return sorted(values) or ["reference/audits/current-implementation.json:10"]


def directly_testable_targets(
    entry: dict[str, object], keyword_by_name: dict[str, str], identifiers: set[str]
) -> set[str]:
    """Return only rows directly named by an existing parser case.

    Construct entries often map one parser helper to many upstream alternatives;
    a single representative case is not evidence for every alternative.
    """
    current_id = str(entry["id"])
    category = str(entry["category"])
    name = str(entry["name"])
    targets: set[str] = set()
    if category == "action":
        if current_id == "action.f-exec-alias":
            add_existing(targets, identifiers, "lexical.exec-shorthand")
        elif current_id == "action.f-cut-alias":
            add_existing(targets, identifiers, "lexical.cut-shorthand")
        elif current_id != "action.unrecognized-f-action":
            target = keyword_by_name.get(normalize(name.split()[0]))
            if target:
                targets.add(target)
    elif category == "directive":
        if current_id == "directive.buttonn-binding":
            add_existing(targets, identifiers, "grammar.stmt.20")
        elif current_id == "directive.quoted-key-binding":
            add_existing(targets, identifiers, "grammar.stmt.19")
        elif current_id != "directive.unrecognized-statement-fallback":
            target = keyword_by_name.get(normalize(name))
            if target:
                targets.add(target)
    return targets


def behavior_relevant(row: dict[str, object]) -> bool:
    if row["inventory_section"] == "lexical_forms":
        return False
    categories = set(row["upstream"]["categories"])  # type: ignore[index]
    return categories != {"grammar-structure"}


def build(source_root: Path) -> tuple[dict[str, object], dict[str, object], str]:
    ledger = json.loads((source_root / LEDGER_PATH).read_text())
    audit = json.loads((source_root / AUDIT_PATH).read_text())
    entries = ledger["entries"]
    identifiers = {row["id"] for row in entries}
    keyword_by_name = {
        normalize(row["upstream"]["spelling"]): row["id"]
        for row in entries
        if row["inventory_section"] == "keywords"
    }
    current_entries = {entry["id"]: entry for entry in audit["entries"]}
    targets_by_current: dict[str, set[str]] = {}
    test_targets_by_current: dict[str, set[str]] = {}
    for current_id, entry in current_entries.items():
        if entry["category"] == "runtime_dispatch":
            targets_by_current[current_id] = set()
        else:
            targets_by_current[current_id] = direct_targets(entry, keyword_by_name, identifiers)
        test_targets_by_current[current_id] = directly_testable_targets(entry, keyword_by_name, identifiers)

    explicitly_targeted = set().union(*targets_by_current.values())
    fallback_id = "directive.unrecognized-statement-fallback"
    action_fallback_id = "action.unrecognized-f-action"
    for row in entries:
        row_id = row["id"]
        if row_id in explicitly_targeted:
            continue
        if row["inventory_section"] == "keywords":
            spelling = row["upstream"]["spelling"]
            if spelling.startswith("f."):
                targets_by_current[action_fallback_id].add(row_id)
            else:
                targets_by_current[fallback_id].add(row_id)
        elif row_id.startswith("grammar.stmt."):
            targets_by_current[fallback_id].add(row_id)

    current_by_ledger: dict[str, list[dict[str, object]]] = defaultdict(list)
    for current_id, target_ids in targets_by_current.items():
        for target_id in target_ids:
            current_by_ledger[target_id].append(current_entries[current_id])

    default_evidence = ["reference/audits/current-implementation.json:10", "src/config.c:569"]
    for row in entries:
        mapped = sorted(current_by_ledger.get(row["id"], []), key=lambda item: item["id"])
        evidence = evidence_for(mapped) if mapped else default_evidence
        mapped_ids = {entry["id"] for entry in mapped}
        fallback = bool(mapped_ids & {fallback_id, action_fallback_id})
        relevant = behavior_relevant(row)
        if not mapped:
            syntax_status = "unsupported"
        elif fallback:
            syntax_status = "partial"
        else:
            syntax_status = "complete"

        effective = [entry for entry in mapped if entry["native_wayland_status"] == "effective"]
        parsed = [entry for entry in mapped if entry["native_wayland_status"] == "parsed_only"]
        if not relevant:
            runtime_status = native_status = "not-applicable"
            xwayland_status = "not-applicable"
        elif effective:
            runtime_status = native_status = "partial"
            xwayland_status = "unavailable"
        elif parsed or fallback:
            runtime_status = native_status = "parsed-only"
            xwayland_status = "unavailable"
        else:
            runtime_status = native_status = "unsupported"
            xwayland_status = "unavailable"

        mappings_by_id: dict[str, dict[str, object]] = {}
        test_locations: list[str] = []
        for entry in mapped:
            if row["id"] not in test_targets_by_current[entry["id"]]:
                continue
            for location in entry["tests"]:
                mapping = test_mapping(str(location))
                if mapping:
                    mappings_by_id[str(mapping["test_id"])] = mapping
                    test_locations.append(str(location))
        test_mappings = sorted(mappings_by_id.values(), key=lambda item: (item["test_id"], item["path"], item["case"]))
        test_status = "partial" if test_mappings else "none"
        test_evidence = sorted(set(test_locations)) or ["tests/config_test.c:117"]

        semantic: list[dict[str, object]] = []
        if syntax_status == "unsupported":
            semantic.append({
                "summary": "No current-tree parser support was identified for this frozen upstream row.",
                "evidence": evidence,
                "tests": [],
            })
        elif runtime_status == "parsed-only":
            semantic.append({
                "summary": "The syntax is accepted, but the current audit identifies no native runtime effect.",
                "evidence": evidence,
                "tests": [mapping["test_id"] for mapping in test_mappings],
            })
        elif relevant and xwayland_status == "unavailable":
            semantic.append({
                "summary": "Native behavior is only partially established and the Xwayland client path is unavailable.",
                "evidence": sorted(set(evidence + ["docs/COMPATIBILITY.md:27"])),
                "tests": [mapping["test_id"] for mapping in test_mappings],
            })
        difference_status = "known" if semantic else "none-known"
        difference_evidence = evidence if semantic else sorted(set(evidence))

        row["syntax_support"] = {
            "status": syntax_status,
            "evidence": evidence,
            "notes": ["Complete means the current parser has an explicit path for this accepted form; partial includes generic compatibility fallback."],
        }
        row["runtime_support"] = {
            "status": runtime_status,
            "evidence": evidence,
            "notes": ["No exact or behaviorally-equivalent status is assigned without frozen-reference runtime comparison."],
        }
        row["native_wayland_behavior"] = {
            "status": native_status,
            "evidence": evidence,
            "notes": ["Partial records an identified native consumer without claiming reference equivalence."],
        }
        row["xwayland_behavior"] = {
            "status": xwayland_status,
            "evidence": sorted(set(evidence + (["docs/COMPATIBILITY.md:27"] if relevant else []))),
            "notes": ["The audited tree has no Xwayland client lifecycle; syntax-only rows are not applicable."],
        }
        row["test_coverage"] = {
            "status": test_status,
            "evidence": test_evidence,
            "mappings": test_mappings,
            "notes": ["Existing config tests cover parser behavior only; data/system.twmrc occurrences are not counted as asserting test cases."],
        }
        row["differences"] = {
            "status": difference_status,
            "evidence": difference_evidence,
            "visual": [],
            "semantic": sorted(semantic, key=lambda item: item["summary"]),
            "notes": ["No visual parity claim is made because the current audit contains no screenshot or differential evidence."],
        }

    ledger["schema_version"] = "1.1"
    ledger["schema_path"] = SCHEMA_PATH
    ledger["current_audit_path"] = AUDIT_PATH
    ledger["crosswalk_path"] = CROSSWALK_PATH
    ledger["assessment_policy"] = {
        "phase": "current-implementation-audited",
        "initial_status": "unassessed",
        "scope": "One row for every keyword, grammar alternative, and successful lexer form in the frozen upstream inventory.",
        "next_step": "Add focused reference, parser, native Wayland, and Xwayland tests for the gaps recorded by this audit.",
    }
    ordered_root = {
        key: ledger[key]
        for key in ("schema_version", "schema_path", "inventory_path", "current_audit_path", "crosswalk_path", "reference", "assessment_policy", "entries")
    }

    mappings = []
    for current_id, entry in sorted(current_entries.items()):
        target_ids = sorted(targets_by_current[current_id])
        classification = "runtime-dispatch" if entry["category"] == "runtime_dispatch" else "ledger-mapped"
        if not target_ids and classification == "ledger-mapped":
            classification = "current-only"
        mappings.append({
            "current_id": current_id,
            "classification": classification,
            "ledger_ids": target_ids,
            "notes": "Runtime dispatch is implementation plumbing, not an upstream syntax row." if classification == "runtime-dispatch" else "Mapped conservatively to frozen rows exercised by this audited parser item.",
        })
    mapped_ledger = set().union(*(set(mapping["ledger_ids"]) for mapping in mappings))
    crosswalk = {
        "schema_version": "1.0",
        "current_audit_path": AUDIT_PATH,
        "ledger_path": LEDGER_PATH,
        "audited_commit": audit["audited_commit"],
        "mappings": mappings,
        "unmapped_ledger_ids": sorted(identifiers - mapped_ledger),
    }

    dimensions = [
        "syntax_support", "runtime_support", "native_wayland_behavior",
        "xwayland_behavior", "test_coverage", "differences",
    ]
    counts = {dimension: Counter(row[dimension]["status"] for row in entries) for dimension in dimensions}
    cross_counts = Counter(mapping["classification"] for mapping in mappings)
    lines = [
        "# Current implementation compatibility-ledger audit",
        "",
        "The authoritative assessment is `reference/ledger/twm-1.0.13.1.json`; its",
        "deterministic current-to-upstream crosswalk is",
        "`reference/audits/current-to-ledger.json`. The audit is conservative:",
        "an identified native consumer is `partial` until reference comparison proves",
        "it exact or behaviorally equivalent, parser retention without a consumer is",
        "`parsed-only`, and parser tests are never credited as runtime tests.",
        "",
        "## Coverage and mapping method",
        "",
        f"All **{len(entries)}** frozen upstream rows remain in the ledger. All",
        f"**{len(mappings)}** current-audit entries are accounted for;",
        f"**{len(mapped_ledger)}** ledger rows have at least one current mapping and",
        f"**{len(crosswalk['unmapped_ledger_ids'])}** are explicitly listed as unmapped.",
        "Exact spelling maps directives and actions to keyword rows. Explicit tables map",
        "aliases, grammar constructs, and statement forms. The generic statement and",
        "unknown-action paths map otherwise-unrecognized upstream spellings only as",
        "partial syntax with parsed-only behavior. Runtime-dispatch entries are classified",
        "as implementation plumbing because they are not upstream syntax rows.",
        "",
        "## Machine-checked assessment counts",
        "",
        "| Dimension | Status | Count |",
        "| --- | --- | ---: |",
    ]
    for dimension in dimensions:
        for status, count in sorted(counts[dimension].items()):
            lines.append(f"| `{dimension}` | `{status}` | {count} |")
    lines += [
        "",
        "## Crosswalk counts",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for status, count in sorted(cross_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines += [
        "",
        "## Largest gaps and limitations",
        "",
        f"- Xwayland behavior is unavailable for {counts['xwayland_behavior'].get('unavailable', 0)} behavior-relevant rows; the tree contains no optional legacy-X11 client lifecycle.",
        f"- {counts['runtime_support'].get('parsed-only', 0)} rows are parsed-only and have no identified native runtime effect.",
        f"- {counts['test_coverage'].get('none', 0)} rows have no exact existing test-case mapping. Existing mapped cases are parser-only, so no runtime, visual, native differential, or Xwayland behavior is proven.",
        (
            f"- {counts['syntax_support'].get('unsupported', 0)} rows have no current-tree syntax evidence; generic compatibility skipping is credited only where the audited fallback directly covers an upstream spelling."
            if counts["syntax_support"].get("unsupported", 0)
            else f"- All {len(entries)} upstream rows have current-tree syntax evidence, but {counts['syntax_support'].get('partial', 0)} rely on generic compatibility acceptance and are therefore only partial."
        ),
        "- No row is classified `exact`, `behaviorally-equivalent`, or `verified-no-op`: the repository has no frozen-reference runtime/differential evidence for those stronger claims.",
        "- Source locations prove current-tree implementation paths, not pixel parity. This audit records that limitation instead of treating documentation or parser acceptance as equivalence evidence.",
        "",
    ]
    return ordered_root, crosswalk, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    ledger, crosswalk, summary = build(source_root)
    outputs = {
        source_root / LEDGER_PATH: canonical(ledger),
        source_root / CROSSWALK_PATH: canonical(crosswalk),
        source_root / SUMMARY_PATH: summary,
    }
    if args.check:
        mismatches = [str(path.relative_to(source_root)) for path, expected in outputs.items() if not path.is_file() or path.read_text() != expected]
        if mismatches:
            print("stale assessed artifacts: " + ", ".join(mismatches))
            return 1
        print("assessed ledger, crosswalk, and summary are deterministic")
        return 0
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        print(f"wrote {path.relative_to(source_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
