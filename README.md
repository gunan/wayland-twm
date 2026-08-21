# wtwm

`wtwm` aims to be to X11 `twm` what Sway is to i3: a `twm`-compatible Wayland
compositor. It is designed to use existing `.twmrc` configurations and reproduce
`twm`'s observable appearance and window-management behavior wherever Wayland
permits. It is installed alongside the desktop you already have: the package
adds a separate **Wayland twm** login session and does not replace Wayland, Xorg,
or X11 `twm`.

The project is currently an **0.1 development release**, suitable for nested
testing. It already has a working wlroots compositor core, classic server-side
titlebars and window names, click-to-focus, interactive move/resize, root and
window menus, xdg-shell windows, clipboard plumbing, multi-output layout, and
a portable `.twmrc` parser. Xwayland clients share the managed stack, and
compositor-owned icons and icon managers implement the reference allocation,
ordering, and navigation model. The stock `twm` 1.0.13.1 `system.twmrc` and all
three upstream sample files parse successfully. Platform validation,
long-duration and hardware testing, compatibility-ledger reconciliation, and
final differential certification remain release blockers for a claim of
drop-in compatibility.

## How to install

`wtwm` targets Debian 13 (Trixie) with wlroots 0.18 and Debian 14 (Forky) with
wlroots 0.20. Forky is exercised through Debian testing until Debian 14 is
released. The 1.0 candidate may be certified on either release; certification
does not require both releases or submission to an official Debian repository.
Build either a co-installable Debian package or a local development tree. The
Debian package is recommended for a real display-manager login because it
installs and tracks the complete session entry; a source-tree build is the
quickest way to test `wtwm` nested inside an existing Wayland desktop.

Do not run `wtwm` or `wtwm-session` as root. Keep your existing compositor
available until you have tested the applications, configuration, input devices,
and displays that matter to you.

### Install a Debian package

Install the package build dependencies, clone the source, build the binary
package, and install the resulting artifact:

```sh
wlroots_dev=libwlroots-0.18-dev # Debian 14/Forky: libwlroots-0.20-dev
sudo apt update
sudo apt install build-essential debhelper devscripts dpkg-dev meson ninja-build \
  pkgconf libfontconfig-dev libpango1.0-dev libwayland-dev \
  "$wlroots_dev" libx11-dev libxcb1-dev libxkbcommon-dev \
  wayland-protocols lintian mandoc xkb-data xwayland foot xfonts-base \
  dialog emacs-gtk x11-apps xterm
git clone https://github.com/gunan/wayland-twm.git
cd wayland-twm
dpkg-buildpackage --build=binary --unsigned-changes --unsigned-source
sudo apt install ../wtwm_0.1.0_*.deb
```

The package installs `wtwm`, `wtwm-config`, `wtwm-session`, manual pages, the
fallback `system.twmrc`, and a distinct
`/usr/share/wayland-sessions/wtwm.desktop`. It does not install an X11 session,
replace `/usr/bin/twm`, use the alternatives system, or change the display
manager's default session.

To remove the package later:

```sh
sudo apt remove wtwm
```

Removal and purge leave user-owned `.twmrc`, saved state, and session logs in
place.

### Build and test from source

For a development build without Debian packaging:

```sh
wlroots_dev=libwlroots-0.18-dev # Debian 14/Forky: libwlroots-0.20-dev
sudo apt update
sudo apt install build-essential meson ninja-build pkgconf \
  libfontconfig-dev libpango1.0-dev libwayland-dev \
  "$wlroots_dev" libx11-dev libxcb1-dev libxkbcommon-dev \
  wayland-protocols xkb-data xwayland foot xfonts-base \
  dialog emacs-gtk x11-apps xterm
git clone https://github.com/gunan/wayland-twm.git
cd wayland-twm
meson setup build -Dcompositor=enabled -Dwerror=true
meson compile -C build
meson test -C build --print-errorlogs
```

If the repository is already cloned, start at `meson setup`. Reconfigure an
existing build directory with `meson setup build --reconfigure` rather than
deleting it. To install the development build under `/usr/local`:

```sh
sudo meson install -C build
```

Some display managers do not search `/usr/local/share/wayland-sessions`; use the
Debian package above when you need a reliable login-session entry.

### Configure wtwm

With no `-f` option, `wtwm` tries `~/.twmrc.0`, then `~/.twmrc`, then the
packaged `system.twmrc`, and finally its compiled-in defaults. Existing files
are read in place and are never rewritten by installation, reload, upgrade, or
removal.

Validate an existing configuration before starting a session:

```sh
wtwm-config "$HOME/.twmrc"
```

For an uninstalled source build, use `build/wtwm-config` instead. Review every
`f.exec` command in an imported configuration because it runs with your user
privileges. The packaged default binds `Meta+Return` to `foot`; install `foot`
or change that command to your preferred terminal.

See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for exact support and
Wayland translations, and [docs/MIGRATING_FROM_TWM.md](docs/MIGRATING_FROM_TWM.md)
for a reversible migration procedure.

### Run nested inside an existing Wayland session

