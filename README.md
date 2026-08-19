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
three upstream sample files parse successfully. Lifecycle/output translations,
hardening, and final differential certification remain release blockers for a
claim of drop-in compatibility.

## Build

On Debian 13 (trixie), install the build dependencies and compile:

```sh
sudo apt install build-essential meson ninja-build pkg-config \
  libwlroots-0.18-dev libwayland-dev libxkbcommon-dev libpango1.0-dev wayland-protocols
meson setup build -Dcompositor=enabled
meson compile -C build
meson test -C build
```

To install into `/usr/local`:

```sh
sudo meson install -C build
```

To produce a co-installable Debian package instead:

```sh
sudo apt install build-essential devscripts debhelper meson ninja-build \
  pkg-config libwlroots-0.18-dev libwayland-dev libxkbcommon-dev libpango1.0-dev wayland-protocols
dpkg-buildpackage -b -uc -us
sudo apt install ../wtwm_0.1.0_*.deb
```

Log out and select **Wayland twm**, or test without replacing your current
session by running it nested:

```sh
WLR_BACKENDS=wayland build/wtwm -s foot
```

The compositor prints its new `WAYLAND_DISPLAY` socket. `Alt+Escape` is an
emergency exit. The packaged configuration also maps `Meta+Return` to `foot`.

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

## Roadmap

The goal of this project is observable `twm` parity on Wayland: given the same
configuration, applications, screen geometry, and user input, a user familiar
with `twm` should see the same decorations and receive the same window-management
behavior.

Native Wayland cannot reproduce X11 at the protocol level. Some X11 concepts,
including server grabs, backing-store hints, save-unders, and global colormap
installation, do not exist in Wayland. For those features, parity means
reproducing their observable effect or proving that a no-op produces no
user-visible difference. Xwayland clients should receive the closest possible
ICCCM-compatible behavior.

Development with Codex Cloud is documented in
[`docs/CODEX_CLOUD.md`](docs/CODEX_CLOUD.md), including environment setup and
internet-access policy. Use [`docs/CODEX_CLOUD_TASKS.md`](docs/CODEX_CLOUD_TASKS.md)
for bounded cloud-agent task prompts.

### Progress tracking

The checkboxes in this section are the project's authoritative progress record.
Work through Milestones 0–10 in order. Within the current milestone, complete
implementation work and its associated testing before treating an exit
criterion as satisfied. Change `[ ]` to `[x]` only after the work is implemented,
verified by the required tests, and documented where applicable. Update the
checkbox in the same feature-focused commit as the completed work. Leave
partially completed or blocked items unchecked and record the remaining work in
the task report.

The definition-of-parity items below are global release gates, not the execution
queue. Track them as the milestone work progresses, but select day-to-day work
from the earliest milestone that still has unchecked tasks.

### Definition of full parity

A release can claim full `twm` parity only when:

- [ ] Every directive and action accepted by the reference `twm` is recorded in a
  machine-readable compatibility ledger.
- [ ] Every valid reference `.twmrc` parses successfully.
- [ ] Every recognized feature is classified as an exact implementation, a
  behaviorally equivalent Wayland implementation, or a verified no-op with no
  observable effect.
- [ ] No feature remains merely “parsed,” “partial,” or “pending.”
- [ ] Window geometry, stacking, focus, input behavior, menus, icons, and
  decorations match the reference implementation in differential tests.
- [ ] Configuration matching works for both Xwayland and native Wayland
  applications.
- [ ] Experienced `twm` users cannot reliably distinguish the implementations in
  controlled A/B testing.
- [ ] Installation and removal do not modify, replace, or require removal of the
  system's existing Wayland compositor.

The initial reference implementation will be `twm` 1.0.13.1. Changing the
reference version after the compatibility ledger is frozen will require an
explicit review.

### Parity profiles

Testing will use two related profiles:

1. **Canonical parity profile:** a fixed one-output, 1× scale, fixed-DPI
   environment with controlled fonts, cursors, colors, applications, and screen
   size. This profile is used for pixel-level comparison against X11 `twm`.
2. **Extended Wayland profile:** native Wayland applications, Xwayland, multiple
   outputs, fractional scaling, hotplugging, modern input devices, and mixed-DPI
   operation. This profile verifies that the `twm` model remains coherent
   outside the canonical X11 environment.

