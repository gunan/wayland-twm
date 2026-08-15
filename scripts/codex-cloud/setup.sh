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

# Debian Trixie provides the exact package used by CI. The Codex universal
# image may use different apt sources, so install it only when available and
# let build.sh select the documented portable fallback otherwise.
if ! pkg-config --exists wlroots-0.18 \
		&& apt-cache show libwlroots-0.18-dev >/dev/null 2>&1; then
	run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
		--no-install-recommends libwlroots-0.18-dev
fi

bash scripts/codex-cloud/build.sh
