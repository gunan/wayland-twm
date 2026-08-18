# Architecture

The code is split at the boundary that makes compatibility testable without a
graphics stack:

```text
~/.twmrc ──> config.c ──> settings / rules / bindings / menus / functions
                              │
                              v
Wayland clients ──> wtwm.c (wlroots scene, input, xdg-shell, decorations)
                              │
                              v
       bindings.c / actions.c / command.c / interaction.c
       (portable trigger, action, launch, and gesture decisions)
                              │
                       session_state.c
          (portable atomic persistence and identity matching)
                              │
              icon_layout.c / icon_manager.c
       (portable allocation, ordering, and navigation state)
                              │
                              v
                     DRM, nested Wayland, or X11 backend
```

`src/config.c` is ISO C plus POSIX file handling. It has no X11, Wayland, or
wlroots dependency. `src/geometry.c` likewise keeps twm's frame math and
`ConstrainSize` ordering portable. `src/interaction.c` owns the reference move
threshold, constrained-axis, outer-bound clamp, auto-relative resize-origin,
anchored constraint, delta-stop, and outline/opaque terminal decisions.
`src/placement.c` owns position-hint policy, maximum-size parsing/defaults,
random-placement state, and outer-frame clamping. The portable tests therefore
exercise these exact decisions without a graphics stack. `wtwm-config` and
those tests build on any ordinary Unix host. `src/wtwm.c` is the Linux
compositor adapter and targets the wlroots 0.18 public API.

`src/bindings.c` owns exact trigger selection, including twm's global
`mods_used` mask, concrete/all contexts, case-sensitive key names, and named
client selectors. `src/actions.c` owns zoom toggle/switch geometry and cyclic
window/output selection. `src/command.c` preserves the complete configured
command while deciding whether a decoded `execvp` argument vector is safe or
the unchanged text requires `/bin/sh -c`. The compositor supplies client,
output, cursor, scene, and process effects around those portable decisions.

Initial Xwayland placement reads `USPosition`/`PPosition` from
`WM_NORMAL_HINTS`, applies `UsePPosition` exactly, and always preserves a
transient's requested position. Windows that still require placement use the
reference process-global random sequence when `RandomPlacement` is enabled.
Without it, managed Xwayland windows retain the blocking outline/confirm path
on the pointer-selected output. Native xdg-shell has no global position-hint
fields or X11 placement-grab contract, so an unparented first map uses the
current pointer immediately and a parented first map inherits its managed
parent's output; remaps retain the managed frame position. Both protocols
receive the initial `MaxWindowSize` clip derived from the selected output.
Accepted Xwayland positions remain exact even when they fall in a layout gap or
outside all outputs. When no output exists, initial management remains deferred
and hidden and does not consume the global random or diagnostic placement
sequence.

Each enabled output's logical layout box is an X-root-equivalent spatial box.
Point selection uses half-open containment and nearest-box fallback; existing
window/icon ownership uses greatest positive outer-box intersection and then a
nearest-center fallback. Canonical output order resolves ties. The compositor
captures one selected output for each initial placement, menu stack, move,
fill, or zoom operation and never substitutes the whole-layout bounding box.
Consequently gaps have no root hit or background and cannot become usable
geometry. An unconstrained move may commit across outputs, after which the next
operation recomputes ownership from the committed outer box. This selection is
spatial adapter state, not a second configuration namespace or independent
per-output keyboard focus.

Each xdg-toplevel owns one scene subtree. A solid frame and title/button
rectangles are server-side nodes; Pango-rendered immutable buffers provide
window and menu text; the client xdg-surface is offset below them. Hit testing
maps scene nodes back into twm's `root`, `window`, `title`, and
`frame` binding contexts. Parsed actions are dispatched by the compositor,
and `f.function` executes the same action records used by menus and bindings
through a bounded continuation stack. Menus form a separate bounded parent
stack so pull-right hover can retain visible ancestors while the active child
receives selection and release.

The compositor holds at most one interactive session. It saves original and
preview client geometry, the initiating pointer coordinates, selected resize
edges or constrained-move axis, the pinned output box for spatial operations,
and whether `MoveDelta` was crossed. A scene
overlay renders the outline path; only opaque moves mutate the managed scene
during motion. Release or second-button abort is the single terminal boundary,
which also resumes a bounded function-continuation stack so `f.deltastop`
observes the completed asynchronous interaction. Unmap and destruction clear
both the session and any continuation before releasing the toplevel.

Restart-style configuration is an atomic compositor-layer transaction rather
than a process re-exec. The portable parser builds a complete temporary
`wtwm_config`; only a successful parse replaces the active configuration.
Before the old object is released, the compositor closes config-owned menus and
continuations, then rebuilds derived scene decorations, icon state, manager
state, cursors, colors, and output backgrounds. The display, backend, Xwayland
server, protocol resources, and managed-client identities are deliberately
outside that transaction, so native and Xwayland connections remain live.

`f.startwm` crosses that boundary only for a direct self-target whose runtime
can be preserved in-process. A no-argument self-target reloads the active
configuration path; a self-target with exactly one `-f` path adopts that path
only after the candidate commits. Arbitrary shell or external targets cannot
receive libwayland resource ownership or the embedded Xwayland XWM, so they are
rejected before execution and the current session remains authoritative.

`src/session_state.c` owns the versioned compositor-state file without linking
Wayland, X11, or wlroots. `f.saveyourself` writes a private same-directory
temporary file, flushes it, and atomically renames it over the previous
snapshot only after every record validates. With `RestartPreviousState`, the
compositor loads the complete candidate before publishing anything, then
consumes a record only when exactly one newly mapped client has the same native
title/`app_id` or Xwayland name/instance/class identity. Each map transaction
clamps saved geometry to current outputs and restores only compositor-owned
iconic, stacking, focus, manual-icon, auto-raise, and zoom state. Transients,
ambiguous identities, client processes, client documents, and active menus or
gestures are deliberately outside the persistence boundary.

Icon windows remain compositor-owned scene subtrees. `src/icon_layout.c` owns
the reference first-fit region allocator, including gravity splits, grid-cell
rounding, collision reservations, and release coalescing; the compositor only
converts output layout geometry and supplies each rendered outer icon size.
`src/icon_manager.c` owns fixed-capacity manager membership, stable or sorted
ordering, partial-row coordinates, selection repair, and wrapped navigation.
The compositor adapter resolves client/window-list rules, renders manager rows,
and maps scene hits back to the `icon` and `iconmgr` binding contexts. Copied
X11 icon pixels never outlive their toplevel, and manager entries and region
reservations are removed at the same unmanage boundary as focus and stacking.

The installed binary is called `wtwm`, not `twm`. The Wayland-session desktop
file is also namespaced, so installing the package is co-installable and
reversible.
