# Parity certification

The final 1.0 certification manifest is
`reference/certification/m10-release-gates.json`. It mirrors the eleven final
1.0 release gates in `README.md` in their authoritative order. A gate has only
two valid states: `pending` or `passed`. The initial manifest intentionally
keeps every gate pending because a task checkbox, a local smoke test, or a
successful CI job is not itself complete release-certification evidence.

The project cannot claim full observable `twm` parity until all eleven gates
are `passed`, every evidence report validates, and
`full_parity_claim_allowed` is `true`. The validator derives that boolean from
the gate states and rejects a premature claim.

## Validate the manifest

Run the normal validation and its deterministic tamper test from the repository
root:

```sh
python3 -B tests/certification/validate_m10_release_gates.py
python3 -B tests/certification/validate_m10_release_gates.py \
  --self-test-tamper
```

The tamper test proves that an unsupported `passed` status, a missing evidence
file, and a premature full-parity claim are rejected. It uses temporary files
and does not change the manifest.

## Evidence report contract

A passed gate names exactly one consolidated, repository-relative JSON report.
The report and every artifact path referenced by its result must be regular,
tracked files inside the repository. Symlinks, untracked output, absolute
paths, parent-directory traversal, dirty-source results, and missing files are
rejected. This keeps CI artifacts or a machine-local log from silently becoming
release evidence.

Every report has these exact top-level fields:

```json
{
  "schema_version": 1,
  "gate_id": "the matching manifest gate ID",
  "reference": "twm 1.0.13.1",
  "recorded_at": "2026-08-19T12:00:00Z",
  "revision": {
    "commit": "a full 40- to 64-digit lowercase hexadecimal object ID",
    "clean": true
  },
  "result": {}
}
```

`result` is gate-specific and is validated strictly:

| Gate ID | Required proof in `result` |
| --- | --- |
| `grammar-coverage` | Exactly 100 percent coverage, equal positive covered/total production counts, and no uncovered productions. |
| `builtin-action-coverage` | Exactly 100 percent coverage, equal positive covered/total action counts, and no uncovered actions. |
| `compatibility-entry-closure` | The frozen ledger path, a positive entry count, and zero partial, parsed-only, or unexplained entries. |
| `canonical-geometry` | The canonical one-output 1x profile, at least one scenario, zero geometry differences, and a checked-in comparison artifact. |
| `focus-stacking` | At least one scenario, zero unexplained focus and stacking differences, and a checked-in differential trace. |
| `golden-images` | A positive image count, review counts with zero unreviewed differences, and a checked-in review log. |
| `soak-72-hours` | RFC 3339 start/end times covering at least 72 continuous hours, matching duration, success, zero crashes/hangs/protocol violations/unbounded leaks, and a checked-in log. |
| `supported-package-matrix` | The checked-in support policy and successful install, upgrade, uninstall, and reinstall evidence for both supported Debian 13 architectures: amd64 and arm64. |
| `deployment-environments` | Passing, checked-in results for exactly nested Wayland, VM login, and physical hardware. Physical evidence must identify the hardware and report `virtualized=false`. |
| `blind-ab-evaluation` | The canonical profile, a checked-in blind protocol, at least two distinct experienced-`twm` reviewers with trial results, and no repeatable distinguishing behavior. |
| `wayland-translation-documentation` | Checked-in manual, ledger, and audit paths, plus the same non-empty, unique set of unavoidable translation IDs in both documentation inventories. |

The validator's field-error output is the executable specification for the
exact gate-specific object keys. Unknown or omitted fields fail validation so
that a report cannot look complete while quietly dropping a required result.

## Collect and promote evidence

1. Start from the clean release-candidate commit recorded in the report. Run
   the complete scenario or audit for one gate, not a reduced local smoke
   profile.
2. Preserve the raw logs, traces, images, reviewer results, platform identity,
   and consolidated JSON report under a stable repository path. Do not use an
   expiring CI artifact URL as the evidence path.
3. Review the result against the gate-specific contract above. Commit the
   report and all paths it references so the validator can establish that the
   evidence is checked in.
4. Change only that manifest gate from `pending` to `passed`, replace its empty
   `evidence` array with the consolidated report path, and set
   `pending_reason` to `null`.
5. Run both validation commands. Set `full_parity_claim_allowed` to `true` only
   in the change that promotes the eleventh and final gate.

Some collection must happen outside ordinary local and GitHub Actions runs. In
particular, do not promote the soak gate from the short stability smoke run;
the recorded timestamps must cover a successful continuous 72 hours. Do not
promote package coverage from compiler jobs; package lifecycle results are
required for every declared distribution/architecture pair. Environment
certification needs separate nested, login-session VM, and non-virtualized
physical-machine results. Blind A/B evidence must preserve the protocol and
per-reviewer results without exposing reviewer identity unnecessarily.

If new platforms become supported, update the support policy and the
validator's required package matrix before collecting release evidence. A
change to the reference version or to any final gate likewise requires an
explicit review of both the manifest and validator; silently adding, removing,
reordering, or retitling a gate fails validation.
