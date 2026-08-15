#!/bin/sh

set -eu

expected_archive_sha256=a52534755aa8b492c884e52fa988bac84ab4d54641954679b9aaf08e323df2c5
expected_source_root=twm-1.0.13.1
expected_version='twm 1.0.13.1'
reference_display=:99

fail()
{
    echo "reference twm build failed: $*" >&2
    exit 1
}

usage()
{
    echo "usage: build_reference_twm.sh [--validate-only] REPOSITORY_ROOT" >&2
    exit 2
}

file_hash()
{
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{ print $1 }'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{ print $1 }'
    else
        fail "neither sha256sum nor shasum is available"
    fi
}

require_archive_member()
{
    tar -tf "$archive" "$expected_source_root/$1" >/dev/null 2>&1 ||
        fail "release archive is missing $1"
}

validate_source()
{
    test -f "$archive" || fail "release archive is missing: $archive"
    actual_sha256=$(file_hash "$archive")
    test "$actual_sha256" = "$expected_archive_sha256" ||
        fail "release archive SHA-256 is $actual_sha256, expected $expected_archive_sha256"

    bad_root=$(tar -tf "$archive" |
        awk -v root="$expected_source_root/" 'index($0, root) != 1 { print; exit }')
    test -z "$bad_root" || fail "release archive has an unexpected root: $bad_root"

    tar -xOf "$archive" "$expected_source_root/configure.ac" |
        grep -Fq 'AC_INIT([twm], [1.0.13.1],' ||
        fail "release configure.ac does not identify twm 1.0.13.1"

    require_archive_member configure
    require_archive_member Makefile.in
    require_archive_member src/Makefile.in
    require_archive_member src/gram.c
    require_archive_member src/lex.c
}

validate_only=false
if test "${1:-}" = --validate-only; then
    validate_only=true
    shift
fi
test "$#" -eq 1 || usage

repo_root=$1
archive="$repo_root/reference/upstream/twm-1.0.13.1/twm-1.0.13.1.tar.xz"
validate_source

if test "$validate_only" = true; then
    echo "reference twm source valid: $expected_version"
    exit 0
fi

test -r /etc/os-release || fail "full build requires Debian Trixie"
os_id=$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"')
os_codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')
test "$os_id" = debian && test "$os_codename" = trixie ||
    fail "full build requires Debian Trixie, found $os_id/$os_codename"

for program in cc make pkgconf tar Xvfb xdpyinfo; do
    command -v "$program" >/dev/null 2>&1 || fail "required program is missing: $program"
done

reference_tmp_base=${TMPDIR:-/tmp}
work_dir=$(mktemp -d "$reference_tmp_base/wtwm-reference-build.XXXXXX") ||
    fail "could not create an isolated build directory"
source_dir="$work_dir/$expected_source_root"
build_dir="$work_dir/build"
twm_pid=
xvfb_pid=

cleanup()
{
    saved_status=$?
    set +e
    trap - 0 1 2 15
    if test -n "$twm_pid" && kill -0 "$twm_pid" >/dev/null 2>&1; then
        kill "$twm_pid" >/dev/null 2>&1
        wait "$twm_pid" >/dev/null 2>&1
    fi
    if test -n "$xvfb_pid" && kill -0 "$xvfb_pid" >/dev/null 2>&1; then
        kill "$xvfb_pid" >/dev/null 2>&1
        wait "$xvfb_pid" >/dev/null 2>&1
    fi
    case "$work_dir" in
        "$reference_tmp_base"/wtwm-reference-build.*)
            rm -rf -- "$work_dir"
            ;;
        *)
            echo "refusing to remove unexpected temporary path: $work_dir" >&2
            ;;
    esac
    exit "$saved_status"
}
trap cleanup 0 1 2 15

tar -xJf "$archive" -C "$work_dir"
mkdir "$build_dir"
(
    cd "$build_dir"
    "$source_dir/configure" --disable-silent-rules --prefix="$work_dir/install"
    make -j2
)

reference_twm="$build_dir/src/twm"
test -x "$reference_twm" || fail "build did not produce src/twm"
actual_version=$("$reference_twm" -V)
test "$actual_version" = "$expected_version" ||
    fail "built binary reports '$actual_version', expected '$expected_version'"

empty_config="$work_dir/empty.twmrc"
printf '%s\n' '# controlled empty reference configuration' >"$empty_config"
Xvfb "$reference_display" -screen 0 1024x768x24 -nolisten tcp \
    >"$work_dir/xvfb.log" 2>&1 &
xvfb_pid=$!

x11_ready=false
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if xdpyinfo -display "$reference_display" >/dev/null 2>&1; then
        x11_ready=true
        break
    fi
    if ! kill -0 "$xvfb_pid" >/dev/null 2>&1; then
        sed 's/^/Xvfb: /' "$work_dir/xvfb.log" >&2
        fail "Xvfb exited during startup"
    fi
    sleep 1
done
test "$x11_ready" = true || fail "Xvfb did not become ready on $reference_display"

"$reference_twm" -display "$reference_display" -f "$empty_config" -q \
    >"$work_dir/twm.log" 2>&1 &
twm_pid=$!
sleep 2
if ! kill -0 "$twm_pid" >/dev/null 2>&1; then
    sed 's/^/twm: /' "$work_dir/twm.log" >&2
    fail "reference twm exited during X11 startup"
fi

echo "reference twm build and X11 smoke test passed: $actual_version"
