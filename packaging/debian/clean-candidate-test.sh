#!/bin/sh
# Exercise only a clean candidate install/remove/purge cycle.  Prior-release
# upgrades and rollbacks are intentionally outside this script's evidence.
set -eu

usage()
{
	cat >&2 <<'EOF'
usage: clean-candidate-test.sh --new CANDIDATE.deb --protect PATH \
       [--protect PATH ...] --evidence OUTPUT_DIRECTORY

The candidate must be the wtwm package for the host architecture. Protected
paths must already exist and remain byte-identical. This script requires root
and /etc/wtwm-package-ci-container because it changes the host package state.
EOF
	exit 2
}

candidate=
evidence_dir=
protected_list=
while test "$#" -gt 0; do
	case $1 in
		--new|--protect|--evidence)
			test "$#" -ge 2 || usage
			option=$1
			value=$2
			shift 2
			case $option in
				--new) candidate=$value ;;
				--protect) protected_list="${protected_list}${value}
" ;;
				--evidence) evidence_dir=$value ;;
			esac
			;;
		*) usage ;;
	esac
done
test -n "$candidate" && test -n "$protected_list" &&
	test -n "$evidence_dir" || usage
case $evidence_dir in /*) ;; *) usage ;; esac

fail()
{
	printf 'clean-candidate-test.sh: %s\n' "$1" >&2
	exit 1
}

case ${WTWM_CLEAN_CANDIDATE_SELF_TEST:-0} in
	0)
		platform_marker=/etc/wtwm-package-ci-container
		package_root=/
		;;
	1)
		platform_marker=${WTWM_PLATFORM_MARKER:?self-test marker is unset}
		package_root=${WTWM_PACKAGE_ROOT:?self-test package root is unset}
		case $package_root in /) fail 'self-test package root must not be /' ;; esac
		;;
	*) fail 'invalid WTWM_CLEAN_CANDIDATE_SELF_TEST value' ;;
esac

test "$(id -u)" -eq 0 || fail 'run as root in the disposable package container'
test -f "$platform_marker" ||
	fail "refusing package changes without marker: $platform_marker"
test -d "$package_root" || fail "package root does not exist: $package_root"
test ! -e "$evidence_dir" || fail "refusing to overwrite evidence: $evidence_dir"
test -f "$candidate" || fail "candidate package not found: $candidate"
candidate=$(CDPATH= cd -- "$(dirname -- "$candidate")" && pwd)/$(basename -- "$candidate")

package_name=$(dpkg-deb -f "$candidate" Package)
package_version=$(dpkg-deb -f "$candidate" Version)
package_architecture=$(dpkg-deb -f "$candidate" Architecture)
host_architecture=$(dpkg --print-architecture)
test "$package_name" = wtwm || fail "candidate package is not wtwm: $package_name"
case $package_architecture in
	"$host_architecture"|all) ;;
	*) fail "candidate architecture is $package_architecture, host is $host_architecture" ;;
esac

if dpkg-query -W -f='${db:Status-Status}' wtwm > /dev/null 2>&1; then
	fail 'a wtwm package record exists; the candidate test requires a clean container'
fi

mkdir -m 0755 "$evidence_dir" || fail "cannot create evidence: $evidence_dir"
protected_manifest=$evidence_dir/protected-before.sha256
: > "$protected_manifest"
printf '%s' "$protected_list" | while IFS= read -r protected_path; do
	test -n "$protected_path" || continue
	case $protected_path in /*) ;; *) fail "protected path is not absolute: $protected_path" ;; esac
	test -f "$protected_path" || fail "protected path is not a file: $protected_path"
	sha256sum "$protected_path" >> "$protected_manifest"
done
test -s "$protected_manifest" || fail 'no protected files were recorded'

test_home=$evidence_dir/test-home
mkdir -m 0700 "$test_home"
printf '%s\n' 'clean candidate sentinel: do not modify' > "$test_home/.twmrc"
(
	cd "$test_home"
	sha256sum .twmrc > "$evidence_dir/twmrc-before.sha256"
)
export HOME=$test_home
export DEBIAN_FRONTEND=noninteractive

verify_protected()
{
	sha256sum -c "$protected_manifest" > /dev/null ||
		fail "pre-existing desktop asset changed during $1"
	(
		cd "$test_home"
		sha256sum -c "$evidence_dir/twmrc-before.sha256" > /dev/null
	) || fail ".twmrc changed during $1"
}

root_path()
{
	if test "$package_root" = /; then
		printf '%s\n' "$1"
	else
		printf '%s%s\n' "$package_root" "$1"
	fi
}

assert_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/assert-coinstallation.sh
apt-get install -y --no-install-recommends "$candidate" \
	> "$evidence_dir/install.log" 2>&1
installed_version=$(dpkg-query -W -f='${Version}' wtwm)
test "$installed_version" = "$package_version" ||
	fail "installed version is $installed_version, expected $package_version"
dpkg -L wtwm > "$evidence_dir/candidate-package-files.txt"
"$assert_script" "$package_root" installed \
	"$evidence_dir/candidate-package-files.txt" \
	> "$evidence_dir/installed-assertion.txt"

binary=$(root_path /usr/bin/wtwm)
config_tool=$(root_path /usr/bin/wtwm-config)
system_config=$(root_path /usr/share/wtwm/system.twmrc)
"$binary" --help > "$evidence_dir/wtwm-help.txt"
"$config_tool" "$system_config" > "$evidence_dir/system-config-dump.txt"
ldd "$binary" > "$evidence_dir/wtwm-ldd.txt"
if grep -F 'not found' "$evidence_dir/wtwm-ldd.txt" > /dev/null; then
	fail 'installed wtwm has an unresolved shared-library dependency'
fi

for manual in \
	/usr/share/man/man1/wtwm.1.gz \
	/usr/share/man/man1/wtwm-config.1.gz \
	/usr/share/man/man5/wtwmrc.5.gz; do
	manual_path=$(root_path "$manual")
	test -f "$manual_path" || fail "installed manual is missing: $manual"
	manual_name=$(basename -- "$manual" .gz)
	gzip -cd "$manual_path" > "$evidence_dir/$manual_name.roff"
	mandoc -T lint "$evidence_dir/$manual_name.roff" \
		> "$evidence_dir/$manual_name.lint.txt" 2>&1
	mandoc -T utf8 "$evidence_dir/$manual_name.roff" \
		> "$evidence_dir/$manual_name.txt"
done

owned_files=$evidence_dir/candidate-owned-files.txt
: > "$owned_files"
while IFS= read -r owned_path; do
	case $owned_path in /*) ;; *) continue ;; esac
	installed_path=$(root_path "$owned_path")
	if test -f "$installed_path" || test -L "$installed_path"; then
		printf '%s\n' "$owned_path" >> "$owned_files"
	fi
done < "$evidence_dir/candidate-package-files.txt"
test -s "$owned_files" || fail 'candidate package did not install any files'
verify_protected install

verify_candidate_files_absent()
{
	while IFS= read -r owned_path; do
		installed_path=$(root_path "$owned_path")
		test ! -e "$installed_path" && test ! -L "$installed_path" ||
			fail "candidate-owned file remains during $1: $owned_path"
	done < "$owned_files"
}

verify_not_installed()
{
	if installed_status=$(dpkg-query -W -f='${db:Status-Status}' wtwm 2>/dev/null); then
		test "$installed_status" != installed || fail "wtwm remains installed during $1"
	fi
}

verify_purged()
{
	if dpkg-query -W -f='${db:Status-Status}' wtwm > /dev/null 2>&1; then
		fail 'wtwm package record remains after purge'
	fi
}

apt-get remove -y wtwm > "$evidence_dir/remove.log" 2>&1
verify_not_installed remove
verify_candidate_files_absent remove
"$assert_script" "$package_root" absent > "$evidence_dir/remove-assertion.txt"
verify_protected remove

apt-get purge -y wtwm > "$evidence_dir/purge.log" 2>&1
verify_not_installed purge
verify_purged
verify_candidate_files_absent purge
"$assert_script" "$package_root" absent > "$evidence_dir/purge-assertion.txt"
verify_protected purge

{
	printf 'scope\tclean-candidate-only\n'
	printf 'candidate_version\t%s\n' "$package_version"
	printf 'architecture\t%s\n' "$host_architecture"
	printf 'clean_install\tpass\n'
	printf 'remove\tpass\n'
	printf 'purge\tpass\n'
	printf 'prior_release_upgrade\tnot-tested\n'
	printf 'rollback\tnot-tested\n'
	printf 'final_state\tabsent\n'
	printf 'result\tpass\n'
} > "$evidence_dir/result.tsv"
printf 'Clean candidate lifecycle passes; evidence: %s\n' "$evidence_dir"
