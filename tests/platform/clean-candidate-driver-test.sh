#!/bin/sh
set -eu

mock_command()
{
	command_name=$(basename -- "$0")
	case $command_name in
		id)
			test "${1:-}" = -u || exit 2
			printf '%s\n' 0
			;;
		dpkg-deb)
			test "${1:-}" = -f && test "$#" -eq 3 || exit 2
			sed -n "s/^$3: //p" "$2"
			;;
		dpkg-query)
			test -f "$WTWM_MOCK_STATE" || exit 1
			case $* in
				*db:Status-Status*) printf '%s\n' installed ;;
				*Version*) sed -n '1p' "$WTWM_MOCK_STATE" ;;
				*) exit 2 ;;
			esac
			;;
		dpkg)
			case ${1:-} in
				--print-architecture) printf '%s\n' arm64 ;;
				--purge)
					test "$#" -eq 2 && test "$2" = wtwm || exit 2
					rm -f -- "$WTWM_MOCK_STATE"
					printf '%s\n' purge >> "$WTWM_MOCK_TRACE"
					;;
				-L)
					test -f "$WTWM_MOCK_STATE" || exit 1
					printf '%s\n' \
						'/usr/bin/wtwm' \
						'/usr/bin/wtwm-config' \
						'/usr/bin/wtwm-session' \
						'/usr/share/wayland-sessions/wtwm.desktop' \
						'/usr/share/xdg-desktop-portal/wtwm-portals.conf' \
						'/usr/share/wtwm/system.twmrc' \
						'/etc/menu-methods/wtwm' \
						'/etc/wtwm/system.twmrc-menu' \
						'/usr/share/man/man1/wtwm.1.gz' \
						'/usr/share/man/man1/wtwm-config.1.gz' \
						'/usr/share/man/man5/wtwmrc.5.gz'
					;;
				*) exit 2 ;;
			esac
			;;
		apt-get)
			action=
			package=
			for argument do
				case $argument in
					install|remove|purge) action=$argument ;;
					*.deb|wtwm) package=$argument ;;
				esac
			done
			case $action in
				install)
					test -f "$package" || exit 2
					version=$(sed -n 's/^Version: //p' "$package")
					printf '%s\n' "$version" > "$WTWM_MOCK_STATE"
					mkdir -p "$WTWM_PACKAGE_ROOT/etc/menu-methods" \
						"$WTWM_PACKAGE_ROOT/etc/wtwm" \
						"$WTWM_PACKAGE_ROOT/usr/bin" \
						"$WTWM_PACKAGE_ROOT/usr/share/wayland-sessions" \
						"$WTWM_PACKAGE_ROOT/usr/share/xdg-desktop-portal" \
						"$WTWM_PACKAGE_ROOT/usr/share/wtwm" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man1" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man5"
					printf '%s\n' '#!/bin/sh' 'exit 0' > "$WTWM_PACKAGE_ROOT/usr/bin/wtwm"
					printf '%s\n' '#!/bin/sh' 'exit 0' > "$WTWM_PACKAGE_ROOT/usr/bin/wtwm-config"
					cp "$WTWM_SOURCE_ROOT/scripts/platform/wtwm-session" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-session"
					chmod +x "$WTWM_PACKAGE_ROOT/usr/bin/wtwm" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-config" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-session"
					cp "$WTWM_SOURCE_ROOT/data/wtwm.desktop" \
						"$WTWM_PACKAGE_ROOT/usr/share/wayland-sessions/wtwm.desktop"
					cp "$WTWM_SOURCE_ROOT/data/wtwm-portals.conf" \
						"$WTWM_PACKAGE_ROOT/usr/share/xdg-desktop-portal/wtwm-portals.conf"
					cp "$WTWM_SOURCE_ROOT/data/system.twmrc" \
						"$WTWM_PACKAGE_ROOT/usr/share/wtwm/system.twmrc"
					cp "$WTWM_SOURCE_ROOT/data/system.twmrc-menu" \
						"$WTWM_PACKAGE_ROOT/etc/wtwm/system.twmrc-menu"
					cp "$WTWM_SOURCE_ROOT/debian/wtwm.menu-method" \
						"$WTWM_PACKAGE_ROOT/etc/menu-methods/wtwm"
					chmod +x "$WTWM_PACKAGE_ROOT/etc/menu-methods/wtwm"
					awk '
