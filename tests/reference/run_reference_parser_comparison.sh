#!/bin/sh

set -eu

fail()
{
    echo "reference parser differential failed: $*" >&2
    exit 1
}

test "$#" -eq 2 || fail "usage: $0 REPOSITORY_ROOT WTWM_CONFIG"
repo_root=$1
config_tool=$2
normalizer="$repo_root/tests/reference/compare_reference_parser.py"
builder="$repo_root/tests/reference/build_reference_twm.sh"

test -f "$normalizer" || fail "comparison harness is missing"
test -f "$builder" || fail "reference builder is missing"

full_environment=true
if test ! -r /etc/os-release; then
    full_environment=false
else
    os_id=$(sed -n 's/^ID=//p' /etc/os-release | tr -d '"')
    os_codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | tr -d '"')
    if test "$os_id" != debian || test "$os_codename" != trixie; then
        full_environment=false
    fi
fi
for program in bison cc flex gdb make pkgconf python3 Xvfb xdpyinfo; do
    command -v "$program" >/dev/null 2>&1 || full_environment=false
done
pkgconf --exists ice sm x11 xext xmu xrandr xt >/dev/null 2>&1 ||
    full_environment=false

if test "$full_environment" != true; then
    python3 -B "$normalizer" --source-root "$repo_root" --validate-only
    echo "full parser differential requires the pinned Debian Trixie X11 environment; contract-only validation passed"
    exit 0
fi

test -x "$config_tool" || fail "wtwm-config is not executable: $config_tool"
comparison_tmp_base=${TMPDIR:-/tmp}
work_dir=$(mktemp -d "$comparison_tmp_base/wtwm-parser-differential.XXXXXX") ||
    fail "could not create an isolated working directory"

cleanup()
{
    saved_status=$?
    trap - 0 1 2 15
    case "$work_dir" in
        "$comparison_tmp_base"/wtwm-parser-differential.*)
            rm -rf -- "$work_dir"
            ;;
        *)
            echo "refusing to remove unexpected temporary path: $work_dir" >&2
            ;;
    esac
    exit "$saved_status"
}
trap cleanup 0 1 2 15

sh "$builder" "$repo_root" "$work_dir/reference"
python3 -B "$normalizer" \
    --source-root "$repo_root" \
    --config-tool "$config_tool" \
    --reference-twm "$work_dir/reference/twm" \
    --output "$work_dir/comparison.json"
test -s "$work_dir/comparison.json" || fail "comparison artifact is empty"
echo "full reference parser differential passed in the pinned X11 environment"
