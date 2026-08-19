#!/bin/sh
set -eu

usage()
{
	printf '%s\n' \
		'usage: assert-coinstallation.sh ROOT {installed|prior|absent} [PACKAGE_FILE_MANIFEST]' >&2
	exit 2
}

test "$#" -ge 2 && test "$#" -le 3 || usage
root=$1
expected=$2
manifest=${3:-}
case $expected in installed|prior|absent) ;; *) usage ;; esac
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
session_launcher=$(path usr/bin/wtwm-session)
session=$(path usr/share/wayland-sessions/wtwm.desktop)
x11_session=$(path usr/share/xsessions/wtwm.desktop)
system_config=$(path usr/share/wtwm/system.twmrc)
wtwm_man=$(path usr/share/man/man1/wtwm.1)
config_man=$(path usr/share/man/man1/wtwm-config.1)
twmrc_man=$(path usr/share/man/man5/wtwmrc.5)

exists_plain_or_gz()
{
	test -f "$1" || test -f "$1.gz"
}

if test "$expected" = absent; then
	for installed_path in "$binary" "$config_tool" "$session_launcher" \
			"$session" "$x11_session" "$system_config"; do
		test ! -e "$installed_path" && test ! -L "$installed_path" ||
			fail "path remains after purge: $installed_path"
	done
	for manual_path in "$wtwm_man" "$config_man" "$twmrc_man"; do
		test ! -e "$manual_path" && test ! -L "$manual_path" &&
			test ! -e "$manual_path.gz" && test ! -L "$manual_path.gz" ||
			fail "manual remains after purge: $manual_path"
	done
	printf '%s\n' 'assert-coinstallation.sh: absent state passes'
	exit 0
fi

test -x "$binary" || fail 'wtwm binary is missing or not executable'
test -x "$config_tool" || fail 'wtwm-config is missing or not executable'
test -x "$session_launcher" || fail 'wtwm-session is missing or not executable'
test -f "$system_config" || fail 'packaged system.twmrc is missing'
test -f "$session" || fail 'Wayland session entry is missing'
exists_plain_or_gz "$wtwm_man" || fail 'wtwm(1) manual is missing'
exists_plain_or_gz "$config_man" || fail 'wtwm-config(1) manual is missing'
if test "$expected" = installed; then
	exists_plain_or_gz "$twmrc_man" || fail 'wtwmrc(5) manual is missing'
fi
test ! -e "$x11_session" && test ! -L "$x11_session" ||
	fail 'wtwm must not install an X11 session entry'

test "$(sed -n 's/^Name=//p' "$session")" = 'Wayland twm' ||
	fail 'Wayland session name is not distinct'
test "$(sed -n 's/^Type=//p' "$session")" = Application ||
	fail 'Wayland session type is invalid'
test "$(sed -n 's/^DesktopNames=//p' "$session")" = wtwm ||
	fail 'DesktopNames is not namespaced to wtwm'
session_exec=$(sed -n 's/^Exec=//p' "$session")
test "$session_exec" = wtwm-session ||
	fail "unexpected session command: $session_exec"
session_try_exec=$(sed -n 's/^TryExec=//p' "$session")
if test "$expected" = installed; then
	test "$session_try_exec" = wtwm-session ||
		fail "unexpected session availability command: $session_try_exec"
fi
test "$(grep -c '^Name=' "$session")" -eq 1 ||
	fail 'session entry must contain exactly one Name'
test "$(grep -c '^Exec=' "$session")" -eq 1 ||
	fail 'session entry must contain exactly one Exec'
if test "$expected" = installed; then
	test "$(grep -c '^TryExec=' "$session")" -eq 1 ||
		fail 'session entry must contain exactly one TryExec'
fi
if grep -Eq '^Hidden=(true|1|yes)$' "$session"; then
	fail 'Wayland session entry is hidden'
fi

if test -n "$manifest"; then
	test -f "$manifest" || fail "package manifest not found: $manifest"
	manifest_has()
	{
		grep -Fx "/$1" "$manifest" >/dev/null ||
			grep -Fx "$1" "$manifest" >/dev/null
	}
	manifest_has_manual()
	{
		manifest_has "$1" || manifest_has "$1.gz"
	}
	for required_path in \
		usr/bin/wtwm \
		usr/bin/wtwm-config \
		usr/bin/wtwm-session \
		usr/share/wayland-sessions/wtwm.desktop \
		usr/share/wtwm/system.twmrc; do
		manifest_has "$required_path" ||
			fail "package manifest omits required path: /$required_path"
	done
	manifest_has_manual usr/share/man/man1/wtwm.1 ||
		fail 'package manifest omits wtwm(1)'
	manifest_has_manual usr/share/man/man1/wtwm-config.1 ||
		fail 'package manifest omits wtwm-config(1)'
	if test "$expected" = installed; then
		manifest_has_manual usr/share/man/man5/wtwmrc.5 ||
			fail 'package manifest omits wtwmrc(5)'
	fi
	if grep -Eq '^/?usr/bin/twm$|^/?usr/share/xsessions/|^/?etc/alternatives/|^/?etc/(gdm|gdm3|lightdm|sddm)/' "$manifest"; then
		fail 'package owns an X11 twm path or desktop/login-manager policy path'
	fi
	if grep -E '^/?usr/share/wayland-sessions/' "$manifest" |
		grep -Ev '^/?usr/share/wayland-sessions/wtwm\.desktop$' >/dev/null; then
		fail 'package owns another compositor session entry'
	fi
fi

printf '%s\n' 'assert-coinstallation.sh: installed state passes'
