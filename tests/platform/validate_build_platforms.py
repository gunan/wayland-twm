#!/usr/bin/env python3
"""Validate the portable build profiles and GitHub Actions platform matrix."""

from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path


REQUIRED_PACKAGES = {
    "build-essential",
    "git",
    "libfontconfig-dev",
    "libpango1.0-dev",
    "libwayland-dev",
    "libwlroots-0.18-dev",
    "libxkbcommon-dev",
    "meson",
    "ninja-build",
    "pkgconf",
    "python3",
    "wayland-protocols",
}

TESTING_REQUIRED_PACKAGES = (REQUIRED_PACKAGES - {"libwlroots-0.18-dev"}) | {
    "debhelper",
    "dpkg-dev",
    "libwlroots-0.20-dev",
    "libx11-dev",
}

REQUIRED_PACKAGE_JOB_PACKAGES = {
    "debhelper",
    "dpkg-dev",
    "libx11-dev",
    "lintian",
    "mandoc",
    "twm",
    "weston",
}

WLROOTS_019_REQUIRED_PACKAGES = {
    "build-essential",
    "dialog",
    "emacs-gtk",
    "git",
    "libfontconfig-dev",
    "libpango1.0-dev",
    "libwayland-dev",
    "libwlroots-0.19-dev",
    "libx11-dev",
    "libxcb1-dev",
    "libxkbcommon-dev",
    "meson",
    "ninja-build",
    "pkgconf",
    "python3",
    "wayland-protocols",
    "x11-apps",
    "xfonts-base",
    "xkb-data",
    "xterm",
    "xwayland",
}

WLROOTS_MASTER_REQUIRED_PACKAGES = (
    WLROOTS_019_REQUIRED_PACKAGES - {"libwlroots-0.19-dev"}
) | {
    "libdrm-dev",
    "libpixman-1-dev",
    "libxcb-composite0-dev",
    "libxcb-ewmh-dev",
    "libxcb-icccm4-dev",
    "libxcb-render0-dev",
    "libxcb-res0-dev",
    "libxcb-shape0-dev",
    "libxcb-xfixes0-dev",
}

PLATFORM_CONFIGURATIONS = (
    ("x86-64 release", "ubuntu-24.04", "amd64", "release"),
    ("x86-64 AddressSanitizer", "ubuntu-24.04", "amd64", "asan"),
    ("x86-64 UndefinedBehaviorSanitizer", "ubuntu-24.04", "amd64", "ubsan"),
    ("ARM64 debug", "ubuntu-24.04-arm", "arm64", "debug"),
    ("ARM64 release", "ubuntu-24.04-arm", "arm64", "release"),
)

HOST_CONFIGURATIONS = (
    ("macOS ARM64", "macos-15", "arm64"),
    ("macOS x86-64", "macos-15-intel", "x86_64"),
)


def job_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    return match.group(1) if match else ""


def include_entry(block: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^          - name: {re.escape(name)}\n(.*?)(?=^          - name: |^    [A-Za-z]|\Z)",
        block,
    )
    return match.group(1) if match else ""


