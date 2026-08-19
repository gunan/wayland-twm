# X.Org `twm` 1.0.13.1 reference freeze

This directory freezes the upstream reference selected by the project's
compatibility and certification requirements.
The canonical source is the complete `twm-1.0.13.1.tar.xz` release archive;
the other `twm` files here are byte-for-byte convenience copies of named
members in that archive. Do not replace files in this directory when a newer
`twm` is released. A reference-version change requires explicit review and a
new versioned directory.

## Provenance

- Release: X.Org individual app release `twm` 1.0.13.1, published 2025-05-05.
- Archive: <https://www.x.org/releases/individual/app/twm-1.0.13.1.tar.xz>
- Detached signature:
  <https://www.x.org/releases/individual/app/twm-1.0.13.1.tar.xz.sig>
- Published signer key:
  <https://invisible-island.net/public/dickey%40invisible-island.net-rsa3072.asc>
- Signer primary-key fingerprint:
  `1988 2D92 DDA4 C400 C22C 0D56 CC2A F447 2167 BE03`.
- Archive size: 272456 bytes.
- Archive SHA-256:
  `a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5`.

The detached signature was verified on 2026-08-15 against the published key
above. The archive, signature, and exact public-key snapshot are checked in so
that subsequent validation is offline and does not depend on mutable download
servers or keyservers. `SHA256SUMS` records every frozen artifact, while the
validation test also embeds the expected hashes so changing an artifact and
its adjacent checksum record together does not silently move the reference.

## Identifying the reference material

- **Source:** the complete release archive. Its `configure.ac` contains
  `AC_INIT([twm], [1.0.13.1], ...)`, independently tying the contents to the
  selected version.
- **Manual:** `man/twm.man`, the sole `twm` manual source shipped in the
  archive. The copy is at `man/twm.man` here.
- **Default bindings:** `src/system.twmrc` says it is the default configuration
  and contains the bindings. `src/gen_deftwmrc.sh` says it converts that file
  into the compiled-in `src/deftwmrc.c`. All three are preserved under
  `defaults/`, so both the editable source and the exact compiled default can
  be audited.
- **Sample configurations:** the archive's complete `sample-twmrc/` directory:
  `jim.twmrc`, `keith.twmrc`, and `lemke.twmrc`. No other sample `.twmrc` files
  ship in this release.

The Meson test `upstream reference freeze` checks the pinned hashes, archive
root and embedded version, exact archive membership of every convenience copy,
and the complete three-file sample set. When GnuPG is installed, it also
verifies the detached signature and requires the pinned signer fingerprint.

For a manual offline check from this directory:

```sh
sha256sum -c SHA256SUMS
gpg --import release-signer.asc
gpg --verify twm-1.0.13.1.tar.xz.sig twm-1.0.13.1.tar.xz
```
