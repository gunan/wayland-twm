#!/usr/bin/env python3
"""Generate the deterministic current-feature to automated-test map."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


AUDIT_PATH = "reference/audits/current-implementation.json"
MAP_PATH = "reference/audits/feature-test-map.json"
SUMMARY_PATH = "docs/audits/feature-test-map.md"
TEST_PATH = "tests/reference/validate_feature_test_map.py"
MESON_TEST = "current feature coverage"
INTERACTION_RUNTIME_PATH = "tests/integration/run_move_resize.py"
INTERACTION_RUNTIME_TEST = "move and resize interaction integration"
INTERACTION_RUNTIME_ID = "test.current-feature.move-resize-runtime"
INTERACTION_RUNTIME_FEATURES = {
    "action.f-deltastop",
    "action.f-forcemove",
    "action.f-move",
    "action.f-resize",
    "directive.autorelativeresize",
    "directive.constrainedmovetime",
    "directive.dontmoveoff",
    "directive.movedelta",
    "directive.noraiseonmove",
    "directive.noraiseonresize",
    "directive.opaquemove",
}
ARGUMENT_ACTIONS = {
    "f.colormap", "f.cut", "f.exec", "f.file", "f.function", "f.menu",
    "f.priority", "f.source", "f.startwm", "f.warpring", "f.warpto",
    "f.warptoiconmgr", "f.warptoscreen",
}


def canonical(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def action_fixture(entry: dict[str, object]) -> str:
    identifier = str(entry["id"])
    name = str(entry["name"])
    if identifier == "action.f-cut-alias":
        action = '^ "cut-buffer"'
    elif identifier == "action.f-exec-alias":
        action = '! "true"'
    elif identifier == "action.unrecognized-f-action":
        action = 'f.future-action "argument"'
    else:
        action = name
        if name in ARGUMENT_ACTIONS:
            action += ' "argument"'
    return f"Button1 = : root : {action}\n"


CONSTRUCT_FIXTURES = {
    "construct.bare-or-list-directives": 'NoTitle\nAutoRaise { "xterm" }\n',
    "construct.base-0-numbers": "MoveDelta 0x10\n",
    "construct.binding-context-alternatives": "Button1 = : window|title|icon|root|frame|iconmgr|all : f.nop\n",
    "construct.braces-and-nested-balanced-blocks": 'FutureBlock { "outer" { "inner" } }\n',
    "construct.button-range-1-through-32": "Button32 = : root : f.nop\n",
    "construct.case-insensitive-keywords-and-actions": "bUtToN1 = : rOoT : F.MOVE\n",
    "construct.comments": "# comment accepted by the lexer\nNoTitle\n",
    "construct.function-action-sequences": 'Function "sequence" { f.move f.raise f.nop }\n',
    "construct.menu-definitions-and-items": 'Menu "ops" { "Move" f.move "Exit" f.quit }\n',
    "construct.modifier-alternatives": "Button1 = shift|control|lock|mod5 : root : f.nop\n",
    "construct.named-window-binding-context": '"F1" = : "xterm" : f.nop\n',
    "construct.newlines": "\n\nNoTitle\n\n",
    "construct.parenthesized-menu-colors": 'Menu "ops" ("white":"black") { "Noop" ("black":"white") f.nop }\n',
    "construct.quoted-strings-and-backslash-escapes": 'TitleFont "Sans\\ Bold"\n',
    "construct.signed-integer-option": "MoveDelta -3\n",
    "construct.title-button-bitmap-action-assignment": 'LeftTitleButton "dot" = f.nop\n',
    "construct.unknown-statement-skipping": 'FutureOption "ignored"\n',
    "construct.window-name-lists": 'NoTitle { "xterm" "xclock" }\n',
    "construct.word-tokens": "Button2 = : root : f.nop\n",
}


# These entries describe permissive behavior in the immutable M0 snapshot.
# M2 deliberately rejects them to match the frozen twm grammar, so their
# historical fixtures remain useful as negative regressions.
REFERENCE_REJECTIONS = {
    "action.unrecognized-f-action",
    "construct.base-0-numbers",
    "construct.braces-and-nested-balanced-blocks",
    "construct.button-range-1-through-32",
    "construct.signed-integer-option",
    "construct.unknown-statement-skipping",
    "directive.unrecognized-statement-fallback",
}


BOOL_DIRECTIVES = {
    "AutoRelativeResize", "ClientBorderWidth", "DecorateTransients", "DontMoveOff",
    "NoCaseSensitive", "NoMenuShadows", "NoRaiseOnDeiconify", "NoRaiseOnMove",
    "NoRaiseOnResize", "NoTitleFocus", "OpaqueMove", "RandomPlacement", "ShowIconManager",
}
INT_DIRECTIVES = {
    "BorderWidth", "ButtonIndent", "ConstrainedMoveTime", "FramePadding",
    "MenuBorderWidth", "MoveDelta", "TitleButtonBorderWidth", "TitlePadding",
}
STRING_DIRECTIVES = {
    "IconFont", "IconManagerFont", "MaxWindowSize", "MenuFont", "ResizeFont",
    "TitleFont", "UsePPosition",
}
COLOR_ENTRIES = {
    "BorderColor", "MenuBackground", "MenuBorderColor", "MenuForeground",
    "MenuTitleBackground", "MenuTitleForeground", "TitleBackground", "TitleForeground",
}
BLOCK_DIRECTIVES = {
    "Cursors": 'Cursors { Button "left_ptr" }\n',
    "DontIconifyByUnmapping": 'DontIconifyByUnmapping { "xterm" }\n',
    "DontSqueezeTitle": 'DontSqueezeTitle { "xterm" }\n',
    "IconifyByUnmapping": 'IconifyByUnmapping { "xterm" }\n',
    "IconManagerDontShow": 'IconManagerDontShow { "xterm" }\n',
    "IconManagers": 'IconManagers { "main" "100x10" 1 }\n',
    "IconManagerShow": 'IconManagerShow { "xterm" }\n',
    "Icons": 'Icons { "xterm" "xterm.xbm" }\n',
    "NoHighlight": 'NoHighlight { "xterm" }\n',
    "NoStackMode": 'NoStackMode { "xterm" }\n',
    "NoTitleHighlight": 'NoTitleHighlight { "xterm" }\n',
    "Pixmaps": 'Pixmaps { TitleHighlight "title.xbm" }\n',
    "SaveColor": 'SaveColor { "red" }\n',
    "SqueezeTitle": 'SqueezeTitle { "xterm" center 0 0 }\n',
    "WarpCursor": 'WarpCursor { "xterm" }\n',
    "WindowRing": 'WindowRing { "xterm" }\n',
}


def directive_fixture(entry: dict[str, object]) -> str:
    identifier = str(entry["id"])
    name = str(entry["name"])
    if identifier == "directive.buttonn-binding":
        return "Button7 = control : window : f.raise\n"
    if identifier == "directive.quoted-key-binding":
        return '"F7" = shift : all : f.exec "true"\n'
    if identifier == "directive.unrecognized-statement-fallback":
        return 'FutureDirective "ignored"\n'
    if name in BOOL_DIRECTIVES:
        return f"{name}\n"
    if name in INT_DIRECTIVES:
        return f"{name} 7\n"
    if name in STRING_DIRECTIVES:
        return f'{name} "Sans 10"\n'
    if name in COLOR_ENTRIES:
        return f'Color {{ {name} "red" }}\n'
    if name in BLOCK_DIRECTIVES:
        return BLOCK_DIRECTIVES[name]
    if name in {"Color", "Grayscale", "Greyscale", "Monochrome"}:
        return f'{name} {{ BorderColor "gray" }}\n'
    if name == "AutoRaise":
        return 'AutoRaise { "xterm" }\n'
    if name == "Function":
        return 'Function "sequence" { f.move f.raise }\n'
    if name == "LeftTitleButton":
        return 'LeftTitleButton "dot" = f.iconify\n'
    if name == "MakeTitle":
        return 'MakeTitle { "xterm" }\n'
    if name == "Menu":
        return 'Menu "ops" { "Noop" f.nop }\n'
    if name == "NoTitle":
        return 'NoTitle { "xterm" }\n'
    if name == "RightTitleButton":
        return 'RightTitleButton "resize" = f.resize\n'
    if name == "StartIconified":
        return 'StartIconified { "xterm" }\n'
    raise ValueError(f"no dedicated syntax fixture for {identifier}: {name}")


def syntax_fixture(entry: dict[str, object]) -> str:
    category = str(entry["category"])
    if category == "action":
        return action_fixture(entry)
    if category == "construct":
        return CONSTRUCT_FIXTURES[str(entry["id"])]
    if category == "directive":
        return directive_fixture(entry)
    raise ValueError(f"runtime-only feature has no syntax fixture: {entry['id']}")


def exact_line(source_root: Path, location: str) -> str:
    path_text, line_text = location.rsplit(":", 1)
    lines = (source_root / path_text).read_text(encoding="utf-8").splitlines()
    line = lines[int(line_text) - 1].strip()
    if not line:
        raise ValueError(f"source contract location is blank: {location}")
    return line


def action_dispatch_check(source_root: Path, entry: dict[str, object]) -> dict[str, str]:
    identifier = str(entry["id"])
    if identifier == "action.f-exec-alias":
        enum_name = "WTWM_ACTION_EXEC"
    else:
        spelling = str(entry["name"]).split()[0]
        config_text = (source_root / "src/config.c").read_text(encoding="utf-8")
        match = re.search(
            r'(?:ACT(?:_ARG)?\(|\{)"' + re.escape(spelling)
            + r'",\s*(WTWM_ACTION_[A-Z0-9_]+)',
            config_text,
        )
        if match is None:
            raise ValueError(f"effective action lacks an action enum: {identifier}")
        enum_name = match.group(1)
    wtwm_lines = (source_root / "src/wtwm.c").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(wtwm_lines, 1):
        if re.search(rf"\bcase\s+{re.escape(enum_name)}\b", line):
            return {"location": f"src/wtwm.c:{index}", "contains": enum_name}
    raise ValueError(f"effective action lacks execute_action dispatch: {identifier} ({enum_name})")


def action_parse_check(source_root: Path, entry: dict[str, object]) -> dict[str, str]:
    identifier = str(entry["id"])
    spelling = str(entry["name"]).split()[0]
    config_lines = (source_root / "src/config.c").read_text(encoding="utf-8").splitlines()
    if identifier == "action.f-exec-alias":
        patterns = ['strcmp(spelling, "!")']
    else:
        patterns = [
            'ACT("' + spelling + '",',
            'ACT_ARG("' + spelling + '",',
            '{"' + spelling + '",',
        ]
    for pattern in patterns:
        for index, line in enumerate(config_lines, 1):
            if pattern in line:
                return {"location": f"src/config.c:{index}", "contains": pattern}
    raise ValueError(f"effective action lacks its exact parser mapping: {identifier}")


RUNTIME_CONTRACT_FRAGMENTS = {
    "runtime_dispatch.auto-raise-rule-dispatch": [
        "toplevel->auto_raise = toplevel->server->config.auto_raise ||"
    ],
    "runtime_dispatch.button-binding-dispatch": ["dispatch_binding(server, WTWM_BINDING_BUTTON,"],
    "runtime_dispatch.configuration-load-at-startup": ["wtwm_config_load(&server.config,"],
    "runtime_dispatch.configured-frame-and-title-rendering": [
        "static int configured_title_bar_height("
    ],
    "runtime_dispatch.execute-configured-action": ["switch (action->type)"],
    "runtime_dispatch.function-action-recursion": [
        "static bool push_action_frame(",
        "struct action_frame *frame =",
    ],
    "runtime_dispatch.key-binding-dispatch": ["dispatch_binding(server, WTWM_BINDING_KEY,"],
    "runtime_dispatch.menu-definition-lookup-and-rendering": ["strcmp(server->config.menus[i].name, name)"],
    "runtime_dispatch.menu-item-action-dispatch": [
        "execute_action(server, target, &action,"
    ],
    "runtime_dispatch.start-iconified-rule-dispatch": ["server->config.start_iconified_windows"],
    "runtime_dispatch.title-button-action-dispatch": [
        "&hit.toplevel->title_buttons[hit.title_button_index].action;"
    ],
    "runtime_dispatch.title-decoration-rule-dispatch": [
        "set_decorated(toplevel, should_decorate(toplevel));"
    ],
}

DIRECTIVE_CONTRACT_FRAGMENTS = {
    "directive.autoraise": [
        "toplevel->auto_raise = toplevel->server->config.auto_raise ||",
        "&toplevel->server->config.auto_raise_windows,",
    ],
    "directive.bordercolor": [
        'configured_color(server, "BorderColor", "black", toplevel, border);'
    ],
    "directive.borderwidth": ["return server->config.border_width;"],
    "directive.buttonn-binding": ["dispatch_binding(server, WTWM_BINDING_BUTTON,"],
    "directive.color": [
        'configured_color(server, "BorderColor", "black", toplevel, border);'
    ],
    "directive.function": [
        "static bool push_action_frame(",
        "struct action_frame *frame =",
    ],
    "directive.lefttitlebutton": [
        "if (configured->right_side != (side != 0)) continue;"
    ],
    "directive.maketitle": ["&toplevel->server->config.make_title_windows,"],
    "directive.menu": ["strcmp(server->config.menus[i].name, name)"],
    "directive.menubackground": [
        '"MenuBackground", "white", NULL);'
    ],
    "directive.menubordercolor": [
        'configured_color(server, "MenuBorderColor", "black", NULL, border);'
    ],
    "directive.menuborderwidth": [
        "visual.menu_border_width = server->config.menu_border_width;"
    ],
    "directive.menufont": [
        "server->config.menu_font, normal_foreground, &widths[i], &heights[i]);"
    ],
    "directive.menuforeground": [
        '"MenuForeground", "black", NULL);'
    ],
    "directive.menutitlebackground": [
        '"MenuTitleBackground", "white", NULL);'
    ],
    "directive.menutitleforeground": [
        '"MenuTitleForeground", "black", NULL);'
    ],
    "directive.notitle": [
        "return wtwm_window_has_title(toplevel->server->config.no_title,",
        "&toplevel->server->config.no_title_windows,",
    ],
    "directive.righttitlebutton": [
        "if (configured->right_side != (side != 0)) continue;"
    ],
    "directive.quoted-key-binding": ["dispatch_binding(server, WTWM_BINDING_KEY,"],
    "directive.starticonified": [
        "&toplevel->server->config.start_iconified_windows,"
    ],
    "directive.titlebackground": [
        "wlr_scene_rect_set_color(toplevel->title, title_color);"
    ],
    "directive.titlefont": ["toplevel->server->config.title_font, foreground, &width, &height);"],
    "directive.titleforeground": [
        "wlr_scene_rect_set_color(button->border, foreground);"
    ],
    "directive.titlepadding": ["visual.title_padding = config->title_padding;"],
}


def find_wtwm_check(source_root: Path, fragment: str) -> dict[str, str]:
    lines = (source_root / "src/wtwm.c").read_text(encoding="utf-8").splitlines()
    matches = [index for index, line in enumerate(lines, 1) if fragment in line]
    if len(matches) != 1:
        raise ValueError(f"source contract fragment is not unique: {fragment!r} ({matches})")
    return {"location": f"src/wtwm.c:{matches[0]}", "contains": fragment}


def source_checks(source_root: Path, entry: dict[str, object]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    category = str(entry["category"])
    if category == "action":
        checks.append(action_parse_check(source_root, entry))
        checks.append(action_dispatch_check(source_root, entry))
    elif category == "runtime_dispatch":
        fragments = RUNTIME_CONTRACT_FRAGMENTS.get(str(entry["id"]))
        if fragments is None:
            raise ValueError(f"runtime dispatch lacks a specific contract: {entry['id']}")
        checks.extend(find_wtwm_check(source_root, fragment) for fragment in fragments)
    else:
        fragments = DIRECTIVE_CONTRACT_FRAGMENTS.get(str(entry["id"]))
        if fragments is not None:
            checks.extend(find_wtwm_check(source_root, fragment) for fragment in fragments)
            return sorted(checks, key=lambda item: (item["location"], item["contains"]))
        locations = [
            str(value) for value in entry["evidence"]  # type: ignore[index]
            if str(value).startswith("src/wtwm.c:")
        ]
        if not locations:
            raise ValueError(f"effective feature lacks compositor evidence: {entry['id']}")
        for location in locations:
            checks.append({"location": location, "contains": exact_line(source_root, location)})
    return sorted(checks, key=lambda item: (item["location"], item["contains"]))


def build(source_root: Path) -> tuple[dict[str, object], str]:
    audit = json.loads((source_root / AUDIT_PATH).read_text(encoding="utf-8"))
    mappings = []
    for feature in audit["entries"]:
        feature_id = str(feature["id"])
        tests = []
        if feature["category"] != "runtime_dispatch":
            expected = "reject" if feature_id in REFERENCE_REJECTIONS else "accept"
            tests.append({
                "test_id": "test.current-feature.syntax",
                "path": TEST_PATH,
                "meson_test": MESON_TEST,
                "case": feature_id,
                "dimension": "syntax",
                "expected": expected,
                "assertions": [
                    f"The dedicated {feature_id} fixture is expected to {expected} under the frozen grammar.",
                    "This parser result does not claim native runtime or reference equivalence.",
                ],
                "fixture": syntax_fixture(feature),
                "checks": [],
            })
        if feature["native_wayland_status"] == "effective":
            tests.append({
                "test_id": "test.current-feature.source-contract",
                "path": TEST_PATH,
                "meson_test": MESON_TEST,
                "case": feature_id,
                "dimension": "source_contract",
                "expected": "not-applicable",
                "assertions": [
                    "Source-contract coverage is structural and does not claim runtime behavior or parity.",
                    f"The exact implementation/dispatch source contract for {feature_id} remains present.",
                ],
                "fixture": "",
                "checks": source_checks(source_root, feature),
            })
        if feature_id in INTERACTION_RUNTIME_FEATURES:
            tests.append({
                "test_id": INTERACTION_RUNTIME_ID,
                "path": INTERACTION_RUNTIME_PATH,
                "meson_test": INTERACTION_RUNTIME_TEST,
                "case": feature_id,
                "dimension": "runtime",
                "expected": "pass",
                "assertions": [
                    f"The Linux headless compositor runner exercises {feature_id} through synthetic pointer/button input and TRACE/STATE assertions.",
                    "The source-derived twm interaction contract supplies the exact expected threshold, geometry, timing, and render-path results.",
                ],
                "fixture": "",
                "checks": [],
            })
        mappings.append({
            "feature_id": feature_id,
            "category": feature["category"],
            "implementation_status": feature["native_wayland_status"],
            "tests": sorted(tests, key=lambda item: (item["dimension"], item["test_id"])),
        })
    dimensions = ["syntax", "source_contract", "runtime"]
    result = {
        "schema_version": "1.1",
        "current_audit_path": AUDIT_PATH,
        "feature_count": len(mappings),
        "dimension_policy": {
            "enum": dimensions,
            "syntax": "Executes a dedicated parser fixture; never implies a runtime effect.",
            "source_contract": "Checks an exact implementation or dispatch site; explicitly non-runtime and non-behavioral.",
            "runtime": "Executes observable compositor behavior; no portable runtime cases are available in Milestone 0.",
        },
        "test_catalog": [
            {
                "test_id": INTERACTION_RUNTIME_ID,
                "path": INTERACTION_RUNTIME_PATH,
                "meson_test": INTERACTION_RUNTIME_TEST,
                "dimension": "runtime",
            },
            {
                "test_id": "test.current-feature.source-contract",
                "path": TEST_PATH,
                "meson_test": MESON_TEST,
                "dimension": "source_contract",
            },
            {
                "test_id": "test.current-feature.syntax",
                "path": TEST_PATH,
                "meson_test": MESON_TEST,
                "dimension": "syntax",
            },
        ],
        "entries": mappings,
    }
    dimension_counts = Counter(
        test["dimension"] for item in mappings for test in item["tests"]
    )
    category_counts = Counter(item["category"] for item in mappings)
    category_dimension_counts = Counter(
        (item["category"], test["dimension"])
        for item in mappings for test in item["tests"]
    )
    status_counts = Counter(item["implementation_status"] for item in mappings)
    lines = [
        "# Current feature test coverage",
        "",
        "`reference/audits/feature-test-map.json` is the authoritative exit-gate",
        "mapping layered over the immutable current-implementation audit snapshot.",
        "Portable mappings are executed by Meson's `current feature coverage` test;",
        "runtime mappings name their separately registered compositor integration test.",
        "Syntax cases use one dedicated accepted or rejected configuration fixture per feature. Source-contract",
        "cases check exact implementation/dispatch sites but are explicitly non-runtime and",
        "non-behavioral; they do not upgrade compatibility-ledger runtime or parity claims.",
        "",
        f"**Features mapped:** {len(mappings)} of {len(audit['entries'])}",
        "",
        f"**Automated case mappings:** {sum(dimension_counts.values())}",
        "",
        "## Mapping counts",
        "",
        "| Dimension | Count |",
        "| --- | ---: |",
    ]
    for dimension in dimensions:
        lines.append(f"| `{dimension}` | {dimension_counts.get(dimension, 0)} |")
    lines += [
        "",
        "| Category | Features | Syntax | Source contract | Runtime |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for category, count in sorted(category_counts.items()):
        lines.append(
            f"| `{category}` | {count} | "
            f"{category_dimension_counts.get((category, 'syntax'), 0)} | "
            f"{category_dimension_counts.get((category, 'source_contract'), 0)} | "
            f"{category_dimension_counts.get((category, 'runtime'), 0)} |"
        )
    lines += ["", "| Implementation status | Features |", "| --- | ---: |"]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines += [
        "",
        "## Limitations",
        "",
        "- Runtime mappings name separately registered Linux headless tests; the portable",
        "  profile still executes their tamper-resistant wiring contracts while wlroots",
        "  behavior runs in the compositor-enabled CI jobs.",
        "- The immutable current audit status records its audited commit. A newer runtime",
        "  mapping is current behavioral evidence and does not rewrite that historical field.",
        "- Parser acceptance proves only that the feature spelling/form loads. It does not",
        "  prove an observable effect, Xwayland behavior, or equivalence with X11 `twm`.",
        "- The immutable current audit retains the tests visible at its audited commit; this",
        "  map is the authoritative current test-coverage layer for the Milestone 0 gate.",
        "",
    ]
    return result, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    feature_map, summary = build(source_root)
    outputs = {
        source_root / MAP_PATH: canonical(feature_map),
        source_root / SUMMARY_PATH: summary,
    }
    if args.check:
        stale = [
            str(path.relative_to(source_root))
            for path, value in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != value
        ]
        if stale:
            print("stale feature-test artifacts: " + ", ".join(stale))
            return 1
        print("feature-test map and summary are deterministic")
        return 0
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        print(f"wrote {path.relative_to(source_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
