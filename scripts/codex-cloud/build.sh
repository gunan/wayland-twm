#!/usr/bin/env bash

set -euo pipefail

build_dir="${CODEX_CLOUD_BUILD_DIR:-build}"
requested_compositor="${CODEX_CLOUD_COMPOSITOR:-auto}"
requested_wlroots_pkg="${CODEX_CLOUD_WLROOTS_PKGCONFIG:-}"

case "$requested_compositor" in
	auto|enabled|disabled) ;;
	*)
		echo "CODEX_CLOUD_COMPOSITOR must be auto, enabled, or disabled" >&2
		exit 2
		;;
esac

case "$requested_wlroots_pkg" in
	*[!A-Za-z0-9_.+-]*)
		echo "CODEX_CLOUD_WLROOTS_PKGCONFIG must be a pkg-config module name" >&2
		exit 2
		;;
esac

if [ -n "$requested_wlroots_pkg" ]; then
	wlroots_candidates=("$requested_wlroots_pkg")
else
	wlroots_candidates=(wlroots-0.20 wlroots-0.19 wlroots-0.18)
fi
selected_wlroots_pkg=
for candidate in "${wlroots_candidates[@]}"; do
	if pkg-config --exists "$candidate"; then
		selected_wlroots_pkg="$candidate"
		break
	fi
done

compositor="$requested_compositor"
if [ "$requested_compositor" = auto ]; then
	if [ -n "$selected_wlroots_pkg" ]; then
		compositor=enabled
	else
		compositor=disabled
	fi
elif [ "$requested_compositor" = enabled ] && [ -z "$selected_wlroots_pkg" ]; then
	echo "CODEX_CLOUD_COMPOSITOR=enabled requires one of: ${wlroots_candidates[*]}" >&2
	echo "Use auto for a portable build, or set CODEX_CLOUD_WLROOTS_PKGCONFIG." >&2
	exit 1
fi

if [ -n "$selected_wlroots_pkg" ]; then
	echo "Configuring Codex Cloud build with compositor=$compositor wlroots=$selected_wlroots_pkg"
else
	echo "Configuring Codex Cloud build with compositor=$compositor"
fi

meson_options=(-Dcompositor="$compositor" -Dwerror=true)
if [ -n "$requested_wlroots_pkg" ]; then
	meson_options+=("-Dwlroots_pkgconfig=$requested_wlroots_pkg")
fi

if [ -f "$build_dir/meson-private/coredata.dat" ]; then
	meson setup "$build_dir" --reconfigure "${meson_options[@]}"
else
	meson setup "$build_dir" "${meson_options[@]}"
fi

meson compile -C "$build_dir"
meson test -C "$build_dir" --print-errorlogs

if [ "$compositor" = disabled ]; then
	echo "Portable parser suite passed; the wlroots compositor build was not available."
fi
