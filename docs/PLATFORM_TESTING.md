# Compositor platform testing

The platform-validation tasks use separate entry points for the three wlroots
environments.
They deliberately do not guess that an SSH shell owns a physical seat.

## Headless and nested runs

Build the compositor, then put the deterministic test client or control-driver
command after `--`:

```sh
scripts/platform/run-compositor-test headless -- build/wtwm -s 'TEST_CLIENT_COMMAND'
scripts/platform/run-compositor-test nested -- build/wtwm -s 'TEST_CLIENT_COMMAND'
```

Headless mode creates a private runtime directory when needed, selects one
headless output and the pixman renderer, disables libinput requirements, and
removes the runtime directory afterward.  Nested mode requires the parent
`WAYLAND_DISPLAY` and selects exactly one nested Wayland output.  Neither mode
changes the user's login session.

Run the headless scenario 100 consecutive times with a fresh compositor per
iteration.  Preserve the test control transcript and screenshot from every
failure, plus the first and last successful runs.  A loop that merely starts
the process without mapping a native client does not meet the task item.

An SSH session can establish a private, non-visible Weston parent without
claiming the later interactive-output task. In one SSH terminal, run:

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
weston --backend=headless --renderer=pixman --socket=wtwm-parent \
  --idle-time=0 --width=1024 --height=768 --fake-seat --no-config
```

While that parent is running, use a second terminal to exercise the real nested
backend, native client mapping, and synthetic event trace:

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=wtwm-parent
python3 -B tests/integration/run_compositor.py \
  --compositor build/wtwm-test-compositor \
  --client build/wtwm-wayland-test-client --nested
```

Stop Weston with `Ctrl-C` after the runner succeeds. This establishes the
nested environment, but it does not prove visible pixels, physical keyboard or
pointer input, a stable capture, or return to an unchanged graphical parent;
those remain the later interactive nested-session task.

## DRM login run

Install wtwm and the session launcher in the disposable Debian ARM64 VM.  From
the display manager, choose the separately named **Wayland twm** entry.  The
launcher writes a mode-0700 log directory at
`${XDG_STATE_HOME:-~/.local/state}/wtwm/session.log` and returns wtwm's exact
status to the display manager.  It never starts, replaces, or loops around the
display manager.  HUP, INT, QUIT, and TERM are forwarded to the compositor as
TERM; the wrapper remains responsible for the child until it is reaped.  wtwm
handles INT, HUP, QUIT, and TERM through its event loop, performs the same
orderly cleanup as `f.quit`, and returns success.  Startup/configuration errors
return nonzero before an optional `-s` command runs, and the launcher never
turns either result into an automatic compositor restart.

For a diagnostic launch on a local virtual terminal, not over SSH:

```sh
scripts/platform/run-compositor-test drm -- scripts/platform/wtwm-session -d
```

The DRM entry point refuses remote or inactive logind sessions and requires a
DRM card.  Verify the real login path by mapping a native Wayland client,
moving the pointer, typing into the client, leaving wtwm normally, and observing
the greeter.  Then install an intentionally invalid `.twmrc`, select the wtwm
session again, and verify that the greeter returns within 30 seconds.  Log in
to the VM's pre-existing Weston session after both exits.  This last action is
required evidence that failure recovery is usable rather than just a process
exit.

The persistent compositor snapshot is separate from `session.log`.  Only
`f.saveyourself` replaces `${XDG_STATE_HOME:-~/.local/state}/wtwm/state`;
logout, signals, failed startup, and crashes neither save nor discard it.
`RestartPreviousState` treats a missing file as empty and reports then ignores a
malformed file without changing it.  The headless lifecycle integration covers
these process and file boundaries, but the greeter observation above remains a
physical login requirement.

The portable tests exercise backend environment selection and launcher status
propagation:

```sh
tests/platform/session-entrypoints-test.sh
tests/platform/session-launcher-test.sh
```

They are not substitutes for a successful nested display or DRM-backed VM
evidence record.

The checked-in UTM image definition remains a reproducible Debian 13 recipe, but
the platform contract does not require a pinned base image. For an existing
Debian 14/Forky guest, record the exact OS release, kernel, architecture, and
package-lock digest and leave the optional VM image build and digest fields
null when they are not known. Never label the existing Trixie image digest as a
Forky image.

## Package lifecycle and rollback

Use a clean VM snapshot of the selected 1.0 release line, Debian 13 (Trixie) or
Debian 14 (Forky), not a development host. The same release must be used for the
amd64 and arm64 certification runs; certification does not require both release
lines. Build or copy one candidate `.deb` and every genuinely older released
`.deb` for the VM's architecture. Mark the disposable VM only after verifying
the snapshot:

```sh
sudo touch /etc/wtwm-platform-test-vm
sudo packaging/debian/package-lifecycle-test.sh \
  --old /tmp/wtwm_OLD1_ARCH.deb \
  --old /tmp/wtwm_OLD2_ARCH.deb \
  --new /tmp/wtwm_CANDIDATE_ARCH.deb \
  --rollback /tmp/wtwm_OLD2_ARCH.deb \
  --protect /usr/bin/EXISTING_COMPOSITOR \
  --protect /usr/share/wayland-sessions/EXISTING.desktop \
  --evidence /var/tmp/wtwm-package-lifecycle
```

The script requires an initially absent wtwm package. For each `--old` it
performs a clean old-version install, direct upgrade to the candidate, and
purge. It then tests a clean candidate install, remove, purge, candidate install,
explicit downgrade, and upgrade back to the candidate. Every phase checks user
configuration and protected-session hashes, installed paths and manuals,
package ownership boundaries, and the distinct Wayland entry. It leaves the
candidate installed so the tester can confirm both old and new login sessions.

Copy the evidence directory out before restoring the snapshot. Repeat on every
supported package architecture. The local command-double test verifies control
flow only and must not be reported as a clean-system package pass.

## Stress, renderer, and soak records

Short stress and sanitizer runs are useful gates before a long run, but they do
not satisfy the 72-hour or hardware task items. A release record must name
the exact clean commit, build profile, backend, renderer, architecture, native
and Xwayland clients, start/end UTC timestamps, and the assertions sampled
during the run. Preserve bounded resource samples and the final exit status.

Run the mixed rapid map/unmap, popup, resize, title-change, and client-crash
scenarios first. Then exercise the required high window count. Only after those
pass should the same candidate enter a 72-hour mixed-client soak. Any restart
resets the duration; a process that merely remains alive is insufficient.

The bounded CI smoke and its evidence validation use the same runner as the
long test:

```sh
python3 -B tests/integration/run_m9_mixed_soak.py \
  --compositor build/wtwm-test-compositor \
  --wayland-client build/wtwm-stress-wayland-client \
  --x11-client build/wtwm-stress-x11-client \
  --output /tmp/wtwm-m9-soak-smoke.json --smoke --overwrite
python3 -B tests/integration/validate_m9_mixed_soak.py \
  --runner tests/integration/run_m9_mixed_soak.py \
  --evidence /tmp/wtwm-m9-soak-smoke.json
```

Omit `--smoke` for the default 259200-second run. The evidence is qualified as
a 72-hour result only when measured elapsed time reaches that value, every
mixed-client workload counter is complete, bounded resource growth passes, and
the one compositor exits cleanly. Preserve the JSON and both adjacent log
files.

Test the GPU renderer on representative physical AMD and Intel systems and the
software renderer through the controlled pixman/headless profile. ARM coverage
must state whether it is native VM hardware, physical hardware, or emulation.
Do not infer physical-machine, DRM-login, GPU, architecture, or soak success
from GitHub Actions labels or portable tests.
