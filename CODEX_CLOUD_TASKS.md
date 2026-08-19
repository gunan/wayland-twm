# Codex Cloud task: audit the current implementation

Repository: `wtwm`

Read and follow the root `AGENTS.md` before doing anything. This is an offline,
evidence-only inventory task. Do not implement features, infer upstream `twm`
completeness, or change any compatibility claim.

## Objective

Create a deterministic inventory of what the repository currently parses,
dispatches at runtime, and tests. This raw evidence will later feed the
compatibility-ledger audit, but this task does not create or update that ledger.

## Branch and starting state

- The branch was created from base commit
  `31b49fb4f85a256ee867c06f120b6438643d7a80`.
- Assigned remote branch: `agent_impl_audit`.
- Immutable dispatch marker:
  `0999450237b2d27745067cb15565a2ecc37c1849`.
- Before editing, run `git branch --show-current`, `git status --short`, and
  `git merge-base --is-ancestor 0999450237b2d27745067cb15565a2ecc37c1849 HEAD`.
- The starting branch may be either literal `agent_impl_audit` or the Codex
  Cloud-managed branch `work`. In both cases, require a clean starting
  worktree and a successful marker-ancestry check.
- On `work`, continue without switching branches. Stop without editing on any
  other branch, a dirty starting worktree, or a failed ancestry check.

## Scope

Task-list ownership: **none**. Do not change any task checkbox.

The actual audit task may create or edit only:

- `reference/audits/current-implementation.json`
- `docs/audits/current-implementation.md`
- `tests/reference/current_implementation_audit_test.sh`

Do not edit `README.md`, any Meson file, `docs/COMPATIBILITY.md`, a ledger,
upstream reference artifacts, source implementation, existing tests, or any
other file.

## Required evidence and artifacts

Inspect the repository at the task's checked-out commit and record one JSON
entry for every currently parsed directive, action, and grammar/lexical
construct, plus every runtime dispatch path that consumes parsed configuration
or invokes a configured action. Derive all claims only from repository source,
tests, fixtures, and documentation at that commit.

`reference/audits/current-implementation.json` must use a documented,
versioned schema with deterministic formatting. At minimum, each entry must
contain:

- a stable unique ID, category (`directive`, `action`, `construct`, or
  `runtime_dispatch`), and repository spelling/name;
- exact repository source locations as `path:line` evidence;
- native Wayland and Xwayland status, each selected from a fixed documented
  enum and backed by repository evidence;
- mappings to every existing relevant test/fixture, with exact paths and test
  names or locations;
- explicit unknowns or evidence gaps instead of assumptions; and
- concise evidence notes that do not claim upstream completeness or parity.

Sort entries by category, then normalized name, then stable ID. Sort and
deduplicate every evidence/test/unknowns array. Include the audited commit and
schema version at the top level; do not include timestamps, host paths, or
other nondeterministic data. If repository evidence cannot establish native or
Xwayland behavior, use the schema's `unknown` value.

`docs/audits/current-implementation.md` must explain the schema and collection
method, summarize counts by category and native/Xwayland evidence status, map
the largest explicit coverage gaps, and state that this is a current-tree
inventory rather than an upstream completeness or compatibility assessment.

`tests/reference/current_implementation_audit_test.sh` must validate the JSON
schema, required fields/enums, unique stable IDs, repository-relative evidence
locations, deterministic ordering/deduplication, summary counts, and the
absence of nondeterministic fields. It must also exercise a deliberately
malformed temporary JSON document and fail it, proving the validator rejects
bad data. Keep temporary output outside the repository and clean it up.

## Acceptance criteria

1. The JSON covers every repository-evidenced parsed directive, action,
   construct, and runtime dispatch path, without importing upstream claims.
2. Every status and test mapping has a repository location; omissions and
   ambiguous native/Xwayland behavior are explicit unknowns.
3. Output and arrays are reproducibly sorted, deduplicated, schema-versioned,
   and stable across repeated validation.
4. The Markdown summary agrees with machine-checked JSON counts and clearly
   identifies coverage gaps.
5. The focused test passes valid audit data and demonstrably rejects malformed
   audit data.
6. No compatibility status, implementation, existing test, ledger, Meson
   registration, or task-checkbox changes.

## Internet and verification

- Agent internet access must remain off. Do not fetch upstream source or use
  live GitHub data.
- Run the focused validation twice:
  `sh tests/reference/current_implementation_audit_test.sh`.
- Run the portable suite with warnings as errors. If `build` exists, use
  `meson setup build --reconfigure -Dcompositor=disabled -Dwerror=true`;
  otherwise use
  `meson setup build -Dcompositor=disabled -Dwerror=true`.
- Then run `meson compile -C build` and
  `meson test -C build --print-errorlogs`.
- Run `git diff --check` and inspect `git diff --stat` before committing.
- Report any command that cannot run and the exact blocker; do not weaken or
  skip validation to obtain a pass.

## Commit, push, and completion evidence

- Make one focused commit with an imperative subject.
- On literal `agent_impl_audit`, recheck the exact branch immediately before
  committing and pushing. Commit and push only `agent_impl_audit`.
- On Cloud-managed `work`, immediately before committing recheck that the
  branch is still exactly `work` and rerun
  `git merge-base --is-ancestor 0999450237b2d27745067cb15565a2ecc37c1849 HEAD`.
  Never push `work`; return its diff through Codex Cloud for human review and
  integration into the assigned remote branch.
- Stop if the applicable branch or marker recheck fails. Never push to
  `agent` or `main`, never merge either branch, and never force-push or rewrite
  published history.
- Return the commit SHA, changed files, inventory counts, explicit unknowns,
  every verification command/result, checkout mode (`agent_impl_audit` or
  `work`), final branch/status, and confirmation that no task checkbox or
  compatibility claim changed. State whether `agent_impl_audit` was pushed;
  confirm that `work`, `agent`, and `main` were not pushed.

This task can run in parallel because it owns only the three new
`current-implementation` audit files, changes no source or shared project
status, and derives evidence from the fixed base lineage without consuming or
modifying another task's outputs.
