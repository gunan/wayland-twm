# twm 1.0.13.1 interaction source contract

`source-contract.json` is a deterministic, executable contract for the
Milestone 4 interaction behavior that can be derived directly from the frozen
X.Org twm 1.0.13.1 source archive.  It does not claim to be a live X11 capture.
The local development host did not provide Xvfb, so `committed_live_baseline`
and `live_capture_run` deliberately remain false.

The validator opens the pinned archive, checks every cited member and line
range, verifies source anchors, recomputes every expected result, rejects
duplicate JSON keys, and runs negative tamper checks.  Run it with:

```sh
python3 -B tests/reference/validate_reference_interaction_contract.py \
  --source-root . --self-test-tamper
```

## Exact source-derived rules

- `MoveDelta` is a per-axis threshold.  A move is still pending only while
  both absolute deltas are strictly less than the configured value, so equality
  starts movement.  Zero makes even the initial position pass the threshold.
- `f.deltastop` stops the remainder of a function when `WindowMoved` is true.
  Resize sets that flag when either axis is greater than or equal to
  `MoveDelta`.
- Constrained movement is entered only when `ConstrainedMoveTime` is nonzero
  and the unsigned time since the previous move invocation is strictly less
  than it.  twm warps to the window center and uses the middle thirds as the
  dead zone.  If the first event exits both grids, the vertical assignment is
  evaluated second and wins.
- `DontMoveOff` clamps the frame/icon outer rectangle.  `f.forcemove` bypasses
  it.  The source computes the far edge before clamping the near edge; an
  oversized window therefore ends aligned to the right/bottom and may retain a
  negative left/top coordinate.
- Non-opaque movement draws an outline and applies geometry on release.
  `OpaqueMove` moves the X window during motion.  A second button press aborts
  either path and restores or preserves the original geometry.
- twm 1.0.13.1 has no `OpaqueResize` directive or path.  Interactive resize
  always rubber-bands an outline and commits with `SetupWindow` on release.
- `AutoRelativeResize` divides the client/frame into thirds, offsetting the
  vertical calculation by title height.  It preselects the nearest outer edge
  or corner, but not a middle third, and is disabled for titlebutton starts.
- Binding contexts are root, window/client, title, icon, frame, icon manager,
  name, and identify.  There is no `C_MENU` binding context in this release;
  active menus are handled by the menu state machine rather than the normal
  surface binding table.
- Default focus is X11 `PointerRoot` (`FocusRoot = TRUE`).  Entering a frame or
  icon-manager entry activates/highlights it.  `NoTitleFocus` suppresses the
  explicit `XSetInputFocus` call while preserving activation and
  `WM_TAKE_FOCUS`.  `f.focus` changes to click focus and toggles back to
  pointer-root focus when invoked on the already-focused window.  Invoking it
  on an iconified window is a no-op.
- `f.raise` and `f.lower` send the corresponding X request.  `f.raiselower`
  sends stack mode `Opposite` (and is suppressed when a preceding function
  moved the window).  `f.circleup` and `f.circledown` delegate directly to the
  X server's root-subwindow circulation operations.
- Transients and `USPosition` always bypass interactive placement.
  `PPosition` does so for `UsePPosition "on"`, and for
  `UsePPosition "non-zero"` only when either coordinate is nonzero.
  `RandomPlacement` starts at `(50,50)`, advances by `(30,30)`, and resets each
  axis independently near an edge.  `MaxWindowSize` clips initial client size
  before placement; its default is `(32767-screen_width,
  32767-screen_height)`.

## Remaining live evidence

The contract intentionally does not fabricate event traces.  A Linux/Xvfb
capture should still validate observable pointer warps, outline pixels,
synthetic focus events, X server `Opposite`/circulation results, and repeated
random-placement traces before Milestone 4 differential exit criteria are
checked.
