# Frozen grammar fixtures

This directory turns the parser grammar from the signed `twm` 1.0.13.1
archive into a machine-checkable fixture contract.  `manifest.json` maps every
upstream grammar alternative and every keyword classified as a top-level
directive to a fixture.  All reachable alternatives require an accepted
fixture; the sole `stmt: error` alternative requires a dedicated rejected
fixture.  The manifest also includes the complete upstream sample set and
upstream system default, plus explicit unknown-keyword and truncated-input
rejection cases.

`tests/reference/validate_parser_fixture_coverage.py` verifies archive
provenance, hashes, acceptance expectations, production coverage, and that a
mapped directive actually occurs as a token in its fixture.  Its self-test
mutates manifests and fixture content in memory to prove omissions, false
mappings, hash drift, and lost rejection coverage are detected.

`tests/reference/compare_reference_parser.py` runs the accepted and rejected
fixtures through both `wtwm-config` and the real frozen `twm` binary under
Xvfb.  It normalizes accept/reject status, diagnostics, and the deterministic
`wtwm-config` dump into JSON before comparing results.  For the reference side,
the JSON also records the ordered Bison reduction trace from the frozen
`gram.y` and all ten normalized effective `ScreenInfo` fields observed
immediately after `ParseTwmrc`.  A full comparison fails unless every field
matches and the accepted-fixture trace union contains all 167 reachable
grammar alternatives; the dedicated rejection trace must contain `stmt: error`.
`--validate-only` checks the executable
comparison contract on hosts that cannot build or run the controlled X11
environment; it never fabricates reference observations.

The final consolidated grammar report is
`reference/certification/reports/grammar-coverage.json`. Its clean-candidate
run observed all 167 accepted alternatives and the dedicated `stmt: error`
alternative, covering all 51 grammar productions with no uncovered production.

After the portable fixture test passes, retain the full Debian/X11 comparison
artifact and use it to migrate the generated compatibility artifacts:

```sh
tests/reference/run_reference_parser_comparison.sh \
    . build/wtwm-config /tmp/wtwm-parser-comparison.json
python3 -B tests/reference/assess_current_implementation.py \
    --source-root . --parser-fixture-coverage \
    --parser-fixture-comparison /tmp/wtwm-parser-comparison.json
```

That opt-in migration marks only syntax and parser-test coverage complete for
the 384 frozen inventory rows, and refuses an artifact unless the aggregate
upstream `yydebug` trace reduced every mapped grammar alternative.  It
deliberately preserves the existing runtime, native Wayland, Xwayland,
difference, and visual assessments.
