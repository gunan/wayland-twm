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
