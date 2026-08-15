#!/bin/sh
set -eu

usage()
{
	printf '%s\n' \
		'usage: assert-coinstallation.sh ROOT {installed|absent} [PACKAGE_FILE_MANIFEST]' >&2
	exit 2
}

test "$#" -ge 2 && test "$#" -le 3 || usage
root=$1
expected=$2
manifest=${3:-}
case $expected in installed|absent) ;; *) usage ;; esac
test -d "$root" || {
	printf 'assert-coinstallation.sh: root does not exist: %s\n' "$root" >&2
	exit 1
}

fail()
{
	printf 'assert-coinstallation.sh: %s\n' "$1" >&2
	exit 1
}

root=${root%/}
test -n "$root" || root=/
path()
{
	if test "$root" = /; then
		printf '/%s\n' "$1"
	else
		printf '%s/%s\n' "$root" "$1"
	fi
}

binary=$(path usr/bin/wtwm)
config_tool=$(path usr/bin/wtwm-config)
session=$(path usr/share/wayland-sessions/wtwm.desktop)
x11_session=$(path usr/share/xsessions/wtwm.desktop)
system_config=$(path usr/share/wtwm/system.twmrc)

if test "$expected" = absent; then
	for installed_path in "$binary" "$config_tool" "$session" "$x11_session" "$system_config"; do
		test ! -e "$installed_path" && test ! -L "$installed_path" ||
			fail "path remains after purge: $installed_path"
	done
	printf '%s\n' 'assert-coinstallation.sh: absent state passes'
	exit 0
fi

test -x "$binary" || fail 'wtwm binary is missing or not executable'
test -x "$config_tool" || fail 'wtwm-config is missing or not executable'
test -f "$system_config" || fail 'packaged system.twmrc is missing'
test -f "$session" || fail 'Wayland session entry is missing'
test ! -e "$x11_session" && test ! -L "$x11_session" ||
	fail 'wtwm must not install an X11 session entry'

test "$(sed -n 's/^Name=//p' "$session")" = 'Wayland twm' ||
	fail 'Wayland session name is not distinct'
test "$(sed -n 's/^Type=//p' "$session")" = Application ||
	fail 'Wayland session type is invalid'
test "$(sed -n 's/^DesktopNames=//p' "$session")" = wtwm ||
	fail 'DesktopNames is not namespaced to wtwm'
session_exec=$(sed -n 's/^Exec=//p' "$session")
case $session_exec in
	wtwm|wtwm-session|/usr/libexec/wtwm-session) ;;
	*) fail "unexpected session command: $session_exec" ;;
esac
test "$(grep -c '^Name=' "$session")" -eq 1 ||
	fail 'session entry must contain exactly one Name'
test "$(grep -c '^Exec=' "$session")" -eq 1 ||
	fail 'session entry must contain exactly one Exec'
if grep -Eq '^Hidden=(true|1|yes)$' "$session"; then
	fail 'Wayland session entry is hidden'
fi

if test -n "$manifest"; then
	test -f "$manifest" || fail "package manifest not found: $manifest"
	if grep -Eq '^/?usr/bin/twm$|^/?usr/share/xsessions/' "$manifest"; then
		fail 'package owns an X11 twm binary or X11 session path'
	fi
fi

printf '%s\n' 'assert-coinstallation.sh: installed state passes'
