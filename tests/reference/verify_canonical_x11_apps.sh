#!/bin/sh

set -eu

fail()
{
    echo "canonical X11 verification failed: $*" >&2
    exit 1
}

usage()
{
    echo "usage: verify_canonical_x11_apps.sh REPOSITORY_ROOT REFERENCE_BUILD" >&2
    exit 2
}

test "$#" -eq 2 || usage
repo_root=$1
reference_build=$2
reference_twm="$reference_build/twm"
scenario_config="$repo_root/reference/fixtures/canonical-x11/scenario.twmrc"
client_source="$repo_root/tests/reference/canonical_x11_client.c"
validator="$repo_root/tests/reference/validate_canonical_x11_apps.py"

test -x "$reference_twm" || fail "verified reference binary is missing: $reference_twm"
test -f "$scenario_config" || fail "canonical scenario configuration is missing"
test -f "$client_source" || fail "canonical Xlib client source is missing"
test -f "$validator" || fail "canonical manifest validator is missing"

for program in cc pkg-config python3 xterm Xvfb xdpyinfo; do
    command -v "$program" >/dev/null 2>&1 || fail "required program is missing: $program"
done

version_output=$("$reference_twm" -V 2>&1) || fail "reference twm version probe failed"
test "$version_output" = "twm 1.0.13.1" ||
    fail "unexpected reference twm version: $version_output"

canonical_tmp_base=${TMPDIR:-/tmp}
canonical_work=$(mktemp -d "$canonical_tmp_base/wtwm-canonical-x11.XXXXXX") ||
    fail "could not create isolated canonical workspace"
client="$canonical_work/canonical-x11-client"
display_file="$canonical_work/display"
runtime_log="$canonical_work/runtime.log"
fixture_pid=
twm_pid=
xterm_pid=
xvfb_pid=

cleanup()
{
    saved_status=$?
    set +e
    trap - 0 1 2 15
    for child_pid in "$xterm_pid" "$fixture_pid" "$twm_pid" "$xvfb_pid"; do
        if test -n "$child_pid" && kill -0 "$child_pid" >/dev/null 2>&1; then
            kill "$child_pid" >/dev/null 2>&1
            wait "$child_pid" >/dev/null 2>&1
        fi
    done
    case "$canonical_work" in
        "$canonical_tmp_base"/wtwm-canonical-x11.*)
            rm -rf -- "$canonical_work"
            ;;
        *)
            echo "refusing to remove unexpected canonical path: $canonical_work" >&2
            ;;
    esac
    exit "$saved_status"
}
trap cleanup 0 1 2 15

# pkg-config output is a controlled compiler argument list supplied by Debian.
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags x11) \
    "$client_source" -o "$client" $(pkg-config --libs x11)

Xvfb -displayfd 3 -screen 0 1024x768x24 -nolisten tcp \
    3>"$display_file" >"$canonical_work/xvfb.log" 2>&1 &
xvfb_pid=$!
x11_ready=false
display=
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if test -s "$display_file"; then
        IFS= read -r display_number <"$display_file" || true
        case "$display_number" in
            ''|*[!0-9]*) fail "Xvfb returned an invalid display number" ;;
        esac
        display=:$display_number
        if xdpyinfo -display "$display" >/dev/null 2>&1; then
            x11_ready=true
            break
        fi
    fi
    if ! kill -0 "$xvfb_pid" >/dev/null 2>&1; then
        sed 's/^/Xvfb: /' "$canonical_work/xvfb.log" >&2
        fail "Xvfb exited during canonical-suite startup"
    fi
    sleep 1
done
test "$x11_ready" = true || fail "Xvfb did not become ready"

LC_ALL=C DISPLAY="$display" "$reference_twm" -display "$display" -single \
    -f "$scenario_config" -quiet >"$canonical_work/twm.log" 2>&1 &
twm_pid=$!
sleep 1
kill -0 "$twm_pid" >/dev/null 2>&1 || {
    sed 's/^/twm: /' "$canonical_work/twm.log" >&2
    fail "reference twm exited during canonical-suite startup"
}

LC_ALL=C DISPLAY="$display" "$client" serve \
    >"$canonical_work/fixture.log" 2>&1 &
fixture_pid=$!
LC_ALL=C DISPLAY="$display" "$client" wait || {
    sed 's/^/fixture: /' "$canonical_work/fixture.log" >&2
    fail "canonical fixtures did not become ready"
}

LC_ALL=C xterm -display "$display" -name wtwm-legacy-xterm \
    -class WtwmLegacyXterm -title "WTWM Legacy Xterm" \
    -geometry 40x8+500+500 -fn fixed +sb -hold -e /bin/true \
    >"$canonical_work/xterm.log" 2>&1 &
xterm_pid=$!
LC_ALL=C DISPLAY="$display" "$client" tag-legacy || {
    sed 's/^/xterm: /' "$canonical_work/xterm.log" >&2
    fail "legacy xterm was not identified and managed"
}

LC_ALL=C DISPLAY="$display" "$client" verify-initial >"$runtime_log"
LC_ALL=C DISPLAY="$display" "$client" mutate-title
LC_ALL=C DISPLAY="$display" "$client" focus-urgent
LC_ALL=C DISPLAY="$display" "$client" verify-final >>"$runtime_log"

kill -0 "$twm_pid" >/dev/null 2>&1 || fail "reference twm exited during verification"
kill -0 "$fixture_pid" >/dev/null 2>&1 || fail "fixture server exited during verification"
kill -0 "$xterm_pid" >/dev/null 2>&1 || fail "legacy xterm exited during verification"

python3 -B "$validator" --source-root "$repo_root" --runtime-log "$runtime_log"
echo "canonical X11 applications verified under reference twm 1.0.13.1"
