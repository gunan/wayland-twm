#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
marker=/etc/wtwm-platform-test-vm
state_dir=/var/lib/wtwm-platform

test "$(id -u)" -eq 0 || {
	printf '%s\n' 'provision.sh: run as root inside the reference VM' >&2
	exit 1
}
test -r /etc/os-release || {
	printf '%s\n' 'provision.sh: /etc/os-release is unavailable' >&2
	exit 1
}
# shellcheck disable=SC1091
. /etc/os-release
test "${ID:-}" = debian && test "${VERSION_CODENAME:-}" = trixie || {
	printf '%s\n' 'provision.sh: Debian trixie is required' >&2
	exit 1
}
test "$(dpkg --print-architecture)" = arm64 || {
	printf '%s\n' 'provision.sh: Debian arm64 is required' >&2
	exit 1
}

export DEBIAN_FRONTEND=noninteractive
apt-get update
xargs apt-get install -y --no-install-recommends < "$script_dir/packages.txt"
install -d -m 0755 "$state_dir"
dpkg-query -W -f='${binary:Package}\t${Version}\n' |
	LC_ALL=C sort > "$state_dir/packages.tsv"
sha512sum "$script_dir/image.env" "$script_dir/packages.txt" > "$state_dir/definition.sha512"
printf '%s\n' 'debian-arm64-20260810-2566' > "$marker"

if getent passwd wtwm >/dev/null 2>&1; then
	for group_name in audio input render seat video; do
		getent group "$group_name" >/dev/null 2>&1 &&
			usermod -a -G "$group_name" wtwm
	done
fi
systemctl enable seatd.service
systemctl enable gdm3.service
printf 'Provisioning complete; package lock: %s/packages.tsv\n' "$state_dir"
