# twm compatibility

This table is a short 0.1 overview; the assessed 384-row ledger and audit
summary are authoritative: `reference/ledger/twm-1.0.13.1.json` and
`docs/audits/compatibility-ledger.md`. “Parsed” never implies a runtime effect,
and `wtwm-config FILE` reports compatibility-fallback statements.

| twm facility | 0.1 status | Wayland mapping |
| --- | --- | --- |
| `~/.twmrc.0`, `~/.twmrc`, `-f` search | Effective | Same precedence, followed by packaged defaults |
| `Color` / `Monochrome` blocks | Effective in part | Frame and title colors accept `#RRGGBB`, `rgb:r/g/b`, gray percentages, and common names |
| Border/title padding and widths | Partial | Border width and title padding have consumers; other stored widths/padding remain parsed-only |
| `ButtonN` and quoted key bindings | Effective | libinput buttons and xkbcommon key symbols |
| `root`, `window`, `title`, `frame`, `all` contexts | Effective | Scene hit-test contexts |
| Shift, Control, Lock, Meta modifiers | Partial | Shift, Control, Lock, Meta/Mod1, and Meta4 have native mappings; other parsed Meta numbers lack audited runtime evidence |
| `Function` and `f.function` | Effective | Recursive action sequence, depth limited to eight |
| Move, force-move, resize, raise, lower | Effective | Compositor-controlled scene operations |
| Focus, unfocus, delete/destroy, exec, quit | Effective | `destroy` becomes a Wayland close request; clients cannot be killed through xdg-shell |
| Native `xdg-shell` windows and popups | Effective | Toplevel map, unmap, remap, metadata, focus cleanup, and destruction are managed; nested popups retain parent-relative placement in the shared unmanaged overlay and are constrained to the output bounds |
| `NoTitle`, `MakeTitle`, `AutoRaise`, `StartIconified` | Effective | X11 lists match `WM_NAME`, then `WM_CLASS` instance and class; native lists match xdg title, then `app_id` |
| `Menu` and `f.menu` | Effective | Press-drag-release root and window menus use a compositor-owned scene layer above client overlays |
| Title buttons | Parsed / partial | Classic built-in dot and resize boxes are effective; bitmap substitution is pending |
| Icon windows and icon manager | Parsed | Wayland has no client icon-window primitive; compositor UI is pending |
| Zoom/maximize variants | Parsed | Output-aware geometry and saved-state restore are pending |
| `WarpCursor` and warp actions | Parsed | Requires explicit Wayland-compositor behavior; pending |
| Fonts / XLFD strings | Partial | Pango/Fontconfig names work; XLFD names use the classic fallback font pending full translation |
| X11 save-under, backing-store, colormap, grabs | Accepted / parsed-only | No verified-no-op claim is made without runtime and reference evidence |
| Xwayland lifecycle and startup inheritance | Effective | A lazy wlroots-managed Xwayland server shares the compositor seat; its allocated `DISPLAY` is exported before `-s` commands and retired during compositor shutdown |
| Xwayland ICCCM window-manager bridge | Implemented | Managed and override-redirect lifecycle, live metadata and hints, transient relationships, configure/stack requests, graceful delete, and forced termination are covered by a purpose-built XCB integration client |
| Xwayland `.twmrc` window-list matching | Effective | Managed X11 windows apply title, instance, and class matches with reference ordering and case sensitivity; override-redirect windows are excluded |
| Wayland/Xwayland selections | Effective | `wl_data_device` CLIPBOARD and primary-selection v1 PRIMARY offers, targets, ownership, and payloads bridge bidirectionally through the shared seat |

Wayland intentionally prevents a compositor from reproducing a few X11
operations literally. The compatibility policy is to preserve the visible
user result when possible, document the translation when it is not, and never
silently reinterpret configuration as a different action.

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
both the X and scene stacks, and configure requests preserve X11 client
coordinates while enforcing advertised minimum, maximum, base-size, and
resize-increment hints. Aspect and gravity values are retained for later
placement/geometry parity work.

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
icon. Rendering supplied icons in compositor-owned icon UI remains pending.

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

Clipboard-manager persistence after the owning client exits is not provided.
Native PRIMARY support requires clients to implement the standard unstable-v1
primary-selection protocol. Legacy X cut buffers and the twm cut-buffer actions
remain separate later-roadmap work; they are not silently treated as these
selections.

For X11 clients, `f.delete` follows `twm`: it sends `WM_DELETE_WINDOW` only
when the client advertises that protocol and never falls back to killing a
non-cooperating client. `f.destroy` uses X client termination. Native Wayland
clients retain their protocol close-request behavior because xdg-shell has no
separate client-kill operation.

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
