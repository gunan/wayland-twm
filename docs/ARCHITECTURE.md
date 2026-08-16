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
                     DRM, nested Wayland, or X11 backend
```

`src/config.c` is ISO C plus POSIX file handling. It has no X11, Wayland, or
wlroots dependency. `src/geometry.c` likewise keeps twm's frame math and
`ConstrainSize` ordering portable, so exhaustive host-native tests do not need
a graphics stack. `wtwm-config` and the portable tests therefore build on any
ordinary Unix host. `src/wtwm.c` is the Linux compositor adapter and targets
the wlroots 0.18 public API.

Each xdg-toplevel owns one scene subtree. A solid frame and title/button
rectangles are server-side nodes; Pango-rendered immutable buffers provide
window and menu text; the client xdg-surface is offset below them. Hit testing
maps scene nodes back into twm's `root`, `window`, `title`, and
`frame` binding contexts. Parsed actions are dispatched by the compositor,
and `f.function` recursively executes the same action records used by menus
and bindings.

The installed binary is called `wtwm`, not `twm`. The Wayland-session desktop
file is also namespaced, so installing the package is co-installable and
reversible.
