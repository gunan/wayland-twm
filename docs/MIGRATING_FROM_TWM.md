# Migrating from X11 twm

wtwm intentionally uses `.twmrc` and installs beside X11 twm. Migration does
not require renaming or converting the original file, changing the default
desktop, or removing a working X11 session. Keep that fallback until the
applications and hardware important to you have been exercised.

## Make a reversible first test

1. Copy the current file for rollback without modifying the live version:

   ```sh
   cp -p ~/.twmrc ~/.twmrc.before-wtwm
   wtwm-config ~/.twmrc >/tmp/wtwm-config.dump
   ```

   Fix every reported syntax error. A successful parse means the language was
   accepted; review the compatibility classifications and every `f.exec`
   command before treating the file as safe and behaviorally equivalent.

2. From an existing Wayland session, run wtwm nested and start one disposable
   terminal:

   ```sh
   WLR_BACKENDS=wayland wtwm -s xterm
   ```

   Check decorations, pointer and keyboard bindings, menus, focus, iconify,
   move/resize, and normal exit. Nested output and input behavior can differ
   from a DRM login, but a failed nested test leaves the parent desktop usable.

3. Install the package and confirm that both login choices remain present.
   The new entry is **Wayland twm**. The package must not own `/usr/bin/twm`,
   create an entry under `/usr/share/xsessions`, alter display-manager policy,
   or change the selected default session.

4. Select **Wayland twm** only after saving work. Exit normally and confirm the
   greeter returns. Then confirm the previous compositor and X11 twm sessions
   still start. If wtwm fails, use the recovery and logging steps in
   `TROUBLESHOOTING.md` from a console or the previous session.

## Identity and matching

twm window lists normally encounter `WM_NAME`, followed by the instance and
class parts of `WM_CLASS`. wtwm keeps that order for Xwayland clients. Native
xdg-shell applications instead expose a title followed by `app_id`; they have
no `WM_CLASS`. An `app_id` is chosen by the application and does not have to
match its executable or desktop-file name.

When a list no longer matches a native application, identify its title and
`app_id`, then add the narrowest extra entry while keeping the X11 entry:

```twmrc
NoTitle
{
    "legacy-x11-class"
    "org.example.NativeApp"
}
```

Keep both forms if the same configuration is used by X11 twm and wtwm. Test
dynamic title changes when rules depend on titles.

## Behavioral translations to review

- A twm screen becomes one Wayland output. Multi-screen traversal uses wtwm's
  configured output order. Output removal and restoration are managed events,
  not changes to one X11 root window.
- Native Wayland clients cannot request an absolute initial position. wtwm
  places unparented clients on the pointer output and native transients on the
  managed parent's output. Xwayland retains the applicable X11 position-hint
  behavior.
- `f.delete` requests graceful close. A compositor cannot forcibly disconnect
  a native client in the same way X11 `f.destroy` can kill a client connection;
  native destroy is translated to close.
- `f.restart` and `f.twmrc` atomically reload compositor configuration without
  replacing the Wayland process or disconnecting clients. Invalid replacement
  configuration leaves the active configuration in place.
- `f.saveyourself` writes wtwm's explicit state snapshot. Ordinary logout,
  signals, failed startup, and crashes do not overwrite that file.
- Global X11 selection and cut-buffer operations are translated through the
  Wayland clipboard, with Xwayland bridging when the protocol is available.
- X server grabs, save-unders, backing-store preferences, global installed
  colormaps, and other X11-only resource policies may be compositor equivalents
  or verified no-ops. Do not infer support only because a directive parses;
  check `docs/COMPATIBILITY.md` for its exact classification.

## Fonts, commands, and applications

Legacy X core font descriptions are matched against installed fonts. Install
the expected bitmap fonts for reference-like metrics, or choose an available
Fontconfig/Pango description. A fallback can change title and menu geometry.

The packaged sample binds Meta+Return and its terminal menu entry to `xterm`,
matching the reference twm configuration through Xwayland. Change those
commands if another terminal is installed. `f.exec` is run with your user
privileges; shell syntax is honored, so imported configurations need the same
security review as shell scripts.

X11 applications require the optional Xwayland runtime. wtwm continues with
native Wayland support if Xwayland is unavailable. Keep native and X11 test
applications distinct when checking rule matching and protocol behavior.

## State and rollback

The user configuration is not a package conffile and is never rewritten by
install, upgrade, removal, or purge. To restore the saved file:

```sh
cp -p ~/.twmrc.before-wtwm ~/.twmrc
```

The explicit state snapshot and login log are below
`${XDG_STATE_HOME:-~/.local/state}/wtwm/`; Debian package removal does not erase
user-owned state. Remove those files manually only if you no longer need the
saved placement or diagnostics.

Removing wtwm removes its binaries, manuals, packaged configuration, and
separately named Wayland session. It does not select another default session;
the display manager retains its own last-session policy. Package rollback must
use a real prior package version and should be tested in a disposable VM with
`packaging/debian/package-lifecycle-test.sh` before release.

The exhaustive, current mapping of twm features is in
`docs/COMPATIBILITY.md`. Do not claim full twm parity from this migration guide
or from a successful configuration parse.
