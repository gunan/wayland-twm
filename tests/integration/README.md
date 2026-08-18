# Compositor integration harness

Meson builds `wtwm-test-compositor` with the private control interface enabled;
the installed `wtwm` binary is built from the same compositor source without
that interface. The control socket accepts one newline-delimited command at a
time and returns one `OK` or `ERROR` line.

Commands are `PING`, `OUTPUT width height`, `POINTER x y`, `BUTTON code
press|release`, `KEY code press|release`, `STATE`, `TRACE`, `TRACE CLEAR`,
`WAIT [frames]`, `CAPTURE path`, `SET ANIMATION_MS n`, `SET PLACEMENT_SEED n`,
`SET CURSOR x y`, `SET FONT description`, and `QUIT`. `STATE` returns JSON
containing focus, client geometry, exact frame/title/border extents,
advertised size constraints,
top-to-bottom stacking order, iconified clients, menu state, cursor position,
the per-window placement decision, next random-placement coordinate, and
deterministic-control values. `CAPTURE` writes the first output as a binary
PPM. The host-native `geometry runtime wiring contract` additionally guards
that only compositor-driven resize paths call the portable constraint model;
ordinary X11 configure requests and hint-property changes remain unsnapped as
they are under reference `twm`.

The focus/stack runner uses two overlapping X11 windows, including an input-false
`WM_TAKE_FOCUS` transient and an `AutoRaise` rule. It distinguishes logical
activation from actual keyboard focus and PointerRoot/sloppy focus from the
click-locked `f.focus` mode. Frame, title, client, and the minimal
compositor-owned icon hit target are recorded as binding contexts; a live menu
is verified to have no binding context and to preserve locked focus. The same
trace proves focus-neutral raise/lower, overlap-dependent `f.raiselower`, both
circulation directions, and single-window rather than transient-group restacks.

`TRACE` returns a versioned, pull-only JSON event ledger. Each entry has a
monotonic sequence, a creation-order window ID, protocol identity strings,
semantic context, current mapped/focused/stack state, and normalized client and
frame geometry. The geometry includes border/title extents and content offsets,
so a reference observer can compare the same visible rectangles without XIDs,
addresses, timestamps, or input-event clocks. Identity strings are capped at
255 bytes. Events cover map/unmap, focus/unfocus, configure/move/resize,
raise/lower/restack, title and icon-name changes, and destroy. Synthetic
pointer, button, and key commands also append a post-dispatch snapshot for each
managed window, including its resulting stack index.

Destroy entries retain the last pre-destroy identity snapshot. This matters for
native clients because wlroots clears xdg-toplevel title and app-id metadata
before it emits the role destroy signal; the stable creation-order ID and the
last protocol identity therefore continue to identify the same ledger entry.

The ledger retains at most 4096 entries. It stops appending on overflow and
increments `dropped`, making incomplete evidence explicit. `TRACE CLEAR` resets
the entries, sequence, and `dropped` count; live windows keep their unique IDs.
The next event therefore starts at sequence 1. A plain `TRACE` never clears or
otherwise changes the captured evidence.

`run_move_resize.py` drives managed X11 fixtures with synthetic pointer and
button input. It distinguishes outline from opaque motion timing, commit from
second-button abort, below/equal `MoveDelta`, rapid constrained moves,
`DontMoveOff` from `f.forcemove`, auto-relative resize corners, increment/aspect
snapping with left/top anchoring, raise suppression, and asynchronous
`f.deltastop`. `STATE.interaction` exposes only deterministic session state and
preview geometry; TRACE records `outline`, `commit`, and `abort` transitions.

The `wtwm Xwayland geometry matrix integration` test consumes every case in
the frozen reference geometry matrix and runs two clean headless
wtwm/Xwayland sessions per case. Because rootless Xwayland does not expose a
reparent frame to the X client, the runner normalizes compositor scene state
into client-inner, frame-inner, frame-outer, title-outer, and four-edge extent
records. It checks title/transient precedence, `ClientBorderWidth`, titleless
frame borders, initial coordinates, and unchanged `WM_NORMAL_HINTS`. The
reference matrix deliberately has no committed numeric observation baseline,
so this structural runner records `reference_numeric_baseline: false` and does
not claim a live differential pass.