### Milestone 0: Freeze the reference and measure the current implementation

Start by converting the existing compatibility documentation into an auditable
specification.

Implementation work:

- [x] Freeze the upstream `twm` source, manual, default bindings, and sample
  configurations used as the reference.
- [x] Inventory every configuration directive, color and monochrome option,
  window-list directive, mouse and key binding form, context and modifier,
  built-in function, menu construct, icon and icon-manager option, cursor,
  pixmap, font, placement option, and title-button option.
- [x] Create a machine-readable compatibility ledger containing syntax support,
  runtime support, native Wayland behavior, Xwayland behavior, test coverage,
  and known visual or semantic differences.
- [x] Audit the current implementation against that ledger.
- [x] Preserve representative real-world `.twmrc` files as regression fixtures.

Testing:

- [x] Build the reference `twm` in a controlled X11 environment.
- [x] Record its parsed configuration, window geometry, focus, stacking order, and
  screenshots.
- [x] Establish canonical test applications for normal windows, dialogs and
  transients, fixed-size windows, resize-increment and aspect-ratio hints, long
  and changing titles, icon names and icon bitmaps, urgency and focus behavior,
  override-redirect windows, and legacy X11 applications.

Exit criteria:

- [x] One hundred percent of upstream syntax and actions are represented in the
  ledger.
- [x] Every existing project feature is mapped to at least one test.
- [x] The reference environment can produce repeatable results from a clean VM
  snapshot.

### Milestone 1: Establish the build and test platforms

Use several environments rather than relying on a single VM.

Development environments:

- [x] Host-native unit tests for the parser and platform-independent logic.
- [ ] A Debian ARM64 VM under UTM for interactive development on Apple Silicon.
- [x] A headless wlroots backend for automated compositor tests.
- [ ] A nested Wayland session for rapid visual testing.
- [ ] A full VM login session using the DRM backend for realistic startup, input,
  and session testing.
- [ ] At least one physical Linux system before a parity release.

Automation:

- [x] Provide a script or image definition that provisions the reference VM.
- [x] Build debug, release, AddressSanitizer, and UndefinedBehaviorSanitizer
  configurations.
- [x] Add CI builds on x86-64 and ARM64.
- [x] Introduce a test-only control interface that can create deterministic virtual
  outputs, inject pointer and keyboard input, query focus, geometry, stacking,
  icons, and menus, wait for a stable frame, capture compositor output, and
  terminate a test cleanly.
- [x] Add deterministic test controls for animation timing, placement, cursor
  position, and font selection.

Testing:

- [x] Start the compositor headlessly and map a native Wayland test client.
- [ ] Start it nested inside another compositor.
- [ ] Start it as the VM's login compositor.
- [ ] Verify that a failed launch returns the user to a usable session.
- [ ] Run package install, upgrade, uninstall, and reinstall tests.

Exit criteria:

- [x] A clean checkout builds and passes tests without manual configuration.
- [x] Headless tests are stable over at least 100 consecutive runs.
- [ ] The compositor works in headless, nested, and DRM-backed VM sessions.
- [ ] Installation adds a separate session entry and does not alter the existing
  compositor.

### Milestone 2: Complete `.twmrc` language compatibility

The parser must accept the complete reference language before feature
implementation is considered complete.

Implementation work:

- [x] Match reference lexical behavior for comments, quoting, escapes, case
  handling, aliases, and errors.
- [x] Implement every scalar, flag, list, color-list, menu, function, cursor,
  pixmap, icon-region, icon-manager, and title-button construct.
- [x] Match configuration search order, including screen-specific files and system
  defaults.
- [x] Match name, resource-name, resource-class, and wildcard selection behavior.
- [x] Preserve directive ordering and last-assignment behavior where it affects
  results.
- [x] Make configuration reload atomic: retain the current configuration if a
  replacement fails.
- [x] Produce filename and line-number diagnostics for invalid configurations.
- [x] Distinguish unsupported syntax from accepted Wayland translations; never
  silently ignore a recognized directive.

Testing:

- [x] Parse upstream examples and a corpus of real `.twmrc` files.
- [x] Compare normalized parser output with the reference parser.
- [x] Add a fixture for every grammar production.
- [x] Test malformed and truncated input.
- [x] Fuzz the lexer and parser.
- [x] Test repeated reloads and failed reload rollback.
- [x] Test matching against X11 `WM_NAME`, `WM_CLASS`, and native Wayland `title`
  and `app_id`.

