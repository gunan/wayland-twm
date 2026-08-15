# Physical Linux validation procedure

Physical validation is a release-gate observation, not something CI or a VM
can impersonate.  A passing record must be produced on a non-virtualized Linux
machine with a real DRM device, connected display, keyboard, and pointer.  Do
not put machine IDs, serial numbers, usernames, network addresses, or EDID
blobs in the evidence bundle.

## Prepare and identify the run

1. Use a machine whose existing compositor and login entry are known to work.
   Record their package versions and SHA-256 hashes before installing wtwm.
2. Check out the exact candidate commit and require an empty
   `git status --short`.  Build debug and release configurations and run the
   host-native suite from that checkout.
3. Run `scripts/platform/collect-linux-platform-facts SOURCE_ROOT OUTPUT_DIR`.
   Review its output for accidental identifying data before copying it.  The
   collector intentionally excludes DMI serials, machine-id, EDID, network
   configuration, and journal contents.
4. Confirm that `virtualization.txt` says `none`.  Record the non-secret
   manufacturer/model, kernel, architecture, login manager, DRM driver/card,
   connected connector, keyboard, and pointer in the evidence JSON.

## Exercise every platform path

Use one timestamped log per check.  Record the literal argv array, start/end
times in UTC, observable assertions, and SHA-256 of the log.

1. **Host native:** run the complete portable test suite from a clean checkout.
2. **Headless:** run
   `scripts/platform/run-headless-stability OUTPUT -- SCENARIO_COMMAND`.
   `SCENARIO_COMMAND` must start a fresh wtwm, map a native Wayland client,
   assert the client's mapped state through the test control interface, capture
   a stable frame, and terminate wtwm cleanly.  The runner records exactly 100
   iterations and stops on the first failure.
3. **Nested:** log into the existing compositor and run
   `scripts/platform/run-compositor-test nested -- SCENARIO_COMMAND`.  Verify a
   visible nested output, a mapped native client, keyboard input, pointer input,
   a stable capture, and a clean exit back to the unchanged parent session.
4. **DRM login:** install the candidate package, log out, and choose the
   separately named **Wayland twm** entry.  Map a native client and verify real
   display output, keyboard, pointer, focus, and clean exit to the greeter.
5. **Failure recovery:** place a syntactically invalid `.twmrc`, select the wtwm
   login entry, and require the greeter to return within 30 seconds.  Then log
   into the original compositor, verify keyboard/pointer operation, and restore
   the test user's `.twmrc`.  A nonzero process status alone is insufficient.
6. **Package lifecycle:** use the guarded lifecycle script in the disposable
   ARM64 VM with genuinely older and newer `.deb` files.  Reference its copied
   evidence bundle from the physical record rather than mutating the physical
   machine through purge/reinstall cycles.
7. **Session isolation:** after the physical install, rerun the pre-install
   hashes, verify `/usr/bin/twm` is still owned by its original package, verify
   the original session launches, and run
   `packaging/debian/assert-coinstallation.sh / installed MANIFEST` with the
   candidate package's `dpkg -L` output.

## Evidence and acceptance

Create `evidence.json` beside the logs using
`tests/platform/platform-evidence.schema.json`.  Every artifact path is
relative to that JSON and every digest is lowercase SHA-256.  `not-run` is
allowed only for an in-progress record.  Validate drafts and final evidence:

```sh
python3 tests/platform/validate-platform-evidence.py \
  --allow-incomplete /path/to/evidence.json
python3 tests/platform/validate-platform-evidence.py /path/to/evidence.json
```

The final validator requires a clean full commit ID, all seven checks marked
`pass`, at least 100 headless iterations, matching on-disk artifact hashes, and
`virtualized: false` for physical Linux.  A reviewer must still compare the
commands and assertions with the procedure; schema validity does not prove the
observations were performed.  Keep the Roadmap physical-system and DRM/login
checkboxes unchecked until this reviewed bundle exists.
