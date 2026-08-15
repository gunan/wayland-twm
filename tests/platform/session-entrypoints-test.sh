#!/bin/sh
set -eu

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
runner=$source_root/scripts/platform/run-compositor-test
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-entrypoints-test.XXXXXX")
cleanup()
{
	rm -rf -- "$test_dir"
}
trap cleanup EXIT HUP INT TERM

fail()
{
	printf 'session-entrypoints-test: %s\n' "$1" >&2
	exit 1
}

probe=$test_dir/probe
printf '%s\n' \
	'#!/bin/sh' \
	'printf "backend=%s\\n" "${WLR_BACKENDS:-}"' \
	'printf "outputs=%s\\n" "${WLR_HEADLESS_OUTPUTS:-${WLR_WL_OUTPUTS:-}}"' \
	'printf "runtime=%s\\n" "${XDG_RUNTIME_DIR:-}"' \
	'printf "wayland=%s\\n" "${WAYLAND_DISPLAY:-}"' \
	'printf "display=%s\\n" "${DISPLAY:-}"' \
	'printf "args=%s\\n" "$*"' > "$probe"
chmod +x "$probe"

headless_output=$test_dir/headless.out
env -u XDG_RUNTIME_DIR WAYLAND_DISPLAY=parent-9 DISPLAY=:7 \
	"$runner" headless -- "$probe" alpha beta > "$headless_output"
grep -Fx 'backend=headless' "$headless_output" >/dev/null ||
	fail 'headless backend was not selected'
grep -Fx 'outputs=1' "$headless_output" >/dev/null ||
	fail 'headless output count was not deterministic'
grep -Fx 'wayland=' "$headless_output" >/dev/null ||
	fail 'parent Wayland display leaked into headless mode'
grep -Fx 'display=' "$headless_output" >/dev/null ||
	fail 'X11 display leaked into headless mode'
grep -Fx 'args=alpha beta' "$headless_output" >/dev/null ||
	fail 'headless command arguments changed'
runtime=$(sed -n 's/^runtime=//p' "$headless_output")
test -n "$runtime" && test ! -e "$runtime" ||
	fail 'temporary runtime directory was not cleaned up'

mkdir -m 700 "$test_dir/runtime"
nested_output=$test_dir/nested.out
XDG_RUNTIME_DIR=$test_dir/runtime WAYLAND_DISPLAY=wayland-parent \
	"$runner" nested -- "$probe" nested > "$nested_output"
grep -Fx 'backend=wayland' "$nested_output" >/dev/null ||
	fail 'nested backend was not selected'
grep -Fx 'wayland=wayland-parent' "$nested_output" >/dev/null ||
	fail 'parent Wayland display was not preserved'
grep -Fx "runtime=$test_dir/runtime" "$nested_output" >/dev/null ||
	fail 'parent runtime directory was not preserved'

if env -u WAYLAND_DISPLAY XDG_RUNTIME_DIR=$test_dir/runtime \
	"$runner" nested -- "$probe" 2>/dev/null; then
	fail 'nested mode accepted a missing parent display'
fi
if env -u XDG_SESSION_ID -u SSH_CONNECTION -u SSH_TTY \
	"$runner" drm -- "$probe" 2>/dev/null; then
	fail 'DRM mode accepted a non-login test environment'
fi

printf '%s\n' 'session-entrypoints-test: pass'
