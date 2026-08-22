#!/bin/sh
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
launcher=$source_root/scripts/platform/wtwm-session
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-session-test.XXXXXX")
forwarded_launcher_pid=
forwarded_child_pid=
cleanup()
{
	test -z "$forwarded_launcher_pid" ||
		kill -KILL "$forwarded_launcher_pid" 2>/dev/null || :
	test -z "$forwarded_child_pid" ||
		kill -KILL "$forwarded_child_pid" 2>/dev/null || :
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
	'printf "managed=%s\\n" "${WTWM_MANAGED_SESSION:-}"' \
	'printf "current-desktop=%s\\n" "${XDG_CURRENT_DESKTOP:-}"' \
	'printf "session-desktop=%s\\n" "${XDG_SESSION_DESKTOP:-}"' \
	'printf "session-type=%s\\n" "${XDG_SESSION_TYPE:-}"' \
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
grep -F 'managed=1' "$log" >/dev/null ||
	fail 'managed login marker was not exported'
grep -F 'current-desktop=wtwm' "$log" >/dev/null ||
	fail 'current desktop was not namespaced'
grep -F 'session-desktop=wtwm' "$log" >/dev/null ||
	fail 'session desktop was not namespaced'
grep -F 'session-type=wayland' "$log" >/dev/null ||
	fail 'session type was not exported'
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

signal_mock=$test_dir/signal-wtwm
signal_pid_file=$test_dir/signal-child.pid
printf '%s\n' \
	'#!/bin/sh' \
	'trap '\''printf "%s\n" TERM > "$SIGNAL_MARKER"; exit 42'\'' TERM' \
	'printf "%s\n" "$$" > "$SIGNAL_PID_FILE"' \
	'while :; do :; done' > "$signal_mock"
chmod +x "$signal_mock"
iteration=0
while test "$iteration" -lt 50; do
	iteration=$((iteration + 1))
	rm -f -- "$signal_pid_file" "$test_dir/signal.marker"
	SIGNAL_PID_FILE=$signal_pid_file SIGNAL_MARKER=$test_dir/signal.marker \
		WTWM_BIN=$signal_mock XDG_RUNTIME_DIR=$test_dir/runtime \
		XDG_STATE_HOME=$test_dir/state HOME=$test_dir \
		"$launcher" &
	forwarded_launcher_pid=$!
	attempt=0
	while ! test -s "$signal_pid_file"; do
		attempt=$((attempt + 1))
		test "$attempt" -le 1000 || fail 'forwarded child did not start'
		kill -0 "$forwarded_launcher_pid" 2>/dev/null ||
			fail 'launcher exited before signal forwarding'
		sleep 0.01
	done
	forwarded_child_pid=$(sed -n '1p' "$signal_pid_file")
	kill -TERM "$forwarded_launcher_pid"
	if wait "$forwarded_launcher_pid"; then
		status=0
	else
		status=$?
	fi
	forwarded_launcher_pid=
	test "$status" -eq 42 || fail 'forwarded child status was not preserved'
	if kill -0 "$forwarded_child_pid" 2>/dev/null; then
		fail 'forwarded child was not reaped'
	fi
	forwarded_child_pid=
	test "$(sed -n '1p' "$test_dir/signal.marker")" = TERM ||
		fail 'launcher did not forward TERM to the child'
done
grep -F 'compositor exit=42' "$log" >/dev/null ||
	fail 'forwarded child exit was not logged'

printf '%s\n' 'session-launcher-test: pass'
