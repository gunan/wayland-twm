#!/bin/sh

set -eu

if [ "$#" -ne 3 ]; then
	echo "usage: run-meson-build.sh BUILD_DIRECTORY COMPOSITOR PROFILE" >&2
	echo "profiles: debug, release, asan, ubsan" >&2
	exit 2
fi

build_dir=$1
compositor=$2
profile=$3

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

echo "Configuring $profile build in $build_dir (compositor=$compositor)"

configure_build()
{
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
