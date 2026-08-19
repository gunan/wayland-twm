#!/usr/bin/env bash

set -euo pipefail

build_dir="${CODEX_CLOUD_BUILD_DIR:-build}"
requested_compositor="${CODEX_CLOUD_COMPOSITOR:-auto}"

case "$requested_compositor" in
	auto|enabled|disabled) ;;
	*)
		echo "CODEX_CLOUD_COMPOSITOR must be auto, enabled, or disabled" >&2
		exit 2
		;;
esac

compositor="$requested_compositor"
if [ "$requested_compositor" = auto ]; then
	if pkg-config --exists wlroots-0.18 || pkg-config --exists wlroots-0.20; then
		compositor=enabled
	else
		compositor=disabled
	fi
elif [ "$requested_compositor" = enabled ] \
		&& ! pkg-config --exists wlroots-0.18 \
		&& ! pkg-config --exists wlroots-0.20; then
	echo "CODEX_CLOUD_COMPOSITOR=enabled requires wlroots-0.18 or wlroots-0.20" >&2
	echo "Use auto for a portable parser build, or provide a supported wlroots API." >&2
	exit 1
fi

echo "Configuring Codex Cloud build with compositor=$compositor"

if [ -f "$build_dir/meson-private/coredata.dat" ]; then
	meson setup "$build_dir" --reconfigure \
		-Dcompositor="$compositor" -Dwerror=true
else
	meson setup "$build_dir" \
		-Dcompositor="$compositor" -Dwerror=true
fi

meson compile -C "$build_dir"
meson test -C "$build_dir" --print-errorlogs

if [ "$compositor" = disabled ]; then
	echo "Portable parser suite passed; the wlroots compositor build was not available."
fi
