# Current feature test coverage

`reference/audits/feature-test-map.json` is the authoritative exit-gate
mapping layered over the immutable current-implementation audit snapshot.
Portable mappings are executed by Meson's `current feature coverage` test;
runtime mappings name their separately registered compositor integration test.
Syntax cases use one dedicated accepted or rejected configuration fixture per feature. Source-contract
cases check exact implementation/dispatch sites but are explicitly non-runtime and
non-behavioral; they do not upgrade compatibility-ledger runtime or parity claims.

**Features mapped:** 134 of 134

**Automated case mappings:** 191

## Mapping counts

| Dimension | Count |
| --- | ---: |
| `syntax` | 122 |
| `source_contract` | 54 |
| `runtime` | 15 |

| Category | Features | Syntax | Source contract | Runtime |
| --- | ---: | ---: | ---: | ---: |
| `action` | 38 | 38 | 18 | 6 |
| `construct` | 19 | 19 | 0 | 1 |
| `directive` | 65 | 65 | 24 | 7 |
| `runtime_dispatch` | 12 | 0 | 12 | 1 |

| Implementation status | Features |
| --- | ---: |
| `effective` | 54 |
| `not_applicable` | 19 |
| `parsed_only` | 61 |

## Limitations

- Runtime mappings name separately registered Linux headless tests; the portable
  profile still executes their tamper-resistant wiring contracts while wlroots
  behavior runs in the compositor-enabled CI jobs.
- The immutable current audit status records its audited commit. A newer runtime
  mapping is current behavioral evidence and does not rewrite that historical field.
- Parser acceptance proves only that the feature spelling/form loads. It does not
  prove an observable effect, Xwayland behavior, or equivalence with X11 `twm`.
- The immutable current audit retains the tests visible at its audited commit; this
  map is the authoritative current test-coverage layer for the Milestone 0 gate.
- Runtime catalog `ledger_features` name frozen upstream ledger IDs separately
  from honest current-audit runtime mappings: the no-op option runner maps three
  X-resource keywords, while the colormap runner maps `keyword.f.colormap` through
  configured-action dispatch.
