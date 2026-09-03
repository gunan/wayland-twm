#!/bin/sh

set -eu

if [ "$#" -ne 5 ]; then
	echo "usage: install-wlroots-source.sh REF EXPECTED_VERSION PKGCONFIG INSTALL_PREFIX ENV_FILE" >&2
	exit 2
fi

ref=$1
expected_version=$2
pkgconfig_name=$3
install_prefix=$4
environment_file=$5

case "$ref" in
	master) ;;
	*) echo "unsupported advisory wlroots ref: $ref" >&2; exit 2 ;;
esac
case "$expected_version:$pkgconfig_name" in
	0.21.0-dev:wlroots-0.21) ;;
	*) echo "unsupported advisory wlroots version: $expected_version ($pkgconfig_name)" >&2; exit 2 ;;
esac
case "$install_prefix:$environment_file" in
	/*:/*) ;;
	*) echo "install prefix and environment file must be absolute paths" >&2; exit 2 ;;
esac

source_dir=$(mktemp -d /tmp/wtwm-wlroots-source.XXXXXX)
build_dir=$(mktemp -d /tmp/wtwm-wlroots-build.XXXXXX)
cleanup()
{
	rm -rf -- "$source_dir" "$build_dir"
}
trap cleanup EXIT HUP INT TERM

git clone --depth 1 --branch "$ref" \
	https://gitlab.freedesktop.org/wlroots/wlroots.git "$source_dir"
source_commit=$(git -C "$source_dir" rev-parse HEAD)
test "$(git -C "$source_dir" rev-parse --abbrev-ref HEAD)" = "$ref"
test "$(sed -n "s/^[[:space:]]*version: '\([^']*\)',/\1/p" \
	"$source_dir/meson.build" | head -n 1)" = "$expected_version"

meson setup "$build_dir" "$source_dir" \
	--prefix="$install_prefix" \
	-Dauto_features=disabled \
	-Dallocators=[] \
	-Dbackends=[] \
	-Dcolor-management=disabled \
	-Dexamples=false \
	-Dlibliftoff=disabled \
	-Drenderers=[] \
	-Dsession=disabled \
	-Dtests=false \
	-Dxcb-errors=disabled \
	-Dxwayland=enabled
meson compile -C "$build_dir"
meson install -C "$build_dir"

pkgconfig_file=$(find "$install_prefix" -type f \
	-name "$pkgconfig_name.pc" -print -quit)
library_file=$(find "$install_prefix" -type f \
	-name "lib$pkgconfig_name.so*" -print -quit)
test -n "$pkgconfig_file"
test -n "$library_file"

{
	printf 'PKG_CONFIG_PATH=%s\n' "$(dirname -- "$pkgconfig_file")"
	printf 'LD_LIBRARY_PATH=%s\n' "$(dirname -- "$library_file")"
	printf 'WLROOTS_SOURCE_COMMIT=%s\n' "$source_commit"
} >> "$environment_file"

printf 'wlroots_source_ref\t%s\n' "$ref"
printf 'wlroots_source_commit\t%s\n' "$source_commit"
printf 'wlroots_source_version\t%s\n' "$expected_version"
