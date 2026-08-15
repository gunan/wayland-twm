#!/bin/sh

set -eu

fail()
{
    echo "reference parser build failed: $*" >&2
    exit 1
}

test "$#" -eq 2 || fail "usage: $0 REPOSITORY_ROOT OUTPUT_DIRECTORY"
repo_root=$1
output_dir=$2
builder="$repo_root/tests/reference/build_reference_twm.sh"

test -f "$builder" || fail "reference twm builder is missing"
command -v gdb >/dev/null 2>&1 || fail "required program is missing: gdb"

CFLAGS='-g -O0 -DYYDEBUG=1'
export CFLAGS
sh "$builder" "$repo_root" "$output_dir"

symbol_log="$output_dir/yydebug-symbol.log"
gdb --quiet --batch -ex 'info address yydebug' "$output_dir/twm" \
    >"$symbol_log" 2>&1 || {
        sed 's/^/GDB: /' "$symbol_log" >&2
        fail "built parser does not expose the required yydebug trace control"
    }
grep -Fq 'Symbol "yydebug"' "$symbol_log" || {
    sed 's/^/GDB: /' "$symbol_log" >&2
    fail "built parser does not contain the required yydebug trace control"
}

echo "reference parser exposes yydebug trace control"
