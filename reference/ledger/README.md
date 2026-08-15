# Compatibility ledger

`twm-1.0.13.1.json` is the authoritative, machine-readable compatibility
ledger for the frozen X.Org `twm` 1.0.13.1 reference. Its 384 rows correspond
one-for-one and in order to the 200 keyword, 168 grammar-alternative, and 16
lexer-form rows in
[`../inventory/twm-1.0.13.1.json`](../inventory/twm-1.0.13.1.json).

The inventory answers what upstream accepts. The ledger provides the stable
place to assess how `wtwm` handles each accepted form. Every ledger row embeds
the complete corresponding inventory row, including its categories and exact
upstream source evidence, so an assessment cannot become detached from the
syntax it describes.

## Assessment state

This initial ledger deliberately makes no claim about the current
implementation. Its `assessment_policy.phase` is `inventory-initialized`, and
all of these required dimensions are explicitly `unassessed`:

- syntax support;
- runtime support;
- native Wayland behavior;
- Xwayland behavior;
- test coverage; and
- known visual or semantic differences.

Milestone 0 implementation item 4 is responsible for auditing the current
tree and replacing those values with evidence-backed assessments. The existing
human-readable compatibility notes are not a substitute for that audit.

## Schema

[`schema-1.0.json`](schema-1.0.json) is a versioned JSON Schema. It fixes all
required fields and ordered enum vocabularies. Syntax status is separate from
runtime/protocol behavior so successfully parsing a construct cannot be
mistaken for implementing it. Native Wayland and Xwayland have independent
status fields.

Test coverage uses structured mappings rather than bare filenames. Each
mapping requires a stable test ID, repository-relative path below `tests/`, an
exact case name, the dimensions exercised, and explicit assertions. Known
differences are split into visual and semantic records, with exact
repository-relative evidence locations and links to the row's test mappings.

The schema intentionally contains no timestamps, host paths, working-tree
paths, or generated commit IDs. Upstream identity comes from the frozen
inventory. Assessment evidence must use canonical repository-relative paths.

## Offline validation

Run the validator from the repository root:

```sh
python3 -B tests/reference/validate_compatibility_ledger.py \
  --source-root . --self-test-tamper
```

The validator works offline. It rejects missing, extra, duplicate, or reordered
rows; any change to the embedded upstream row; invalid or reordered enums;
missing required fields; non-canonical JSON; malformed test mappings;
nonexistent or nondeterministic repository paths; malformed difference
evidence; pre-audit claims; and schema tampering. Its self-test mutates the
ledger and schema to prove those rejection paths remain active.

The checked-in ledger was initialized deterministically with:

```sh
python3 -B tests/reference/validate_compatibility_ledger.py \
  --source-root . --write
```

`--write` resets every assessment to `unassessed`. Do not run it after the
Milestone 0 implementation audit has begun. Any future schema or frozen
reference change requires explicit review and a deliberate migration rather
than ad hoc regeneration.