$0 == "include-menu-defs" {
	print "Menu \"/Debian\" { \"Example\" f.exec \"example-app &\" }"
	next
}
{ print }
' "$WTWM_SOURCE_ROOT/data/system.twmrc-menu" \
						> "$WTWM_PACKAGE_ROOT/etc/wtwm/system.twmrc"
					for manual in wtwm.1 wtwm-config.1; do
						cp "$WTWM_SOURCE_ROOT/data/$manual" \
							"$WTWM_PACKAGE_ROOT/usr/share/man/man1/$manual.gz"
					done
					cp "$WTWM_SOURCE_ROOT/data/wtwmrc.5" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man5/wtwmrc.5.gz"
					printf '%s\n' install >> "$WTWM_MOCK_TRACE"
					if test "${WTWM_MOCK_TAMPER_PROTECTED:-0}" = 1; then
						printf '%s\n' tampered > "$WTWM_PACKAGE_ROOT/usr/bin/twm"
					fi
					;;
				remove|purge)
					rm -f -- "$WTWM_MOCK_STATE" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-config" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-session" \
						"$WTWM_PACKAGE_ROOT/usr/share/wayland-sessions/wtwm.desktop" \
						"$WTWM_PACKAGE_ROOT/usr/share/xdg-desktop-portal/wtwm-portals.conf" \
						"$WTWM_PACKAGE_ROOT/usr/share/wtwm/system.twmrc" \
						"$WTWM_PACKAGE_ROOT/etc/menu-methods/wtwm" \
						"$WTWM_PACKAGE_ROOT/etc/wtwm/system.twmrc" \
						"$WTWM_PACKAGE_ROOT/etc/wtwm/system.twmrc-menu" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man1/wtwm.1.gz" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man1/wtwm-config.1.gz" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man5/wtwmrc.5.gz"
					printf '%s\n' "$action" >> "$WTWM_MOCK_TRACE"
					;;
				*) exit 2 ;;
			esac
			;;
		sha256sum)
			if test "${1:-}" = -c; then
				while read -r expected file; do
					actual=$("$WTWM_SHASUM" -a 256 "$file" | awk '{print $1}')
					test "$actual" = "$expected" || exit 1
				done < "$2"
			else
				"$WTWM_SHASUM" -a 256 "$@"
			fi
			;;
		ldd)
			printf '%s\n' 'libwayland-server.so.0 => /mock/libwayland-server.so.0'
			;;
		gzip)
			test "${1:-}" = -cd && test -f "${2:-}" || exit 2
			cat "$2"
			;;
		mandoc)
			test "${1:-}" = -T && test -f "${3:-}" || exit 2
			case $2 in lint) ;; utf8) cat "$3" ;; *) exit 2 ;; esac
			;;
		*) exit 127 ;;
	esac
	exit 0
}

if test "${WTWM_CLEAN_CANDIDATE_MOCK_COMMAND:-0}" = 1; then
	mock_command "$@"
fi

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
driver=$source_root/packaging/debian/clean-candidate-test.sh
self=$source_root/tests/platform/clean-candidate-driver-test.sh
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-clean-candidate-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'clean-candidate-driver-test: %s\n' "$1" >&2
	exit 1
}

mkdir -p "$test_dir/bin" "$test_dir/root/usr/bin" \
	"$test_dir/root/usr/share/xsessions" \
	"$test_dir/root/usr/share/wayland-sessions"
for command_name in apt-get dpkg dpkg-deb dpkg-query gzip id ldd mandoc sha256sum; do
	ln -s "$self" "$test_dir/bin/$command_name"
done
{
	printf '%s\n' 'Package: wtwm'
	printf '%s\n' 'Version: 0.1.0'
	printf '%s\n' 'Architecture: arm64'
} > "$test_dir/wtwm-0.1.0.deb"
printf '%s\n' marker > "$test_dir/platform-marker"
printf '%s\n' x11-twm > "$test_dir/root/usr/bin/twm"
printf '%s\n' x11-session > "$test_dir/root/usr/share/xsessions/twm.desktop"
printf '%s\n' weston > "$test_dir/root/usr/bin/weston"
printf '%s\n' weston-session > \
	"$test_dir/root/usr/share/wayland-sessions/weston.desktop"

export WTWM_CLEAN_CANDIDATE_MOCK_COMMAND=1
export WTWM_CLEAN_CANDIDATE_SELF_TEST=1
export WTWM_SOURCE_ROOT=$source_root
export WTWM_PACKAGE_ROOT=$test_dir/root
export WTWM_PLATFORM_MARKER=$test_dir/platform-marker
export WTWM_MOCK_STATE=$test_dir/package-state
export WTWM_MOCK_TRACE=$test_dir/trace
WTWM_SHASUM=$(command -v shasum) || fail 'shasum is unavailable'
export WTWM_SHASUM
PATH=$test_dir/bin:$PATH
export PATH

"$driver" \
	--new "$test_dir/wtwm-0.1.0.deb" \
	--protect "$test_dir/root/usr/bin/twm" \
	--protect "$test_dir/root/usr/share/xsessions/twm.desktop" \
	--protect "$test_dir/root/usr/bin/weston" \
	--protect "$test_dir/root/usr/share/wayland-sessions/weston.desktop" \
	--evidence "$test_dir/evidence" > /dev/null || fail 'mock lifecycle failed'

printf '%s\n' install remove purge > "$test_dir/expected-trace"
cmp "$test_dir/expected-trace" "$test_dir/trace" > /dev/null ||
	fail 'clean candidate phase order changed'
for expected in \
	'scope	clean-candidate-only' \
	'clean_install	pass' \
	'remove	pass' \
	'purge	pass' \
	'prior_release_upgrade	not-tested' \
	'rollback	not-tested' \
	'final_state	absent' \
	'result	pass'; do
	grep -Fx "$expected" "$test_dir/evidence/result.tsv" > /dev/null ||
		fail "missing evidence: $expected"
done
test ! -e "$test_dir/root/usr/bin/wtwm" || fail 'candidate binary remains'
test -f "$test_dir/root/usr/bin/twm" || fail 'X11 twm was removed'
test -f "$test_dir/root/usr/bin/weston" || fail 'Weston was removed'

export WTWM_MOCK_TAMPER_PROTECTED=1
if "$driver" \
	--new "$test_dir/wtwm-0.1.0.deb" \
	--protect "$test_dir/root/usr/bin/twm" \
	--protect "$test_dir/root/usr/share/xsessions/twm.desktop" \
	--protect "$test_dir/root/usr/bin/weston" \
	--protect "$test_dir/root/usr/share/wayland-sessions/weston.desktop" \
	--evidence "$test_dir/tampered-evidence" > /dev/null 2>&1; then
	fail 'a protected compositor mutation was accepted'
fi

printf '%s\n' 'clean-candidate-driver-test: pass'
