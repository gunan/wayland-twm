# Canonical X11 application fixtures

This suite is the stable application vocabulary for reference and future
compatibility tests. It deliberately defines client-side X11 semantics rather
than recording a visual or behavioral compatibility baseline.

`canonical_x11_client.c` creates one symbolically tagged client for each
purpose-built role. `_WTWM_CANONICAL_ROLE` is the stable selector; XIDs,
process IDs, display numbers, timestamps, and temporary paths are never part of
the contract. The established legacy application is Debian's real `xterm`,
launched with a controlled `WM_CLASS` and then assigned the `legacy-xterm`
symbolic role after it is managed.

The runtime verifier builds the frozen `twm` separately, starts a private Xvfb
server, launches the exact verified binary, and checks the assertions listed in
`manifest.json`. The initial and mutated title states are checked separately.
The suite records no screenshots or geometry baselines and makes no claim that
`wtwm` already matches the reference behavior.

Portable validation checks the complete category-to-assertion map, source
hashes, environment/workflow wiring, and several deliberate manifest/runtime
tamper cases. The Linux/X11 verification runs in the `reference-twm` GitHub
Actions job.
