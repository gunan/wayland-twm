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
				--compare-versions)
					test "$#" -eq 4 && test "$3" = lt || exit 2
					awk -v left="$2" -v right="$4" 'BEGIN {
						split(left, l, "."); split(right, r, ".");
						for (i = 1; i <= 3; ++i) {
							if ((l[i] + 0) < (r[i] + 0)) exit 0;
							if ((l[i] + 0) > (r[i] + 0)) exit 1;
						}
						exit 1;
					}'
					;;
				-L)
				test -f "$WTWM_MOCK_STATE" || exit 1
				printf '%s\n' \
					'/usr/bin/wtwm' \
					'/usr/bin/wtwm-config' \
					'/usr/bin/wtwm-session' \
					'/usr/share/wayland-sessions/wtwm.desktop' \
					'/usr/share/wtwm/system.twmrc' \
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
					mkdir -p "$WTWM_PACKAGE_ROOT/usr/bin" \
						"$WTWM_PACKAGE_ROOT/usr/share/wayland-sessions" \
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
					cp "$WTWM_SOURCE_ROOT/data/system.twmrc" \
						"$WTWM_PACKAGE_ROOT/usr/share/wtwm/system.twmrc"
					cp "$WTWM_SOURCE_ROOT/data/wtwm.1" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man1/wtwm.1.gz"
					cp "$WTWM_SOURCE_ROOT/data/wtwm-config.1" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man1/wtwm-config.1.gz"
					cp "$WTWM_SOURCE_ROOT/data/wtwmrc.5" \
						"$WTWM_PACKAGE_ROOT/usr/share/man/man5/wtwmrc.5.gz"
					printf 'install\t%s\n' "$version" >> "$WTWM_MOCK_TRACE"
					;;
				remove|purge)
					rm -f -- "$WTWM_MOCK_STATE" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-config" \
						"$WTWM_PACKAGE_ROOT/usr/bin/wtwm-session" \
						"$WTWM_PACKAGE_ROOT/usr/share/wayland-sessions/wtwm.desktop" \
						"$WTWM_PACKAGE_ROOT/usr/share/wtwm/system.twmrc" \
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
		*) exit 127 ;;
	esac
	exit 0
}

if test "${WTWM_LIFECYCLE_MOCK_COMMAND:-0}" = 1; then
	mock_command "$@"
fi

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
lifecycle=$source_root/packaging/debian/package-lifecycle-test.sh
self=$source_root/tests/platform/package-lifecycle-driver-test.sh
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-lifecycle-driver-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'package-lifecycle-driver-test: %s\n' "$1" >&2
	exit 1
}

mkdir -p "$test_dir/bin" "$test_dir/root/usr/bin" \
	"$test_dir/root/usr/share/wayland-sessions"
for command_name in apt-get dpkg dpkg-deb dpkg-query id sha256sum; do
	ln -s "$self" "$test_dir/bin/$command_name"
done
for version in 0.1.0 0.2.0 0.3.0; do
	{
		printf '%s\n' 'Package: wtwm'
		printf 'Version: %s\n' "$version"
		printf '%s\n' 'Architecture: arm64'
	} > "$test_dir/wtwm-$version.deb"
done
printf '%s\n' marker > "$test_dir/platform-marker"
printf '%s\n' existing-compositor > "$test_dir/root/usr/bin/existing-wm"
printf '%s\n' existing-session > \
	"$test_dir/root/usr/share/wayland-sessions/existing.desktop"

export WTWM_LIFECYCLE_MOCK_COMMAND=1
export WTWM_LIFECYCLE_SELF_TEST=1
export WTWM_SOURCE_ROOT=$source_root
export WTWM_PACKAGE_ROOT=$test_dir/root
export WTWM_PLATFORM_MARKER=$test_dir/platform-marker
export WTWM_MOCK_STATE=$test_dir/package-state
export WTWM_MOCK_TRACE=$test_dir/trace.tsv
WTWM_SHASUM=$(command -v shasum) || fail 'shasum is unavailable'
export WTWM_SHASUM
PATH=$test_dir/bin:$PATH
export PATH

"$lifecycle" \
	--old "$test_dir/wtwm-0.1.0.deb" \
	--old "$test_dir/wtwm-0.2.0.deb" \
	--new "$test_dir/wtwm-0.3.0.deb" \
	--rollback "$test_dir/wtwm-0.2.0.deb" \
	--protect "$test_dir/root/usr/bin/existing-wm" \
	--protect "$test_dir/root/usr/share/wayland-sessions/existing.desktop" \
	--evidence "$test_dir/evidence" >/dev/null || fail 'mock lifecycle failed'

cat > "$test_dir/expected-trace.tsv" <<'EOF'
install	0.1.0
install	0.3.0
purge
install	0.2.0
install	0.3.0
purge
install	0.3.0
remove
purge
install	0.3.0
install	0.2.0
install	0.3.0
EOF
cmp "$test_dir/expected-trace.tsv" "$test_dir/trace.tsv" >/dev/null ||
	fail 'lifecycle phase order changed'
grep -Fx 'candidate_version	0.3.0' "$test_dir/evidence/result.tsv" >/dev/null ||
	fail 'candidate version evidence is missing'
grep -Fx 'prior_versions	0.1.0,0.2.0' "$test_dir/evidence/result.tsv" >/dev/null ||
	fail 'prior version evidence is missing'
grep -Fx 'rollback_version	0.2.0' "$test_dir/evidence/result.tsv" >/dev/null ||
	fail 'rollback evidence is missing'
grep -Fx 'result	pass' "$test_dir/evidence/result.tsv" >/dev/null ||
	fail 'pass evidence is missing'

if "$lifecycle" \
		--old "$test_dir/wtwm-0.3.0.deb" \
		--new "$test_dir/wtwm-0.3.0.deb" \
		--protect "$test_dir/root/usr/bin/existing-wm" \
		--evidence "$test_dir/equal-evidence" >/dev/null 2>&1; then
	fail 'equal-version upgrade was accepted'
fi

printf '%s\n' 'package-lifecycle-driver-test: pass'
