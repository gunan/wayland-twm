#!/bin/sh

set -eu

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
	echo "usage: run-meson-build.sh BUILD_DIRECTORY COMPOSITOR PROFILE [WLROOTS_PKGCONFIG]" >&2
	echo "profiles: debug, release, asan, ubsan" >&2
	exit 2
fi

build_dir=$1
compositor=$2
profile=$3
wlroots_pkgconfig=${4:-}

case "$compositor" in
	enabled|disabled) ;;
	*)
		echo "compositor must be enabled or disabled" >&2
		exit 2
		;;
esac

case "$profile" in
	debug)
		buildtype=debug
		sanitize=none
		;;
	release)
		buildtype=release
		sanitize=none
		;;
	asan)
		buildtype=debugoptimized
		sanitize=address
		;;
	ubsan)
		buildtype=debugoptimized
		sanitize=undefined
		;;
	*)
		echo "profile must be debug, release, asan, or ubsan" >&2
		exit 2
		;;
esac

case "$wlroots_pkgconfig" in
	""|wlroots-0.18|wlroots-0.19|wlroots-0.20|wlroots-0.21) ;;
	*)
		echo "unsupported wlroots pkg-config dependency: $wlroots_pkgconfig" >&2
		exit 2
		;;
esac

if [ -n "$wlroots_pkgconfig" ]; then
	expected_version=${wlroots_pkgconfig#wlroots-}
	actual_version=$(pkg-config --modversion "$wlroots_pkgconfig")
	case "$actual_version" in
		"$expected_version"|"$expected_version".*) ;;
		*)
			echo "$wlroots_pkgconfig resolved to unexpected version $actual_version" >&2
			exit 1
			;;
	esac
fi

echo "Configuring $profile build in $build_dir (compositor=$compositor, wlroots=${wlroots_pkgconfig:-auto})"

configure_build()
{
	if [ -n "$wlroots_pkgconfig" ]; then
		set -- "$@" "-Dwlroots_pkgconfig=$wlroots_pkgconfig"
	fi
	if [ "$sanitize" = none ]; then
		meson setup "$build_dir" "$@" \
			-Dcompositor="$compositor" \
			-Dwerror=true \
			--buildtype="$buildtype"
	else
		meson setup "$build_dir" "$@" \
			-Dcompositor="$compositor" \
			-Dwerror=true \
			--buildtype="$buildtype" \
			-Db_sanitize="$sanitize" \
			-Db_lundef=false
	fi
}

if [ -f "$build_dir/meson-private/coredata.dat" ]; then
	configure_build --reconfigure
else
	configure_build
fi

meson compile -C "$build_dir"

case "$profile" in
	asan)
		# Instrumented Xwayland instances can starve one another's initial frame
		# handshake when every integration test starts in parallel.
		if [ "$(uname -s)" = Darwin ]; then
			# Apple's AddressSanitizer runtime aborts when leak detection is requested.
			ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
				meson test -C "$build_dir" --print-errorlogs --num-processes 1
		else
			ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
				meson test -C "$build_dir" --print-errorlogs --num-processes 1
		fi
		;;
	ubsan)
		UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
			meson test -C "$build_dir" --print-errorlogs
		;;
	*)
		meson test -C "$build_dir" --print-errorlogs
		;;
esac
