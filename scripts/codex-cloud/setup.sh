#!/usr/bin/env bash

set -euo pipefail

run_as_root() {
	if [ "$(id -u)" -eq 0 ]; then
		"$@"
	else
		sudo "$@"
	fi
}

if ! command -v apt-get >/dev/null 2>&1; then
	echo "This setup expects the apt-based Codex universal environment." >&2
	exit 1
fi

run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
	--no-install-recommends \
	build-essential \
	meson \
	ninja-build \
	pkgconf \
	libwayland-dev \
	libxkbcommon-dev \
	libpango1.0-dev \
	wayland-protocols

# Debian suites expose different versioned wlroots pkg-config modules. Install
# the newest supported development package available, or derive the package
# name from an explicit source-compatibility override.
requested_wlroots_pkg="${CODEX_CLOUD_WLROOTS_PKGCONFIG:-}"
case "$requested_wlroots_pkg" in
	*[!A-Za-z0-9_.+-]*)
		echo "CODEX_CLOUD_WLROOTS_PKGCONFIG must be a pkg-config module name" >&2
		exit 2
		;;
esac
if [ -n "$requested_wlroots_pkg" ]; then
	wlroots_modules=("$requested_wlroots_pkg")
	wlroots_packages=("lib${requested_wlroots_pkg}-dev")
else
	wlroots_modules=(wlroots-0.20 wlroots-0.19 wlroots-0.18)
	wlroots_packages=(libwlroots-0.20-dev libwlroots-0.19-dev libwlroots-0.18-dev)
fi
have_wlroots=false
for module in "${wlroots_modules[@]}"; do
	if pkg-config --exists "$module"; then
		have_wlroots=true
		break
	fi
done
if [ "$have_wlroots" = false ]; then
	for package in "${wlroots_packages[@]}"; do
		if apt-cache show "$package" >/dev/null 2>&1; then
			run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
				--no-install-recommends "$package"
			break
		fi
	done
fi

bash scripts/codex-cloud/build.sh
