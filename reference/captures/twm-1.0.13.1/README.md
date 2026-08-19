# X.Org `twm` 1.0.13.1 reference capture

This directory records a deliberately small, deterministic observation of the
frozen reference window manager. It is baseline reference-capture evidence,
not the comprehensive canonical-application matrix used for final
certification.

`scenario.twmrc` is the exact configuration supplied with `twm -f`. The
`parser.json` artifact calls its result an accepted parser outcome and reports
only 13 bounded effective observations. Those fields come from an unmodified
reference binary stopped at `assign_var_savecolor`, the call immediately after
`ParseTwmrc`; GDB records selected `ScreenInfo` values, detaches, and the exact
binary continues as the window manager. This is not described as a complete
internal parse dump.

The purpose-built Xlib probe creates only two overlapping normal windows,
symbolically tagged `alpha` and `bravo`. It records client and frame geometry,
explicit input focus, and the controlled frames' order among root children.
Volatile XIDs, process IDs, temporary paths, and timestamps are omitted. Root
stacking arrays intentionally exclude unrelated internal `twm` windows.

Two phases raise and focus `bravo`, then `alpha`. Each phase stores normalized
JSON and a real 260x180 PPM root screenshot compressed with `gzip -n`. The
capture script executes the entire Xvfb/twm/client scenario twice on separate
displays from clean temporary state and requires all five artifacts to match
byte-for-byte. CI additionally compares them with `baseline/`.

`manifest.json` pins the frozen release, controlled environment, scenario and
observer sources, bootstrap CI run/artifact, committed baseline hashes, and
uncompressed screenshot hashes. The portable Meson test `reference capture
baselines` validates the full contract offline.
