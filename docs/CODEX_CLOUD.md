# Codex Cloud setup for `wtwm`

Codex Cloud is useful for this project as a reviewable Linux workspace for
parser work, documentation, CI diagnosis, and bounded implementation tasks.
GitHub Actions on Debian Trixie remains the authoritative full compositor
build because the project requires the wlroots 0.18 public API.

Official references:

- [Codex Cloud](https://learn.chatgpt.com/docs/cloud)
- [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [Agent internet access](https://learn.chatgpt.com/docs/cloud/internet-access)
- [Custom instructions with `AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## Connect the repository

1. Open [Codex environment settings](https://chatgpt.com/codex/settings/environments)
   and connect the GitHub account or organization that owns
   `gunan/wayland-twm`.
2. Grant the Codex GitHub integration access to this repository. Prefer
   selected-repository access rather than organization-wide access.
3. Create an environment for `gunan/wayland-twm` and use `agent` as the task's
   starting branch. The protected `main` branch is never a working branch.
4. If the environment or repository is unavailable, ask the ChatGPT workspace
   administrator to check Codex access, GitHub-app policy, and repository
   permissions. Product access can depend on plan and workspace settings.

Cloud tasks only see commits available to the connected GitHub repository.
Commit and push any intended starting state to `agent` before dispatching a
task; uncommitted local files are not transferred by a fresh cloud checkout.

## Configure the environment

Set the environment's **Setup script** to:

```bash
bash scripts/codex-cloud/setup.sh
```

Set its optional **Maintenance script** to:

```bash
bash scripts/codex-cloud/maintenance.sh
```

The setup installs the project's portable build dependencies, then configures,
builds, and tests the checkout with warnings as errors. It uses the full
compositor build when `wlroots-0.18` is available through `pkg-config`; otherwise
it runs the portable parser build required by `AGENTS.md`. The maintenance
script reconfigures and retests after a cached environment checks out the task
branch.

No secrets are required to build this repository. Do not add personal GitHub,
OpenAI, SSH, signing, or package-registry credentials to the environment.
Normal environment variables are visible throughout a task. Cloud secrets are
available to setup only and are removed before the agent phase, so neither is a
substitute for the Codex GitHub integration.

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_CLOUD_COMPOSITOR` | `auto` | `auto` uses wlroots when present and otherwise runs parser-only; `enabled` makes missing wlroots a setup failure; `disabled` always builds the portable parser. |
| `CODEX_CLOUD_BUILD_DIR` | `build` | Selects the disposable Meson build directory. |

Use `auto` for the first environment. Set `enabled` only after confirming that
the environment provides `wlroots-0.18`. A parser-only pass is not evidence that
compositor or interaction changes are complete; the agent must report that the
enabled suite did not run, and any Roadmap item requiring runtime behavior stays
unchecked.

Codex caches cloud containers. Use **Reset cache** in the environment settings
after changing setup, maintenance, variables, secrets, or installed system
dependencies if a resumed environment behaves as though it has stale state.

## Internet-access policy

Setup scripts have internet access so they can install packages. The agent
phase starts with internet access off. Keep it off for ordinary source edits,
local tests, and documentation work after setup has completed.

Create a second, research-oriented environment when a task genuinely needs
live upstream or CI data. Enable agent internet access with:

- the **None** allowlist preset, followed by only the domains the task needs;
- `GET`, `HEAD`, and `OPTIONS` methods only;
- no long-lived credential exposed to the agent.

Useful task-specific domains are:

| Need | Domains |
| --- | --- |
| GitHub source, pull requests, or Actions evidence | `github.com`, `api.github.com`, `raw.githubusercontent.com`, `githubusercontent.com` |
| wlroots or X.Org `twm` reference source | `gitlab.freedesktop.org` |
| Official Codex documentation | `learn.chatgpt.com`, `developers.openai.com` |

Do not use unrestricted access for routine work. Internet content can contain
prompt injections, and broader network access increases the risk of source or
secret exfiltration and unreviewed dependency downloads. Put the exact allowed
sites and read-only purpose in the task prompt, review the agent log, and turn
access back off when the research task is done.

## Verify the first cloud checkout

Start a task on the remote `agent` branch with this read-only prompt:

```text
Read and follow the root AGENTS.md. Do not edit files, commit, or push.
Run `git branch --show-current`, `git status --short`,
`pkg-config --modversion wlroots-0.18` if available,
`meson compile -C build`, and `meson test -C build --print-errorlogs`.
Report the branch, whether the compositor or portable parser build was
configured, each command's result, and any missing dependency.
```

The expected result is a clean `agent` checkout and passing tests. Confirm
whether the environment selected the full or portable build before assigning
implementation work.

## Dispatch tasks

Use [`docs/CODEX_CLOUD_TASKS.md`](CODEX_CLOUD_TASKS.md) for the repository's
copy/paste task contract, CI-fix example, Roadmap vertical-slice example, and
parallel-work boundaries. Every cloud prompt should name one objective, exact
file or subsystem scope, acceptance criteria, required tests, branch and push
limits, Roadmap ownership, and completion evidence.

Review the returned diff and test evidence before creating a pull request or
integrating it into `agent`. Codex Cloud can prepare a pull request, but this
repository's policy requires human review and prohibits the agent from merging
or pushing to `main`.
