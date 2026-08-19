# Upstream configuration inventory

`twm-1.0.13.1.json` is the versioned, machine-readable inventory of syntax
accepted by the frozen X.Org `twm` 1.0.13.1 reference. It is an upstream
language inventory, not the compatibility ledger: it deliberately contains no
claims about `wtwm` parser support, runtime support, Wayland translations, or
test coverage.

## Schema

The JSON document has these top-level fields:

- `schema_version`: inventory format version.
- `upstream`: release identity, repository-relative archive path, and pinned
  SHA-256.
- `category_order` and `category_descriptions`: the complete category
  vocabulary and its canonical ordering.
- `source_observations`: exact archive-member lines showing how the manual
  describes the configuration model and how the upstream defaults exercise
  bindings and menus.
- `keywords`: every row of `src/parse.c`'s `keytable`, in source order. Each
  entry records a stable `keyword.<accepted-spelling>` ID, the case-folded
  spelling, parser token/value, one or more scope categories, and exact source
  evidence.
- `grammar`: every alternative of every production between the two `%%`
  delimiters in `src/gram.y`, in source order. Semantic C actions are removed
  from `syntax`; an empty string is an empty production. IDs have the stable
  form `grammar.<production>.<one-based-alternative>`.
- `lexical_forms`: every successful lexer rule in `src/lex.l`, excluding the
  final error rule. These include delimiters, strings, numbers, comments,
  whitespace, and the `!`/`^` action shorthands.

Every evidence object names a path *inside the signed release archive*, a
one-based line number, and the exact text at that line. Evidence therefore does
not depend on convenience copies outside the archive.

## Inventory method

The parser table is the authority for accepted keyword spellings. This is
important because it exposes accepted aliases and legacy actions that are
absent from, or commented out of, the manual. The complete grammar supplies
binding forms, contexts, modifiers, menu/function constructs, lists, cursors,
pixmaps, colors, icons, icon managers, placement, title buttons, and literal
argument shapes. The lexer supplies syntax which has no keyword-table row.

The upstream manual was inspected to cross-check the intended configuration
domains and argument terminology. `src/system.twmrc`, the input to the
compiled-in defaults, was inspected to cross-check actual upstream binding,
function, and menu forms. Exact observation lines from both are retained in the
JSON, while completeness is measured against the code that accepts input.

Categories are non-exclusive. For example, `iconmgr` is both a binding context
and a cursor role, and `meta` is both a modifier and the grammar's historical
icon-manager-context alias. Keeping all applicable categories avoids silently
losing accepted uses behind a single primary label.

## Deterministic validation and regeneration

Run the offline validator from the repository root:

```sh
python3 -B tests/reference/validate_upstream_inventory.py \
  --source-root . --self-test-tamper
```

The validator checks the pinned archive hash, independently reconstructs all
three ordered entry sets from archive members, verifies stable IDs and category
ordering, and checks every evidence line byte-for-byte. Omitting, adding,
editing, or reordering an entry fails. Its tamper self-test also mutates one
property at a time to prove those failure paths remain active.

After an explicitly approved reference-version or schema change, regenerate
the checked-in JSON with:

```sh
python3 -B tests/reference/validate_upstream_inventory.py \
  --source-root . --write
```

Do not use regeneration to change the compatibility status of `wtwm`; that
belongs in the separate compatibility ledger.
