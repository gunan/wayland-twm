# Compositor platform testing

Milestone 1 uses separate entry points for the three wlroots environments.
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
the process without mapping a native client does not meet the Roadmap item.

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
