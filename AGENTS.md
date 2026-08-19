# AGENTS.md

These instructions apply to the entire repository. Follow them before making
changes, in addition to the user's task-specific instructions.

## Mandatory branch policy

`main` is a protected integration branch. Treat it as read-only.

- The coordinating agent works only on the branch named `agent`.
- Every subagent works on its own unique branch named
  `agent_<short_feature_label>`, for example `agent_ci_fix`,
  `agent_config_ledger`, or `agent_parser_fuzz`.
- Use only lowercase letters, digits, and underscores in the short label. Keep
  it concise and descriptive. Never assign the same branch to two agents.
- Every subagent, including a research-, review-, or test-focused subagent, must
  receive a separate branch and isolated worktree before it starts.
- At the beginning of every task, and before editing any file, each agent must
  run `git branch --show-current` and inspect `git status --short`.
- If the coordinating agent is not on `agent`, preserve existing work and
  switch safely to `agent` before editing. Use the local branch when present,
  otherwise track `origin/agent`, otherwise create `agent` from the current
  `origin/main`.
- If a subagent is not on its assigned `agent_<short_feature_label>` branch in
  its assigned worktree, it must stop without editing and report the mismatch
  to the coordinating agent.
- Codex Cloud may expose the selected remote branch on a managed local branch
  named `work`. Treat `work` as the assigned `agent_<short_feature_label>`
  branch only when the task assignment names that branch and an immutable
  dispatch-marker commit, the worktree starts clean, and
  `git merge-base --is-ancestor <dispatch-marker> HEAD` succeeds. In that
  verified Cloud case, do not switch branches merely to restore the remote
  branch name. Recheck the `work` branch and marker ancestry before committing,
  never push the managed `work` branch, and return the diff through Codex Cloud
  for human review and integration. A `work` checkout that fails any condition
  above is still a branch mismatch and must stop. This exception does not apply
  to local worktrees or relax any rule for `agent`, `main`, or direct pushes.
- If uncommitted changes, worktree restrictions, or repository state make that
  switch unsafe, stop and report the blocker. Do not discard or overwrite work
  to force the switch.
- Never edit, commit, merge, rebase, reset, or cherry-pick changes while `main`
  is checked out.
- Never push to `main`, including through an explicit refspec such as
  `HEAD:main`.
- The coordinating agent may push only `agent`. A subagent may push only its
  assigned `agent_<short_feature_label>` branch and only when the coordinating
  agent or user requests it.
- Never force-push or rewrite `agent` or any `agent_<short_feature_label>`
  branch. Fetch and integrate remote work before pushing; if histories cannot
  be reconciled safely, stop and report the conflict.
- A pull request from `agent` to `main` may be prepared for human review, but
  the agent must not merge it or bypass repository protections.

Check the branch again immediately before every commit and push. Outside the
verified Codex Cloud `work` exception above, the coordinating agent must see
`agent`; a subagent must see its exact assigned `agent_<short_feature_label>`
branch. Otherwise, stop.

## Subagents and parallel work

Use subagents as a normal part of repository work. At the start of a task,
decompose it into bounded pieces and identify which pieces are genuinely
independent.

- For every non-trivial task, delegate at least one concrete, bounded subtask
  with clear acceptance criteria. Work without a subagent only when the task is
  a trivial edit or has no safe delegation boundary, and state that reason in
  the completion report.
- When two or more tasks can proceed without depending on or editing the same
  state, run multiple subagents concurrently, up to the available concurrency
  limit.
- Prefer parallel delegation for independent code areas, parser fixtures,
  reference-behavior research, test-harness work, CI-log diagnosis,
  documentation audits, and separate review passes.
- Keep dependent tasks sequential. Do not parallelize work that modifies the
  same functions, data structures, generated artifacts, task checkbox, or
  other tightly overlapping files unless the coordinating agent has an
  explicit conflict-free integration plan.
- Give each subagent one clearly scoped task, its acceptance criteria, its
  permitted files or subsystem, the required tests, its exact branch name, and
  its isolated worktree path.
- Subagents must follow all repository instructions, make small focused commits,
  run relevant tests, and return commit IDs plus a concise result summary to the
  coordinating agent.

Before spawning any subagent, the coordinating agent must start from a clean
committed `agent` state, confirm that the proposed branch name is unused locally
and remotely, create a unique feature branch from the current `agent` tip, and
create an isolated worktree for it. A typical setup is:

