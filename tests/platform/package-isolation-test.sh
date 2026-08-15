#!/bin/sh
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
assert_script=$source_root/packaging/debian/assert-coinstallation.sh
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-package-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'package-isolation-test: %s\n' "$1" >&2
	exit 1
}

mkdir -p "$test_dir/usr/bin" "$test_dir/usr/share/wayland-sessions" \
	"$test_dir/usr/share/wtwm"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_dir/usr/bin/wtwm"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_dir/usr/bin/wtwm-config"
cp "$source_root/scripts/platform/wtwm-session" "$test_dir/usr/bin/wtwm-session"
chmod +x "$test_dir/usr/bin/wtwm" "$test_dir/usr/bin/wtwm-config" \
	"$test_dir/usr/bin/wtwm-session"
cp "$source_root/data/system.twmrc" "$test_dir/usr/share/wtwm/system.twmrc"
cp "$source_root/data/wtwm.desktop" \
	"$test_dir/usr/share/wayland-sessions/wtwm.desktop"
printf '%s\n' \
	'/usr/bin/wtwm' \
	'/usr/bin/wtwm-config' \
	'/usr/bin/wtwm-session' \
	'/usr/share/wayland-sessions/wtwm.desktop' \
	'/usr/share/wtwm/system.twmrc' > "$test_dir/manifest"

"$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null

mkdir -p "$test_dir/usr/share/xsessions"
cp "$source_root/data/wtwm.desktop" "$test_dir/usr/share/xsessions/wtwm.desktop"
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'an X11 session collision was accepted'
fi
rm "$test_dir/usr/share/xsessions/wtwm.desktop"

printf '%s\n' '/usr/bin/twm' >> "$test_dir/manifest"
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'ownership of the X11 twm binary was accepted'
fi
sed '$d' "$test_dir/manifest" > "$test_dir/manifest.clean"
mv "$test_dir/manifest.clean" "$test_dir/manifest"

sed 's/^Name=.*/Name=twm/' "$test_dir/usr/share/wayland-sessions/wtwm.desktop" \
	> "$test_dir/bad.desktop"
mv "$test_dir/bad.desktop" "$test_dir/usr/share/wayland-sessions/wtwm.desktop"
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'a non-distinct session name was accepted'
fi

rm "$test_dir/usr/bin/wtwm" "$test_dir/usr/bin/wtwm-config" \
	"$test_dir/usr/bin/wtwm-session" \
	"$test_dir/usr/share/wayland-sessions/wtwm.desktop" \
	"$test_dir/usr/share/wtwm/system.twmrc"
"$assert_script" "$test_dir" absent >/dev/null

printf '%s\n' 'package-isolation-test: pass'
