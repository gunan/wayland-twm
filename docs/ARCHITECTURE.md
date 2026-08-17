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
reference random sequence when `RandomPlacement` is enabled. Without it, wtwm
uses an explicit Wayland translation of twm's blocking rubber-band prompt: an
instant 24-pixel cascade anchored at the current pointer supplies requested
client origins, with `DontMoveOff` applied to each resulting outer frame. This
map-time adapter does not take an input grab or wait for a confirm click. Native xdg-shell has no
position-hint fields, so every first map follows the same random-or-pointer
policy; remaps retain the managed frame position. Both protocols receive the
initial `MaxWindowSize` clip, including twm's screen-derived default.

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
edges or constrained-move axis, and whether `MoveDelta` was crossed. A scene
overlay renders the outline path; only opaque moves mutate the managed scene
during motion. Release or second-button abort is the single terminal boundary,
which also resumes a bounded function-continuation stack so `f.deltastop`
observes the completed asynchronous interaction. Unmap and destruction clear
both the session and any continuation before releasing the toplevel.

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
