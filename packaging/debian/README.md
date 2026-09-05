# Debian package lifecycle validation

`package-lifecycle-test.sh` performs real clean installs, direct upgrades from
every supplied prior release, removal, purge, rollback to a selected prior
release, and an upgrade back to the candidate.  It refuses to run unless
`/etc/wtwm-platform-test-vm` exists, so it is intended for a disposable VM of
the selected Debian 13 (Trixie) or Debian 14 (Forky) release line.  Use the same
line for amd64 and arm64 certification.  It leaves the candidate installed.

Build independently versioned wtwm packages, copy them into the VM, and protect
at least the existing compositor binary and its session entry:

```sh
sudo packaging/debian/package-lifecycle-test.sh \
  --old /tmp/wtwm_0.1.0_arm64.deb \
  --old /tmp/wtwm_0.2.0_arm64.deb \
  --new /tmp/wtwm_NEW_arm64.deb \
  --rollback /tmp/wtwm_0.2.0_arm64.deb \
  --protect /usr/bin/weston \
  --protect /usr/share/wayland-sessions/weston.desktop \
  --evidence /var/tmp/wtwm-package-lifecycle
```

Repeat `--old` once for every previously released package for the target
architecture.  The script rejects equal or newer versions; reinstalling the
same artifact is not an upgrade test.  `--rollback` defaults to the last
`--old` argument.  At every phase the script checks the exact protected-file
hashes, the user `.twmrc` sentinel, installed version, baseline prior-release
contents, candidate binaries/manuals/configuration, the uniquely named Wayland
session, the namespaced GTK desktop-portal policy, the absence of an X11
session, and package ownership boundaries.  Copy
the evidence directory out of the VM before restoring the snapshot.  Each
installed phase also executes `wtwm --help` and parses the installed static
`system.twmrc`. Candidate phases additionally parse the Debian-menu-generated
`/etc/wtwm/system.twmrc`, catching a broken `install-menu` method or unusable
package content.

`tests/platform/package-isolation-test.sh` is the non-root self-test for the
filesystem and package-manifest assertions.  It does not mutate packages.
`tests/platform/package-lifecycle-driver-test.sh` runs the complete lifecycle
state machine against disposable command doubles.  It proves phase ordering
and local invariants, but only a guarded VM run proves Debian package-manager
behavior.