Exit criteria:

- [x] Every valid reference configuration in the corpus parses.
- [x] Every upstream directive has a test.
- [x] Recognized directives are never silently discarded.
- [x] The parser survives a sustained fuzzing run without crashes, leaks, or hangs.

### Milestone 3: Complete the client model and Xwayland integration

Xwayland is required both for legacy applications and for the strongest
comparison with the original `twm`.

Implementation work:

- [x] Manage native `xdg-shell` toplevels and popups correctly.
- [x] Integrate Xwayland lifecycle management and `DISPLAY` export.
- [x] Implement an X window-manager bridge for names and classes, transient
  relationships, normal and size hints, delete-window requests, forced client
  termination, icon names and supplied icons, urgency and input hints,
  override-redirect windows, stacking, and configure requests.
- [x] Apply `.twmrc` window lists identically to Xwayland clients.
- [x] Define a documented mapping from native `app_id` and title to `twm` name/class
  rules.
- [x] Implement clipboard and selection interoperation where legacy actions require
  it.
- [x] Ensure popups, menus, and unmanaged X11 windows stack correctly.

Testing:

- [x] Run xterm, xclock, xload, emacs, terminal dialogs, and purpose-built ICCCM
  test clients.
- [x] Exercise changing titles, classes, hints, transients, icons, and resize
  constraints.
- [x] Compare Xwayland client results with the same clients under reference `twm`.
- [x] Mix native Wayland and Xwayland clients in the same session.
- [x] Test clients that crash, hang, ignore close requests, or rapidly map and unmap
  windows.

Exit criteria:

- [x] Xwayland applications receive the same visible management behavior as under
  `twm`.
- [x] Native and Xwayland applications can coexist without incorrect focus or
  stacking.
- [x] `f.delete` requests a graceful close.
- [x] `f.destroy` forcibly disconnects or terminates the selected client with
  appropriate safeguards.

### Milestone 4: Match core window-management behavior

Implementation work:

- [x] Match frame geometry, client geometry, border calculations, and title
  extents.
- [x] Honor minimum, maximum, base-size, resize-increment, and aspect-ratio
  constraints.
- [x] Implement exact move and resize interaction, including outline and opaque
  movement, `MoveDelta`, `ConstrainedMoveTime`, `DontMoveOff`,
  `AutoRelativeResize`, `f.forcemove`, and `f.deltastop`.
- [x] Match focus behavior for root, frame, title, icon, menu, and client contexts.
- [x] Implement `NoTitleFocus`, click-to-focus, pointer focus, focus/unfocus, and
  auto-raise semantics.
- [x] Match raise, lower, raise-or-lower, and circulation order.
- [x] Implement initial placement, random placement, position-hint handling,
  maximum window sizes, and transient placement.
- [x] Handle map, unmap, remap, destruction, and title changes without stale
  compositor state.

Testing:

- [x] Record geometry and stacking after every input event.
- [x] Replay identical input traces against reference `twm` and the Wayland
  implementation.
- [x] Test every combination of title, border, transient, and size-hint state.
- [x] Test focus transitions across windows, menus, icons, and empty root space.
- [x] Run randomized window lifecycle and stacking model tests.

Exit criteria:

- [x] Geometry matches the reference exactly in the canonical 1× profile.
- [x] Focus and stacking traces contain no unexplained differences.
- [x] Every move, resize, placement, and focus option has an integration test.

### Milestone 5: Achieve pixel-level visual parity

Implementation work:

- [x] Match title height, padding, borders, button indentation, spacing, menu
  borders, and shadows.
- [x] Implement XBM loading for title buttons, icons, cursors, and other monochrome
  assets.
- [x] Match title-button ordering, hit areas, pressed state, and highlight state.
- [x] Implement title squeezing and justification.
- [x] Match focused and unfocused border tiling and highlight behavior.
- [x] Support the complete color and monochrome configuration model.
- [x] Match menu typography, per-entry colors, interpolation, separators, disabled
  entries, submenus, and shadows.
- [x] Reproduce classic cursor shapes and configured foreground/background colors.
- [x] Provide a bitmap-compatible font path for canonical parity, including
  practical XLFD mapping.
