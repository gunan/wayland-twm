# Real-world `.twmrc` regression corpus

This corpus uses the complete historical user-configuration sample set shipped
in the signed X.Org `twm` 1.0.13.1 release: `jim.twmrc`, `keith.twmrc`, and
`lemke.twmrc`. The files are referenced directly from
`reference/upstream/twm-1.0.13.1/sample-twmrc/`; they are not duplicated or
normalized here. The upstream-reference test proves that those files are
byte-for-byte copies of the signed release archive members.

These are representative regression inputs rather than minimal syntax
fixtures. Together, their 728 lines combine global options, fonts, color and
monochrome blocks, cursor and pixmap definitions, squeeze-title rules,
per-window lists, title buttons, icon-manager settings, mouse bindings,
modifier and context combinations, composed functions, and menus. They also
retain historically realistic values such as host-specific paths, font names,
window-name lists, and commands.

`manifest.json` pins the corpus selection, provenance, canonical paths, hashes,
and the broad behavior represented by each file. The Meson test `real-world
twmrc corpus` validates the manifest and compares every canonical file with its
signed-archive member. Three additional Meson tests run each file through
`wtwm-config`; a parser change that rejects any complete real-world input is
therefore a regression.

The release archive's `COPYING` member supplies the copyright notices and
redistribution permissions for the release contents. The archive, detached
signature, signer key, hashes, and detailed provenance are preserved in
`reference/upstream/twm-1.0.13.1/`.
