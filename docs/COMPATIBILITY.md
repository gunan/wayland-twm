# twm compatibility

This table is a short 0.1 overview; the assessed 384-row ledger and audit
summary are authoritative: `reference/ledger/twm-1.0.13.1.json` and
`docs/audits/compatibility-ledger.md`. “Parsed” never implies a runtime effect,
and `wtwm-config FILE` reports compatibility-fallback statements.

| twm facility | 0.1 status | Wayland mapping |
| --- | --- | --- |
| `~/.twmrc.0`, `~/.twmrc`, `-f` search | Effective global translation | Implicit startup selects only screen zero (`~/.twmrc.0`, then `~/.twmrc`) before system/built-in fallbacks; an explicit unsuffixed `-f` file is global. The one active configuration applies to every Wayland output and is never merged with `~/.twmrc.1` or higher |
| `Color` / `Grayscale` / `Monochrome` blocks | Effective | `--visual-mode` selects the active block. X11 hexadecimal and `rgb:` widths, gray percentages, and named colors resolve through exact 16-bit channels before deterministic grayscale or monochrome conversion; base and per-window colors feed frames, titles, menus, icons, the root, and cursors |
| Frame, border, and title extents | Exact in the canonical profile | Managed windows retain a frame border with or without a title; `ClientBorderWidth` preserves the original X11 border on the frame. Title height, padding, lower border, squeeze placement, text baseline and clipping, button spacing, and focus/tile patterns use the frozen reference formulas. Initial and managed `ConfigureRequest` coordinates use the reference gravity translations |
| Client size constraints | Effective during compositor-driven resize | X11 min/max/base/increment/aspect hints use reference `ConstrainSize` ordering; native xdg-shell exposes only min/max constraints, which use the same model. Ordinary client configure requests and hint-only changes do not resize a window |
| `ButtonN` and quoted key bindings | Effective | libinput buttons and exact, case-sensitive xkbcommon key-symbol names; later declarations replace the same twm trigger slot |
| `root`, `window`, `title`, `icon`, `frame`, `iconmgr`, `all`, and named contexts | Effective | Scene hit-test contexts; `all` expands to the six concrete contexts. Each enabled output background is one root-equivalent hit box; gaps and the zero-output state have no root target. Named keys use case-sensitive title, resource/`app_id`, then class prefixes and execute for every client in the first successful category |
| Shift, Control, Lock, Meta modifiers | Effective | Shift, Control, Lock, and Mod1 through Mod5 use xkb state. As in twm, Shift, Control, and Mod1 are always significant; configuring any other modifier makes it globally significant, so a configured Lock binding makes Caps Lock distinguish every binding |
| `Function` and `f.function` | Effective | Nested action sequences preserve reference order and pause across interactive move/resize; `f.deltastop` observes the completed gesture. The continuation stack permits the root function plus eight nested calls |
| Move, force-move, resize, raise, lower | Effective for move/resize interaction | Non-opaque moves and all resizes use compositor-owned outlines with release commit; `OpaqueMove` updates the live window, while second-button abort restores the original geometry. Raise/lower never imply focus |
| Focus, unfocus, delete/destroy, exec, quit | Effective | PointerRoot/sloppy focus is distinct from the click-locked `f.focus` toggle; `NoTitleFocus`, X11 input hints, and `WM_TAKE_FOCUS` are applied independently. Direct X input focus also synchronizes wlroots' XWM focus record so its guarded X11/Wayland selection bridge remains available, after which wtwm reasserts the exact core-focus target. `destroy` becomes a Wayland close request; clients cannot be killed through xdg-shell. Commands retain the exact configured source text; simple quoted/escaped argument vectors execute directly, while shell syntax alone selects unchanged `/bin/sh -c` text |
| `f.raiselower`, `f.circleup`, `f.circledown` | Effective | The shared native/Xwayland stack uses actual visible overlap: overlap-dependent `f.raiselower` matches X `Opposite`, while circulation moves the bottommost occluded or topmost occluding item. Parent/transient actions are not grouped |
| Native `xdg-shell` windows and popups | Effective | Toplevel map, unmap, remap, metadata, focus cleanup, and destruction are managed; nested popups retain parent-relative placement in the shared unmanaged overlay and are constrained to the output bounds |
| `NoTitle`, `MakeTitle`, `DecorateTransients`, `AutoRaise`, `StartIconified` | Effective | X11 lists match `WM_NAME`, then `WM_CLASS` instance and class; native lists match xdg title, then `app_id`. X11 transient title suppression is applied after `MakeTitle` and `NoTitle`, as in reference `twm` |
| `Menu` and `f.menu` | Effective | Press-drag-release root and window menus use a compositor-owned scene layer above client overlays. A root menu is pinned to its invocation output; a window menu is pinned to the target's owner output, and the whole submenu stack clamps to that box rather than the layout union. Pull-right hover opens a bounded nested stack, moving back into a parent pops its descendants, a second press cancels the stack, and release dispatches only an enabled leaf. Source-derived row, text, border, separator, pull-arrow, highlight, interpolation, title-entry, submenu, and five-pixel shadow rendering uses the configured X core font and colors |
| `NoBackingStore`, `NoSaveUnders`, `NoGrabServer` | Verified Wayland-translated no-ops | wtwm menus and opaque moves are compositor-owned scene operations: they neither request X backing-store/save-under resources nor wrap the operation in a global X server grab. The spellings remain accepted and explicitly classified without changing native or managed-Xwayland pixels, state, input traces, or liveness |
| Title buttons | Effective | Default and configured left/right buttons retain reference ordering, borders, spacing, XBM/built-in glyphs, and full hit boxes. Reference `twm` has no distinct hover/pressed pixels; the held-pointer captures are therefore identical while the action still fires on press |
| Icon windows and icon manager | Effective | Compositor-owned configured-XBM and client-image icon scenes use the reference font, per-window colors, border, bitmap/text layout, mapping state, regions, and animation endpoints. X11 `WM_HINTS` one-bit pixmaps and `_NET_WM_ICON` pixels are copied into owned buffers; configured `Icons`/`ForceIcons`, `UnknownIcon`, and `IconDirectory` preserve reference precedence. Managers implement matching, geometry, columns, sorting, visibility, highlighting, pointer focus, and all navigation actions across the ordered Wayland output layout |
| Cursors and monochrome assets | Effective | Classic role-specific Xcursor shapes are selected for frame, title, button, move, resize, menu, wait, select, and destroy contexts. Two-XBM configured cursors preserve hotspots, masks, and `PointerForeground`/`PointerBackground`; XBM also feeds title buttons, title highlights, and configured icons |
| Zoom/maximize variants | Effective | Vertical, horizontal, full, and four half-output variants use the target's current owner-output geometry, retain one pre-zoom client box while switching modes, and restore it when the current mode is repeated |
| Warp actions | Behaviorally equivalent | Window, next/previous, and window-ring warps use the shared native/Xwayland identity and stacking model. `WarpUnmapped` and `NoRaiseOnWarp` retain their reference gates. A numeric `f.warptoscreen` target selects the canonical Wayland output index and preserves the cursor's output-relative position; next/prev/back screen history and topology changes remain later Milestone 8 work |
| Fonts / XLFD strings | Exact for canonical ASCII; translated for general Unicode | Xwayland's X core font server supplies exact canonical `fixed` metrics and glyph pixels for ASCII decoration text. Numeric aliases and 14-field XLFDs map family, weight, slant, spacing, pixel size, and decipoint size into bounded Pango descriptions; non-ASCII text falls back to Pango without corrupting title geometry |
| Output scaling | Deterministic translation | Canonical layout remains integer 1×. Fractional output projection rounds coordinates expressed in Wayland 120ths by shared edges, so adjacent title/menu boxes remain adjacent and negative origins are symmetric |
| Legacy bell, priority, and save-yourself actions | Effective or verified conditional no-op | Xwayland provides the X bell and advertised `WM_SAVE_YOURSELF`. Native Wayland has no bell or save-yourself protocol. Xwayland exposes no twm XSync priority control, so that action is an explicit no-op under its documented missing-capability condition |
| `f.colormap` | Exact for relevant Xwayland clients; verified native no-op | Managed X11 targets retain the bounded `WM_COLORMAP_WINDOWS` order, including the top-level fallback, and `next`, `prev`, and `default` perform the reference circular selection and checked installed-colormap requests. Native true-color Wayland has no global installed-colormap mechanism, so the same configured action issues no X request and leaves Xwayland's installed set unchanged |
| `f.cut`, `f.cutfile`, `f.file` | Exact X cut-buffer result; Wayland clipboard translation | Successful actions replace a persistent compositor-owned byte buffer, publish it as ordinary Wayland `CLIPBOARD` text, and mirror the same bytes to Xwayland root `CUT_BUFFER0` with `STRING` type and 8-bit format. Native clients observe `CLIPBOARD`, not a nonexistent native global cut-buffer protocol; `PRIMARY` remains independent |
| Xwayland lifecycle and startup inheritance | Effective | A lazy wlroots-managed Xwayland server shares the compositor seat; its allocated `DISPLAY` is exported before `-s` commands and retired during compositor shutdown |
| Xwayland ICCCM window-manager bridge | Implemented | Managed and override-redirect lifecycle, live metadata and hints, transient relationships, configure/stack requests, graceful delete, and forced termination are covered by a purpose-built XCB integration client |
| Initial placement and `MaxWindowSize` | Exact for X11; behaviorally equivalent for native Wayland | Each first map selects one enabled output rather than the layout union. X11 `USPosition`, all `UsePPosition` modes, transient positions, the process-global `(50,50)`/`(30,30)` random sequence with selected-output edge reset, output-derived maximum-size clipping, remap stability, and the non-random outline/confirm prompt follow reference twm. Accepted X11 requests retain their exact global coordinates even in a gap or outside all outputs. Native clients have no position hints; unparented maps select the pointer output, parented maps select the managed parent's output, and non-random native maps use the pointer immediately because xdg-shell has no X11-style blocking placement grab. With zero outputs, a first map remains pending and unexposed without consuming placement state. |
| Canonical X11 applications under wtwm | Verified smoke coverage | Debian Trixie `xterm`, `xclock`, `xload`, GUI Emacs, and a real terminal `dialog` are identity-checked while mapped through Xwayland alongside the purpose-built ICCCM normal, transient, hint, and override-redirect fixtures |
| Canonical X11 reference differential | Exact through Milestone 5 | One Debian Trixie CI job runs identical clients, configuration, and input descriptions under frozen `twm` 1.0.13.1 and wtwm/Xwayland. The base comparison covers identity, lifecycle, roles, protocols, icons, and hints; a distinct reparent frame proves reference management and a compositor scene decoration proves wtwm management. A 21-event trace compares exact geometry, focus, mapped/iconified/title state, and stacking after every event; a 48-case Cartesian product compares title, border, transient, and size-hint combinations with no numeric tolerances or geometry exclusions. The Milestone 5 pixel comparison adds two stable 260×180 canonical phases whose complete PPM bytes, geometry classification, configured-color counts, and X core font pixels match the frozen reference with zero masks and zero mismatched pixels. Native/cross-protocol visual equivalence remains a separate boundary. |
| Xwayland `.twmrc` window-list matching | Effective | Managed X11 windows apply title, instance, and class matches with reference ordering and case sensitivity; override-redirect windows are excluded |
| Wayland/Xwayland selections | Effective | `wl_data_device` CLIPBOARD and primary-selection v1 PRIMARY offers, targets, ownership, and payloads bridge bidirectionally through the shared seat |
| Mixed native Wayland/Xwayland session | Verified | One headless wlroots/Xwayland session concurrently manages two native xdg toplevels and two managed X11 toplevels in one focus and stacking model. Native→X11→native and X11→native→X11 transitions require protocol-recipient keyboard acknowledgements, while native and X11 raise/lower/restore plus one unmap/remap lifecycle per protocol prove cross-protocol cleanup without losing the other clients. Selection bridging and popup/override-redirect ordering remain separate focused scenarios. |
| Adversarial client lifecycle | Verified headlessly | Separate native and X11 connections cover `SIGABRT` crashes, non-dispatching hangs, ignored close requests, and 32 numbered unmap/remap cycles per protocol. Bounded control/state/frame barriers and survivor keyboard acknowledgements prove compositor liveness, while exact scene, focus, and Xwayland association counts reject stale or duplicate lifecycle state. |