- [x] Define deterministic scaling rules for HiDPI and fractional-scale displays.

Testing:

- [x] Capture screenshots for every focus, title, border, menu, icon, and button
  state.
- [x] Compare screenshots with masks only for genuinely nondeterministic client
  content.
- [x] Separately compare geometry, color, and font rasterization.
- [x] Test color, grayscale, and monochrome configurations.
- [x] Test long, empty, non-ASCII, and rapidly changing titles.

Exit criteria:

- [x] Frame and menu geometry differ by zero pixels in the canonical profile.
- [x] Configured colors match exactly after the defined color conversion.
- [x] Golden-image differences are either eliminated or individually reviewed and
  documented.
- [x] A blind reviewer cannot identify the compositor from decorations alone.

### Milestone 6: Complete menus, bindings, and built-in functions

Implementation work:

- [x] Reproduce exact key and pointer binding behavior for all modifiers and
  contexts.
- [x] Match press, drag, threshold, release, cancellation, and submenu interaction.
- [x] Implement nested menus and named functions with reference ordering and
  interruption behavior.
- [x] Complete every built-in function family: raise, lower, move, resize, focus,
  delete, destroy, iconify, circulation, raise-or-lower, all zoom variants and
  aliases, warp-to-window, warp-ring, warp-screen, icon-manager navigation,
  menu, function, title, no-op, delta-stop, execute, priority, quit, restart,
  the `f.twmrc` restart alias, start-window-manager, identify, version, beep,
  refresh, window-refresh, and the legacy cut-buffer, file, colormap, and
  save-yourself actions.
- [x] Reproduce `DefaultFunction` and `WindowFunction`.
- [x] Preserve exact command execution and quoting behavior without invoking an
  unnecessary shell.

Testing:

- [x] Give every function an initial-state, input-sequence, and expected-state test.
- [x] Test functions both directly and from nested named functions.
- [x] Test all root, window, title, frame, icon, icon-manager, and all-context
  bindings.
- [x] Test modifier-lock handling, repeated input, canceled gestures, and
  simultaneous client changes.
- [x] Compare function traces with reference `twm`.

Exit criteria:

- [x] Every upstream function is effective, behaviorally equivalent, or a verified
  no-op.
- [x] Every binding context and modifier combination has automated coverage.
- [x] No function remains in a parser-only state.

### Milestone 7: Complete icons and icon managers

Implementation work:

- [x] Implement compositor-owned icon windows with reference text, borders, colors,
  and images.
- [x] Complete `IconifyByUnmapping`, icon-window mapping, `ForceIcons`,
  `UnknownIcon`, and `IconDirectory`.
- [x] Implement icon regions, gravity, placement direction, grid behavior, and
  collision handling.
- [x] Implement per-window icon selection and supplied client icons.
- [x] Complete single and multiple icon managers, including window matching,
  geometry and columns, sorting, show and hide rules, active-row highlighting,
  focus and pointer interaction, and all directional and cross-manager
  navigation functions.
- [x] Match `StartIconified`, iconify/deiconify animation, and associated raise
  behavior.

Testing:

- [x] Compare icon placement for identical creation and destruction sequences.
- [x] Exercise full and partially occupied icon regions.
- [x] Test multiple icon managers across outputs.
- [x] Compare icon and icon-manager screenshots and navigation traces.
- [x] Repeatedly iconify, deiconify, close, and recreate large window sets.

Exit criteria:

- [x] Icon placement and manager ordering match reference `twm`.
- [x] Every icon-related directive and action is covered.
- [x] Long-running icon lifecycle tests produce no stale entries or overlapping
  allocations.

### Milestone 8: Reconcile Wayland-specific lifecycle and screen behavior

Some X11 operations require a compatibility contract rather than literal
implementation.

Required mappings:

- [x] Keep `f.twmrc` as the exact `f.restart` alias; restart compositor state in
  place so existing clients are not disconnected.
- [x] `f.startwm` supports a safe configured handoff where possible, and reports
  unsupported handoffs without destroying the session.
- [x] `f.saveyourself` and `RestartPreviousState` persist all compositor-owned state
  that can be restored safely.
- [x] Backing-store, save-under, and server-grab options become verified no-ops
  unless they have a visible compatibility effect.
