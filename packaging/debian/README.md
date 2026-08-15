# Debian package lifecycle validation

`package-lifecycle-test.sh` performs a real install, upgrade, purge, and
reinstall.  It refuses to run unless `/etc/wtwm-platform-test-vm` exists, so it
is intended for the disposable Debian ARM64 VM's `clean-provisioned` snapshot.
It leaves the new package installed.

Build two independently versioned wtwm packages, copy them into the VM, and
protect at least the existing Weston binary and its session entry:

```sh
sudo packaging/debian/package-lifecycle-test.sh \
  --old /tmp/wtwm_OLD_arm64.deb \
  --new /tmp/wtwm_NEW_arm64.deb \
  --protect /usr/bin/weston \
  --protect /usr/share/wayland-sessions/weston.desktop \
  --evidence /var/tmp/wtwm-package-lifecycle
```

The script rejects equal versions; reinstalling the same artifact is not an
upgrade test.  At every phase it checks the exact protected-file hashes, the
user `.twmrc` sentinel, the installed package version, binary/config presence,
the uniquely named Wayland session, the absence of an X11 session entry, and
that the package does not own `/usr/bin/twm`.  Copy the evidence directory out
of the VM before restoring the snapshot.

`tests/platform/package-isolation-test.sh` is the non-root self-test for the
filesystem and package-manifest assertions.  It does not mutate packages.
