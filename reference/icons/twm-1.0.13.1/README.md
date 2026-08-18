# twm 1.0.13.1 icon reference contract

`icon-contract.json` is the frozen-source behavioral contract for Milestone 7.
It describes what the `wtwm` compositor and differential tests must reproduce;
it is not a statement that the behaviors are implemented yet.

The contract is derived from the repository-pinned X.Org `twm` 1.0.13.1
archive. It pins the archive, every source/manpage member used, and exact line
anchors. The validator reads members directly from the archive, so validation
does not depend on a locally installed `twm` or a mutable source checkout.

## Scope

The machine-readable rules freeze:

- compositor-owned icon label, bitmap, border, color, and geometry behavior;
- `IconifyByUnmapping`, `DontIconifyByUnmapping`, `ForceIcons`, `Icons`,
  `UnknownIcon`, and `IconDirectory` interaction and precedence;
- client `WM_HINTS` icon window, pixmap, and position precedence, including
  property changes after initial management;
- ordered icon-region first-fit allocation, gravity splits, grid rounding,
  centering, collision avoidance, release coalescing, and moved-icon behavior;
- icon-manager membership, multiple-manager routing, geometry, columns,
  ordering, visibility, drawing, active/down highlighting, focus, pointer
  behavior, and every directional or cross-manager navigation action; and
- `StartIconified`, animation endpoints/counts, transient grouping, mapping
  state, raise behavior, and cleanup.

The scenario catalog is an executable-test design. It includes deterministic
creation/destruction replay, full and partially occupied regions, multiple
managers across reference X screens and Wayland outputs, screenshot and
navigation-trace comparisons, and a 2,000-iteration/256-window churn case.
The X-screen-to-Wayland-output comparison is a harness translation; the
observable manager traversal order remains the reference oracle.

## Precedence notes

Image precedence is qualified rather than a simple bitmap list. A matching,
loadable `Icons` bitmap under `ForceIcons` causes `twm` to reject a client icon
window as well as ignore its pixmap. Without a usable forced bitmap, a client
icon window supplies the entire icon surface. A client icon pixmap beats the
non-forced `Icons` list. `UnknownIcon` and then a text-only owned icon are the
final fallbacks. A client `IconPositionHint` bypasses `IconRegion` allocation.

Manager lists use the standard `twm` match order: `WM_NAME`, then
`WM_CLASS.res_name`, then `WM_CLASS.res_class`. Lists are prepended during
parsing, so later matching records win within a field. Manager sorting uses
the icon name and is case-sensitive unless `NoCaseSensitive` is configured.

## Validation

From the repository root, run:

```sh
python3 tests/reference/validate_reference_icon_contract.py
```

An alternate JSON path may be supplied to exercise negative cases. The
validator rejects duplicate JSON keys, archive or source drift, stale line
anchors, missing directives/actions/rules, broken evidence references,
incomplete scenario coverage, and undersized lifecycle or multi-output cases.

The prose in `twm.man` is treated as public intent. Source is authoritative for
observable details that the manual leaves implicit, including image precedence,
allocation splitting/coalescing, partial-row geometry, dynamic hint updates,
and navigation wrap/filter behavior.
