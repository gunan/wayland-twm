# Current feature test coverage

`reference/audits/feature-test-map.json` is the authoritative exit-gate
mapping layered over the immutable current-implementation audit snapshot.
Every mapping is executed by the Meson `current feature coverage` test.
Syntax cases use one dedicated accepted or rejected configuration fixture per feature. Source-contract
cases check exact implementation/dispatch sites but are explicitly non-runtime and
non-behavioral; they do not upgrade compatibility-ledger runtime or parity claims.

**Features mapped:** 134 of 134

**Automated case mappings:** 176

## Mapping counts

| Dimension | Count |
| --- | ---: |
| `syntax` | 122 |
| `source_contract` | 54 |
| `runtime` | 0 |

| Category | Features | Syntax | Source contract | Runtime |
| --- | ---: | ---: | ---: | ---: |
| `action` | 38 | 38 | 18 | 0 |
| `construct` | 19 | 19 | 0 | 0 |
| `directive` | 65 | 65 | 24 | 0 |
| `runtime_dispatch` | 12 | 0 | 12 | 0 |

| Implementation status | Features |
| --- | ---: |
| `effective` | 54 |
| `not_applicable` | 19 |
| `parsed_only` | 61 |

## Limitations

- The portable profile has no wlroots compositor runtime, so the map makes zero
  `runtime` claims. Effective features receive exact `source_contract` coverage
  and, when configurable, a separate syntax case.
- Parser acceptance proves only that the feature spelling/form loads. It does not
  prove an observable effect, Xwayland behavior, or equivalence with X11 `twm`.
- The immutable current audit retains the tests visible at its audited commit; this
  map is the authoritative current test-coverage layer for the Milestone 0 gate.