def validate(source_root: Path) -> list[str]:
    errors: list[str] = []
    workflow_path = source_root / ".github/workflows/build.yml"
    script_path = source_root / "scripts/ci/run-meson-build.sh"
    packages_path = source_root / "scripts/ci/debian-trixie-build-packages.txt"
    testing_packages_path = source_root / "scripts/ci/debian-testing-build-packages.txt"
    package_script_path = source_root / "scripts/ci/run-debian-package-ci.sh"
    package_packages_path = source_root / "scripts/ci/debian-trixie-package-packages.txt"
    wlroots_019_packages_path = (
        source_root / "scripts/ci/debian-sid-wlroots-0.19-build-packages.txt"
    )
    wlroots_master_packages_path = (
        source_root / "scripts/ci/debian-sid-wlroots-master-build-packages.txt"
    )
    wlroots_source_script_path = source_root / "scripts/ci/install-wlroots-source.sh"
    candidate_script_path = source_root / "packaging/debian/clean-candidate-test.sh"
    candidate_test_path = source_root / "tests/platform/clean-candidate-driver-test.sh"

    for path in (
        workflow_path,
        script_path,
        packages_path,
        testing_packages_path,
        package_script_path,
        package_packages_path,
        wlroots_019_packages_path,
        wlroots_master_packages_path,
        wlroots_source_script_path,
        candidate_script_path,
        candidate_test_path,
    ):
        if not path.is_file():
            errors.append(f"missing build-platform file: {path.relative_to(source_root)}")
    if errors:
        return errors

    workflow = workflow_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8")
    packages = {
        line.strip()
        for line in packages_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    testing_packages = {
        line.strip()
        for line in testing_packages_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    package_job_packages = {
        line.strip()
        for line in package_packages_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    package_script = package_script_path.read_text(encoding="utf-8")
    candidate_script = candidate_script_path.read_text(encoding="utf-8")
    wlroots_019_packages = {
        line.strip()
        for line in wlroots_019_packages_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    wlroots_master_packages = {
        line.strip()
        for line in wlroots_master_packages_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    wlroots_source_script = wlroots_source_script_path.read_text(encoding="utf-8")

    missing_packages = sorted(REQUIRED_PACKAGES - packages)
    if missing_packages:
        errors.append("Debian Trixie package list is missing: " + ", ".join(missing_packages))
    missing_testing_packages = sorted(TESTING_REQUIRED_PACKAGES - testing_packages)
    if missing_testing_packages:
        errors.append(
            "Debian testing package list is missing: " + ", ".join(missing_testing_packages)
        )
    missing_package_job_packages = sorted(REQUIRED_PACKAGE_JOB_PACKAGES - package_job_packages)
    if missing_package_job_packages:
        errors.append(
            "Debian package job list is missing: " + ", ".join(missing_package_job_packages)
        )
    missing_wlroots_019_packages = sorted(
        WLROOTS_019_REQUIRED_PACKAGES - wlroots_019_packages
    )
    if missing_wlroots_019_packages:
        errors.append(
            "Debian sid wlroots 0.19 package list is missing: "
            + ", ".join(missing_wlroots_019_packages)
        )
    unexpected_wlroots_019_packages = sorted(
        package
        for package in wlroots_019_packages
        if package.startswith("libwlroots") and package != "libwlroots-0.19-dev"
    )
    if unexpected_wlroots_019_packages:
        errors.append(
            "Debian sid wlroots 0.19 package list mixes API minors: "
            + ", ".join(unexpected_wlroots_019_packages)
        )
    missing_wlroots_master_packages = sorted(
        WLROOTS_MASTER_REQUIRED_PACKAGES - wlroots_master_packages
    )
    if missing_wlroots_master_packages:
        errors.append(
            "Debian sid wlroots master package list is missing: "
            + ", ".join(missing_wlroots_master_packages)
        )
    packaged_wlroots_master_dependencies = sorted(
        package
        for package in wlroots_master_packages
        if package.startswith("libwlroots")
    )
    if packaged_wlroots_master_dependencies:
        errors.append(
            "wlroots master must be built from source, not distro packages: "
            + ", ".join(packaged_wlroots_master_dependencies)
        )

    for marker in ("workflow_dispatch:", "schedule:", "cron: '23 5 * * 1'"):
        if marker not in workflow:
            errors.append(f"workflow is missing advisory trigger: {marker!r}")

    baseline = job_block(workflow, "debian-trixie")
    if not baseline:
        errors.append("workflow is missing the required debian-trixie job")
    else:
        for marker in (
            "runs-on: ubuntu-latest",
            "container: debian:trixie",
            'test "$(dpkg --print-architecture)" = amd64',
            "pkg-config --atleast-version=0.18 wlroots-0.18",
            "pkg-config --max-version=0.18.999 wlroots-0.18",
            "scripts/ci/run-meson-build.sh build enabled debug wlroots-0.18",
        ):
            if marker not in baseline:
                errors.append(f"debian-trixie job is missing contract marker: {marker!r}")
        for marker in (
            "if: always()",
            "name: m9-mixed-soak-smoke-debug",
            "path: build/m9-mixed-soak-smoke.json*",
            "if-no-files-found: warn",
        ):
            if marker not in baseline:
                errors.append(f"debian-trixie soak upload is missing marker: {marker!r}")

    testing = job_block(workflow, "debian-testing")
    if not testing:
        errors.append("workflow is missing the required debian-testing job")
    else:
        for marker in (
            "container: debian:testing",
            "scripts/ci/debian-testing-build-packages.txt",
            'test "$(dpkg --print-architecture)" = amd64',
            "pkg-config --atleast-version=0.20 wlroots-0.20",
            "pkg-config --max-version=0.20.999 wlroots-0.20",
            "dpkg-checkbuilddeps",
            "scripts/ci/run-meson-build.sh build-testing enabled debug wlroots-0.20",
        ):
            if marker not in testing:
                errors.append(f"debian-testing job is missing contract marker: {marker!r}")

    package_job = job_block(workflow, "debian-package")
    if not package_job:
        errors.append("workflow is missing the required debian-package job")
    else:
        for marker in (
            "container: debian:trixie",
            "scripts/ci/debian-trixie-package-packages.txt",
            "test -x /usr/bin/twm",
            "test -f /usr/share/xsessions/twm.desktop",
            "test -x /usr/bin/weston",
            "test -f /usr/share/wayland-sessions/weston.desktop",
            "test ! -e /usr/bin/wtwm",
            "touch /etc/wtwm-package-ci-container",
            "scripts/ci/run-debian-package-ci.sh",
            "if: always()",
            "actions/upload-artifact@v4",
            "path: /tmp/wtwm-package-artifacts",
            "if-no-files-found: error",
        ):
            if marker not in package_job:
                errors.append(f"debian-package job is missing contract marker: {marker!r}")

    minimal_package_job = job_block(workflow, "debian-minimal-package")
    if not minimal_package_job:
        errors.append("workflow is missing the required debian-minimal-package job")
    else:
        for marker in (
            "container: debian:trixie",
            "DEB_BUILD_OPTIONS: nocheck",
            "DEB_BUILD_PROFILES: nocheck",
            "apt-get build-dep -y --no-install-recommends -Pnocheck .",
            "dpkg-checkbuilddeps -Pnocheck",
            "dpkg-buildpackage --build=binary --unsigned-changes --unsigned-source",
            "dpkg-deb -f \"$candidate\" Depends",
        ):
            if marker not in minimal_package_job:
                errors.append(
                    "debian-minimal-package job is missing contract marker: "
                    f"{marker!r}"
                )

    wlroots_019 = job_block(workflow, "wlroots-019")
    if not wlroots_019:
        errors.append("workflow is missing the required wlroots-019 job")
    else:
        for marker in (
            "container: debian:sid",
            "scripts/ci/debian-sid-wlroots-0.19-build-packages.txt",
            'test "$(dpkg --print-architecture)" = amd64',
            "pkg-config --atleast-version=0.19 wlroots-0.19",
            "pkg-config --max-version=0.19.999 wlroots-0.19",
            "! pkg-config --exists wlroots-0.18",
            "! pkg-config --exists wlroots-0.20",
            "scripts/ci/run-meson-build.sh build-wlroots-019 enabled debug wlroots-0.19",
        ):
            if marker not in wlroots_019:
                errors.append(f"wlroots-019 job is missing contract marker: {marker!r}")

    wlroots_advisory = job_block(workflow, "wlroots-upstream-advisory")
    if not wlroots_advisory:
        errors.append("workflow is missing the wlroots upstream advisory job")
    else:
        for marker in (
            "github.event_name == 'schedule'",
            "github.event_name == 'workflow_dispatch'",
            "container: debian:sid",
            "scripts/ci/debian-sid-wlroots-master-build-packages.txt",
            "scripts/ci/install-wlroots-source.sh master 0.21.0-dev wlroots-0.21",
            'test "$(pkg-config --modversion wlroots-0.21)" = 0.21.0-dev',
            "scripts/ci/run-meson-build.sh build-wlroots-master enabled debug wlroots-0.21",
        ):
            if marker not in wlroots_advisory:
                errors.append(
                    f"wlroots upstream advisory job is missing contract marker: {marker!r}"
                )

    reference = job_block(workflow, "reference-twm")
    if not reference:
        errors.append("workflow is missing the required reference-twm job")
    else:
        for marker in (
            "tests/reference/build_reference_twm.sh",
            "tests/reference/capture_reference_twm.sh",
            "tests/reference/verify_canonical_x11_apps.sh",
            "actions/upload-artifact@v4",
        ):
            if marker not in reference:
                errors.append(f"reference-twm job is missing contract marker: {marker!r}")

    platforms = job_block(workflow, "debian-trixie-configurations")
    if not platforms:
        errors.append("workflow is missing the Debian architecture/profile matrix")
    else:
        for name, runner, architecture, profile in PLATFORM_CONFIGURATIONS:
            entry = include_entry(platforms, name)
            if not entry:
                errors.append(f"platform matrix is missing {name}")
                continue
            for marker in (
                f"runner: {runner}",
                f"architecture: {architecture}",
                f"profile: {profile}",
            ):
                if marker not in entry:
                    errors.append(f"platform matrix entry {name!r} is missing {marker!r}")
        for marker in (
            "container: debian:trixie",
            'test "$(dpkg --print-architecture)" = "${{ matrix.architecture }}"',
            "scripts/ci/run-meson-build.sh",
            "enabled",
            '"${{ matrix.profile }}"',
            "wlroots-0.18",
        ):
            if marker not in platforms:
                errors.append(f"platform matrix is missing contract marker: {marker!r}")
        for marker in (
            "if: always()",
            "name: m9-mixed-soak-smoke-${{ matrix.architecture }}-${{ matrix.profile }}",
            "path: build-${{ matrix.profile }}/m9-mixed-soak-smoke.json*",
            "if-no-files-found: warn",
        ):
            if marker not in platforms:
                errors.append(f"platform matrix soak upload is missing marker: {marker!r}")

    hosts = job_block(workflow, "host-native-portable")
    if not hosts:
        errors.append("workflow is missing host-native portable tests")
    else:
        for name, runner, architecture in HOST_CONFIGURATIONS:
            entry = include_entry(hosts, name)
            if not entry:
                errors.append(f"host-native matrix is missing {name}")
                continue
            for marker in (f"runner: {runner}", f"architecture: {architecture}"):
                if marker not in entry:
                    errors.append(f"host-native entry {name!r} is missing {marker!r}")
        for marker in (
            'test "$(uname -m)" = "${{ matrix.architecture }}"',
            "scripts/ci/run-meson-build.sh build-host disabled debug",
        ):
            if marker not in hosts:
                errors.append(f"host-native job is missing contract marker: {marker!r}")

    for marker in (
        "-Dcompositor=\"$compositor\"",
        "-Dwerror=true",
        "--buildtype=\"$buildtype\"",
        "-Db_sanitize=\"$sanitize\"",
        "-Db_lundef=false",
        "meson compile -C \"$build_dir\"",
        "meson test -C \"$build_dir\" --print-errorlogs",
        "ASAN_OPTIONS=detect_leaks=1:halt_on_error=1",
        "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1",
        'actual_version=$(pkg-config --modversion "$wlroots_pkgconfig")',
        '"-Dwlroots_pkgconfig=$wlroots_pkgconfig"',
    ):
        if marker not in script:
            errors.append(f"Meson profile runner is missing contract marker: {marker!r}")

    for marker in (
        "https://gitlab.freedesktop.org/wlroots/wlroots.git",
        'git clone --depth 1 --branch "$ref"',
        "0.21.0-dev:wlroots-0.21",
        "-Dauto_features=disabled",
        "-Dbackends=[]",
        "-Drenderers=[]",
        "-Dxwayland=enabled",
        'printf \'PKG_CONFIG_PATH=%s\\n\'',
        'printf \'LD_LIBRARY_PATH=%s\\n\'',
        'printf \'WLROOTS_SOURCE_COMMIT=%s\\n\'',
    ):
        if marker not in wlroots_source_script:
            errors.append(f"wlroots source installer is missing contract marker: {marker!r}")

    for marker in (
        "dpkg-buildpackage -us -uc -b",
        "-name 'm9-mixed-soak-smoke.json*'",
        "lintian --fail-on error",
        "packaging/debian/clean-candidate-test.sh",
        "--protect /usr/bin/twm",
        "--protect /usr/share/xsessions/twm.desktop",
        "--protect /usr/bin/weston",
        "--protect /usr/share/wayland-sessions/weston.desktop",
    ):
        if marker not in package_script:
            errors.append(f"Debian package runner is missing contract marker: {marker!r}")

    for marker in (
        "clean-candidate-only",
        "apt-get install -y --no-install-recommends",
        "apt-get remove -y wtwm",
        "dpkg --purge wtwm",
        "candidate-owned file remains",
        "prior_release_upgrade\\tnot-tested",
        "rollback\\tnot-tested",
    ):
        if marker not in candidate_script:
            errors.append(f"clean candidate lifecycle is missing contract marker: {marker!r}")

    if "continue-on-error" in workflow:
        errors.append("workflow must not hide failures with continue-on-error")

    return errors


def self_test_tamper(source_root: Path) -> list[str]:
    source_workflow = source_root / ".github/workflows/build.yml"
    with tempfile.TemporaryDirectory(prefix="wtwm-platform-contract-") as temporary:
        root = Path(temporary)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "scripts/ci").mkdir(parents=True)
        (root / "packaging/debian").mkdir(parents=True)
        (root / "tests/platform").mkdir(parents=True)
        workflow = source_workflow.read_text(encoding="utf-8")
        (root / ".github/workflows/build.yml").write_text(
            workflow.replace("runner: ubuntu-24.04-arm", "runner: ubuntu-24.04", 1).replace(
                "test -f /usr/share/wayland-sessions/weston.desktop",
                "test -f /tmp/unprotected-weston.desktop",
                1,
            ).replace("container: debian:testing", "container: debian:trixie", 1).replace(
                "apt-get build-dep -y --no-install-recommends -Pnocheck .",
                "apt-get build-dep -y --no-install-recommends .",
                1,
            ).replace(
                "pkg-config --max-version=0.19.999 wlroots-0.19",
                "pkg-config --max-version=0.20.999 wlroots-0.19",
                1,
            ),
            encoding="utf-8",
        )
        (root / "scripts/ci/run-meson-build.sh").write_text(
            (source_root / "scripts/ci/run-meson-build.sh").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (root / "scripts/ci/debian-trixie-build-packages.txt").write_text(
            (source_root / "scripts/ci/debian-trixie-build-packages.txt")
            .read_text(encoding="utf-8")
            .replace("git\n", "", 1),
            encoding="utf-8",
        )
        (root / "scripts/ci/debian-testing-build-packages.txt").write_text(
            (source_root / "scripts/ci/debian-testing-build-packages.txt").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        for relative in (
            "scripts/ci/run-debian-package-ci.sh",
            "scripts/ci/debian-trixie-package-packages.txt",
            "scripts/ci/debian-sid-wlroots-0.19-build-packages.txt",
            "scripts/ci/debian-sid-wlroots-master-build-packages.txt",
            "scripts/ci/install-wlroots-source.sh",
            "packaging/debian/clean-candidate-test.sh",
            "tests/platform/clean-candidate-driver-test.sh",
        ):
            (root / relative).write_text(
                (source_root / relative).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        tamper_errors = validate(root)
    if not any(
        "debian-package job" in error and "/usr/share/wayland-sessions/weston.desktop" in error
        for error in tamper_errors
    ):
        return ["self-test failed: removing protected Weston session coverage was not detected"]
    if not any("ARM64 debug" in error and "ubuntu-24.04-arm" in error for error in tamper_errors):
        return ["self-test failed: replacing the native ARM64 runner was not detected"]
    if not any(
        "debian-testing job" in error and "container: debian:testing" in error
        for error in tamper_errors
    ):
        return ["self-test failed: replacing the Debian testing container was not detected"]
    if not any(
        "Debian Trixie package list is missing: git" in error
        for error in tamper_errors
    ):
        return ["self-test failed: removing the validator git dependency was not detected"]
    if not any(
        "debian-minimal-package job" in error and "-Pnocheck" in error
        for error in tamper_errors
    ):
        return ["self-test failed: removing the nocheck dependency profile was not detected"]
    if not any(
        "wlroots-019 job" in error and "0.19.999" in error
        for error in tamper_errors
    ):
        return ["self-test failed: widening the wlroots 0.19 range was not detected"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--self-test-tamper", action="store_true")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    errors = validate(source_root)
    if args.self_test_tamper and not errors:
        errors.extend(self_test_tamper(source_root))
    if errors:
        for error in errors:
            print(f"build-platform validation failed: {error}")
        return 1

    print(
        "build-platform validation passed: wlroots 0.18/0.19/0.20, upstream "
        "advisory, native hosts, architectures, and profiles are covered"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
