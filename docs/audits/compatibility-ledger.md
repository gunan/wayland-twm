# Current implementation compatibility-ledger audit

The authoritative assessment is `reference/ledger/twm-1.0.13.1.json`; its
deterministic current-to-upstream crosswalk is
`reference/audits/current-to-ledger.json`. The immutable Milestone 0 source
audit supplies that crosswalk; this final reconciliation overlays the later
live runtime, native Wayland, Xwayland, visual, and frozen-reference suites.
Parser tests are never credited as runtime tests.

## Coverage and mapping method

All **384** frozen upstream rows remain in the ledger. All
**134** current-audit entries are accounted for;
**384** ledger rows have at least one current mapping and
**0** are explicitly listed as unmapped.
Exact spelling maps directives and actions to keyword rows. Explicit tables map
aliases, grammar constructs, and statement forms. Category-specific closure
profiles map every behavior-relevant row to live tests; grammar-only alternatives
remain not-applicable at runtime. Runtime-dispatch entries are classified
as implementation plumbing because they are not upstream syntax rows.

## Machine-checked assessment counts

| Dimension | Status | Count |
| --- | --- | ---: |
| `syntax_support` | `complete` | 384 |
| `runtime_support` | `behaviorally-equivalent` | 308 |
| `runtime_support` | `not-applicable` | 76 |
| `native_wayland_behavior` | `behaviorally-equivalent` | 304 |
| `native_wayland_behavior` | `not-applicable` | 76 |
| `native_wayland_behavior` | `verified-no-op` | 4 |
| `xwayland_behavior` | `behaviorally-equivalent` | 305 |
| `xwayland_behavior` | `not-applicable` | 76 |
| `xwayland_behavior` | `verified-no-op` | 3 |
| `test_coverage` | `complete` | 384 |
| `differences` | `known` | 308 |
| `differences` | `none-known` | 76 |

## Crosswalk counts

| Classification | Count |
| --- | ---: |
| `ledger-mapped` | 122 |
| `runtime-dispatch` | 12 |

## Closure result and limitations

- Unavoidable Wayland translation inventory IDs: 24.
- Unavailable Xwayland rows: 0.
- Parsed-only runtime rows: 0.
- Rows without exact test mappings: 0.
- All 384 upstream rows have complete current-tree syntax evidence.
- Every behavior-relevant row is classified `behaviorally-equivalent` or `verified-no-op` for runtime, native Wayland, and Xwayland behavior and has category-specific live test mappings.
- A `known` difference is an explained protocol translation, not an open gap. Canonical pixel comparisons are exact where the mapped visual differential says so; this ledger does not inflate those focused exact results into a universal pixel claim.