Wayland intentionally prevents a compositor from reproducing a few X11
operations literally. The compatibility policy is to preserve the visible
user result when possible, document the translation when it is not, and never
silently reinterpret configuration as a different action.

Milestone 5 also runs a compositor-owned visual-state matrix in color,
grayscale, and monochrome modes. Every capture is repeated after stable frame
barriers and must be byte-identical to its repeat; no masks are used. The matrix
covers focused and unfocused decoration in the same frame, normal/hover/pressed
title buttons, long/empty/non-ASCII/rapid titles, configured XBM icons, menu
titles and separators, normal/highlight/pull/submenu rows, shadows, and exact
configured-color samples. Because both frozen canonical decoration images are
byte-for-byte identical between reference `twm` and wtwm, an A/B reviewer has
no decoration pixels from which to identify the compositor in that profile.

Native xdg-shell toplevels are absent from the scene until their first map and
can unmap and remap without retaining focus, interactive grabs, or target-owned
menus. Title and `app_id` changes immediately update compositor metadata and
window-list matching. Popup trees retain their validated xdg parent and root,
including nested popups, while their rendered nodes are projected into the
shared unmanaged overlay. Parent-relative placement is recomputed after popup
commits and toplevel moves, and placement is unconstrained against the
containing output's layout bounds in root-surface coordinates. Parent unmap or
destruction dismisses every rooted popup before the toplevel state is released.
Layer-shell exclusive zones are not implemented yet, so the usable area is
currently the full output-layout box.

