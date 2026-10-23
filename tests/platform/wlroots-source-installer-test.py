#!/usr/bin/env python3
"""Exercise the source installer with real Meson and an offline upstream fixture."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


# Public options from wlroots 297e01d2d4a7a7c5a343b3d244767e55f37433ba.
# In particular, color-management was renamed to icc-profile by that revision.
OPTIONS = """\
option('xcb-errors', type: 'feature', value: 'auto')
option('xwayland', type: 'feature', value: 'auto')
option('examples', type: 'boolean', value: true)
option('renderers', type: 'array', choices: ['auto', 'gles2', 'vulkan'], value: ['auto'])
option('backends', type: 'array', choices: ['auto', 'drm', 'libinput', 'x11'], value: ['auto'])
option('allocators', type: 'array', choices: ['auto', 'gbm', 'udmabuf'], value: ['auto'])
option('session', type: 'feature', value: 'auto')
option('tests', type: 'boolean', value: true)
option('icc-profile', type: 'feature', value: 'auto')
option('libliftoff', type: 'feature', value: 'auto')
"""
PROJECT = """\
project('wlroots-installer-fixture',
  version: '0.21.0-dev',
)
assert(get_option('icc-profile').disabled(), 'ICC profiles must stay disabled')
assert(get_option('xwayland').enabled(), 'Xwayland must stay enabled')
install_data('wlroots-0.21.pc', install_dir: 'lib/pkgconfig')
install_data('libwlroots-0.21.so', install_dir: 'lib')
"""
SHA = "297e01d2d4a7a7c5a343b3d244767e55f37433ba"


def main() -> None:
    source_root = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="wtwm-wlroots-installer-") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        fixture.mkdir()
        (fixture / "meson.options").write_text(OPTIONS)
        (fixture / "meson.build").write_text(PROJECT)
        (fixture / "wlroots-0.21.pc").write_text("fixture pkg-config file\n")
        (fixture / "libwlroots-0.21.so").write_bytes(b"fixture library\n")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        git = bin_dir / "git"
        git.write_text("""#!/bin/sh
set -eu
if [ "$1" = clone ]; then
    test "$#" -eq 7
    test "$2 $3 $4 $5" = '--depth 1 --branch master'
    test "$6" = https://gitlab.freedesktop.org/wlroots/wlroots.git
    cp -R "$WTWM_INSTALLER_FIXTURE/." "$7/"
elif [ "$1" = -C ] && [ "$3" = rev-parse ]; then
    case "$4" in
        HEAD) printf '%s\\n' "$WTWM_INSTALLER_SHA" ;;
        --abbrev-ref) printf '%s\\n' master ;;
        *) exit 2 ;;
    esac
else
    exit 2
fi
""")
        git.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "WTWM_INSTALLER_FIXTURE": str(fixture),
            "WTWM_INSTALLER_SHA": SHA,
        }

        def install(name: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["sh", str(source_root / "scripts/ci/install-wlroots-source.sh"),
                 "master", "0.21.0-dev", "wlroots-0.21", str(root / name),
                 str(root / (name + ".env"))],
                env=environment, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, check=False,
            )

        success = install("success")
        assert success.returncode == 0, success.stdout
        exported = (root / "success.env").read_text()
        assert f"WLROOTS_SOURCE_COMMIT={SHA}\n" in exported, exported
        assert f"PKG_CONFIG_PATH={root}/success/lib/pkgconfig\n" in exported, exported
        assert f"LD_LIBRARY_PATH={root}/success/lib\n" in exported, exported

        (fixture / "meson.build").write_text(
            PROJECT + "error('injected upstream configure failure')\n"
        )
        failure = install("failure")
        assert failure.returncode != 0, failure.stdout
        assert "injected upstream configure failure" in failure.stdout, failure.stdout
        assert not (root / "failure.env").exists(), "failed install exported its environment"
        for diagnostic in (
            "wlroots_source_ref\tmaster",
            f"wlroots_source_commit\t{SHA}",
            "wlroots_source_version\t0.21.0-dev",
        ):
            assert diagnostic in failure.stdout, failure.stdout
            assert failure.stdout.index(diagnostic) < failure.stdout.index("The Meson build system")

    print("wlroots source installer: current options, environment, and failure diagnostics passed")


if __name__ == "__main__":
    main()
