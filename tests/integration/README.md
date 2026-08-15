# Compositor integration harness

Meson builds `wtwm-test-compositor` with the private control interface enabled;
the installed `wtwm` binary is built from the same compositor source without
that interface. The control socket accepts one newline-delimited command at a
time and returns one `OK` or `ERROR` line.

Commands are `PING`, `OUTPUT width height`, `POINTER x y`, `BUTTON code
press|release`, `KEY code press|release`, `STATE`, `WAIT [frames]`, `CAPTURE
path`, `SET ANIMATION_MS n`, `SET PLACEMENT_SEED n`, `SET CURSOR x y`, `SET
FONT description`, and `QUIT`. `STATE` returns JSON containing focus, client
geometry, top-to-bottom stacking order, iconified clients, menu state, cursor
position, and deterministic-control values. `CAPTURE` writes the first output
as a binary PPM.

Run the headless stability check explicitly with:

```sh
python3 tests/integration/run_compositor.py \
  --compositor build/wtwm-test-compositor \
  --client build/wtwm-wayland-test-client --repeat 100
```

Pass `--nested` to use the parent `WAYLAND_DISPLAY`; the harness exits with the
standard skip status when there is no usable parent Wayland socket.
