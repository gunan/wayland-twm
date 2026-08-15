# Current implementation evidence inventory

This document summarizes the deterministic inventory in
`reference/audits/current-implementation.json`. It describes only evidence in the
audited repository tree. It is **not** an inventory of upstream `twm`, an
upstream-completeness statement, or a compatibility/parity assessment.

`wtwm` is a native Wayland compositor. It runs directly on Wayland/wlroots and
its native Wayland behavior is the primary subject of this inventory. The
Xwayland column does **not** describe how `wtwm` itself runs and does not make
Xwayland a runtime requirement. It records only whether the current tree has
evidence for optionally managing legacy X11 applications through Xwayland, as
required by the audit schema. That optional client path is currently recorded
as unavailable.

## Schema and collection method

Schema version `1.0` records the audited commit without a timestamp. Each entry
has a stable category-prefixed ID, category, repository spelling/name, sorted
repository-relative `path:line` evidence and test locations, native Wayland and
Xwayland evidence statuses, explicit unknowns, and a short evidence note. The
fixed categories are `directive`, `action`, `construct`, and `runtime_dispatch`.
The fixed status enum is:

- `effective`: source contains an identified native runtime consumer or action
  implementation;
- `parsed_only`: source accepts or stores the item, but the inventory found no
  native runtime effect for it;
- `unavailable`: repository evidence explicitly says the client path is absent;
- `not_applicable`: a client-runtime status does not apply to the lexical or
  grammar construct; and
- `unknown`: repository evidence does not establish behavior.

Collection was offline and evidence-only. Directive tables and statement
branches in `src/config.c` supplied parsed items; its lexer and parsing helpers
supplied constructs; the named action table supplied actions; and configuration
consumers and action call sites in `src/wtwm.c` supplied runtime dispatch paths.
Existing `tests/config_test.c` cases and `data/system.twmrc` lines were mapped
only when they directly exercise an entry. Documentation is used as evidence
for the repository's explicitly absent Xwayland lifecycle. No upstream source,
live service, inferred upstream feature, or other audit output was imported.

## Machine-checked counts

**Total entries:** 134

| Dimension | Value | Count |
| --- | --- | ---: |
| category | `action` | 38 |
| category | `construct` | 19 |
| category | `directive` | 65 |
| category | `runtime_dispatch` | 12 |
| native_wayland_status | `effective` | 54 |
| native_wayland_status | `not_applicable` | 19 |
| native_wayland_status | `parsed_only` | 61 |
| xwayland_status | `not_applicable` | 19 |
| xwayland_status | `unavailable` | 115 |

## Largest explicit evidence gaps

- **Optional legacy-X11 client behavior:** all 115 client-relevant Xwayland
  statuses are `unavailable` because the current tree documents that optional
  lifecycle integration as pending. This does not affect `wtwm` running as a
  native Wayland compositor. The inventory does not substitute native behavior
  or infer future behavior.
- **Parsed without an identified native consumer:** 61 entries are
  `parsed_only`. This includes compatibility blocks, stored options without a
  `src/wtwm.c` reader, actions that reach `execute_action`'s default branch, and
  the deliberately open-ended unknown-statement and unknown-`f.*` paths.
- **Runtime testing:** each of the 12 runtime dispatch entries explicitly notes
  that no focused runtime test is mapped. Existing tests exercise parser state;
  they do not start the compositor or validate configured interaction paths.
- **Sparse lexical/grammar tests:** constructs such as menu color tuples,
  named-window binding contexts, signed integers, and several punctuation/token
  forms have parser evidence but no direct existing test location.

These are evidence gaps, not claims that an upstream feature is missing and not
changes to any existing compatibility classification.
