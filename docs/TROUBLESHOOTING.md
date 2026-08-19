# Troubleshooting wtwm

Start with the least disruptive check. Validate configuration outside a login
session, reproduce nested when possible, and keep another compositor or local
console available for recovery.

## A login returns immediately to the greeter

This is the intended recoverable result when startup fails. From another
session or a local console, inspect the private launcher log:

```sh
sed -n '1,240p' "${XDG_STATE_HOME:-$HOME/.local/state}/wtwm/session.log"
```

Then validate the exact configuration selected for screen zero:

```sh
test ! -e ~/.twmrc.0 || wtwm-config ~/.twmrc.0
test -e ~/.twmrc.0 || test ! -e ~/.twmrc || wtwm-config ~/.twmrc
```

The launcher starts one compositor and returns its status. It deliberately has
no restart loop. A status of 127 means `wtwm` could not be executed. Other
nonzero statuses should be read together with the first error in the log.

If a hand-written session launch reports `XDG_RUNTIME_DIR`, use the display
manager's login entry or an active local logind session. Do not invent a shared
runtime directory, run wtwm as root, or start the DRM backend over SSH.

## Blank or missing output

- For nested testing, confirm the parent exports both `WAYLAND_DISPLAY` and a
  writable `XDG_RUNTIME_DIR`, then set `WLR_BACKENDS=wayland` explicitly.
- For a real login, remove test-only backend overrides such as `WLR_BACKENDS`,
  `WLR_RENDERER`, `WLR_HEADLESS_OUTPUTS`, and `WLR_WL_OUTPUTS` from the session
  environment.
- Confirm the login user owns an active local logind session and has access to
  a DRM device. A process that merely stays alive does not prove DRM output.
- Return to the prior compositor and verify the device and display still work.
  Preserve the wtwm log before retrying.

Physical DRM success requires visible output plus keyboard and pointer input;
it cannot be established by the portable tests or a headless CI job.

## Native applications work but X11 applications do not

wtwm continues without X11 support when the Xwayland executable is unavailable
or setup fails. Install the distribution's `xwayland` package, restart the
session, and look for the Xwayland allocation/ready messages in debug logging.

Do not use X11 `WM_CLASS` values to diagnose native applications. Native rules
match xdg title and `app_id`; Xwayland rules match `WM_NAME` and `WM_CLASS`.

## A rule or binding does not match

Run `wtwm-config FILE` first. It detects grammar errors but cannot know the
runtime identity or input delivered by an application and seat.

- Check whether the target is native Wayland or Xwayland.
- For native windows, verify title and `app_id`; for Xwayland, verify name,
  instance, and class.
- Check modifier and context fields independently. A title, root, icon, or
  icon-manager binding does not automatically apply to the client surface.
- Test title-changing applications after their final title appears.
- Check the compatibility ledger when the output reports accepted compatibility
  directives; accepted syntax is not proof of a runtime effect.

## Fonts or geometry look different from twm

Reference-like X core font metrics require the corresponding bitmap fonts. A
font fallback can change title height, menu width, icon labels, and placement.
Install the font named by the configuration or replace it deliberately with an
available description. Capture the resolved configuration and package list
when reporting a geometry difference.

Also check output logical size, scale, transform, and the selected
`--visual-mode`. Pixel comparison requires the controlled one-output, scale-1
canonical profile; results from arbitrary scaled desktops are not comparable.

## Commands do not start

`f.exec` and `-s` use the session's environment, which is often smaller than an
interactive shell environment. Use an absolute program path while diagnosing,
check `PATH`, and run the command as the same unprivileged user. Shell syntax is
only invoked when the command requires it. Quoting that works in an interactive
shell may represent different literal text in `.twmrc`.

The packaged sample expects `foot`. Install it or change both the Meta+Return
binding and terminal menu entry.

## Reload did not take effect

`f.restart` and `f.twmrc` validate the replacement before swapping it into the
running compositor. A reported error intentionally leaves the old settings
active and clients connected. Fix the named file and line, validate with
`wtwm-config`, and retry. Reload is not a process exec and does not reread the
login manager's environment.

## Saved placement did not return

Only `f.saveyourself` replaces
`${XDG_STATE_HOME:-$HOME/.local/state}/wtwm/state`. Normal exit, termination
signals, startup failure, and crashes preserve any existing file. With
`RestartPreviousState`, a missing file is empty state and a malformed file is
reported and ignored. Check ownership and permissions without deleting the file
until it has been copied for diagnosis.

## Package or session collisions

On Debian, record the package manifest and run the read-only assertion:

```sh
dpkg -L wtwm >/tmp/wtwm-package-files.txt
packaging/debian/assert-coinstallation.sh / installed \
  /tmp/wtwm-package-files.txt
```

Confirm `/usr/bin/twm` and the previous compositor/session files still have
their original package owner and hash. wtwm should own only
`/usr/share/wayland-sessions/wtwm.desktop` in the Wayland session directory and
must not own X11-session, alternatives, or display-manager policy paths.

Removal and purge do not erase `~/.twmrc`, the state snapshot, or session log.
The guarded lifecycle procedure in `packaging/debian/README.md` is the release
test for clean install, every prior-version upgrade, removal, purge, rollback,
and co-installation. Its command-double self-test is not a substitute for that
VM run.

## Collecting a useful report

Include:

- the exact wtwm commit or package version and host architecture;
- whether the client is native Wayland or Xwayland;
- the first relevant debug-log error, without usernames or private paths;
- a minimal configuration that still reproduces the problem;
- output logical size, scale, transform, renderer, and backend;
- precise actions and the observed versus expected state; and
- whether the problem reproduces nested, headless, DRM, or under X11 twm.

Do not attach `.twmrc` files containing secrets, shell tokens, private hostnames,
or identifying commands. Physical-test evidence must also omit machine IDs,
serial numbers, network addresses, EDID blobs, and unrelated journal contents.
