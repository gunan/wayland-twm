#!/usr/bin/env python3
"""Generate and validate the frozen twm 1.0.13.1 configuration inventory."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path


ARCHIVE_SHA256 = "a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5"
ARCHIVE_MEMBER_ROOT = "twm-1.0.13.1"
PARSE_MEMBER = f"{ARCHIVE_MEMBER_ROOT}/src/parse.c"
GRAMMAR_MEMBER = f"{ARCHIVE_MEMBER_ROOT}/src/gram.y"
LEXER_MEMBER = f"{ARCHIVE_MEMBER_ROOT}/src/lex.l"
MANUAL_MEMBER = f"{ARCHIVE_MEMBER_ROOT}/man/twm.man"
DEFAULTS_MEMBER = f"{ARCHIVE_MEMBER_ROOT}/src/system.twmrc"

CATEGORY_ORDER = [
    "directive",
    "color-monochrome-option",
    "window-list-directive",
    "mouse-binding-form",
    "key-binding-form",
    "binding-context",
    "binding-modifier",
    "built-in-action",
    "menu-construct",
    "icon-option",
    "icon-manager-option",
    "cursor-option",
    "pixmap-option",
    "font-option",
    "placement-option",
    "title-button-option",
    "direction-or-justification",
    "lexical-form",
    "grammar-structure",
]

CATEGORY_DESCRIPTIONS = {
    "directive": "Top-level startup-file directive or generic directive form.",
    "color-monochrome-option": "Color, grayscale, monochrome, or saved-color syntax.",
    "window-list-directive": "Directive or production whose behavior is selected by a window list.",
    "mouse-binding-form": "Pointer-button binding syntax or its contexts.",
    "key-binding-form": "Keyboard binding syntax or its name-selecting contexts.",
    "binding-context": "Context accepted in a mouse or key binding.",
    "binding-modifier": "Modifier accepted in a mouse or key binding.",
    "built-in-action": "Built-in f.* action accepted by the parser.",
    "menu-construct": "Menu or named-function declaration and entry syntax.",
    "icon-option": "Icon configuration syntax.",
    "icon-manager-option": "Icon-manager configuration syntax.",
    "cursor-option": "Cursor declaration syntax or cursor role.",
    "pixmap-option": "Pixmap declaration syntax.",
    "font-option": "Font configuration directive.",
    "placement-option": "Window, title, or icon placement/layout syntax.",
    "title-button-option": "Title-button declaration or layout option.",
    "direction-or-justification": "Direction, gravity, or title justification keyword.",
    "lexical-form": "Accepted punctuation, literal, comment, or shorthand form.",
    "grammar-structure": "Structural grammar production needed to express accepted syntax.",
}

LEXICAL_RULES = [
    ("left-brace", '"{"'),
    ("right-brace", '"}"'),
    ("left-parenthesis", '"("'),
    ("right-parenthesis", '")"'),
    ("equals", '"="'),
    ("colon", '":"'),
    ("plus", '"+"'),
    ("minus", '"-"'),
    ("or", '"|"'),
    ("keyword", r"[a-zA-Z\.]+"),
    ("exec-shorthand", '"!"'),
    ("cut-shorthand", '"^"'),
    ("string", "{string}"),
    ("number", "{number}"),
    ("comment", r"\#[^\n]*\n"),
    ("whitespace", r"[\r\n\t ]"),
]

WINDOW_LIST_TOKENS = {
    "AUTO_RAISE",
    "DONT_ICONIFY_BY_UNMAPPING",
    "DONT_SQUEEZE_TITLE",
    "ICONIFY_BY_UNMAPPING",
    "ICONMGR_NOSHOW",
    "ICONMGR_SHOW",
    "MAKE_TITLE",
    "NO_HILITE",
    "NO_STACKMODE",
    "NO_TITLE",
    "NO_TITLE_HILITE",
    "START_ICONIFIED",
    "WARP_CURSOR",
    "WINDOW_RING",
}

PLACEMENT_NAMES = {
    "autorelativeresize",
    "constrainedmovetime",
    "dontmoveoff",
    "iconregion",
    "maxwindowsize",
    "movedelta",
    "opaquemove",
    "randomplacement",
    "squeezetitle",
    "dontsqueezetitle",
    "usepposition",
    "zoom",
}

MENU_NAMES = {
    "defaultfunction",
    "function",
    "menu",
    "windowfunction",
    "f.function",
    "f.menu",
    "f.title",
}

GRAMMAR_CATEGORIES = {
    "full": ["mouse-binding-form"],
    "fullkey": ["key-binding-form"],
    "keys": ["binding-modifier"],
    "key": ["binding-modifier"],
    "contexts": ["mouse-binding-form", "binding-context"],
    "context": ["mouse-binding-form", "binding-context"],
    "contextkeys": ["key-binding-form", "binding-context"],
    "contextkey": ["key-binding-form", "binding-context"],
    "pixmap_list": ["pixmap-option"],
    "pixmap_entries": ["pixmap-option"],
    "pixmap_entry": ["pixmap-option"],
    "cursor_list": ["cursor-option"],
    "cursor_entries": ["cursor-option"],
    "cursor_entry": ["cursor-option"],
    "color_list": ["color-monochrome-option"],
    "color_entries": ["color-monochrome-option"],
    "color_entry": ["color-monochrome-option"],
    "save_color_list": ["color-monochrome-option"],
    "s_color_entries": ["color-monochrome-option"],
    "s_color_entry": ["color-monochrome-option"],
    "win_color_list": ["color-monochrome-option", "window-list-directive"],
    "win_color_entries": ["color-monochrome-option", "window-list-directive"],
    "win_color_entry": ["color-monochrome-option", "window-list-directive"],
    "squeeze": ["placement-option", "window-list-directive"],
    "win_sqz_entries": ["placement-option", "window-list-directive"],
    "iconm_list": ["icon-manager-option"],
    "iconm_entries": ["icon-manager-option"],
    "iconm_entry": ["icon-manager-option"],
    "win_list": ["window-list-directive"],
    "win_entries": ["window-list-directive"],
    "win_entry": ["window-list-directive"],
    "icon_list": ["icon-option", "window-list-directive"],
    "icon_entries": ["icon-option", "window-list-directive"],
    "icon_entry": ["icon-option", "window-list-directive"],
    "function": ["menu-construct"],
    "function_entries": ["menu-construct"],
    "function_entry": ["menu-construct"],
    "menu": ["menu-construct"],
    "menu_entries": ["menu-construct"],
    "menu_entry": ["menu-construct"],
    "action": ["built-in-action"],
    "button": ["mouse-binding-form"],
}


def _read_archive(archive: Path) -> dict[str, list[str]]:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError(f"archive SHA-256 is {digest}, expected {ARCHIVE_SHA256}")

    members = [PARSE_MEMBER, GRAMMAR_MEMBER, LEXER_MEMBER, MANUAL_MEMBER, DEFAULTS_MEMBER]
    result: dict[str, list[str]] = {}
    with tarfile.open(archive, "r:xz") as tf:
        for member in members:
            extracted = tf.extractfile(member)
            if extracted is None:
                raise ValueError(f"archive member is missing: {member}")
            result[member] = extracted.read().decode("utf-8").splitlines()
    return result


def _evidence(member: str, lines: list[str], line_number: int) -> dict[str, object]:
    return {
        "archive_member": member,
        "line": line_number,
        "text": lines[line_number - 1],
    }


def _ordered_categories(categories: set[str] | list[str]) -> list[str]:
    requested = set(categories)
    unknown = requested.difference(CATEGORY_ORDER)
    if unknown:
        raise ValueError(f"unknown categories: {sorted(unknown)}")
    return [category for category in CATEGORY_ORDER if category in requested]


def _strip_grammar_actions(lines: list[str]) -> list[str]:
    """Remove C semantic actions and comments while preserving line positions."""
    result: list[str] = []
    action_depth = 0
    block_comment = False
    quote: str | None = None
    escaped = False

    for line in lines:
        output: list[str] = []
        i = 0
        while i < len(line):
            ch = line[i]
            nxt = line[i + 1] if i + 1 < len(line) else ""
            if block_comment:
                if ch == "*" and nxt == "/":
                    block_comment = False
                    i += 2
                else:
                    i += 1
                continue
            if action_depth:
                if quote:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == quote:
                        quote = None
                elif ch in {'"', "'"}:
                    quote = ch
                elif ch == "/" and nxt == "*":
                    block_comment = True
                    i += 2
                    continue
                elif ch == "{":
                    action_depth += 1
                elif ch == "}":
                    action_depth -= 1
                i += 1
                continue
            if ch == "/" and nxt == "*":
                block_comment = True
                i += 2
                continue
            if ch == "{":
                action_depth = 1
                i += 1
                continue
            output.append(ch)
            i += 1
        result.append("".join(output))
    if action_depth or block_comment or quote:
        raise ValueError("unterminated action, comment, or quote in grammar")
    return result


def _parse_grammar(lines: list[str]) -> list[dict[str, object]]:
    markers = [i for i, line in enumerate(lines) if line.strip() == "%%"]
    if len(markers) < 2:
        raise ValueError("grammar does not contain two %% delimiters")
    first, second = markers[:2]
    cleaned = _strip_grammar_actions(lines[first + 1 : second])
    line_offset = first + 2

    productions: list[dict[str, object]] = []
    current_name: str | None = None
    current_parts: list[str] = []
    current_line = 0
    ordinal = 0

    def finish_alternative() -> None:
        nonlocal current_parts
        if current_name is None:
            return
        syntax = " ".join(" ".join(current_parts).split())
        categories = GRAMMAR_CATEGORIES.get(current_name, ["grammar-structure"])
        productions.append(
            {
                "id": f"grammar.{current_name}.{ordinal}",
                "production": current_name,
                "ordinal": ordinal,
                "syntax": syntax,
                "categories": _ordered_categories(categories),
                "evidence": _evidence(GRAMMAR_MEMBER, lines, current_line),
            }
        )
        current_parts = []

    for relative_index, clean_line in enumerate(cleaned):
        source_line = relative_index + line_offset
        header = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*(.*)$", clean_line)
        alternative = re.match(r"^\s*\|\s*(.*)$", clean_line)
        terminator = re.match(r"^\s*;\s*$", clean_line)
        if header:
            if current_name is not None:
                raise ValueError(f"production {current_name} has no terminator")
            current_name = header.group(1)
            ordinal = 1
            current_line = source_line
            current_parts = [header.group(2)]
        elif alternative and current_name is not None:
            finish_alternative()
            ordinal += 1
            current_line = source_line
            current_parts = [alternative.group(1)]
        elif terminator and current_name is not None:
            finish_alternative()
            current_name = None
            ordinal = 0
        elif current_name is not None and clean_line.strip():
            current_parts.append(clean_line.strip())

    if current_name is not None:
        raise ValueError(f"unterminated production: {current_name}")
    if not productions:
        raise ValueError("no grammar productions found")
    return productions


def _grammar_token_usage(grammar_entries: list[dict[str, object]]) -> dict[str, set[str]]:
    usage: dict[str, set[str]] = {}
    for entry in grammar_entries:
        production = str(entry["production"])
        for symbol in str(entry["syntax"]).split():
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", symbol):
                usage.setdefault(symbol, set()).add(production)
    return usage


def _keyword_categories(
    spelling: str, token: str, token_usage: dict[str, set[str]]
) -> list[str]:
    categories: set[str] = set()
    productions = token_usage.get(token, set())

    if token in {"KEYWORD", "SKEYWORD", "NKEYWORD"} or "stmt" in productions:
        categories.add("directive")
    if token in {"CKEYWORD", "CLKEYWORD", "COLOR", "GRAYSCALE", "MONOCHROME", "SAVECOLOR"}:
        categories.add("color-monochrome-option")
    if token in WINDOW_LIST_TOKENS or token == "CLKEYWORD":
        categories.add("window-list-directive")
    if token in {"FKEYWORD", "FSKEYWORD"}:
        categories.add("built-in-action")
    if productions.intersection({"key"}):
        categories.add("binding-modifier")
    if productions.intersection({"context", "contextkey"}):
        categories.add("binding-context")
    if productions.intersection({"context"}):
        categories.add("mouse-binding-form")
    if productions.intersection({"contextkey"}):
        categories.add("key-binding-form")
    if token == "BUTTON":
        categories.add("mouse-binding-form")
    if token in {"DKEYWORD", "JKEYWORD"}:
        categories.add("direction-or-justification")
    if token in {"CURSORS", "FRAME", "TITLE", "ICON", "ICONMGR", "BUTTON", "MOVE", "RESIZE", "WAIT", "MENU", "SELECT", "KILL"} and "cursor_entry" in productions:
        categories.add("cursor-option")
    if token in {"PIXMAPS", "TITLE_HILITE"}:
        categories.add("pixmap-option")
    if spelling.endswith("font"):
        categories.add("font-option")
    if spelling in PLACEMENT_NAMES:
        categories.add("placement-option")
    if spelling in MENU_NAMES or spelling.startswith("menu") or "menu" in spelling:
        categories.add("menu-construct")
    if "iconmanager" in spelling or "iconmgr" in spelling:
        categories.add("icon-manager-option")
    elif "icon" in spelling:
        categories.add("icon-option")
    if "titlebutton" in spelling or spelling == "buttonindent":
        categories.add("title-button-option")
    if not categories:
        categories.add("grammar-structure")
    return _ordered_categories(categories)


def _parse_keywords(
    lines: list[str], grammar_entries: list[dict[str, object]]
) -> list[dict[str, object]]:
    start = next(
        (i for i, line in enumerate(lines) if "static TwmKeyword keytable[]" in line),
        None,
    )
    if start is None:
        raise ValueError("parse.c keytable declaration not found")
    row_re = re.compile(
        r'^\s*\{\s*"([^"]+)",\s*([A-Z0-9_]+),\s*([^\s},]+)\s*\},'
    )
    token_usage = _grammar_token_usage(grammar_entries)
    entries: list[dict[str, object]] = []
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "};":
            break
        match = row_re.match(lines[index])
        if not match:
            continue
        spelling, token, value = match.groups()
        entries.append(
            {
                "id": f"keyword.{spelling}",
                "spelling": spelling,
                "parser_token": token,
                "parser_value": value,
                "categories": _keyword_categories(spelling, token, token_usage),
                "evidence": _evidence(PARSE_MEMBER, lines, index + 1),
            }
        )
    if not entries:
        raise ValueError("parse.c keytable has no entries")
    spellings = [str(entry["spelling"]) for entry in entries]
    if spellings != sorted(spellings):
        raise ValueError("upstream parse.c keytable is not in lexical order")
    return entries


def _parse_lexical_entries(lines: list[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    cursor = 0
    for identifier, pattern in LEXICAL_RULES:
        found = None
        for index in range(cursor, len(lines)):
            if lines[index].lstrip().startswith(pattern) and "{" in lines[index]:
                found = index
                break
        if found is None:
            raise ValueError(f"accepted lexer rule not found in order: {pattern}")
        cursor = found + 1
        categories = {"lexical-form"}
        if identifier in {"exec-shorthand", "cut-shorthand"}:
            categories.add("built-in-action")
        entries.append(
            {
                "id": f"lexical.{identifier}",
                "pattern": pattern,
                "categories": _ordered_categories(categories),
                "evidence": _evidence(LEXER_MEMBER, lines, found + 1),
            }
        )
    return entries


def _observation(member: str, lines: list[str], line: int, identifier: str) -> dict[str, object]:
    return {"id": identifier, "evidence": _evidence(member, lines, line)}


def build_inventory(archive: Path) -> dict[str, object]:
    source = _read_archive(archive)
    grammar_entries = _parse_grammar(source[GRAMMAR_MEMBER])
    keyword_entries = _parse_keywords(source[PARSE_MEMBER], grammar_entries)
    lexical_entries = _parse_lexical_entries(source[LEXER_MEMBER])
    return {
        "schema_version": 1,
        "upstream": {
            "name": "X.Org twm",
            "version": "1.0.13.1",
            "archive": "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz",
            "sha256": ARCHIVE_SHA256,
        },
        "category_order": CATEGORY_ORDER,
        "category_descriptions": CATEGORY_DESCRIPTIONS,
        "source_observations": [
            _observation(MANUAL_MEMBER, source[MANUAL_MEMBER], 206, "manual.configuration-model"),
            _observation(MANUAL_MEMBER, source[MANUAL_MEMBER], 220, "manual.case-insensitive-keywords"),
            _observation(MANUAL_MEMBER, source[MANUAL_MEMBER], 234, "manual.list-delimiters"),
            _observation(DEFAULTS_MEMBER, source[DEFAULTS_MEMBER], 2, "defaults.identity"),
            _observation(DEFAULTS_MEMBER, source[DEFAULTS_MEMBER], 51, "defaults.mouse-binding"),
            _observation(DEFAULTS_MEMBER, source[DEFAULTS_MEMBER], 69, "defaults.menu"),
        ],
        "keywords": keyword_entries,
        "grammar": grammar_entries,
        "lexical_forms": lexical_entries,
    }


def _validate_shape(inventory: dict[str, object], sources: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    ids: list[str] = []
    allowed = set(CATEGORY_ORDER)
    for section in ("source_observations", "keywords", "grammar", "lexical_forms"):
        entries = inventory.get(section)
        if not isinstance(entries, list):
            errors.append(f"{section} must be an array")
            continue
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{section}[{position}] must be an object")
                continue
            identifier = entry.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9_.-]+", identifier):
                errors.append(f"{section}[{position}] has an invalid stable id")
            else:
                ids.append(identifier)
            if section != "source_observations":
                categories = entry.get("categories")
                if not isinstance(categories, list) or not categories:
                    errors.append(f"{identifier}: categories must be a non-empty array")
                elif any(category not in allowed for category in categories):
                    errors.append(f"{identifier}: contains an unknown category")
                elif categories != _ordered_categories(categories):
                    errors.append(f"{identifier}: categories are not in canonical order")
            evidence = entry.get("evidence")
            if not isinstance(evidence, dict):
                errors.append(f"{identifier}: evidence must be an object")
                continue
            member = evidence.get("archive_member")
            line = evidence.get("line")
            text = evidence.get("text")
            if member not in sources:
                errors.append(f"{identifier}: unknown evidence member {member!r}")
            elif not isinstance(line, int) or line < 1 or line > len(sources[member]):
                errors.append(f"{identifier}: invalid evidence line {line!r}")
            elif text != sources[member][line - 1]:
                errors.append(f"{identifier}: evidence text does not match archive line {line}")
    if len(ids) != len(set(ids)):
        errors.append("stable IDs are not globally unique")
    return errors


def _compare(actual: dict[str, object], expected: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for key in expected:
        if key not in actual:
            errors.append(f"missing top-level field: {key}")
    for key in actual:
        if key not in expected:
            errors.append(f"unexpected top-level field: {key}")
    for section in ("schema_version", "upstream", "category_order", "category_descriptions"):
        if actual.get(section) != expected.get(section):
            errors.append(f"{section} differs from the canonical generated value")
    for section in ("source_observations", "keywords", "grammar", "lexical_forms"):
        actual_entries = actual.get(section)
        expected_entries = expected.get(section)
        if actual_entries == expected_entries:
            continue
        if isinstance(actual_entries, list) and isinstance(expected_entries, list):
            actual_ids = [entry.get("id") for entry in actual_entries if isinstance(entry, dict)]
            expected_ids = [entry.get("id") for entry in expected_entries if isinstance(entry, dict)]
            missing = [identifier for identifier in expected_ids if identifier not in actual_ids]
            extra = [identifier for identifier in actual_ids if identifier not in expected_ids]
            if missing:
                errors.append(f"{section} is missing: {', '.join(str(item) for item in missing[:8])}")
            if extra:
                errors.append(f"{section} has unexpected entries: {', '.join(str(item) for item in extra[:8])}")
            if not missing and not extra:
                errors.append(f"{section} content or source order differs from the archive-derived inventory")
        else:
            errors.append(f"{section} differs from the archive-derived inventory")
    return errors


def validate_inventory(
    inventory: dict[str, object], expected: dict[str, object], sources: dict[str, list[str]]
) -> list[str]:
    return _validate_shape(inventory, sources) + _compare(inventory, expected)


def _tamper_self_test(
    inventory: dict[str, object], expected: dict[str, object], sources: dict[str, list[str]]
) -> int:
    mutations = []
    for section in ("keywords", "grammar", "lexical_forms"):
        changed = copy.deepcopy(inventory)
        changed[section].pop(0)  # type: ignore[index,union-attr]
        mutations.append((f"remove-{section}", changed))

    changed = copy.deepcopy(inventory)
    changed["keywords"][0]["id"] = "keyword.invalid"  # type: ignore[index]
    mutations.append(("stable-id", changed))
    changed = copy.deepcopy(inventory)
    changed["keywords"][0]["categories"] = ["not-a-category"]  # type: ignore[index]
    mutations.append(("category", changed))
    changed = copy.deepcopy(inventory)
    changed["keywords"][0]["evidence"]["line"] = 1  # type: ignore[index]
    mutations.append(("evidence", changed))
    changed = copy.deepcopy(inventory)
    changed["keywords"][0], changed["keywords"][1] = changed["keywords"][1], changed["keywords"][0]  # type: ignore[index]
    mutations.append(("order", changed))

    failures = [name for name, changed in mutations if not validate_inventory(changed, expected, sources)]
    if failures:
        print(f"tamper self-test failed to reject: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"tamper self-test: {len(mutations)} inventory mutations rejected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    archive = source_root / "reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz"
    inventory_path = args.inventory or source_root / "reference/inventory/twm-1.0.13.1.json"
    try:
        expected = build_inventory(archive)
        sources = _read_archive(archive)
        if args.write:
            inventory_path.parent.mkdir(parents=True, exist_ok=True)
            inventory_path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {inventory_path}")
            return 0
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(inventory, dict):
            raise ValueError("inventory root must be an object")
        errors = validate_inventory(inventory, expected, sources)
        if errors:
            for error in errors:
                print(f"inventory error: {error}", file=sys.stderr)
            return 1
        if args.self_test_tamper:
            status = _tamper_self_test(inventory, expected, sources)
            if status:
                return status
        print(
            "upstream inventory valid: "
            f"{len(inventory['keywords'])} keywords, "
            f"{len(inventory['grammar'])} grammar alternatives, "
            f"{len(inventory['lexical_forms'])} lexical forms"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        print(f"inventory validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
