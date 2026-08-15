# Controlled reference X11 environment

The `reference-twm` GitHub Actions job is the canonical build environment for
the frozen X.Org `twm` 1.0.13.1 reference. It starts with a clean Debian Trixie
container, installs only the packages listed in
`debian-trixie-x11-packages.txt`, records their resolved versions in the job
log, and invokes `tests/reference/build_reference_twm.sh`.

The build script performs no network access. It verifies the checked-in release
archive's SHA-256 and embedded version, requires the release-generated
`configure`, `Makefile.in`, `src/Makefile.in`, `src/gram.c`, and `src/lex.c`,
and extracts into a guarded temporary directory. It then performs an
out-of-tree build using the generated Autoconf/Automake files; regenerating
those files is intentionally outside this reference path. The resulting
binary must print exactly `twm 1.0.13.1` for `-V`.

The same job starts an Xvfb server at 1024x768x24, waits for `xdpyinfo` to
connect, launches the reference window manager with a controlled empty
configuration, and verifies that it remains alive. Build files, the temporary
configuration, logs, and the X server are cleaned up on every exit.

Run only the offline source and environment-contract checks on any Unix host:

```sh
sh tests/reference/build_reference_twm.sh --validate-only .
python3 -B tests/reference/validate_reference_environment.py --source-root .
```

Run the complete build and X11 smoke test inside the documented Debian Trixie
environment after installing the package list:

```sh
xargs apt-get install -y --no-install-recommends < \
  reference/environment/debian-trixie-x11-packages.txt
sh tests/reference/build_reference_twm.sh .
```

This environment establishes the reference build and startup baseline only.
Configuration-state recording, geometry/focus/stacking probes, screenshots,
and canonical client applications are separate later Milestone 0 tasks.
