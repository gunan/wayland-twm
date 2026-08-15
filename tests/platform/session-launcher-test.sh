#!/bin/sh
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
launcher=$source_root/scripts/platform/wtwm-session
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-session-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'session-launcher-test: %s\n' "$1" >&2
	exit 1
}

mock=$test_dir/mock-wtwm
printf '%s\n' \
	'#!/bin/sh' \
	'printf "mock-args=%s\\n" "$*"' \
	'exit "${MOCK_STATUS:-0}"' > "$mock"
chmod +x "$mock"
mkdir -m 700 "$test_dir/runtime" "$test_dir/state"

WTWM_BIN=$mock MOCK_STATUS=0 XDG_RUNTIME_DIR=$test_dir/runtime \
	XDG_STATE_HOME=$test_dir/state HOME=$test_dir \
	"$launcher" -d -f fixture.twmrc || fail 'successful child failed'
log=$test_dir/state/wtwm/session.log
test -f "$log" || fail 'private session log was not created'
grep -F 'mock-args=-d -f fixture.twmrc' "$log" >/dev/null ||
	fail 'arguments were not passed unchanged'
grep -F 'compositor exit=0' "$log" >/dev/null ||
	fail 'successful exit was not logged'

if WTWM_BIN=$mock MOCK_STATUS=73 XDG_RUNTIME_DIR=$test_dir/runtime \
	XDG_STATE_HOME=$test_dir/state HOME=$test_dir \
	"$launcher"; then
	fail 'failed compositor was reported as successful'
else
	status=$?
fi
test "$status" -eq 73 || fail 'compositor exit status was not preserved'
grep -F 'compositor exit=73' "$log" >/dev/null ||
	fail 'failed exit was not logged'

# A failed compositor returns to its caller.  A display manager uses this exact
# boundary to redisplay the greeter; the DRM procedure verifies that behavior.
test -x /bin/sh || fail 'caller was not usable after failed child'

if WTWM_BIN=$test_dir/missing XDG_RUNTIME_DIR=$test_dir/runtime \
	XDG_STATE_HOME=$test_dir/state HOME=$test_dir "$launcher" 2>/dev/null; then
	fail 'missing compositor was accepted'
else
	status=$?
fi
test "$status" -eq 127 || fail 'missing compositor did not return 127'

printf '%s\n' 'session-launcher-test: pass'
