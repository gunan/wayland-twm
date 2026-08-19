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

for direct_build_dependency in libx11-dev libxcb1-dev; do
	grep -Eq "^ ${direct_build_dependency},?$" "$source_root/debian/control" ||
		fail "missing direct build dependency: $direct_build_dependency"
done
grep -Eq '^Depends: .*xkb-data' "$source_root/debian/control" ||
	fail 'runtime keyboard data dependency is missing'
grep -Eq '^Recommends: .*xwayland' "$source_root/debian/control" ||
	fail 'optional Xwayland runtime recommendation is missing'
if grep -Eq '^(Conflicts|Replaces|Breaks):.*(^|[, ])twm([, ]|$)' \
		"$source_root/debian/control"; then
	fail 'package metadata conflicts with X11 twm'
fi
for documented_file in \
	docs/MIGRATING_FROM_TWM.md \
	docs/TROUBLESHOOTING.md \
	packaging/debian/README.md; do
	grep -Fx "$documented_file" "$source_root/debian/wtwm.docs" >/dev/null ||
		fail "package documentation omits $documented_file"
	test -f "$source_root/$documented_file" ||
		fail "listed package documentation is missing: $documented_file"
done

mkdir -p "$test_dir/usr/bin" "$test_dir/usr/share/wayland-sessions" \
	"$test_dir/usr/share/wtwm" "$test_dir/usr/share/man/man1" \
	"$test_dir/usr/share/man/man5"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_dir/usr/bin/wtwm"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_dir/usr/bin/wtwm-config"
cp "$source_root/scripts/platform/wtwm-session" "$test_dir/usr/bin/wtwm-session"
chmod +x "$test_dir/usr/bin/wtwm" "$test_dir/usr/bin/wtwm-config" \
	"$test_dir/usr/bin/wtwm-session"
cp "$source_root/data/system.twmrc" "$test_dir/usr/share/wtwm/system.twmrc"
cp "$source_root/data/wtwm.desktop" \
	"$test_dir/usr/share/wayland-sessions/wtwm.desktop"
cp "$source_root/data/wtwm.1" "$test_dir/usr/share/man/man1/wtwm.1"
cp "$source_root/data/wtwm-config.1" \
	"$test_dir/usr/share/man/man1/wtwm-config.1"
cp "$source_root/data/wtwmrc.5" "$test_dir/usr/share/man/man5/wtwmrc.5"
printf '%s\n' \
	'/usr/bin/wtwm' \
	'/usr/bin/wtwm-config' \
	'/usr/bin/wtwm-session' \
	'/usr/share/wayland-sessions/wtwm.desktop' \
	'/usr/share/wtwm/system.twmrc' \
	'/usr/share/man/man1/wtwm.1.gz' \
	'/usr/share/man/man1/wtwm-config.1.gz' \
	'/usr/share/man/man5/wtwmrc.5.gz' > "$test_dir/manifest"

"$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null

cp "$test_dir/usr/share/wayland-sessions/wtwm.desktop" \
	"$test_dir/session.candidate"
sed '/^TryExec=/d' "$test_dir/session.candidate" \
	> "$test_dir/usr/share/wayland-sessions/wtwm.desktop"
rm "$test_dir/usr/share/man/man5/wtwmrc.5"
"$assert_script" "$test_dir" prior "$test_dir/manifest" >/dev/null
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'a prior package passed candidate-only assertions'
fi
mv "$test_dir/session.candidate" \
	"$test_dir/usr/share/wayland-sessions/wtwm.desktop"
cp "$source_root/data/wtwmrc.5" "$test_dir/usr/share/man/man5/wtwmrc.5"

sed '\|^/usr/share/wtwm/system.twmrc$|d' "$test_dir/manifest" \
	> "$test_dir/manifest.missing"
if "$assert_script" "$test_dir" installed "$test_dir/manifest.missing" \
		>/dev/null 2>&1; then
	fail 'a package manifest missing the system configuration was accepted'
fi

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

printf '%s\n' '/etc/gdm3/daemon.conf' >> "$test_dir/manifest"
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'ownership of display-manager policy was accepted'
fi
sed '$d' "$test_dir/manifest" > "$test_dir/manifest.clean"
mv "$test_dir/manifest.clean" "$test_dir/manifest"

printf '%s\n' '/usr/share/wayland-sessions/weston.desktop' >> "$test_dir/manifest"
if "$assert_script" "$test_dir" installed "$test_dir/manifest" >/dev/null 2>&1; then
	fail 'ownership of another Wayland session was accepted'
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
	"$test_dir/usr/share/wtwm/system.twmrc" \
	"$test_dir/usr/share/man/man1/wtwm.1" \
	"$test_dir/usr/share/man/man1/wtwm-config.1" \
	"$test_dir/usr/share/man/man5/wtwmrc.5"
"$assert_script" "$test_dir" absent >/dev/null

printf '%s\n' 'package-isolation-test: pass'
