#!/bin/sh

set -eu

fail()
{
    echo "reference geometry matrix failed: $*" >&2
    exit 1
}

usage()
{
    echo "usage: capture_reference_geometry_matrix.sh REPOSITORY_ROOT REFERENCE_BUILD OUTPUT_DIRECTORY" >&2
    exit 2
}

test "$#" -eq 3 || usage
repo_root=$1
reference_build=$2
output_dir=$3
reference_twm="$reference_build/twm"
client_source="$repo_root/tests/reference/geometry_matrix_client.c"
runner="$repo_root/tests/reference/run_reference_geometry_matrix.py"
validator="$repo_root/tests/reference/validate_reference_geometry_matrix.py"

test -x "$reference_twm" || fail "verified reference binary is missing: $reference_twm"
test -f "$client_source" || fail "geometry matrix client source is missing"
test -f "$runner" || fail "geometry matrix runner is missing"
test -f "$validator" || fail "geometry matrix validator is missing"
test ! -e "$output_dir" || fail "output directory already exists: $output_dir"
test "$("$reference_twm" -V)" = "twm 1.0.13.1" ||
    fail "reference binary does not report twm 1.0.13.1"

for program in cc cmp pkg-config python3 Xvfb xdpyinfo; do
    command -v "$program" >/dev/null 2>&1 || fail "required program is missing: $program"
done

capture_tmp_base=${TMPDIR:-/tmp}
capture_work=$(mktemp -d "$capture_tmp_base/wtwm-reference-geometry.XXXXXX") ||
    fail "could not create isolated capture workspace"
client="$capture_work/geometry-matrix-client"

cleanup()
{
    saved_status=$?
    set +e
    trap - 0 1 2 15
    case "$capture_work" in
        "$capture_tmp_base"/wtwm-reference-geometry.*)
            rm -rf -- "$capture_work"
            ;;
        *)
            echo "refusing to remove unexpected capture path: $capture_work" >&2
            ;;
    esac
    exit "$saved_status"
}
trap cleanup 0 1 2 15

# pkg-config output is a controlled compiler argument list supplied by Debian.
cc -std=c11 -Wall -Wextra -Wpedantic -Werror $(pkg-config --cflags x11) \
    "$client_source" -o "$client" $(pkg-config --libs x11)

python3 -B "$runner" \
    --source-root "$repo_root" \
    --reference-twm "$reference_twm" \
    --client "$client" \
    --display-base 110 \
    --output "$capture_work/run-one.json"
python3 -B "$runner" \
    --source-root "$repo_root" \
    --reference-twm "$reference_twm" \
    --client "$client" \
    --display-base 140 \
    --output "$capture_work/run-two.json"

cmp "$capture_work/run-one.json" "$capture_work/run-two.json" >/dev/null ||
    fail "two clean geometry matrix runs differ"
python3 -B "$validator" \
    --source-root "$repo_root" \
    --capture "$capture_work/run-one.json"

mkdir "$output_dir"
cp "$capture_work/run-one.json" "$output_dir/geometry-matrix.json"
echo "reference geometry matrix is repeatable across two clean runs"