The CI-only Milestone 4 geometry differential supplements that representative
matrix with a generated 48-case Cartesian product. It starts the same client
semantics under frozen reference twm and wtwm, requires three stable samples per
backend in each of two clean runs, and compares the normalized client-inner,
frame-outer, title-outer, and extent records exactly. No geometry field or case
is excluded from this differential.

The `initial placement integration` test maps tailored X11 windows through all
three `UsePPosition` modes, `USPosition`, missing hints, transients, random
sequences and edge resets (including an oversized client), explicit and
screen-derived maximum sizes, `DontMoveOff`, and unmap/remap. It checks both
`STATE` and `TRACE` placement classifications. The ordinary native headless
test separately fixes the pointer before map and verifies the first origin in
the documented pointer-anchored cascade used where xdg-shell has no hints.

Run the headless stability check explicitly with:

```sh
python3 tests/integration/run_compositor.py \
  --compositor build/wtwm-test-compositor \
  --client build/wtwm-wayland-test-client --repeat 100
```

Pass `--nested` to use the parent `WAYLAND_DISPLAY`; the harness exits with the
standard skip status when there is no usable parent Wayland socket.

The `canonical X11 applications under wtwm` test is Linux-only because it runs
inside a real wtwm/Xwayland session. Meson requires the Debian-packaged `xterm`,
`xclock`, `xload`, `emacs`, and `dialog` executables at configure time. The
runner waits for their exact X11 identities and mapped lifecycle state, proves
the terminal dialog process is live, and observes the existing purpose-built
ICCCM normal, transient, hint, and override-redirect fixtures. A second state
snapshot after compositor frames verifies that none exited during observation;
bounded teardown then checks that all client surfaces and the compositor exit.

The dedicated `x11-differential` CI job builds frozen `twm` 1.0.13.1 and wtwm,
then launches one shared command list containing those five real applications
and the purpose-built XCB ICCCM client under both window managers. An Xlib
observer normalizes client properties without window IDs. Managed reference
clients must have a reparent frame, while the matching wtwm test-control entry
must have a scene decoration; the normalized results must otherwise match
exactly. The uploaded JSON deliberately excludes frame geometry, pixels, and
native/cross-protocol semantics assigned to later tests and milestones.

The `mixed native and Xwayland client integration` test maps two native xdg
toplevels and two managed X11 toplevels together. It checks their exact
identities and simultaneous lifecycle associations, drives
native→X11→native and X11→native→X11 focus paths, and requires the actual
protocol recipient to acknowledge keyboard press/release while the other
protocol reports zero keys. It also raises, lowers, and restores clients across
the unified managed stack, then unmap/remaps one native and one X11 client while
the other protocol remains live. Selection bridging and popup/override-redirect
ordering remain separate focused scenarios.

The `adversarial client lifecycle integration` test keeps a native survivor
connection mapped while separate native and X11 connections fail. Purpose-built
clients exit through `SIGABRT`, become deliberately non-dispatching, and ignore
graceful close requests. Bounded control `PING`, state, and frame barriers plus
survivor keyboard acknowledgements prove that neither dead nor hung clients
stall the compositor. Random placement leaves focus on PointerRoot until the
explicit survivor click, matching twm instead of inventing map-time focus. The
runner then kills hung clients and requires exact focus, scene, and Xwayland
lifecycle cleanup. A close-capable client for each
protocol receives and ignores `f.delete` while remaining mapped. Native
`f.destroy` is necessarily another xdg-shell close request and is ignored too;
X11 `f.destroy` terminates only the selected X client connection. Finally, each
protocol completes 32 numbered unmap/remap cycles, with protocol roundtrips and
exact no-duplicate scene/lifecycle assertions at every transition.

