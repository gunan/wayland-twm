#!/bin/sh
set -eu

if test "$#" -ne 2; then
	printf '%s\n' 'usage: run-debian-package-ci.sh SOURCE_ROOT ARTIFACT_DIRECTORY' >&2
	exit 2
fi

source_root=$(CDPATH= cd -- "$1" && pwd)
artifact_dir=$2
case $artifact_dir in
	/*) ;;
	*) printf '%s\n' 'artifact directory must be absolute' >&2; exit 2 ;;
esac
mkdir -p "$artifact_dir"

phase=initialization
finish()
{
	status=$?
	trap - EXIT
	find "$source_root" -maxdepth 2 -type f \
		-name 'm9-mixed-soak-smoke.json*' \
		-exec cp {} "$artifact_dir/" \;
	{
		printf 'phase\t%s\n' "$phase"
		printf 'exit_status\t%s\n' "$status"
	} > "$artifact_dir/ci-result.tsv"
	exit "$status"
}
trap finish EXIT

test "$(id -u)" -eq 0
test -f /etc/wtwm-package-ci-container
test -r /etc/os-release
. /etc/os-release
test "${ID:-}" = debian
test "${VERSION_CODENAME:-}" = trixie

build_parent=$(dirname -- "$source_root")
build_marker=$artifact_dir/build-started
: > "$build_marker"
phase=package-build
(
	cd "$source_root"
	dpkg-buildpackage -us -uc -b
) > "$artifact_dir/dpkg-buildpackage.log" 2>&1

changes_list=$artifact_dir/changes-files.txt
find "$build_parent" -maxdepth 1 -type f -name 'wtwm_*.changes' \
	-newer "$build_marker" -print > "$changes_list"
changes_file=$(sed -n '1p' "$changes_list")
test -n "$changes_file"
test -z "$(sed -n '2p' "$changes_list")"

cp "$changes_file" "$artifact_dir/"
buildinfo_list=$artifact_dir/buildinfo-files.txt
find "$build_parent" -maxdepth 1 -type f -name 'wtwm_*.buildinfo' \
	-newer "$build_marker" -print > "$buildinfo_list"
while IFS= read -r buildinfo; do
	test -n "$buildinfo" || continue
	cp "$buildinfo" "$artifact_dir/"
done < "$buildinfo_list"

candidate=
deb_list=$artifact_dir/deb-files.txt
find "$build_parent" -maxdepth 1 -type f -name 'wtwm_*.deb' \
	-newer "$build_marker" -print > "$deb_list"
while IFS= read -r deb; do
	test -n "$deb" || continue
	cp "$deb" "$artifact_dir/"
	if test "$(dpkg-deb -f "$deb" Package)" = wtwm; then
		test -z "$candidate"
		candidate=$artifact_dir/$(basename -- "$deb")
	fi
done < "$deb_list"
test -n "$candidate"
sha256sum "$candidate" > "$artifact_dir/candidate.sha256"

phase=lintian
lintian --fail-on error "$changes_file" > "$artifact_dir/lintian.log" 2>&1

phase=clean-candidate-lifecycle
test ! -e "$artifact_dir/clean-candidate-evidence"
"$source_root/packaging/debian/clean-candidate-test.sh" \
	--new "$candidate" \
	--protect /usr/bin/twm \
	--protect /usr/share/xsessions/twm.desktop \
	--protect /usr/bin/weston \
	--protect /usr/share/wayland-sessions/weston.desktop \
	--evidence "$artifact_dir/clean-candidate-evidence"
phase=complete
