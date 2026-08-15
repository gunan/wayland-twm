#!/bin/sh
# Destructive only inside a marked disposable test VM.  Leaves the new wtwm
# package installed after install/upgrade/purge/reinstall verification.
set -eu

usage()
{
	cat >&2 <<'EOF'
usage: package-lifecycle-test.sh --old OLD.deb --new NEW.deb \
       --protect PATH [--protect PATH ...] --evidence OUTPUT_DIRECTORY

The old package version must compare lower than the new version.  Protected
paths must name an existing compositor binary and/or session entry whose bytes
must remain unchanged.  This script requires /etc/wtwm-platform-test-vm.
EOF
	exit 2
}

old_deb=
new_deb=
evidence_dir=
protected_list=
while test "$#" -gt 0; do
	case $1 in
		--old|--new|--protect|--evidence)
			test "$#" -ge 2 || usage
			option=$1
			value=$2
			shift 2
			case $option in
				--old) old_deb=$value ;;
				--new) new_deb=$value ;;
				--protect) protected_list="${protected_list}${value}
" ;;
				--evidence) evidence_dir=$value ;;
			esac
			;;
		*) usage ;;
	esac
done
test -n "$old_deb" && test -n "$new_deb" && test -n "$evidence_dir" &&
	test -n "$protected_list" || usage
case $evidence_dir in /*) ;; *) usage ;; esac

fail()
{
	printf 'package-lifecycle-test.sh: %s\n' "$1" >&2
	exit 1
}

test "$(id -u)" -eq 0 || fail 'run as root in the disposable platform VM'
test -f /etc/wtwm-platform-test-vm ||
	fail 'refusing to modify packages outside a marked wtwm platform VM'
test ! -e "$evidence_dir" || fail "refusing to overwrite evidence: $evidence_dir"
test -f "$old_deb" || fail "old package not found: $old_deb"
test -f "$new_deb" || fail "new package not found: $new_deb"

old_deb=$(CDPATH= cd -- "$(dirname -- "$old_deb")" && pwd)/$(basename -- "$old_deb")
new_deb=$(CDPATH= cd -- "$(dirname -- "$new_deb")" && pwd)/$(basename -- "$new_deb")
assert_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/assert-coinstallation.sh
old_name=$(dpkg-deb -f "$old_deb" Package)
new_name=$(dpkg-deb -f "$new_deb" Package)
old_version=$(dpkg-deb -f "$old_deb" Version)
new_version=$(dpkg-deb -f "$new_deb" Version)
old_arch=$(dpkg-deb -f "$old_deb" Architecture)
new_arch=$(dpkg-deb -f "$new_deb" Architecture)
host_arch=$(dpkg --print-architecture)
test "$old_name" = wtwm && test "$new_name" = wtwm ||
	fail 'both packages must have Package: wtwm'
dpkg --compare-versions "$old_version" lt "$new_version" ||
	fail "upgrade is not newer: $old_version -> $new_version"
case $old_arch in "$host_arch"|all) ;; *) fail "old package architecture is $old_arch, host is $host_arch" ;; esac
case $new_arch in "$host_arch"|all) ;; *) fail "new package architecture is $new_arch, host is $host_arch" ;; esac

if dpkg-query -W -f='${db:Status-Status}' wtwm 2>/dev/null |
	grep -Fx installed >/dev/null; then
	fail 'wtwm is already installed; restore the clean-provisioned snapshot'
fi

mkdir -m 0700 "$evidence_dir"
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
printf '%s\n' 'package lifecycle sentinel: do not modify' > "$test_home/.twmrc"
(
	cd "$test_home"
	sha256sum .twmrc > "$evidence_dir/twmrc-before.sha256"
)
export HOME=$test_home
export DEBIAN_FRONTEND=noninteractive

verify_protected()
{
	sha256sum -c "$protected_manifest" >/dev/null ||
		fail "pre-existing compositor changed during $1"
	(
		cd "$test_home"
		sha256sum -c "$evidence_dir/twmrc-before.sha256" >/dev/null
	) || fail ".twmrc changed during $1"
}

verify_version()
{
	installed_version=$(dpkg-query -W -f='${Version}' wtwm)
	test "$installed_version" = "$1" ||
		fail "installed version is $installed_version, expected $1"
	dpkg -L wtwm > "$evidence_dir/$2-package-files.txt"
	"$assert_script" / installed "$evidence_dir/$2-package-files.txt"
	verify_protected "$2"
}

apt-get install -y --no-install-recommends "$old_deb" \
	> "$evidence_dir/install-old.log" 2>&1
verify_version "$old_version" install

apt-get install -y --no-install-recommends "$new_deb" \
	> "$evidence_dir/upgrade.log" 2>&1
verify_version "$new_version" upgrade

apt-get purge -y wtwm > "$evidence_dir/purge.log" 2>&1
"$assert_script" / absent
verify_protected purge

apt-get install -y --no-install-recommends "$new_deb" \
	> "$evidence_dir/reinstall.log" 2>&1
verify_version "$new_version" reinstall

{
	printf 'old_version\t%s\n' "$old_version"
	printf 'new_version\t%s\n' "$new_version"
	printf 'architecture\t%s\n' "$host_arch"
	printf 'final_state\tinstalled\n'
	printf 'result\tpass\n'
} > "$evidence_dir/result.tsv"
printf 'Package lifecycle passes; evidence: %s\n' "$evidence_dir"
