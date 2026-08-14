# twm compatibility

This table describes 0.1 behavior. “Parsed” means a normal twm file loads and
the construct is retained, but every resulting operation may not be visible
yet. `wtwm-config FILE` reports a count for statements accepted only for
forward compatibility.

| twm facility | 0.1 status | Wayland mapping |
| --- | --- | --- |
| `~/.twmrc.0`, `~/.twmrc`, `-f` search | Effective | Same precedence, followed by packaged defaults |
| `Color` / `Monochrome` blocks | Effective in part | Frame and title colors accept `#RRGGBB`, `rgb:r/g/b`, gray percentages, and common names |
| Border/title padding and widths | Effective | Server-side scene rectangles |
| `ButtonN` and quoted key bindings | Effective | libinput buttons and xkbcommon key symbols |
| `root`, `window`, `title`, `frame`, `all` contexts | Effective | Scene hit-test contexts |
| Shift, Control, Lock, Meta modifiers | Effective | Meta is Alt/Mod1; Meta4 maps the logo key |
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
| X11 save-under, backing-store, colormap, grabs | Accepted/no-op | No Wayland equivalent |
| Xwayland applications and `WM_CLASS` matching | Not yet | Xwayland lifecycle integration is pending |

Wayland intentionally prevents a compositor from reproducing a few X11
operations literally. The compatibility policy is to preserve the visible
user result when possible, document the translation when it is not, and never
silently reinterpret configuration as a different action.