The native mapping for every twm name/class window list is explicit:

| twm identity role | X11 value | Native xdg-shell value |
| --- | --- | --- |
| window name | `WM_NAME` | xdg title, checked first |
| `WM_CLASS` resource name (instance) | resource name | xdg `app_id`, checked second |
| `WM_CLASS` resource class | resource class | the same xdg `app_id`; native clients have no third identity value |

Thus the two X11 resource-selection roles intentionally collapse to the one
stable native application identity. Each candidate uses exact, case-sensitive
comparison. There is no wildcard expansion, so a configured `"*"` matches only
a literal title or `app_id` of `*`. An unset/null field is skipped and cannot
match even a configured empty string. A present empty title or `app_id` is
compared normally and therefore matches only a configured empty string; it is
not a wildcard or fallback value.

Live title and `app_id` changes recompute `NoTitle`/`MakeTitle` decoration in
that order: the global `NoTitle` state is the starting point, a matching
`MakeTitle` enables decoration, and a matching `NoTitle` disables it last, so
`NoTitle` wins a collision. `AutoRaise` is snapshotted on the first map of an
xdg-toplevel object and is not recomputed by later metadata changes.
`StartIconified` is likewise considered only on that object's first map. Both
object-lifetime decisions survive a protocol unmap/remap; in particular, a
remap is not iconified a second time. Destroying the xdg-toplevel and creating
a new one begins a fresh native management lifetime and takes fresh snapshots.

