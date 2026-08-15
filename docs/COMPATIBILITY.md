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
| `NoTitle`, `MakeTitle`, `AutoRaise`, `StartIconified` | Effective | Bare forms and lists match Wayland `app_id` and title |
| `Menu` and `f.menu` | Effective | Press-drag-release root and window menus use compositor scene nodes |
| Title buttons | Parsed / partial | Classic built-in dot and resize boxes are effective; bitmap substitution is pending |
| Icon windows and icon manager | Parsed | Wayland has no client icon-window primitive; compositor UI is pending |
| Zoom/maximize variants | Parsed | Output-aware geometry and saved-state restore are pending |
| `WarpCursor` and warp actions | Parsed | Requires explicit Wayland-compositor behavior; pending |
| Fonts / XLFD strings | Partial | Pango/Fontconfig names work; XLFD names use the classic fallback font pending full translation |
| X11 save-under, backing-store, colormap, grabs | Accepted / parsed-only | No verified-no-op claim is made without runtime and reference evidence |
| Xwayland applications and `WM_CLASS` matching | Not yet | Xwayland lifecycle integration is pending |

Wayland intentionally prevents a compositor from reproducing a few X11
operations literally. The compatibility policy is to preserve the visible
user result when possible, document the translation when it is not, and never
silently reinterpret configuration as a different action.

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
resource class, so a configured `"*"` is literal. The native mapping compares
title and then `app_id` with the same rule. Named key contexts and `f.warpto`
selectors are a separate case-sensitive prefix mode, likewise with no glob
interpretation; the native prefix mapping compares title and then `app_id`.
`NoCaseSensitive` affects icon-manager sorting in reference twm and does not
change either selection mode.
