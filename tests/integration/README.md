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

The `canonical X11 applications under wtwm` test is Linux-only because it runs
inside a real wtwm/Xwayland session. Meson requires the Debian-packaged `xterm`,
`xclock`, `xload`, `emacs`, and `dialog` executables at configure time. The
runner waits for their exact X11 identities and mapped lifecycle state, proves
the terminal dialog process is live, and observes the existing purpose-built
ICCCM normal, transient, hint, and override-redirect fixtures. A second state
snapshot after compositor frames verifies that none exited during observation;
bounded teardown then checks that all client surfaces and the compositor exit.

The dedicated `x11-differential` CI job builds frozen `twm` 1.0.13.1 and wtwm,
then launches one shared command list containing those five real applications
and the purpose-built XCB ICCCM client under both window managers. An Xlib
observer normalizes client properties without window IDs. Managed reference
clients must have a reparent frame, while the matching wtwm test-control entry
must have a scene decoration; the normalized results must otherwise match
exactly. The uploaded JSON deliberately excludes frame geometry, pixels, and
native/cross-protocol semantics assigned to later tests and milestones.

The `mixed native and Xwayland client integration` test maps two native xdg
toplevels and two managed X11 toplevels together. It checks their exact
identities and simultaneous lifecycle associations, drives
native→X11→native and X11→native→X11 focus paths, and requires the actual
protocol recipient to acknowledge keyboard press/release while the other
protocol reports zero keys. It also raises, lowers, and restores clients across
the unified managed stack, then unmap/remaps one native and one X11 client while
the other protocol remains live. Selection bridging and popup/override-redirect
ordering remain separate focused scenarios.