wtwm reserves an Xwayland display during compositor startup and starts the X
server lazily when the first X11 client connects. The allocated `DISPLAY` is
exported before the `-s` startup command, so legacy programs launched there
inherit the correct server instead of a parent session's display. Xwayland is
wired to the compositor seat, reports every successful readiness event
including a wlroots-managed restart, and is destroyed before the remaining
Wayland clients and display. If Xwayland cannot be created or its display
cannot be exported, wtwm keeps the inherited `DISPLAY` unchanged and continues
with native Wayland support.

Xwayland windows have independent create, Wayland-surface association, map,
unmap, dissociation, remap, and destruction handling. Managed windows share the
native decoration, focus, move, resize, iconify, raise/lower, menu-target, and
action model. Override-redirect windows remain undecorated and outside the
managed focus/action list. They share an overlay stack above managed clients
with native xdg popups, so each popup or override-redirect map/remap raises that
surface above older overlay siblings. Transient relationships are mirrored in
both the X and scene stacks. A transient has no title by default, and
`DecorateTransients` restores the ordinary global/`MakeTitle`/`NoTitle`
decision; transient suppression otherwise runs last and therefore also wins
over a matching `MakeTitle`. As in reference `twm`, ordinary X11 client
configure requests are not snapped to `WM_NORMAL_HINTS`, and changing the
hints alone does not resize a mapped client. Compositor-driven resizing applies
minimum, maximum, base-size, resize-increment, and aspect constraints in
reference order: clamp, snap down to the base/increment lattice, then adjust
aspect without a final reclamp. Native xdg-shell has no base-size, increment,
or aspect protocol fields, so only its advertised minimum and maximum sizes
can be honored. Initial map and managed `ConfigureRequest` coordinates use the
reference gravity and border translations. Initial maximum clipping and
position-hint/random/transient selection run before that conversion. X11
windows without an honored hint use a compositor-owned outline while their
client scene remains hidden: pointer motion selects the outer-frame origin,
Button1 confirms on release, Button2 enters placement resize, and Button3 fills
the remaining lower-right output area. Native xdg-shell has no position-hint
protocol and its initial map cannot be held inside the synchronous X11
`MapRequest` path, so non-random native maps use the current pointer immediately
without the obsolete cascade offset.

Interactive move and resize use the source-derived `twm` state machine.
`MoveDelta` is a strict per-axis threshold (equality starts, zero starts on the
first motion); a rapid second move enters `ConstrainedMoveTime` only when the
unsigned elapsed timestamp is strictly smaller than the configured value.
Leaving both outer-rectangle thirds at once selects vertical motion, matching
the reference's ordered tests. `DontMoveOff` clamps the outer frame in
near-edge/far-edge order, including the reference far-edge result for a frame
larger than the output, while `f.forcemove` bypasses that clamp.
`AutoRelativeResize` selects left/right and top/bottom edges from thirds after
the title offset and is disabled for title-bar invocation. Size constraints
preserve the opposite edge during left/top resizing. Non-opaque moves and every
resize keep client geometry unchanged while an overlay outline is displayed;
release commits it, and a second button press cancels it. `OpaqueMove` changes
the live window during motion and restores the saved origin on cancel.
`f.deltastop` resumes its function only after the asynchronous interaction has
ended and stops the remainder exactly when the pointer crossed `MoveDelta`.
`NoRaiseOnMove` and `NoRaiseOnResize` suppress their respective interaction
raises without changing focus policy. These paths are covered by a Linux
headless Xwayland runner plus a portable model/tamper contract for hosts without
wlroots.

Menu-started movement keeps its separate reference intent. A menu invoked for
a window centers the pointer and commits on the next press; a root menu defers
target selection to the next press and commits that ordinary drag on release.
Only an additional press during an ordinary drag takes the abort path.

Unbound pointer presses run `DefaultFunction`; target-requiring root actions
enter the same select-a-window state used by reference twm. The built-in
`TwmWindows` menu is assembled from the current managed stack. Selecting one
of its clients runs `WindowFunction`, or deiconifies and raises the selection
when no override was configured. Menus, title buttons, direct bindings, and
nested named functions all feed one action dispatcher, so an action is not
classified as effective merely because its spelling parsed.

`f.refresh` and `f.winrefresh` schedule compositor redraws instead of creating
temporary X cover windows. As in reference twm, `f.twmrc` is an exact alias for
`f.restart`; there is no separate upstream reload action. Reference twm
restores client borders and re-executes its original argument vector. Doing
that literally would destroy every Wayland connection, so wtwm translates both
spellings to the same in-process restart. It parses the selected `-f`,
screen-specific, user, system, or built-in configuration into a temporary
object and swaps it only after a complete successful parse. A malformed
replacement reports an error and leaves the active configuration and session
untouched. A successful swap rebuilds configured decorations, colors, cursors,
icons, icon managers, bindings, menus, and placement policy while retaining the
Wayland display, Xwayland server, client resources, stable window identities,
mapping, stack, geometry, focus, and selections. The headless Milestone 8
restart test exercises both aliases and an invalid replacement while native and
Xwayland clients prove their original protocol connections remain usable.

