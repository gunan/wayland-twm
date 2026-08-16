# Reference `twm` geometry matrix

This directory defines the live X11 oracle for the Milestone 4 frame-geometry
work. `matrix.json` pins the frozen `twm` release and Debian Trixie X11
environment, the exact configurations, and the ordered client cases. The
matrix covers ordinary decorated windows, both outcomes of
`ClientBorderWidth`, global `NoTitle` with a `MakeTitle` exception, transient
title suppression and `DecorateTransients`, three distinct
border/padding/font profiles, and four `WM_NORMAL_HINTS` profiles.

The purpose-built Xlib client reports the root-relative inner and outer boxes
of the client, reparent frame, and direct title child. The normalizer derives
the left, right, top, and bottom frame extents from those observations. XIDs,
display numbers, process IDs, timestamps, and temporary paths are omitted.
Each case must reach three consecutive identical observations, and the full
matrix is run twice on disjoint Xvfb displays and compared byte for byte.

There is intentionally no checked-in geometry result yet. This contract was
added from a host that cannot run the pinned Debian Trixie X11 environment, so
claiming a golden baseline would be unverifiable. The `reference-twm` CI job
runs the live oracle and uploads `geometry-matrix.json`. That normalized
artifact is suitable as the reference half of the later `wtwm` geometry
differential. A baseline may be committed only after a successful CI artifact
is reviewed and its run provenance is recorded; until then the corresponding
Roadmap checkbox must remain unchecked.

The portable Meson test validates configuration and observer hashes, required
case coverage, normalization invariants, and deliberate tamper cases. The live
capture additionally checks that the title spans the frame top, frame-border
selection follows `ClientBorderWidth`, side and bottom extents equal the frame
border, titleless top extent equals the border, and decorated top extent equals
the observed title outer height.

`cross-product.json` closes the representative-set limitation without
duplicating 48 handwritten cases. Its four ordered axes generate every
combination of titled/untitled policy, frame/client border ownership, normal or
transient decoration policy, and none/min-max/base-increment/aspect size hints.
The generated 48 cases and 12 configurations have canonical hashes. A portable
tamper validator checks those hashes, cardinalities, and the complete Cartesian
coverage.

The controlled Linux `x11-differential` job runs those generated clients under
both frozen `twm` and wtwm twice. Each backend must converge for three equal
observations. The comparison is exact over root-relative client inner boxes,
frame outer boxes, title outer boxes, and all four extents; it has no geometry
case, field, or numeric-tolerance exclusions. The job always uploads the report
and success or failure evidence.
