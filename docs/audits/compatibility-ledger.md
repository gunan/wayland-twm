# Current implementation compatibility-ledger audit

The authoritative assessment is `reference/ledger/twm-1.0.13.1.json`; its
deterministic current-to-upstream crosswalk is
`reference/audits/current-to-ledger.json`. The audit is conservative:
an identified native consumer is `partial` until reference comparison proves
it exact or behaviorally equivalent, parser retention without a consumer is
`parsed-only`, and parser tests are never credited as runtime tests.

## Coverage and mapping method

All **384** frozen upstream rows remain in the ledger. All
**134** current-audit entries are accounted for;
**384** ledger rows have at least one current mapping and
**0** are explicitly listed as unmapped.
Exact spelling maps directives and actions to keyword rows. Explicit tables map
aliases, grammar constructs, and statement forms. The generic statement and
unknown-action paths map otherwise-unrecognized upstream spellings only as
partial syntax with parsed-only behavior. Runtime-dispatch entries are classified
as implementation plumbing because they are not upstream syntax rows.

## Machine-checked assessment counts

| Dimension | Status | Count |
| --- | --- | ---: |
| `syntax_support` | `complete` | 384 |
| `runtime_support` | `not-applicable` | 76 |
| `runtime_support` | `parsed-only` | 190 |
| `runtime_support` | `partial` | 118 |
| `native_wayland_behavior` | `not-applicable` | 76 |
| `native_wayland_behavior` | `parsed-only` | 190 |
| `native_wayland_behavior` | `partial` | 118 |
| `xwayland_behavior` | `not-applicable` | 76 |
| `xwayland_behavior` | `unavailable` | 308 |
| `test_coverage` | `complete` | 384 |
| `differences` | `known` | 308 |
| `differences` | `none-known` | 76 |

## Crosswalk counts

| Classification | Count |
| --- | ---: |
| `ledger-mapped` | 122 |
| `runtime-dispatch` | 12 |

## Largest gaps and limitations

- Xwayland behavior is unavailable for 308 behavior-relevant rows; the tree contains no optional legacy-X11 client lifecycle.
- 190 rows are parsed-only and have no identified native runtime effect.
- 0 rows have no exact existing test-case mapping. Existing mapped cases are parser-only, so no runtime, visual, native differential, or Xwayland behavior is proven.
- All 384 upstream rows have current-tree syntax evidence, but 0 rely on generic compatibility acceptance and are therefore only partial.
- No row is classified `exact`, `behaviorally-equivalent`, or `verified-no-op`: the repository has no frozen-reference runtime/differential evidence for those stronger claims.
- Source locations prove current-tree implementation paths, not pixel parity. This audit records that limitation instead of treating documentation or parser acceptance as equivalence evidence.
