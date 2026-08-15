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

## Continuous integration

GitHub Actions preserves the baseline Debian Trixie debug job and the controlled
reference-`twm` job. Additional jobs cover release, AddressSanitizer, and
UndefinedBehaviorSanitizer builds on x86-64; debug and release builds run on
native ARM64 hardware. The workflow explicitly checks the architecture reported
inside each Debian container, so an accidentally emulated or mislabeled build
fails instead of being counted as native coverage.

Portable builds run natively on macOS x86-64 and ARM64. GitHub documents the
standard Linux ARM64 runner label in its
[hosted-runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Validate the checked-in workflow, package list, and build-profile script without
starting a Linux compositor build:

```sh
python3 -B tests/platform/validate_build_platforms.py \
  --source-root . --self-test-tamper
```
