#!/bin/sh
set -eu

test "$#" -eq 2 || {
	printf 'usage: packaged-config-test.sh WTWM_CONFIG SYSTEM_TWMRC\n' >&2
	exit 2
}

config_tool=$1
system_twmrc=$2
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-packaged-config-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'packaged-config-test: %s\n' "$1" >&2
	exit 1
}

dump=$test_dir/system-twmrc.dump
"$config_tool" "$system_twmrc" > "$dump"

grep -Fx '  key=Return mods=0x8 contexts=0x3f action=f.exec xterm' \
	"$dump" >/dev/null ||
	fail 'Meta+Return does not start the reference xterm client'
test "$(grep -Fc 'f.exec "xterm"' "$system_twmrc")" -eq 2 ||
	fail 'packaged terminal binding and menu entry do not both start xterm'
if grep -F 'f.exec "foot"' "$system_twmrc" >/dev/null; then
	fail 'packaged configuration still selects foot as a default terminal'
fi

grep -Fx '  button=1 mods=0x0 contexts=0x8 action=f.function move-or-iconify' \
	"$dump" >/dev/null ||
	fail 'plain Button1 on an icon does not restore or move the window'
grep -Fx '  button=2 mods=0x0 contexts=0x8 action=f.iconify' \
	"$dump" >/dev/null ||
	fail 'plain Button2 on an icon does not toggle the window'
grep -Fx '  button=1 mods=0x0 contexts=0x20 action=f.iconify' \
	"$dump" >/dev/null ||
	fail 'plain Button1 on an icon-manager entry does not toggle the window'
grep -Fx '  button=2 mods=0x0 contexts=0x20 action=f.iconify' \
	"$dump" >/dev/null ||
	fail 'plain Button2 on an icon-manager entry does not toggle the window'

printf '%s\n' 'packaged-config-test: pass'