- [x] Colormap actions operate for relevant Xwayland clients and become a documented
  no-op for native true-color Wayland clients.
- [x] Legacy cut-buffer actions map to the appropriate Wayland/Xwayland clipboard
  mechanism.
- [x] X screen-specific configuration maps predictably to Wayland outputs.

Implementation work:

- [x] Implement output-aware placement and per-output root behavior.
- [x] Complete warp-to-screen behavior and screen history.
- [x] Handle output addition, removal, scale changes, and mode changes.
- [x] Restore windows safely when an output disappears.
- [x] Support input hotplugging and multiple keyboards and pointers.
- [x] Define session startup, logout, failure recovery, and state-file behavior.

Testing:

- [x] Reload good and invalid configurations while clients are active.
- [x] Exercise output hotplug and rearrangement.
- [x] Test one-output and multi-output screen-specific configurations.
- [x] Verify lifecycle translations with both native and Xwayland clients.
- [x] Confirm that every X11-only directive has no unexplained visible consequence.

Exit criteria:

- [x] All compatibility translations are documented and tested.
- [x] Reload and restart-style operations preserve active clients.
- [x] Output changes cannot strand or permanently hide a managed window.

### Milestone 9: Hardening, packaging, and long-duration testing

Implementation work:

- [ ] Validate all Wayland request serials and client-supplied sizes.
- [ ] Harden configuration parsing, bitmap decoding, command execution, and Xwayland
  metadata handling.
- [ ] Eliminate compositor crashes caused by malformed or hostile clients.
- [ ] Add structured logging and an optional diagnostic state dump.
- [ ] Complete manual pages, sample configurations, migration notes, and
  troubleshooting documentation.
- [ ] Produce packages for the initially supported distributions.
- [ ] Ship a session file under a distinct name; never replace the user's default
  desktop automatically.

Testing:

- [ ] Run sanitizers, parser fuzzing, and protocol fuzzing.
- [ ] Run rapid map/unmap, popup, resize, title-change, and client-crash stress
  tests.
- [ ] Test hundreds of simultaneously managed windows.
- [ ] Run at least a 72-hour mixed native/Xwayland soak test.
- [ ] Test GPU and software rendering.
- [ ] Test clean installation, upgrade from each prior release, removal, and
  rollback.
- [ ] Perform physical-machine tests across representative AMD, Intel, and ARM
  systems where available.

Exit criteria:

- [ ] No known crash, hang, protocol violation, or unbounded resource leak.
- [ ] Packages pass clean-system installation and removal tests.
- [ ] A compositor failure returns the user to a recoverable login state.

### Milestone 10: Differential parity certification

The final milestone runs identical scenarios against reference `twm` and the
Wayland implementation.

The differential harness will compare:

- [ ] Parsed configuration.
- [ ] Window position and dimensions.
- [ ] Frame extents.
- [ ] Focus owner.
- [ ] Stacking order.
- [ ] Pointer location.
- [ ] Menu state.
- [ ] Icon and icon-manager state.
- [ ] Commands launched.
- [ ] Client close and destruction behavior.
- [ ] Screenshots after every significant action.

The certification corpus will include:

- [ ] Upstream sample configurations.
- [ ] The project's exhaustive generated configurations.
- [ ] Collected real-world `.twmrc` files.
- [ ] Legacy X11 applications.
- [ ] Native Wayland equivalents.
- [ ] Single-output, multi-output, monochrome, and color scenarios.
- [ ] Keyboard-driven, mouse-driven, and mixed workflows.

Final 1.0 release gates:

- [ ] One hundred percent grammar coverage.
- [ ] One hundred percent built-in action coverage.
- [ ] No “partial,” “parsed only,” or unexplained compatibility entries.
- [ ] Zero geometry differences in the canonical profile.
- [ ] Zero unexplained focus or stacking differences.
- [ ] No unreviewed golden-image differences.
- [ ] Successful 72-hour soak testing.
- [ ] Successful package tests on every supported distribution and architecture.
- [ ] Successful testing in nested, VM login, and physical hardware environments.
- [ ] Blind A/B evaluation by experienced `twm` users, with no repeatable
  distinguishing behavior in the canonical profile.
- [ ] All unavoidable Wayland translations documented in the manual and
  compatibility ledger.

Only after these gates pass should the project describe itself as providing
full observable `twm` parity on Wayland.