Reference twm gives each managed X screen a distinct root and parses its
screen-specific startup search independently. Wayland outputs are not separate
root namespaces, so wtwm uses one compositor-global configuration instead.
Without `-f`, screen zero is the sole compatibility source: wtwm tries
`$HOME/.twmrc.0`, then `$HOME/.twmrc`, then the system and built-in defaults.
It never reads or merges `.twmrc.1` or a higher suffix because another output
appeared. With `-f`, the exact unsuffixed file is the single global candidate;
HOME screen files are ignored. The configuration remains active with zero
outputs and applies unchanged to every active output.

Active outputs receive dense zero-based compatibility indices by sorting an
immutable session identity tuple `(name, make, model, serial)` in unsigned-byte
lexicographic order, treating null fields as empty, with a never-reused
announcement ordinal as the final tie-break. List insertion, scene order,
layout coordinates, mode, scale, and pointer focus do not define identity.
Numeric `f.warptoscreen` accepts only a complete unsigned ASCII decimal value
that fits `int` and names a current index; signed, partial, overflow, and
out-of-range forms are no-ops rather than reference twm's `atoi`-and-wrap
behavior. A successful numeric warp preserves the cursor's output-relative
coordinate, clamped only when the target is smaller.

The Milestone 8 headless runner starts an implicit session with zero outputs
and mutually conflicting `.twmrc.0`, `.twmrc.1`, and `.twmrc` files. One and
then two equal-sized auto-laid-out outputs prove that the screen-zero bindings
apply on both roots, `HEADLESS-1` remains index zero despite reverse compositor
list insertion, an out-of-range target preserves exact pointer coordinates,
and root `f.restart` retains the source and mapping. A second session proves an
explicit unsuffixed file is global and HOME screen files are ignored. This
mapping does not by itself claim placement or topology behavior.

Reference twm confines placement and spatial root actions to the selected X
screen's `RootWindow`, width, and height. wtwm maps each enabled Wayland
output's current logical layout box to one such spatial root. The layout-union
bounding rectangle is never a root: disabled outputs, empty gaps, and space
outside all output boxes cannot supply root bindings, backgrounds, placement,
menu, zoom, fill, or `DontMoveOff` bounds. Every enabled output owns one
`DefaultBackground` rectangle covering exactly its box, while the one Wayland
seat deliberately retains one compositor-global PointerRoot-style focus state.

A point inside an output selects that output; overlaps use canonical output
index order. A point in a gap or outside the layout selects the nearest closed
output box by squared Euclidean distance, with the same canonical tie-break,
without turning the gap into root surface. Existing window and manually moved
icon ownership uses the greatest positive intersection area, then the nearest
output to the outer-box center. Menus, initial-placement prompts/fills, zooms,
and interactive moves capture that output for the operation, so pointer motion
cannot switch bounds mid-gesture. After `f.forcemove` commits across an output
boundary, the next operation recomputes ownership from the committed geometry.

Unparented native maps select from the pointer; parented native maps inherit
their managed parent's current owner. Xwayland windows that require a prompt or
`RandomPlacement` select from the pointer. An accepted gravity-adjusted
`USPosition`/`PPosition` selects by its global frame origin (or nearest output
when the origin is in a gap/outside) but retains that requested position exactly
and bypasses `DontMoveOff`, as in reference twm. The random cursor is one
process-global cascade because upstream `PlaceX`/`PlaceY` are file-scope
statics: placements on different outputs consume successive pairs, apply only
the selected output's local edge reset, then add that output's global origin.
No output means no selected root; a managed first map stays pending and
unexposed until an output appears and neither random nor diagnostic placement
state advances.

The bounded model covers real gaps, outside points, overlaps, canonical ties,
per-output background/root hits, owner recomputation, and zero-output state.
The Linux live runner adds two auto-laid-out outputs and exact native/Xwayland
`STATE`/`TRACE` checks for global random placement, requested positions,
selected-output `MaxWindowSize`, root-menu/submenu clamping, full zoom on both
sides, Button3 fill, pinned window/icon moves, `f.forcemove`, restart continuity,
and deferred zero-output mapping. This steady-state slice deliberately leaves
next/previous/back screen history, output add/remove/scale/mode transaction
repair, restoration after output disappearance, persistent topology
reassociation, multiple-seat/input hotplug, and session lifecycle work for the
following Milestone 8 tasks. Milestone 7's globally ordered IconRegion and
icon-manager allocation pools also remain global; only an explicit icon move's
`DontMoveOff` bounds are output-pinned here.

Reference `f.startwm` replaces twm by passing its decoded argument to
`/bin/sh -c`. Wayland has no generic transfer for an existing compositor's
accepted client resources, focus, selections, or Xwayland ownership, so wtwm
does not destroy the session merely because a shell or different executable
could be launched. A direct invocation of the running wtwm program, with no
arguments or with exactly one `-f` configuration, is the supported safe
handoff: it is translated to the same atomic in-process transaction as
`f.restart`, and `-f` adopts the new path only after that configuration parses
and applies successfully. Shell commands, other program names, and unsupported
wtwm option combinations report an unsupported handoff and ring the minor-error
bell while leaving native and Xwayland clients, focus, stack, geometry, and
selection ownership live. An invalid replacement config receives the same
rollback guarantee. `f.identify` and `f.version` report through the compositor
log because Wayland has no server-owned X information-window primitive.

