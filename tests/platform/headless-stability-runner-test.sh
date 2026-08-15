#!/bin/sh
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
runner=$source_root/scripts/platform/run-headless-stability
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-stability-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'headless-stability-runner-test: %s\n' "$1" >&2
	exit 1
}

probe=$test_dir/probe
printf '%s\n' \
	'#!/bin/sh' \
	'test "${WLR_BACKENDS:-}" = headless || exit 10' \
	'test "${WLR_HEADLESS_OUTPUTS:-}" = 1 || exit 11' \
	'test -n "${XDG_RUNTIME_DIR:-}" || exit 12' \
	'printf "%s\\n" run >> "$WTWM_PROBE_COUNT"' > "$probe"
chmod +x "$probe"

WTWM_PROBE_COUNT=$test_dir/count "$runner" "$test_dir/evidence" -- "$probe" \
	> "$test_dir/runner.log"
test "$(wc -l < "$test_dir/count" | tr -d ' ')" = 100 ||
	fail 'runner did not invoke exactly 100 fresh scenarios'
test "$(find "$test_dir/evidence" -name 'run-*.log' -type f | wc -l | tr -d ' ')" = 100 ||
	fail 'runner did not retain exactly 100 logs'
awk -F '	' '$1 == "completed_iterations" && $2 == "100" { found = 1 } END { exit !found }' \
	"$test_dir/evidence/result.tsv" ||
	fail 'runner did not record 100 completed iterations'
(
	cd "$test_dir/evidence"
	sha256sum -c SHA256SUMS >/dev/null
) || fail 'runner checksum manifest does not verify'

printf '%s\n' 'headless-stability-runner-test: pass'
