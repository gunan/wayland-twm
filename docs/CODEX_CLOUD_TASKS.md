# Writing Codex Cloud tasks for `wtwm`

Use this guide to turn repository work into bounded, reviewable Codex Cloud
tasks. It supplements, but never replaces, the root `AGENTS.md`.

## Sources of truth

Every task must tell the agent to read and follow the root `AGENTS.md` before
acting. That file owns branch policy, the current CI-first priority, build and
test commands, architecture constraints, commit rules, and completion
reporting. If a task prompt conflicts with `AGENTS.md`, stop and ask the
coordinating human to resolve the conflict.

The `## Tasks` section in `README.md` is the authoritative ordered work queue,
progress record, and release gate. After the immediate GitHub Actions task in
`AGENTS.md` is complete, choose the earliest eligible unchecked task item.
Do not treat the Full parity acceptance checklist as the day-to-day queue, and
do not check an item until its implementation and required tests are complete.

Also consult `docs/ARCHITECTURE.md` for subsystem boundaries and
`docs/COMPATIBILITY.md` for current compatibility claims and Wayland
translations.

## Copy/paste task template

Replace every bracketed field. Delete optional lines that do not apply.

```text
Repository: wtwm

Read and follow the root AGENTS.md before doing anything. The README.md
"Tasks" section is the authoritative ordered task list and progress record.

Objective
- [One concrete outcome that can be implemented and verified in this task.]

Branch and workspace
- Base/start branch: agent at commit [SHA].
- Working branch: [agent for the coordinating task, or the pre-created unique
  agent_<short_feature_label> branch for delegated/parallel work].
- Before editing, run `git branch --show-current` and `git status --short`.
- Stop without editing if the branch is wrong or the worktree is not clean.

Allowed scope
- May edit: [exact files, directories, or subsystem].
- Must not edit: [overlapping subsystems, generated files, unrelated docs].
- Task-list ownership: [exact checkbox text, or "none"]. Do not change any other
  checkbox.

Acceptance criteria
1. [Observable behavior or exact artifact.]
2. [Regression coverage, including accepted and malformed input where relevant.]
3. [Compatibility or architecture requirement.]

Verification
- Focused test: `[exact command]`
- Required full suite: `[exact Meson setup/reconfigure command]`
- Required full suite: `meson compile -C build`
- Required full suite: `meson test -C build --print-errorlogs`
- Before commit: `git diff --check`
- If a required test cannot run, leave the task checkbox unchecked and
  report the exact missing dependency or external blocker.

Documentation and Tasks
- Update [docs/COMPATIBILITY.md and/or docs/ARCHITECTURE.md] if behavior,
  compatibility status, or a Wayland translation changes.
- Change only [exact README.md Tasks checkbox] from `[ ]` to `[x]`, in the
  feature commit, and only after all acceptance criteria are verified.

Commit and push boundaries
- Make small, focused commits with imperative subjects.
- Check the branch again immediately before every commit and push.
- Do not amend or rewrite pushed commits; never force-push.
- [Do not push. Return commits for human integration. | Push only agent after
  local verification, then inspect the complete resulting workflow.]
- Never push to or merge main. Never merge a delegated branch into agent.

Completion evidence
- Return commit SHA(s) and one-line purpose for each.
- List the task checkbox completed and the next unchecked eligible task.
- List every test command and result, plus anything not run and why.
- Summarize remaining compatibility differences or follow-up work.
- Confirm the final branch name, clean/dirty status, files changed, and that
  nothing was pushed to main.
```

Use exact file names, commands, checkbox text, and expected behavior. A useful
task is small enough for one owner and precise enough that a reviewer can decide
whether it is complete from the returned evidence.

## Example: diagnose and fix GitHub Actions

