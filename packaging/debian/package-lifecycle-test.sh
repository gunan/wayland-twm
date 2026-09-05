#!/bin/sh
# Destructive only inside a marked disposable test VM.  Leaves the candidate
# package installed after direct upgrades, removal, purge, and rollback checks.
set -eu

usage()
{
	cat >&2 <<'EOF'
usage: package-lifecycle-test.sh --old OLD.deb [--old OLD.deb ...] \
       --new NEW.deb [--rollback OLD.deb] --protect PATH \
       [--protect PATH ...] --evidence OUTPUT_DIRECTORY

Every old package must compare lower than the new package.  Each old package is
installed on a clean package state and upgraded directly to the candidate.
Rollback defaults to the last --old package.  Protected paths must name an
existing compositor binary and/or session entry whose bytes must remain
unchanged.  This script requires /etc/wtwm-platform-test-vm.
EOF
	exit 2
}

old_list=
new_deb=
rollback_deb=
evidence_dir=
protected_list=
while test "$#" -gt 0; do
	case $1 in
		--old|--new|--rollback|--protect|--evidence)
			test "$#" -ge 2 || usage
			option=$1
			value=$2
			shift 2
			case $option in
				--old) old_list="${old_list}${value}
" ;;
				--new) new_deb=$value ;;
				--rollback) rollback_deb=$value ;;
				--protect) protected_list="${protected_list}${value}
" ;;
				--evidence) evidence_dir=$value ;;
			esac
			;;
		*) usage ;;
	esac
done
test -n "$old_list" && test -n "$new_deb" && test -n "$evidence_dir" &&
	test -n "$protected_list" || usage
