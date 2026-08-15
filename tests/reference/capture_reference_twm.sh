#!/bin/sh

set -eu

fail()
{
    echo "reference capture failed: $*" >&2
    exit 1
}

usage()
{
    echo "usage: capture_reference_twm.sh REPOSITORY_ROOT REFERENCE_BUILD OUTPUT_DIRECTORY [BASELINE_DIRECTORY]" >&2
    exit 2
}

test "$#" -ge 3 && test "$#" -le 4 || usage
repo_root=$1
reference_build=$2
output_dir=$3
baseline_dir=${4:-}
reference_twm="$reference_build/twm"
scenario_config="$repo_root/reference/captures/twm-1.0.13.1/scenario.twmrc"
probe_source="$repo_root/tests/reference/reference_capture_client.c"
normalizer="$repo_root/tests/reference/normalize_reference_capture.py"

test -x "$reference_twm" || fail "verified reference binary is missing: $reference_twm"
test -f "$scenario_config" || fail "controlled scenario configuration is missing"
test -f "$probe_source" || fail "Xlib probe source is missing"
test -f "$normalizer" || fail "capture normalizer is missing"
test ! -e "$output_dir" || fail "output directory already exists: $output_dir"

for program in cc gdb gzip pkg-config python3 xwd xwdtopnm Xvfb xdpyinfo; do
    command -v "$program" >/dev/null 2>&1 || fail "required program is missing: $program"
done

capture_tmp_base=${TMPDIR:-/tmp}
capture_work=$(mktemp -d "$capture_tmp_base/wtwm-reference-capture.XXXXXX") ||
    fail "could not create isolated capture workspace"
probe="$capture_work/reference-capture-client"

cleanup()
{
    saved_status=$?
    set +e
    trap - 0 1 2 15
    case "$capture_work" in
        "$capture_tmp_base"/wtwm-reference-capture.*)
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
cc -std=c11 -Wall -Wextra -Werror $(pkg-config --cflags x11) \
    "$probe_source" -o "$probe" $(pkg-config --libs x11)