Nested mode is the safest first run. From a terminal inside an existing Wayland
desktop, confirm that `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` are set, then run:

```sh
WLR_BACKENDS=wayland wtwm -s foot
```

From an uninstalled source tree, replace `wtwm` with `build/wtwm`. A new window
containing the nested compositor should appear, and `foot` should open inside
it. `Alt+Escape` is the emergency exit. Use `-d` for verbose logging or
`-f /path/to/file` to select a specific configuration.

### Run as a login session

After installing the Debian package, log out, choose **Wayland twm** in the
display manager, and log in normally. The `wtwm-session` wrapper starts one
foreground compositor, writes a private log to
`${XDG_STATE_HOME:-$HOME/.local/state}/wtwm/session.log`, and returns the exact
exit status to the display manager. A normal exit or failed startup should
therefore return to the greeter.

Do not force the DRM backend from SSH. A direct DRM session requires an active
local logind session, a usable DRM device, and local keyboard and pointer
access. If login returns immediately or the display is blank, return to your
previous session and follow [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Configuration compatibility

`wtwm` searches `~/.twmrc.0`, `~/.twmrc`, and the packaged `system.twmrc`, in
that order. Existing files are not rewritten. Check one before starting a
session:

```sh
build/wtwm-config ~/.twmrc
```

See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the exact support table
and the unavoidable Wayland translations. Architecture and contributor notes
are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Why a compositor?

An X11 window manager cannot manage native Wayland windows. A Wayland
compositor is the component that owns placement, focus, decorations, input,
and output rendering, so implementing twm behavior at that layer is the only
route to the same interaction model for Wayland-native applications.

## License

MIT. The compositor's event-loop structure is informed by wlroots' `tinywl`
reference compositor, also distributed under the wlroots MIT license. The
configuration behavior is based on the public twm grammar and manual.

## Tasks

This section is the authoritative remaining-work list for `wtwm` 1.0. The goal
is observable `twm` 1.0.13.1 parity: given the same configuration,
applications, screen geometry, and input, an experienced user should see the
same decorations and receive the same window-management behavior wherever
Wayland protocols permit it.

Task ownership is recorded as:

- **Agent:** repository implementation, automation, validation, or evidence
  work that can be completed without physical observation.
- **Manual:** hardware access, interactive observation, policy approval, or
  human judgment that cannot be replaced by an automated result.
- **Shared:** the agent can drive commands and prepare evidence after a person
  supplies the environment, access, hardware, or reviewers.

Work through the numbered task groups in order. Within the current group,
select the earliest unchecked item whose prerequisites are satisfied. Change
`[ ]` to `[x]` only after implementation, required testing, and documentation
are complete, and update the checkbox in the same focused commit. Leave partial
or blocked work unchecked and record the remaining work in the task report.
Keep the latest `agent` workflow and the pull-request checks against `main`
green before starting a later task group.

Testing uses two profiles:

1. The **canonical parity profile** is fixed at one output, 1× scale, fixed DPI,
   and controlled fonts, cursors, colors, applications, and screen size for
   exact comparison with X11 `twm`.
2. The **extended Wayland profile** covers native applications, Xwayland,
   multiple outputs, fractional scaling, hotplugging, modern input devices, and
   mixed-DPI operation.

Development with Codex Cloud is documented in
[docs/CODEX_CLOUD.md](docs/CODEX_CLOUD.md); bounded cloud-agent prompts are in
[docs/CODEX_CLOUD_TASKS.md](docs/CODEX_CLOUD_TASKS.md).

### 1. Platform and session validation

- [x] **Shared:** Provision a Debian 13 or Debian 14 ARM64 VM under UTM for
  interactive development on Apple Silicon.
- [x] **Shared:** Establish a nested Wayland environment inside a working parent
  compositor.
- [x] **Shared:** Establish a full display-manager login session using the DRM
  backend in a disposable VM.
- [ ] **Manual:** Supply at least one non-virtualized Linux system with a real DRM
  device, display, keyboard, and pointer before the parity release.
- [ ] **Shared:** Start `wtwm` nested, map a native client, verify visible output,
  keyboard and pointer input, capture a stable frame, and exit cleanly to the
  unchanged parent session.
- [ ] **Shared:** Install the candidate package and start `wtwm` as the VM's
  **Wayland twm** login session.
- [ ] **Manual/shared:** Deliberately fail startup with an invalid configuration,
  observe return to the greeter within 30 seconds, and successfully log into the
  original compositor afterward.
- [ ] **Shared:** Run real clean install, upgrade, uninstall, reinstall, purge,
  and rollback tests in disposable Debian VMs, using every genuinely older
  released package for the target architecture.
- [ ] **Shared:** Check in validated evidence that the compositor works in
  headless, nested, and DRM-backed VM sessions.
- [ ] **Manual/shared:** Prove the package installs a separate Wayland session,
  leaves X11 `twm` and the existing compositor untouched, and preserves a usable
  original login session.

Use [docs/PLATFORM_TESTING.md](docs/PLATFORM_TESTING.md) and
[docs/PHYSICAL_LINUX_VALIDATION.md](docs/PHYSICAL_LINUX_VALIDATION.md) as the
acceptance procedures for this group.

### 2. Hardening and endurance

- [x] **Shared:** Validate every Wayland request serial and client-supplied size.
  The contract is explicitly limited to the public APIs of supported wlroots
  0.18/0.20; the dependency-owned exceptions are recorded in
  [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).
- [ ] **Shared:** Run one uninterrupted 72-hour mixed native/Xwayland soak from a
  clean candidate commit, with bounded resource samples and no compositor
  restart.
- [ ] **Shared:** Test both the controlled pixman/software renderer and real GPU
  rendering on representative systems.
- [ ] **Shared:** Complete the clean install, every-prior-release upgrade,
  removal, purge, rollback, and reinstall matrix on amd64 and arm64 for one
  selected 1.0 release line: Debian 13 or Debian 14.
- [ ] **Manual/shared:** Perform physical-machine validation on representative
  AMD, Intel, and ARM systems where available, recording which runs are physical,
  virtualized, or emulated.
- [ ] **Shared:** Establish from sanitizer, fuzz, stress, renderer, soak, and
  hardware evidence that there is no known crash, hang, protocol violation, or
  unbounded resource leak.
- [ ] **Manual/shared:** Establish on a real login path that compositor failure
  returns the user to a recoverable greeter and original session.

### 3. Differential parity

- [x] **Agent:** Extend normalized reference and `wtwm` traces to record and
  compare exact pointer coordinates after every significant input action.
- [x] **Agent:** Add a live reference/`wtwm` menu differential covering menu name,
  depth, selected row, pull-right submenu state, and rendered states.
- [x] **Agent:** Add controlled command observers and compare the action spelling,
  decoded command, direct argument vector or unchanged shell text, execution,
  and intentional non-execution.
- [x] **Agent:** Add one end-to-end reference/`wtwm` X11 close-and-destruction
  differential, and separately record the unavoidable native Wayland close-only
  translation.
- [x] **Agent/shared:** Capture paired stable screenshots after every significant
  certification action, compare them without unexplained masks, and submit every
  nonzero difference for review.

The machine-readable coverage contract is
`reference/certification/m10-differential-contract.json`. Existing mappings are
not final pass evidence until the complete clean-candidate run is checked in.

### 4. Final 1.0 certification

- [x] **Agent:** Check in a consolidated report proving exactly 100 percent
  grammar coverage with no uncovered productions.
- [x] **Agent:** Check in a consolidated report proving exactly 100 percent
  built-in action coverage with no uncovered spellings or behaviors.
- [x] **Agent/shared:** Reconcile all 384 compatibility-ledger rows with current
  runtime and test evidence; implement genuine gaps and reach zero partial,
  parsed-only, unavailable-without-explanation, or otherwise unexplained entries.
- [x] **Agent:** Run the complete canonical one-output 1× matrix and check in a
  report showing zero geometry differences.
- [x] **Agent:** Run the complete focus and stacking differential and check in a
  report showing zero unexplained differences.
- [ ] **Shared:** Review every golden image and check in a review log with zero
  unreviewed differences.
- [ ] **Shared:** Promote the successful continuous 72-hour soak evidence.
- [ ] **Shared:** Check in successful package lifecycle evidence for amd64 and
  arm64 on the selected supported release line, either Debian 13 or Debian 14.
- [ ] **Manual/shared:** Check in passing nested Wayland, VM login, and
  non-virtualized physical-hardware evidence.
- [ ] **Manual:** Conduct a blinded canonical-profile A/B evaluation with at
  least two distinct experienced `twm` users and no repeatable distinguishing
  behavior.
- [ ] **Agent/shared:** Audit every unavoidable Wayland translation and check in
  matching translation inventories in the manual, compatibility ledger, and
  certification report.

Each passed gate must reference one consolidated, tracked JSON report produced
from a clean release-candidate commit. Follow
[docs/PARITY_CERTIFICATION.md](docs/PARITY_CERTIFICATION.md); a smoke test or
expiring CI artifact is not release evidence.

### Full parity acceptance

These are derived acceptance gates, not a separate execution queue. Check them
only after the numbered task groups provide complete evidence.

- [ ] Every directive and action accepted by reference `twm` is present in the
  machine-readable compatibility ledger.
- [ ] Every valid reference `.twmrc` parses successfully in the final candidate.
- [ ] Every recognized feature is classified as exact, behaviorally equivalent,
  or a verified no-op with no observable effect.
- [ ] No feature remains merely parsed, partial, pending, or unexplained.
- [ ] Geometry, stacking, focus, input, menus, icons, and decorations match the
  reference implementation in the complete differential suite.
- [ ] Configuration matching is certified for both Xwayland and native Wayland
  applications.
- [ ] Experienced `twm` users cannot reliably distinguish the implementations in
  the controlled blind A/B evaluation.
- [ ] Installation and removal do not modify, replace, or require removal of the
  system's existing Wayland compositor or X11 `twm`.

Only after every numbered task and derived acceptance gate is checked may the
project describe itself as providing full observable `twm` parity on Wayland.