```sh
git worktree add <isolated-path> -b agent_<short_feature_label> agent
```

Do not run subagents in the coordinating agent's working directory or share one
working directory between subagents. A branch alone does not isolate
simultaneous filesystem changes.

The coordinating agent owns integration:

1. Wait for all subagents in the current parallel batch.
2. Review each subagent's commits, diff, test evidence, and scope compliance.
3. Reject or send back incomplete, overlapping, or untested work.
4. Integrate approved feature commits into `agent` one branch at a time while
   preserving their small logical commit boundaries.
5. Resolve integration conflicts only on `agent`; never rewrite a subagent's
   branch to conceal a conflict.
6. Run the combined relevant tests after all approved branches are integrated.
7. Confirm that each integrated task's checkbox is checked only after
   the work is present on `agent` and verified in the combined tree. If combined
   validation invalidates a subagent's checked item, restore it to `[ ]`.
8. Remove an isolated worktree or retire a feature branch only after its commits
   are safely integrated and the worktree is confirmed clean.

Subagents never merge to `main`, never merge their own branches into `agent`,
and never mark another subagent's task complete. The coordinating agent
is responsible for the final branch state and progress record.

## Project objective

Build `wtwm`, a co-installable Wayland compositor whose observable appearance,
configuration, and interaction behavior match X11 `twm` 1.0.13.1.

- Use the `## Tasks` section of `README.md` as the authoritative ordered task
  list, progress record, and release gate.
- Use `docs/COMPATIBILITY.md` as the current compatibility record.
- Use `docs/ARCHITECTURE.md` as the source of architectural boundaries.
- Prefer the smallest unfinished, testable vertical slice in the current
  task group.
- Do not claim a feature is complete merely because its configuration parses.
  Runtime behavior and appropriate tests are required.
- Do not describe the project as having full parity until every final 1.0 gate
  in the Tasks section is satisfied.

## Immediate task: Make GitHub Actions pass

Before starting work from the Tasks section, get the repository's GitHub
Actions workflow running reliably and passing on `agent` and on pull requests
from `agent` to `main`.

1. Inspect the latest GitHub Actions run and record the failing job, step, and
   relevant error output.
2. Reproduce the failure using the same Debian Trixie dependencies and Meson
   options declared in `.github/workflows/build.yml`.
3. Fix the underlying workflow, build, source, test, or packaging problem. Do
   not hide it with `continue-on-error`, skipped tests, ignored exit codes,
   relaxed compiler warnings, or removal of required checks.
4. Keep CI corrections in small, focused commits. Separate workflow-only fixes
   from source or test fixes when they are independently reviewable.
5. Push only `agent`, wait for the resulting workflow, and inspect the complete
   run rather than assuming that a local pass guarantees a CI pass.
6. Repeat until every required job and test is green. If an external GitHub
   service failure prevents completion, preserve the evidence and report the
   exact blocker.

This task is complete only when the latest `agent` workflow and the pull-request
checks against `main` finish successfully with all intended checks enabled.

## Task execution and tracking

After the GitHub Actions task above is complete, use the checklists in the
`## Tasks` section of `README.md` as the work queue.

1. Start with the first task group and find the earliest group that has unchecked
   items. The Full parity acceptance checklist is a release gate, not the
   day-to-day queue.
2. Select the first unchecked task in that group whose prerequisites are
   satisfied. Do not skip ahead merely because a later task is easier.
3. Implement the task completely, add or update its tests, run the required
   verification, and update related compatibility documentation.
4. Change that task item from `[ ]` to `[x]` in the same feature-focused
   commit. A checkbox is evidence of completed and verified work, not just work
   that was attempted or code that was written.
5. Leave partially complete, untested, failing, or blocked items unchecked.
   Record the remaining work or blocker in the completion report.
6. Check an acceptance criterion only after every fact it asserts has been
   verified. When every item in a task group is checked, continue to the next
   group.
7. After committing a completed task, move directly to the next unchecked task
   for task-continuation requests. Stop only at the user's
   requested boundary or when a genuine blocker prevents safe progress.

Do not mark multiple boxes complete merely because they are related. Each
checked item must be fully supported by the implementation and test evidence.
If a regression invalidates a checked item, change it back to `[ ]` in the fix
or regression commit.