run_once()
(
    display=$1
    run_dir=$2
    mkdir "$run_dir"
    mkdir "$run_dir/artifacts"
    gdb_commands="$run_dir/observe.gdb"
    gdb_log="$run_dir/gdb.log"
    twm_log="$run_dir/twm.log"
    scenario_pid=
    twm_pid=
    xvfb_pid=

    cleanup_run()
    {
        saved_status=$?
        set +e
        trap - 0 1 2 15
        if test -n "$scenario_pid" && kill -0 "$scenario_pid" >/dev/null 2>&1; then
            kill "$scenario_pid" >/dev/null 2>&1
            wait "$scenario_pid" >/dev/null 2>&1
        fi
        if test -n "$xvfb_pid" && kill -0 "$xvfb_pid" >/dev/null 2>&1; then
            kill "$xvfb_pid" >/dev/null 2>&1
            wait "$xvfb_pid" >/dev/null 2>&1
        fi
        if test -n "$twm_pid" && kill -0 "$twm_pid" >/dev/null 2>&1; then
            kill "$twm_pid" >/dev/null 2>&1
        fi
        exit "$saved_status"
    }
    trap cleanup_run 0 1 2 15

    Xvfb "$display" -screen 0 260x180x24 -nolisten tcp \
        >"$run_dir/xvfb.log" 2>&1 &
    xvfb_pid=$!
    x11_ready=false
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if xdpyinfo -display "$display" >/dev/null 2>&1; then
            x11_ready=true
            break
        fi
        if ! kill -0 "$xvfb_pid" >/dev/null 2>&1; then
            sed 's/^/Xvfb: /' "$run_dir/xvfb.log" >&2
            fail "Xvfb exited during capture startup"
        fi
        sleep 1
    done
    test "$x11_ready" = true || fail "Xvfb did not become ready on $display"

    {
        printf '%s\n' 'set pagination off'
        printf '%s\n' 'set confirm off'
        printf '%s\n' 'break assign_var_savecolor'
        printf '%s\n' 'commands'
        printf '%s\n' 'silent'
        printf '%s\n' 'disable 1'
        printf '%s\n' 'printf "effective\tborder_width\t%d\n", Scr->BorderWidth'
        printf '%s\n' 'printf "effective\tbutton_indent\t%d\n", Scr->ButtonIndent'
        printf '%s\n' 'printf "effective\tframe_padding\t%d\n", Scr->FramePadding'
        printf '%s\n' 'printf "effective\thighlight\t%d\n", Scr->Highlight'
        printf '%s\n' 'printf "effective\tmove_delta\t%d\n", Scr->MoveDelta'
        printf '%s\n' 'printf "effective\tno_defaults\t%d\n", Scr->NoDefaults'
        printf '%s\n' 'printf "effective\tno_grab_server\t%d\n", Scr->NoGrabServer'
        printf '%s\n' 'printf "effective\tno_icon_managers\t%d\n", Scr->NoIconManagers'
        printf '%s\n' 'printf "effective\ttitle_button_border_width\t%d\n", Scr->TBInfo.border'
        printf '%s\n' 'printf "effective\ttitle_focus\t%d\n", Scr->TitleFocus'
        printf '%s\n' 'printf "effective\ttitle_font\t%s\n", Scr->TitleBarFont.name'
        printf '%s\n' 'printf "effective\ttitle_padding\t%d\n", Scr->TitlePadding'
        printf '%s\n' 'printf "effective\tuse_p_position\t%d\n", Scr->UsePPosition'
        printf '%s\n' 'info inferiors'
        printf '%s\n' 'detach'
        printf '%s\n' 'quit'
        printf '%s\n' 'end'
        printf 'run -display %s -single -f %s -quiet > %s 2>&1\n' \
            "$display" "$scenario_config" "$twm_log"
    } >"$gdb_commands"

    gdb --quiet --batch --command="$gdb_commands" "$reference_twm" \
        >"$gdb_log" 2>&1 || {
            sed 's/^/GDB: /' "$gdb_log" >&2
            fail "effective-configuration observer failed"
        }
    twm_pid=$(awk '
        /process [0-9]+/ {
            for (i = 1; i <= NF; i++) {
                if ($i == "process" && $(i + 1) ~ /^[0-9]+/) {
                    print $(i + 1)
                    exit
                }
            }
        }
    ' "$gdb_log")
    test -n "$twm_pid" || {
        sed 's/^/GDB: /' "$gdb_log" >&2
        fail "observer did not report the detached twm process"
    }
    kill -0 "$twm_pid" >/dev/null 2>&1 || fail "detached reference twm is not running"
    effective_count=$(awk -F '\t' '$1 == "effective" { count++ } END { print count + 0 }' "$gdb_log")
    test "$effective_count" -eq 13 || fail "observer recorded $effective_count fields, expected 13"

    DISPLAY="$display" "$probe" scenario >"$run_dir/scenario.log" 2>&1 &
    scenario_pid=$!
    DISPLAY="$display" "$probe" wait || {
        sed 's/^/scenario: /' "$run_dir/scenario.log" >&2
        fail "controlled alpha/bravo scenario did not become ready"
    }

    for phase in bravo alpha; do
        DISPLAY="$display" "$probe" set-phase "$phase"
        DISPLAY="$display" "$probe" capture "$run_dir/phase-$phase.tsv"
        xwd -display "$display" -root -silent -out "$run_dir/phase-$phase.xwd"
        xwdtopnm "$run_dir/phase-$phase.xwd" >"$run_dir/phase-$phase.ppm"
        gzip -n -c "$run_dir/phase-$phase.ppm" >"$run_dir/phase-$phase.ppm.gz"
    done

    python3 -B "$normalizer" \
        --config "$scenario_config" \
        --gdb-log "$gdb_log" \
        --twm-log "$twm_log" \
        --bravo-state "$run_dir/phase-bravo.tsv" \
        --bravo-screenshot "$run_dir/phase-bravo.ppm.gz" \
        --alpha-state "$run_dir/phase-alpha.tsv" \
        --alpha-screenshot "$run_dir/phase-alpha.ppm.gz" \
        --output-dir "$run_dir/artifacts"
)

run_one="$capture_work/run-one"
run_two="$capture_work/run-two"
run_once :100 "$run_one"
run_once :101 "$run_two"

artifact_files='parser.json phase-bravo.json phase-bravo.ppm.gz phase-alpha.json phase-alpha.ppm.gz'
for artifact in $artifact_files; do
    cmp "$run_one/artifacts/$artifact" "$run_two/artifacts/$artifact" >/dev/null ||
        fail "clean capture runs differ: $artifact"
done

mkdir "$output_dir"
for artifact in $artifact_files; do
    cp "$run_one/artifacts/$artifact" "$output_dir/$artifact"
done

if test -n "$baseline_dir"; then
    test -d "$baseline_dir" || fail "baseline directory is missing: $baseline_dir"
    for artifact in $artifact_files; do
        cmp "$output_dir/$artifact" "$baseline_dir/$artifact" >/dev/null ||
            fail "capture differs from committed baseline: $artifact"
    done
    echo "reference capture matches two clean runs and committed baselines"
else
    echo "reference capture repeatable across two clean runs; baseline comparison not requested"
fi