Reference `f.saveyourself` sends `WM_SAVE_YOURSELF` only to an X11 client that
advertises that protocol, ringing the minor-error bell otherwise;
`RestartPreviousState` consults the client's `WM_STATE` property only for
normal-versus-iconic startup. wtwm preserves both observable rules for
Xwayland and extends the Wayland translation with a compositor-owned snapshot
at `$XDG_STATE_HOME/wtwm/state` (or `$HOME/.local/state/wtwm/state`). The
versioned file is mode `0600` and atomically replaced. A complete valid file is
loaded before restoration; malformed or unsupported files are reported and
ignored without disturbing the running session. Uniquely matched native
title/`app_id` and Xwayland name/instance/class records restore output-clamped
geometry, iconic state, relative stack, valid focus, manual icon position,
auto-raise, and pre-zoom state as those clients map. Exact duplicate identities,
transients, client process/document state, and ephemeral menus or grabs are not
restored. Native clients have no `WM_SAVE_YOURSELF` protocol, so their action
saves only the compositor-owned snapshot; Xwayland clients still receive the
ClientMessage when advertised and retain the reference bell when it is absent.

Reference `twm` uses `NoBackingStore` to suppress a backing-store request on
its X menu windows, `NoSaveUnders` to suppress their save-under request, and
`NoGrabServer` to avoid a global X server grab while menus are active or opaque
moves are in progress. None of those X server resource choices exists on a
Wayland scene graph. wtwm always redraws its own menu layer from retained scene
state, composites opaque movement directly, and never grabs the X server around
either operation. Reference `twm` still performs its outlined-move server grab
regardless of `NoGrabServer`; wtwm's compositor-owned outline cannot reproduce
that global X exclusion, and the test therefore verifies the outlined path
separately. The three directives are retained as
Wayland-translated no-ops rather than silently dropped or reported unsupported.
This boundary covers wtwm-owned menus and movement for both native and managed
Xwayland toplevels; it does not rewrite independent backing-store, save-under,
or grab requests that an X11 client may make for its own windows.

The Milestone 8 headless A/B runner starts all eight subsets of mixed-case
spellings of these three flags and compares every non-empty subset with the
same option-free baseline, preventing individual effects from cancelling one
another. Each subset is tested in both outlined- and opaque-move
configurations. Every run maps one native and one managed Xwayland client,
drives the selected move path for each protocol, selects and cancels compositor
menus, and compares full-output PPM bytes plus normalized `STATE` and `TRACE`
at the same stable frame barriers. Both clients must also complete protocol
control roundtrips afterward. The comparison has no pixel masks or tolerated
state/trace differences.

For a managed Xwayland target, `f.colormap` reads up to 4096
`WM_COLORMAP_WINDOWS` entries, inserts the top-level first when the property
omits it, removes invalid windows without reordering the valid survivors, and
falls back to the top-level when the property supplies no usable entry. The
cached window/colormap identity and rotation belong to that managed toplevel;
`PropertyNotify` discards them. `next` rotates left, `prev` rotates right, and
`default` refetches and restores index zero. wtwm selects at most the X screen's
advertised `max_installed_maps`, then sends checked `InstallColormap` requests
in the same reverse list-index order as reference `twm`, leaving the first
rotated entry as the final request. X errors are reported without corrupting
the cache or terminating the XWM connection.

Native xdg-shell surfaces are true-color buffers and expose neither
`WM_COLORMAP_WINDOWS` nor an installed-colormap protocol. Dispatch therefore
returns before obtaining the XWM XCB connection, records a `native-noop`
colormap trace, and logs that no X11 request was issued. The Milestone 8
headless runner creates an X11 top-level and three child windows with private
colormaps, deliberately omits the top-level from the property, and exercises
`next`, `prev`, and `default` through configured pointer bindings. It then
replaces the property with an invalid XID followed by a new order, proving
stable invalid-entry removal and reset before checking the native no-op against
an unchanged root installed-colormap snapshot. Both client protocol
connections and the compositor control connection must remain responsive.

Reference `f.cut` stores its configured argument followed by exactly one
newline. `f.file` reads at most 4095 bytes from its configured filename, while
`f.cutfile` takes the first whitespace-delimited filename from Xwayland root
`CUT_BUFFER0` when that property is available and otherwise from wtwm's
persistent legacy buffer. A successful nonempty read replaces that buffer;
an empty file, missing file, or other read failure leaves the previous bytes
and selection ownership intact. Embedded NUL bytes are retained rather than
being mistaken for a string terminator.

Every successful replacement is exposed through the ordinary Wayland
`CLIPBOARD` selection with UTF-8/plain-text MIME targets and, while Xwayland is
available, mirrored byte-for-byte to root `CUT_BUFFER0` as `STRING` with 8-bit
format. If an action runs before Xwayland is ready, the internal buffer and
native clipboard publication still succeed and the buffer is mirrored when
Xwayland later becomes ready. External `CLIPBOARD` ownership can cancel the
current offer but does not rewrite the persistent legacy buffer, and none of
these actions changes `PRIMARY`. In-place restart retains the buffer and its
selection source. This is exact for the observable X cut-buffer result; native
Wayland has no literal global cut-buffer protocol, so native clients receive
the same bytes through the compositor-owned clipboard translation instead.