```text
Repository: wtwm

Read and follow the root AGENTS.md before doing anything. This is the immediate
CI task and takes priority over new task-list work.

Objective
- Make the latest GitHub Actions workflow pass on agent and on the pull request
  from agent to main, with every intended check still enabled.

Branch and workspace
- Base/start and working branch: agent.
- Before editing, run `git branch --show-current` and `git status --short`; stop
  if the branch is not agent or the worktree is not clean.

Allowed scope
- May inspect the complete latest Actions run and edit only the workflow,
  source, tests, or packaging files proven to cause the failure.
- Do not start task-list features or change task checkboxes.

Acceptance criteria
1. Record the failing job, step, and relevant error output before changing code.
2. Reproduce with the Debian Trixie dependencies and Meson options from
   `.github/workflows/build.yml`.
3. Fix the root cause without skipped tests, ignored failures,
   `continue-on-error`, relaxed warnings, or removed checks.
4. The resulting agent run and pull-request checks against main are green.

Verification
- Run the exact failing command locally first.
- Run `meson setup build -Dcompositor=enabled -Dwerror=true` (or reconfigure the
  existing build), `meson compile -C build`, and
  `meson test -C build --print-errorlogs` in the matching Linux environment.
- Run `git diff --check` before each commit.

Commit and push boundaries
- Separate independently reviewable workflow-only and source/test fixes.
- Check that the branch is agent before every commit and push.
- Push only agent; never push to or merge main; never force-push.
- After each push, wait for and inspect the complete workflow. Repeat until all
  required checks pass or preserve evidence for an external-service blocker.

Completion evidence
- Return failing-run evidence, commit SHAs, local commands/results, final agent
  workflow URL/status, pull-request check status, final branch/status, and
  confirmation that nothing was pushed to main.
```

## Example: one task-list vertical slice

Use this only after the CI completion condition in `AGENTS.md` is satisfied.
Replace the sample checkbox and paths with the actual earliest eligible item.

```text
Repository: wtwm

Read and follow the root AGENTS.md before doing anything. Confirm the immediate
GitHub Actions task is complete, then verify this is the earliest eligible
unchecked item in the earliest unfinished task group.

Objective
- Complete this single task-list slice: "[paste the exact checkbox text]."

Branch and workspace
- Base/start and working branch: agent.
- Before editing, run `git branch --show-current` and `git status --short`; stop
  if the branch is not agent or the worktree is not clean.

Allowed scope
- May edit: [implementation files], [focused tests/fixtures], README.md only for
  the named checkbox, and [specific compatibility/architecture documentation].
- Must not edit unrelated subsystems or any other task checkbox.

Acceptance criteria
1. Add a focused failing regression test or fixture for [exact behavior].
2. Implement [runtime-observable behavior], not parser acceptance alone.
3. Cover [malformed input/Wayland and Xwayland paths/reference comparison, as
   applicable].
4. Update the compatibility record for the verified result or translation.

Verification
- Focused: `[exact test command and fixture name]`
- Full: `meson setup build -Dcompositor=enabled -Dwerror=true` (or reconfigure),
  `meson compile -C build`, and `meson test -C build --print-errorlogs`.
- If compositor dependencies are unavailable, also run the portable disabled
  build required by AGENTS.md, report the enabled suite as not run, and leave
  any checkbox that requires runtime compositor evidence unchecked.
- Run `git diff --check` before committing.

Documentation, commit, and handoff
- Update only the named task checkbox after all required evidence passes.
- Commit implementation, tests, directly related docs, and its checkbox as one
  cohesive feature commit with an imperative subject.
- Do not push. Return the commit SHA, exact tests/results, changed checkbox,
  next unchecked eligible task, remaining differences, final branch/status,
  and confirmation that nothing was pushed to main.
```

## Splitting independent cloud tasks

Split work only at genuine non-overlapping boundaries. Good candidates include
separate reference-behavior research, parser fixtures, CI-log diagnosis, or a
review pass when each task has distinct owned files and output. Do not run two
tasks that edit the same functions, generated artifacts, compatibility entry,
or task checkbox. Do not split implementation from the tests and
documentation required to prove that same checkbox.

Before dispatching parallel tasks, the coordinating human should:

1. Start from a clean, committed `agent` tip.
2. Assign each task an unused `agent_<short_feature_label>` branch based on that
   exact tip and an isolated workspace, as required by `AGENTS.md`.
3. Put the exact branch, permitted files, tests, and sole checkbox owner in each
   prompt. A task with no checkbox ownership must say so.
4. Require each task to commit but not push or integrate unless explicitly
   authorized.

The coordinating human reviews every returned commit, diff, test result, and
scope boundary. Integrate approved commits into `agent` one at a time, preserve
their focused commit boundaries, resolve conflicts only on `agent`, and run the
combined full suite. Check or retain a task checkbox only after the combined
tree verifies it. Only then may the coordinating `agent` branch be pushed for
CI and a human-reviewed pull request to `main`; cloud agents must not merge it.