case $evidence_dir in /*) ;; *) usage ;; esac

fail()
{
	printf 'package-lifecycle-test.sh: %s\n' "$1" >&2
	exit 1
}

case ${WTWM_LIFECYCLE_SELF_TEST:-0} in
	0)
		platform_marker=/etc/wtwm-platform-test-vm
		package_root=/
		;;
	1)
		platform_marker=${WTWM_PLATFORM_MARKER:?self-test marker is unset}
		package_root=${WTWM_PACKAGE_ROOT:?self-test package root is unset}
		case $package_root in /) fail 'self-test package root must not be /' ;; esac
		;;
	*) fail 'invalid WTWM_LIFECYCLE_SELF_TEST value' ;;
esac
test "$(id -u)" -eq 0 || fail 'run as root in the disposable platform VM'
test -f "$platform_marker" ||
	fail "refusing to modify packages without marker: $platform_marker"
test -d "$package_root" || fail "package assertion root does not exist: $package_root"
test ! -e "$evidence_dir" || fail "refusing to overwrite evidence: $evidence_dir"
test -f "$new_deb" || fail "new package not found: $new_deb"

absolute_file()
{
	test -f "$1" || fail "package not found: $1"
	printf '%s/%s\n' "$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)" \
		"$(basename -- "$1")"
}

new_deb=$(absolute_file "$new_deb")
old_list_file=$(mktemp /tmp/wtwm-old-packages.XXXXXX)
printf '%s' "$old_list" | while IFS= read -r old_deb; do
	test -n "$old_deb" || continue
	absolute_file "$old_deb"
done > "$old_list_file"
cleanup()
{
	rm -f -- "$old_list_file"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
test -s "$old_list_file" || fail 'no old packages were provided'

if test -n "$rollback_deb"; then
	rollback_deb=$(absolute_file "$rollback_deb")
else
	rollback_deb=$(sed -n '$p' "$old_list_file")
fi

assert_script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/assert-coinstallation.sh
new_name=$(dpkg-deb -f "$new_deb" Package)
new_version=$(dpkg-deb -f "$new_deb" Version)
new_arch=$(dpkg-deb -f "$new_deb" Architecture)
rollback_name=$(dpkg-deb -f "$rollback_deb" Package)
rollback_version=$(dpkg-deb -f "$rollback_deb" Version)
rollback_arch=$(dpkg-deb -f "$rollback_deb" Architecture)
host_arch=$(dpkg --print-architecture)
test "$new_name" = wtwm && test "$rollback_name" = wtwm ||
	fail 'candidate and rollback packages must have Package: wtwm'
case $new_arch in "$host_arch"|all) ;; *) fail "new package architecture is $new_arch, host is $host_arch" ;; esac
case $rollback_arch in "$host_arch"|all) ;; *) fail "rollback package architecture is $rollback_arch, host is $host_arch" ;; esac
dpkg --compare-versions "$rollback_version" lt "$new_version" ||
	fail "rollback package is not older: $rollback_version -> $new_version"

while IFS= read -r old_deb; do
	old_name=$(dpkg-deb -f "$old_deb" Package)
	old_version=$(dpkg-deb -f "$old_deb" Version)
	old_arch=$(dpkg-deb -f "$old_deb" Architecture)
	test "$old_name" = wtwm || fail "old package is not wtwm: $old_deb"
	dpkg --compare-versions "$old_version" lt "$new_version" ||
		fail "upgrade is not newer: $old_version -> $new_version"
	case $old_arch in "$host_arch"|all) ;; *) fail "old package architecture is $old_arch, host is $host_arch" ;; esac
done < "$old_list_file"

if dpkg-query -W -f='${db:Status-Status}' wtwm 2>/dev/null |
	grep -Fx installed >/dev/null; then
	fail 'wtwm is already installed; restore the clean-provisioned snapshot'
fi

mkdir -m 0700 "$evidence_dir" || fail "cannot create evidence: $evidence_dir"
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
	"$assert_script" "$package_root" "$3" \
		"$evidence_dir/$2-package-files.txt"
	if test "$package_root" = /; then
		installed_prefix=
	else
		installed_prefix=$package_root
	fi
	"$installed_prefix/usr/bin/wtwm" --help > "$evidence_dir/$2-wtwm-help.txt"
	"$installed_prefix/usr/bin/wtwm-config" \
		"$installed_prefix/usr/share/wtwm/system.twmrc" \
		> "$evidence_dir/$2-config-dump.txt"
	if test "$3" = installed; then
		"$installed_prefix/usr/bin/wtwm-config" \
			"$installed_prefix/etc/wtwm/system.twmrc" \
			> "$evidence_dir/$2-generated-menu-config-dump.txt"
	fi
	verify_protected "$2"
}

verify_absent()
{
	"$assert_script" "$package_root" absent
	verify_protected "$1"
}

phase=0
while IFS= read -r old_deb; do
	phase=$((phase + 1))
	old_version=$(dpkg-deb -f "$old_deb" Version)
	apt-get install -y --no-install-recommends "$old_deb" \
		> "$evidence_dir/prior-$phase-install.log" 2>&1
	verify_version "$old_version" "prior-$phase-install" prior

	apt-get install -y --no-install-recommends "$new_deb" \
		> "$evidence_dir/prior-$phase-upgrade.log" 2>&1
	verify_version "$new_version" "prior-$phase-upgrade" installed

	apt-get purge -y wtwm > "$evidence_dir/prior-$phase-purge.log" 2>&1
	verify_absent "prior-$phase-purge"
done < "$old_list_file"

apt-get install -y --no-install-recommends "$new_deb" \
	> "$evidence_dir/clean-install.log" 2>&1
verify_version "$new_version" clean-install installed

apt-get remove -y wtwm > "$evidence_dir/remove.log" 2>&1
verify_absent remove
apt-get purge -y wtwm > "$evidence_dir/purge-after-remove.log" 2>&1
verify_absent purge-after-remove

apt-get install -y --no-install-recommends "$new_deb" \
	> "$evidence_dir/pre-rollback-install.log" 2>&1
verify_version "$new_version" pre-rollback-install installed
apt-get install -y --allow-downgrades --no-install-recommends "$rollback_deb" \
	> "$evidence_dir/rollback.log" 2>&1
verify_version "$rollback_version" rollback prior
apt-get install -y --no-install-recommends "$new_deb" \
	> "$evidence_dir/post-rollback-upgrade.log" 2>&1
verify_version "$new_version" post-rollback-upgrade installed

{
	printf 'candidate_version\t%s\n' "$new_version"
	printf 'prior_versions\t'
	separator=
	while IFS= read -r old_deb; do
		printf '%s%s' "$separator" "$(dpkg-deb -f "$old_deb" Version)"
		separator=,
	done < "$old_list_file"
	printf '\nrollback_version\t%s\n' "$rollback_version"
	printf 'architecture\t%s\n' "$host_arch"
	printf 'final_state\tinstalled\n'
	printf 'result\tpass\n'
} > "$evidence_dir/result.tsv"
printf 'Package lifecycle passes; evidence: %s\n' "$evidence_dir"