The Milestone 8 headless runner dispatches the direct actions and `^` shorthand
on native and managed Xwayland targets. It checks exact hexadecimal data from
both clipboard paths and the root property's type, format, length, and bytes,
including the newline rule, a 4095-byte embedded-NUL file, first-token filename
selection, successive replacement, empty/error preservation, foreign
clipboard independence, unchanged PRIMARY, restart persistence, and client
liveness.

Milestone 6 verification enumerates all 66 upstream action spellings and 59
distinct behaviors from the frozen source contract. Each spelling is parsed as
a direct action and through a two-level named function, checked against its
runtime dispatch case and expected state/no-op condition, and classified as
effective, behaviorally equivalent, or a conditional verified no-op. Portable
tests cross every binding context and modifier bit; Linux headless tests add
menu cancellation, nested hover/release, client-list mutation during named
bindings, icon move/resize rules, zoom restore, and function continuation and
`f.deltastop` traces.

This overlay ordering follows the visible X11 result: override-redirect windows
bypass twm's `MapRequest` management path and participate in the root sibling
stack, while reference twm maps its own menus raised. wtwm keeps managed native
and X11 windows in the base stack, places native popups and override-redirect
X11 windows in one dynamic map-ordered overlay, and reserves a final
compositor-menu layer above both. Hiding a menu destroys that top-layer subtree;
unmapping an overlay removes it from hit-testing and rendering, and remapping it
raises it again. A mixed Wayland/XCB headless integration verifies these
transitions from captured pixels, including popup anchoring across parent moves
and popup teardown/recreation across parent unmap/remap.

Override-redirect configure/restack requests remain an explicit cross-protocol
boundary. Such requests bypass X11 window-manager redirection, and the
resulting `ConfigureNotify` describes only X siblings. A native popup has no
XID, so that event cannot reveal whether an X11 raise/lower should cross it.
wtwm therefore leaves X-internal configuration unchanged but changes shared
overlay order only on map/remap; it does not invent an unconditional
cross-protocol raise/lower translation.

The bridge live-updates `WM_NAME`, both `WM_CLASS` strings,
`WM_TRANSIENT_FOR`, `WM_NORMAL_HINTS`, `WM_HINTS`, `WM_PROTOCOLS`,
`WM_ICON_NAME`, and `_NET_WM_ICON`. Input and urgency state plus client-supplied
icon pixmap, mask, and window identifiers are retained. `_NET_WM_ICON` parsing
is bounded to one complete 256x256 image worth of 32-bit words; incomplete or
larger properties are reported as truncated and never treated as a complete
icon. One-bit `WM_HINTS` pixmaps and bounded `_NET_WM_ICON` pixels are rendered
inside compositor-owned icon scenes. X11 client icon-window identifiers remain
observable, but rootless Xwayland cannot safely transplant an arbitrary X
window into a Wayland scene; wtwm therefore preserves its supplied pixmap (or
`_NET_WM_ICON`) appearance in an owned surface instead of exposing the literal
client window. Native xdg-shell has no standard icon-image or icon-window
request, so native clients use matching configured icons and `UnknownIcon`.

Iconification keeps logical membership separate from visible representation.
`IconifyByUnmapping` suppresses the owned icon scene while retaining the
window's icon-manager row; named opt-ins override the exclusion list, while a
bare global directive is carved back by `DontIconifyByUnmapping`. Ordinary
icons allocate the first fitting border-inclusive cell from configured
`IconRegion` records, with X-geometry negative offsets, reference gravity
split order, independent grid rounding, centered contents, collision avoidance,
release coalescing, and client `IconPositionHint` precedence. A manually moved
icon leaves its region allocation, as in reference twm.

The portable icon-manager model retains stable insertion order, optional
case-sensitive or folded icon-name sorting, partial-row packing, active and
per-manager selection, wrapped directional navigation, and visible/nonempty
next/previous manager traversal. Compositor scenes add the configured geometry,
columns, colors, iconified marker, active/down borders, pointer hit context,
focus behavior, and show/hide actions. Custom managers placed with negative
geometry offsets resolve against the combined ordered output layout, providing
the Wayland translation of reference multi-screen traversal. `Zoom` draws a
timer-driven outline between exact frame and icon endpoints; `Zoom` count and
`NoRaiseOnDeiconify` retain their independent reference effects.

Managed Xwayland windows use the reference `LookInList` identity order:
case-sensitive `WM_NAME`, then the `WM_CLASS` resource name (instance), then
the resource class. `NoTitle` starts from the bare global setting, applies a
matching `MakeTitle`, and finally applies a matching `NoTitle`, so `NoTitle`
wins when both lists contain the same identity. Title and class property
changes immediately recompute visible title decoration. `AutoRaise` is
captured for each management cycle, as in `twm`, rather than changing with
live metadata. An X11 client unmap withdraws that managed window; its next
map begins a fresh cycle that snapshots `AutoRaise` again and re-applies
`StartIconified`. A native xdg toplevel retains its snapshots across a
protocol unmap and remap because it remains the same managed object.
Override-redirect windows bypass all of these managed-window rules.

