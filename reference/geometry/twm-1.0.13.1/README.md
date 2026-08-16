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

`baseline.json` is the reviewed, normalized result from GitHub Actions workflow
run `31966479997` at commit `d04249381a987f2ca65516cf163029909179096a`.
`matrix.json` records the workflow artifact ID, archive digest, captured matrix
hash, and baseline-file hash. Every `reference-twm` run validates the new live
capture and compares its geometry payload byte-for-byte with this committed
baseline; only the self-referential source-matrix hash is excluded from that
comparison.

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
