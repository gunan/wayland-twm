#!/bin/sh
set -eu

test "$#" -eq 3 || {
	printf '%s\n' \
		'usage: debian-menu-integration-test.sh WTWM_CONFIG TEMPLATE MENU_METHOD' >&2
	exit 2
}

config_tool=$1
template=$2
menu_method=$3
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-debian-menu-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'debian-menu-integration-test: %s\n' "$1" >&2
	exit 1
}

test "$(grep -Fxc 'include-menu-defs' "$template")" -eq 1 ||
	fail 'template does not contain exactly one install-menu placeholder'
grep -Fx 'Button1 = : root : f.menu "/Debian"' "$template" >/dev/null ||
	fail 'Button1 does not open the generated Debian menu'
grep -Fx 'Button2 = : root : f.menu "defops"' "$template" >/dev/null ||
	fail 'Button2 does not retain the built-in operations menu'

grep -Fx '#!/usr/bin/install-menu' "$menu_method" >/dev/null ||
	fail 'menu method does not use install-menu'
grep -Fx '    x11=item($command);' "$menu_method" >/dev/null ||
	fail 'menu method does not translate graphical application entries'
grep -Fx '    text=item(term());' "$menu_method" >/dev/null ||
	fail 'menu method does not translate terminal application entries'
grep -Fx 'rootprefix="/etc/wtwm/";' "$menu_method" >/dev/null ||
	fail 'menu method output is not namespaced under /etc/wtwm'
grep -Fx 'examplercfile="system.twmrc-menu";' "$menu_method" >/dev/null ||
	fail 'menu method does not select the packaged wtwm template'
if grep -Eq '/etc/X11/twm|(^|[[:space:]])wm=' "$menu_method"; then
	fail 'menu method targets X11 twm or exposes unsafe compositor switching'
fi

generated=$test_dir/system.twmrc
awk '
$0 == "include-menu-defs" {
	print "Menu \"/Debian\""
	print "{"
	print "  \"Applications\" f.menu \"/Debian/Applications\""
	print "}"
	print "Menu \"/Debian/Applications\""
	print "{"
	print "  \"Example\" f.exec \"example-app &\""
	print "}"
	next
}
{ print }
' "$template" > "$generated"

dump=$test_dir/generated.dump
"$config_tool" "$generated" > "$dump"
grep -Fx '  button=1 mods=0x0 contexts=0x1 action=f.menu /Debian' \
	"$dump" >/dev/null || fail 'generated config does not bind the Debian menu'
grep -Fx '  button=2 mods=0x0 contexts=0x1 action=f.menu defops' \
	"$dump" >/dev/null || fail 'generated config loses the operations menu'
grep -Fx '  /Debian items=1' "$dump" >/dev/null ||
	fail 'generated Debian root menu is not parseable'
grep -Fx '  /Debian/Applications items=1' "$dump" >/dev/null ||
	fail 'generated Debian application submenu is not parseable'
grep -Fx '  key=Return mods=0x8 contexts=0x3f action=f.exec xterm' \
	"$dump" >/dev/null || fail 'generated config loses the xterm shortcut'

printf '%s\n' 'debian-menu-integration-test: pass'