The ordinary Wayland `wl_data_device` selection maps to the X11 `CLIPBOARD`
selection, while `zwp_primary_selection_v1` maps to X11 `PRIMARY`. Both paths
share the compositor seat supplied to the wlroots Xwayland window manager.
MIME type `text/plain;charset=utf-8` is exposed to X11 as `UTF8_STRING`, and
`text/plain` is exposed as `TEXT`; other MIME names are interned as X target
atoms. Transfer data remains client-owned and moves through file descriptors
and X selection properties rather than a compositor-side text cache.

The bridge follows Wayland's keyboard-focus and input-serial rules. A native
client needs a valid seat serial to claim either selection, and offers are sent
to the keyboard-focused native client. During X-to-Wayland import, wlroots
admits an X-owned selection to the shared seat only while an Xwayland surface
is focused during `TARGETS` negotiation. An X11 requestor likewise needs a
focused Xwayland surface to read a Wayland-owned selection. Replacing a source
cancels the prior source, and disconnecting either a native or X11 owner clears
the corresponding proxy ownership instead of leaving stale `CLIPBOARD` or
`PRIMARY` contents.

General clipboard-manager persistence after an arbitrary owning client exits is
not provided; the compositor-owned legacy cut-buffer translation above is the
deliberate exception. Its byte cache is independent of external selection
owners.
Native PRIMARY support requires clients to implement the standard unstable-v1
primary-selection protocol. X cut buffers remain distinct from selection
ownership even though successful twm cut-buffer actions additionally publish
their bytes through `CLIPBOARD` for native interoperability.

For X11 clients, `f.delete` follows `twm`: it sends `WM_DELETE_WINDOW` only
when the client advertises that protocol and never falls back to killing a
non-cooperating client. `f.destroy` uses X client termination. Native Wayland
clients retain their protocol close-request behavior because xdg-shell has no
separate client-kill operation.

The adversarial lifecycle test makes that boundary observable. A close-capable
native client receives and ignores `f.delete`, remains mapped, then receives a
second close event because native `f.destroy` can only send the same xdg-shell
request; external process supervision is required to force that client away.
A close-capable X11 client likewise ignores `f.delete` and stays mapped, but
X11 `f.destroy` disconnects only its owning X client while the compositor and a
native survivor remain responsive. A hung client is never inferred from a
timeout alone: the fixture acknowledges its transition into the hung state
first, and control plus survivor input succeed before the runner kills it and
verifies cleanup.

## Complete configuration model

The portable configuration library now recognizes the complete frozen
1.0.13.1 grammar: scalar and singleton options, window and window-color lists,
menus, functions, all built-in actions and aliases, bindings, cursors, pixmaps,
icons, icon managers, icon regions, squeeze-title entries, title buttons, and
save-color entries. Every top-level construct is retained in source order with
its filename line, original source text, normalized value, and one of four
explicit classifications: effective, Wayland-translated, parsed-only, or
unsupported. Every non-effective entry contributes a compatibility warning;
no recognized directive is skipped as an unknown line.

Lexing follows the frozen Flex source: keywords and aliases are
case-insensitive; strings are quoted and implement the reference control,
octal, hexadecimal, quote, backslash, and continued-line escapes; comments
start with `#`; numbers are unsigned decimal input except for the explicitly
signed squeeze-title numerator. Unknown keywords, invalid characters,
unterminated strings and blocks, missing arguments, and numeric overflow are
errors with filename and line diagnostics. The original source and unbounded
normalized directive value are dynamically retained even when a legacy
fixed-size compositor-facing projection must be shortened; such a projection
is counted and reported rather than silently truncated.

Parsing and loading are transactional. A successful parse replaces the prior
model; any lexical, syntactic, I/O, or allocation failure destroys only the
candidate and leaves the active configuration intact. Repeated menu and
function definitions with the same case-sensitive name append entries as
reference `GetRoot` does; differently cased names remain distinct. Numeric,
string, and base-color assignments are last-assignment-wins. Later bindings
replace only overlapping indexed trigger/modifier/context slots, and ordered
generic records retain the original declaration sequence.

Without an explicit path, search uses the reference precedence:
`$HOME/.twmrc.<screen>`, `$HOME/.twmrc`, the packaged system file, then the
substantive compiled-in frozen system defaults. An explicit path suppresses
both home-file probes; if missing, it falls directly to the system file and
then built-in defaults. The screen-aware API makes the screen suffix explicit;
the original load API is a screen-zero wrapper.

Reference window lists do not provide shell wildcards: matching is an exact,
case-sensitive comparison against X11 `WM_NAME`, then resource name, then
resource class, so a configured `"*"` is literal. The native mapping above
compares title and then `app_id` with the same rule. Named key contexts and `f.warpto`
selectors are a separate case-sensitive prefix mode, likewise with no glob
interpretation; the native prefix mapping compares title and then `app_id`.
`NoCaseSensitive` affects icon-manager sorting in reference twm and does not
change either selection mode.
