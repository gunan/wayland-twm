# Build and test platforms

The project intentionally exercises portable code and the wlroots compositor in
different environments. All automated builds treat compiler warnings as errors.

## Host-native portable tests

The configuration parser, `wtwm-config`, and platform-independent validation
tests do not require Wayland or wlroots. Run the same debug profile used by the
macOS x86-64 and ARM64 GitHub-hosted runners with:

```sh
sh scripts/ci/run-meson-build.sh build-host disabled debug
```

This is the supported host-native path for parser work on macOS. It compiles the
portable targets and runs every test registered by the parser-only Meson build.

## Debian Trixie profiles

Debian 13 (Trixie) remains the pinned package and reference-comparison baseline.
That pin makes CI repeatable; it is not a requirement to publish through the
official Debian archive. The package is built for each architecture exercised
by the Debian CI jobs; a successful compiler job alone is not package-install
evidence for that architecture.

Install the controlled dependency set on Debian Trixie with:

```sh
apt-get update
xargs apt-get install -y --no-install-recommends < scripts/ci/debian-trixie-build-packages.txt
```

Then select one of four build profiles:

```sh
sh scripts/ci/run-meson-build.sh build-debug enabled debug
sh scripts/ci/run-meson-build.sh build-release enabled release
sh scripts/ci/run-meson-build.sh build-asan enabled asan
sh scripts/ci/run-meson-build.sh build-ubsan enabled ubsan
```

Each command configures Meson with `-Dcompositor=enabled` and `-Dwerror=true`,
compiles the result, and runs the full registered test suite. The sanitizer
profiles also make AddressSanitizer or UndefinedBehaviorSanitizer abort the test
run on the first reported defect. Separate build directories keep profile
artifacts from contaminating one another.

## Debian 14 / testing profile

Debian 14 (Forky) is a continuously tested target through Debian testing until
it is released, using wlroots 0.20. For 1.0, select either Debian 13 or Debian 14
as the package-certification release and run the complete amd64 and arm64 matrix
on that one release; testing both releases is not required. This project does
not require an official Debian repository submission. Install the dependency
set used by the Forky/testing CI lane and run the full debug profile with:

```sh
apt-get update
xargs apt-get install -y --no-install-recommends < scripts/ci/debian-testing-build-packages.txt
sh scripts/ci/run-meson-build.sh build-testing enabled debug
```

The compositor must be explicitly enabled. A parser-only build is not evidence
of Debian testing compatibility.

## Continuous integration

GitHub Actions preserves the baseline Debian Trixie debug job and the controlled
reference-`twm` job, and adds a Debian testing/wlroots 0.20 debug lane. Additional
jobs cover release, AddressSanitizer, and UndefinedBehaviorSanitizer builds on
x86-64; debug and release builds run on native ARM64 hardware. The workflow
explicitly checks the architecture reported inside each Debian container, so an
accidentally emulated or mislabeled build fails instead of being counted as
native coverage.

Portable builds run natively on macOS x86-64 and ARM64. GitHub documents the
standard Linux ARM64 runner label in its
[hosted-runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Validate the checked-in workflow, package list, and build-profile script without
starting a Linux compositor build:

```sh
python3 -B tests/platform/validate_build_platforms.py \
  --source-root . --self-test-tamper
```

## Debian package build and local contracts

Build the binary package from a clean source tree on the selected Debian 13 or
Debian 14 release. The example below is the pinned Trixie profile; substitute
`libwlroots-0.20-dev` on Forky:

```sh
sudo apt-get install -y --no-install-recommends \
  build-essential devscripts debhelper meson ninja-build pkgconf \
  libfontconfig-dev libpango1.0-dev libwayland-dev \
  libwlroots-0.18-dev libx11-dev libxcb1-dev libxkbcommon-dev \
  wayland-protocols dialog emacs-gtk x11-apps xterm xwayland
dpkg-buildpackage --build=binary --unsigned-changes --unsigned-source
```

Inspect the resulting artifact before installation:

```sh
dpkg-deb --info ../wtwm_*.deb
dpkg-deb --contents ../wtwm_*.deb
lintian ../wtwm_*.changes
```

The portable package contracts run without root and do not install a package:

```sh
tests/platform/package-isolation-test.sh
tests/platform/package-lifecycle-driver-test.sh
tests/platform/session-launcher-test.sh
tests/platform/session-entrypoints-test.sh
mandoc -T lint data/wtwm.1 data/wtwm-config.1 data/wtwmrc.5
```

They validate the namespaced filesystem/session contract and the lifecycle
driver's phase ordering. They cannot prove dpkg/apt maintainer behavior. For a
release candidate, run the guarded Debian VM procedure in
`packaging/debian/README.md` with the candidate and every prior released `.deb`
for the same architecture. Keep clean install/removal and per-architecture
task items unchecked until the real artifact run succeeds.

The package intentionally has no maintainer script that changes login-manager
policy or user files. It installs one `wtwm.desktop` Wayland session and never
uses the alternatives system for `twm` or a compositor default.
