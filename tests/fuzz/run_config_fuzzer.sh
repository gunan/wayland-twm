#!/bin/sh

set -eu

fail()
{
    echo "config fuzzer failed: $*" >&2
    exit 1
}

if test "${1:-}" = --validate-only; then
    test "$#" -eq 2 || fail "usage: $0 --validate-only REPOSITORY_ROOT"
    repo_root=$2
    test -f "$repo_root/tests/fuzz/config_fuzzer.c" || fail "fuzzer source is missing"
    test -f "$repo_root/src/placement.c" || fail "placement parser source is missing"
    test -f "$repo_root/reference/grammar/fixtures/complete-language.twmrc" ||
        fail "complete-language seed is missing"
    grep -Fq 'LLVMFuzzerTestOneInput' "$repo_root/tests/fuzz/config_fuzzer.c" ||
        fail "libFuzzer entry point is missing"
    grep -Fq 'wtwm_config_parse' "$repo_root/tests/fuzz/config_fuzzer.c" ||
        fail "parser invocation is missing"
    echo "config fuzzer contract valid"
    exit 0
fi

test "$#" -ge 2 && test "$#" -le 3 ||
    fail "usage: $0 REPOSITORY_ROOT WORK_DIRECTORY [RUNS]"
repo_root=$1
work_dir=$2
runs=${3:-100000}

case "$runs" in
    ''|*[!0-9]*) fail "RUNS must be a positive integer" ;;
esac
test "$runs" -gt 0 || fail "RUNS must be a positive integer"
case "$work_dir" in
    /*) ;;
    *) fail "WORK_DIRECTORY must be absolute" ;;
esac
test ! -e "$work_dir" || fail "work directory already exists: $work_dir"

fuzzer_cc=${WTWM_FUZZ_CC:-clang}
command -v "$fuzzer_cc" >/dev/null 2>&1 || fail "compiler is missing: $fuzzer_cc"
mkdir -p "$work_dir/corpus" "$work_dir/artifacts"

cp "$repo_root/data/system.twmrc" "$work_dir/corpus/wtwm-system.twmrc"
cp "$repo_root/reference/grammar/fixtures/complete-language.twmrc" \
    "$work_dir/corpus/complete-language.twmrc"
cp "$repo_root/reference/grammar/fixtures/lexical-behavior.twmrc" \
    "$work_dir/corpus/lexical-behavior.twmrc"
for seed in "$repo_root"/reference/grammar/fixtures/malformed-*.twmrc; do
    cp "$seed" "$work_dir/corpus/$(basename "$seed")"
done
for seed in "$repo_root"/reference/upstream/twm-1.0.13.1/sample-twmrc/*.twmrc; do
    cp "$seed" "$work_dir/corpus/upstream-$(basename "$seed")"
done

"$fuzzer_cc" -std=c11 -Wall -Wextra -Wpedantic -Werror -g -O1 \
    -fno-omit-frame-pointer -fsanitize=fuzzer,address,undefined \
    -I"$repo_root/include" \
    "$repo_root/src/config.c" "$repo_root/src/placement.c" \
    "$repo_root/tests/fuzz/config_fuzzer.c" \
    -o "$work_dir/config-fuzzer"

asan_options=${WTWM_FUZZ_ASAN_OPTIONS:-detect_leaks=1:abort_on_error=1:halt_on_error=1}
ASAN_OPTIONS=$asan_options \
UBSAN_OPTIONS=abort_on_error=1:halt_on_error=1:print_stacktrace=1 \
    "$work_dir/config-fuzzer" "$work_dir/corpus" \
    -artifact_prefix="$work_dir/artifacts/" \
    -max_len=8192 -rss_limit_mb=2048 -timeout=2 -runs="$runs" \
    -print_final_stats=1

echo "config fuzzer completed $runs runs under AddressSanitizer, LeakSanitizer, and UndefinedBehaviorSanitizer"