The portable randomized lifecycle oracle applies 6,000 operations over five
fixed seeds, validating stable creation IDs, map/list membership, focus and icon
cleanup, stack uniqueness, and transient-parent references after every step. A
second-run history digest proves each seeded sequence is deterministic. The
model takes focus selection and reference occlusion/circulation decisions as
explicit inputs, so its assertions cover safety without inventing policy. The
Linux headless companion drives 96 lifecycle/stack actions twice across native
and X11 clients, including live title mutations and an iconify/deiconify action
cycle. It checks STATE and TRACE structural invariants continuously
and compares the normalized histories without freezing focus or stacking
outcomes that belong to the focused interaction compatibility tests.

`run_m7_icons.py` starts two X11 fixture clients on a two-output headless wtwm
session. It checks `StartIconified`, `IconifyByUnmapping`, configured/forced and
client-supplied image precedence, collision-free region placement, manager
matching and sorting, custom negative-output geometry, row activation,
iconify/deiconify clicks, directional and cross-manager warps, show/hide, live
icon-name reorder, animation traces, and a rendered screenshot. The portable
allocator and manager tests add full/partial regions, release/reuse, malformed
inputs, capacity churn, selection repair, and wrapped grid navigation. The
frozen `reference/icons/twm-1.0.13.1/icon-contract.json` validator ties those
assertions to exact reference source and manual anchors.

`run_m8_restart.py` keeps one native xdg-shell client and one managed X11
client mapped while it replaces the active configuration. A root `f.restart`
applies a valid `NoTitle` change; the exact `f.twmrc` alias then rejects a
malformed replacement without changing active state and applies a subsequent
valid replacement. Stable compositor IDs and the original XID must remain
unchanged throughout, both client processes perform protocol roundtrips after
every attempt, and the original test-control connection remains usable. This
would fail immediately if restart tore down the Wayland display or Xwayland.

`run_m8_startwm.py` exercises the narrow safe-handoff translation with the
same native/Xwayland pair. A direct self-target adopts an alternate `-f`
configuration in-process, an invalid candidate rolls back, and a different
executable is proven not to run. A subsequent no-argument self-target reloads
the adopted path while compositor/client connections and managed state remain
unchanged.

`run_m8_session_state.py` spans three compositor lifetimes in one isolated
state home. It saves a mixed native/Xwayland session with moved geometry,
manual icon position, iconic state, stacking, click focus, auto-raise, and an
active zoom restore box; reconnects the clients in reverse order and requires
the same compositor-owned state; then corrupts the version header and proves
the next session starts clean with a diagnostic. The runner also checks that
the published state file is private mode `0600`.

`run_m8_noop_options.py` runs an exact headless A/B comparison for the X11
server-resource directives `NoBackingStore`, `NoSaveUnders`, and
`NoGrabServer`. It runs all eight subsets of mixed-case spellings and compares
each non-empty subset with the same option-free baseline, so compensating
effects cannot conceal a difference. Every subset runs in both outlined- and
opaque-move configurations, covering each path for one native and one managed
Xwayland client alongside compositor-menu selection and second-button
cancellation. At stable frame barriers the runner compares every full-output
PPM byte and normalized `STATE`/`TRACE`, then
requires both clients and the compositor control socket to answer roundtrips.
This proves the options do not leak an unexplained visible or interaction
consequence into wtwm-owned Wayland scene behavior; independent resource
requests made by X11 clients are outside that contract.

`run_m8_colormap.py` drives configured `f.colormap` bindings against one
managed Xwayland client and one native xdg-shell client. Its dedicated XCB
fixture owns a top-level plus child windows with distinct private colormaps,
publishes `WM_COLORMAP_WINDOWS` without the top-level, and observes the root's
installed-colormap set after exact `next`, `prev`, and `default` sequences. A
replacement property contains an invalid XID and reordered valid survivors,
covering cache reset, stable compaction, and fallback. A portable model check
also fixes the multi-map reverse request order. Native dispatch must retain an
identical installed-colormap snapshot and emit three `native-noop` traces;
both clients and test control then prove connection liveness.
