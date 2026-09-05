#!/bin/sh

set -eu

source_root=$1
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-codex-cloud-wlroots.XXXXXX")
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM
mkdir -p "$test_dir/bin"

fail()
{
	echo "codex-cloud wlroots test failed: $*" >&2
	exit 1
}

cat > "$test_dir/bin/pkg-config" <<'EOF'
#!/bin/sh
if [ "$#" -eq 2 ] && [ "$1" = --exists ]; then
	case ":${WTWM_TEST_PKG_MODULES:-}:" in
		*":$2:"*) exit 0 ;;
	esac
fi
exit 1
EOF
cat > "$test_dir/bin/meson" <<'EOF'
#!/bin/sh
printf 'meson' >> "$WTWM_TEST_LOG"
printf '\t%s' "$@" >> "$WTWM_TEST_LOG"
printf '\n' >> "$WTWM_TEST_LOG"
EOF
chmod +x "$test_dir/bin/pkg-config" "$test_dir/bin/meson"

run_build()
{
	WTWM_TEST_LOG="$test_dir/meson.log" \
	PATH="$test_dir/bin:/usr/bin:/bin" \
	CODEX_CLOUD_BUILD_DIR="$test_dir/build" \
	WTWM_TEST_PKG_MODULES="$1" \
	CODEX_CLOUD_COMPOSITOR="$2" \
	CODEX_CLOUD_WLROOTS_PKGCONFIG="$3" \
		bash "$source_root/scripts/codex-cloud/build.sh"
}

: > "$test_dir/meson.log"
run_build 'wlroots-0.18:wlroots-0.19:wlroots-0.20' auto '' \
	> "$test_dir/default.out"
grep -F 'compositor=enabled wlroots=wlroots-0.20' "$test_dir/default.out" \
	>/dev/null || fail 'automatic discovery did not prefer wlroots 0.20'
grep -F -- '-Dcompositor=enabled' "$test_dir/meson.log" >/dev/null ||
	fail 'automatic discovery did not enable the compositor'
if grep -F -- '-Dwlroots_pkgconfig=' "$test_dir/meson.log" >/dev/null; then
	fail 'automatic discovery unexpectedly set an override'
fi

: > "$test_dir/meson.log"
run_build 'wlroots-0.19' auto '' > "$test_dir/019.out"
grep -F 'compositor=enabled wlroots=wlroots-0.19' "$test_dir/019.out" \
	>/dev/null || fail 'wlroots 0.19 was not recognized'

: > "$test_dir/meson.log"
run_build 'wlroots-0.21' auto 'wlroots-0.21' > "$test_dir/future.out"
grep -F 'compositor=enabled wlroots=wlroots-0.21' "$test_dir/future.out" \
	>/dev/null || fail 'explicit future module was not selected'
grep -F -- '-Dwlroots_pkgconfig=wlroots-0.21' "$test_dir/meson.log" >/dev/null ||
	fail 'explicit module was not passed to Meson'

: > "$test_dir/meson.log"
run_build '' auto '' > "$test_dir/portable.out"
grep -F 'compositor=disabled' "$test_dir/portable.out" >/dev/null ||
	fail 'missing wlroots did not select the portable build'

if run_build '' enabled '' > "$test_dir/missing.out" 2> "$test_dir/missing.err"; then
	fail 'enabled compositor accepted a missing wlroots dependency'
fi
grep -F 'wlroots-0.20 wlroots-0.19 wlroots-0.18' "$test_dir/missing.err" \
	>/dev/null || fail 'missing-dependency diagnostic omitted supported modules'

if run_build '' auto '../bad' > "$test_dir/invalid.out" 2> "$test_dir/invalid.err"; then
	fail 'invalid pkg-config module override was accepted'
fi
grep -F 'must be a pkg-config module name' "$test_dir/invalid.err" >/dev/null ||
	fail 'invalid override diagnostic was not emitted'

mkdir -p "$test_dir/setup-bin"
cat > "$test_dir/setup-bin/apt-get" <<'EOF'
#!/bin/sh
printf 'apt-get\t%s\n' "$*" >> "$WTWM_TEST_SETUP_LOG"
EOF
cat > "$test_dir/setup-bin/apt-cache" <<'EOF'
#!/bin/sh
if [ "$1" = show ]; then
	case ":${WTWM_TEST_APT_PACKAGES:-}:" in
		*":$2:"*) exit 0 ;;
	esac
fi
exit 1
EOF
cat > "$test_dir/setup-bin/id" <<'EOF'
#!/bin/sh
if [ "$1" = -u ]; then
	echo 0
	exit 0
fi
exit 1
EOF
cat > "$test_dir/setup-bin/bash" <<'EOF'
#!/bin/sh
printf 'bash\t%s\n' "$*" >> "$WTWM_TEST_SETUP_LOG"
EOF
chmod +x "$test_dir/setup-bin/apt-get" "$test_dir/setup-bin/apt-cache" \
	"$test_dir/setup-bin/id" "$test_dir/setup-bin/bash"

run_setup()
{
	WTWM_TEST_SETUP_LOG="$test_dir/setup.log" \
	PATH="$test_dir/setup-bin:$test_dir/bin:/usr/bin:/bin" \
	WTWM_TEST_PKG_MODULES="$1" \
	WTWM_TEST_APT_PACKAGES="$2" \
	CODEX_CLOUD_WLROOTS_PKGCONFIG="$3" \
		/bin/bash "$source_root/scripts/codex-cloud/setup.sh"
}

: > "$test_dir/setup.log"
run_setup 'wlroots-0.19' '' ''
if grep -F 'libwlroots-' "$test_dir/setup.log" >/dev/null; then
	fail 'setup tried to replace an installed wlroots 0.19 module'
fi

: > "$test_dir/setup.log"
run_setup '' 'libwlroots-0.19-dev' ''
grep -F 'libwlroots-0.19-dev' "$test_dir/setup.log" >/dev/null ||
	fail 'setup did not select the available wlroots 0.19 development package'

: > "$test_dir/setup.log"
run_setup '' 'libwlroots-0.21-dev' 'wlroots-0.21'
grep -F 'libwlroots-0.21-dev' "$test_dir/setup.log" >/dev/null ||
	fail 'setup did not derive the future development package from the override'
grep -F 'scripts/codex-cloud/build.sh' "$test_dir/setup.log" >/dev/null ||
	fail 'setup did not hand off the override-aware build'

echo 'codex-cloud wlroots selection passed'