## Architectural constraints

- Keep `src/config.c` portable ISO C plus POSIX file handling. It must not gain
  dependencies on Wayland, wlroots, X11, Pango, or compositor state.
- Keep Wayland and wlroots integration in the compositor layer.
- Continue targeting the wlroots 0.18 public API until a deliberate dependency
  upgrade is approved and tested.
- Preserve the `wtwm` binary and session names. Do not conflict with or replace
  the installed X11 `twm` binary, Xorg session, or another Wayland compositor.
- Preserve existing `.twmrc` semantics. Never silently reinterpret a recognized
  directive as a different action.
- Where Wayland has no literal X11 equivalent, preserve the visible result when
  possible and document the translation in `docs/COMPATIBILITY.md`.
- Treat native Wayland and Xwayland behavior as separate compatibility paths
  when their protocol capabilities differ.

## Implementation workflow

For each feature or fix:

1. Read the relevant task group and compatibility entry.
2. Inspect the reference `twm` behavior or grammar rather than relying on
   memory when exact compatibility matters.
3. Add or update a failing focused test when the behavior is testable before
   implementation.
4. Implement the smallest coherent change that makes that behavior work.
5. Run focused tests, then the full available test suite.
6. Update compatibility documentation in the same commit when status or a
   Wayland translation changes.
7. Inspect the diff for unrelated edits before committing.

Do not bundle opportunistic refactors, formatting sweeps, dependency upgrades,
or unrelated task-list items into a feature change.

## Commit policy

Create small, reviewable commits throughout the task instead of one large final
commit.

- One commit should represent one cohesive feature, fix, test-harness
  improvement, or documentation change.
- Include a feature's tests and directly related documentation in the same
  commit as its implementation.
- Split independent parser, compositor, rendering, packaging, and documentation
  work into separate commits.
- Commit after each complete subfeature passes its relevant tests; do not wait
  until an entire task group is implemented.
- Do not commit known-broken intermediate states or placeholder code unless the
  user explicitly requests a checkpoint.
- Use imperative, descriptive commit subjects, preferably with an area prefix,
  for example `config: implement IconRegion parsing` or
  `compositor: honor resize increments`.
- Before committing, run `git diff --check`, inspect `git diff --stat`, and
  verify that no build products, credentials, editor files, or unrelated user
  changes are staged.
- Do not amend or rewrite a commit that has already been pushed unless the user
  explicitly authorizes it.

## Build and test requirements

The primary Linux build and test sequence is:

```sh
meson setup build -Dcompositor=enabled -Dwerror=true
meson compile -C build
meson test -C build --print-errorlogs
```

If `build` already exists, use Meson's reconfigure support rather than deleting
the directory. Build directories are disposable generated output and must not
be committed.

When wlroots or other Linux compositor dependencies are unavailable, run at
least the portable parser build and tests:

```sh
meson setup build -Dcompositor=disabled -Dwerror=true
meson compile -C build
meson test -C build --print-errorlogs
```

- Run focused tests before each feature commit.
- Run the complete available suite before pushing `agent` or presenting a task
  as complete.
- Add regression coverage for every bug fix.
- Do not weaken, delete, or skip tests merely to make a change pass.
- If dependencies or environment limitations prevent a required test, report
  exactly what was not run and why. Do not claim the test passed.
- Changes that affect rendering or interaction require the most relevant
  headless, nested, differential, or screenshot test required by that task.

## Configuration compatibility

- Add parser fixtures for every newly supported grammar production or edge
  case.
- Test both accepted input and malformed input.
- Preserve filenames and line numbers in configuration diagnostics.
- Maintain atomic reload behavior: an invalid replacement configuration must
  not destroy the active valid configuration.
- Keep matching behavior explicit for X11 name/class data and native Wayland
  title/`app_id` data.
- Every recognized directive must eventually be classified as exact,
  behaviorally equivalent, or a verified no-op with no observable effect.

## Completion report

At the end of a task, report:

- the feature-sized commits created;
- the task checkboxes completed and the next unchecked task;
- the tests run and their results;
- any tests that could not run;
- remaining compatibility differences or follow-up work;
- the subagents used, their assigned branches, and the commits integrated;
- confirmation that coordinating work stayed on `agent`, subagent work stayed
  on the assigned `agent_<short_feature_label>` branches, and nothing was pushed
  to `main`.
