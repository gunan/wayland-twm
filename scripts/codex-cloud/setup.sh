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

# Debian Trixie and testing expose different versioned wlroots pkg-config
# modules. Install the first supported development package available from the
# environment's apt suite and otherwise retain the documented portable fallback.
if ! pkg-config --exists wlroots-0.18 && ! pkg-config --exists wlroots-0.20; then
	for package in libwlroots-0.18-dev libwlroots-0.20-dev; do
		if apt-cache show "$package" >/dev/null 2>&1; then
			run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
				--no-install-recommends "$package"
			break
		fi
	done
fi

bash scripts/codex-cloud/build.sh
