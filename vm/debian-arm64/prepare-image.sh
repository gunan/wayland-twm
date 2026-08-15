#!/bin/sh
set -eu

usage()
{
	cat >&2 <<'EOF'
usage: prepare-image.sh SSH_PUBLIC_KEY_FILE PASSWORD_HASH_FILE OUTPUT_DIRECTORY

Create a verified Debian ARM64 qcow2 disk and NoCloud seed ISO for UTM.
The output directory must not already exist.
EOF
	exit 2
}

test "$#" -eq 3 || usage
ssh_key_file=$1
password_hash_file=$2
output_dir=$3
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

test -f "$ssh_key_file" || {
	printf 'prepare-image.sh: SSH public key not found: %s\n' "$ssh_key_file" >&2
	exit 1
}
test -f "$password_hash_file" || {
	printf 'prepare-image.sh: password hash not found: %s\n' "$password_hash_file" >&2
	exit 1
}
test ! -e "$output_dir" || {
	printf 'prepare-image.sh: refusing to overwrite: %s\n' "$output_dir" >&2
	exit 1
}

for command_name in awk curl qemu-img shasum xorriso; do
	command -v "$command_name" >/dev/null 2>&1 || {
		printf 'prepare-image.sh: required command not found: %s\n' "$command_name" >&2
		exit 1
	}
done

# shellcheck disable=SC1091
. "$script_dir/image.env"
case $WTWM_VM_IMAGE_URL in
	https://cloud.debian.org/images/cloud/trixie/"$WTWM_VM_IMAGE_BUILD"/*) ;;
	*) printf '%s\n' 'prepare-image.sh: image URL/build mismatch' >&2; exit 1 ;;
esac
case $WTWM_VM_IMAGE_SHA512 in
	*[!0123456789abcdef]*|'')
		printf '%s\n' 'prepare-image.sh: invalid image SHA-512' >&2
		exit 1
		;;
esac
test "${#WTWM_VM_IMAGE_SHA512}" -eq 128 || {
	printf '%s\n' 'prepare-image.sh: image SHA-512 must contain 128 hex digits' >&2
	exit 1
}

# Only the key type and base64 payload are put in cloud-init.  Discarding the
# comment avoids YAML quoting surprises and keeps personal email out of output.
ssh_key_type=$(awk 'NR == 1 { print $1; exit }' "$ssh_key_file")
ssh_key_payload=$(awk 'NR == 1 { print $2; exit }' "$ssh_key_file")
case $ssh_key_type in
	ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521) ;;
	*) printf '%s\n' 'prepare-image.sh: unsupported SSH public key type' >&2; exit 1 ;;
esac
case $ssh_key_payload in
	''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]*)
		printf '%s\n' 'prepare-image.sh: malformed SSH public key payload' >&2
		exit 1
		;;
esac
ssh_key="$ssh_key_type $ssh_key_payload"
password_hash=$(awk 'NR == 1 { print; exit }' "$password_hash_file")
case $password_hash in
	\$6\$*|\$y\$*) ;;
	*)
		printf '%s\n' 'prepare-image.sh: password must be a SHA-512 crypt or yescrypt hash' >&2
		exit 1
		;;
esac
case $password_hash in
	*[!\$./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*)
		printf '%s\n' 'prepare-image.sh: password hash contains unsafe YAML characters' >&2
		exit 1
		;;
esac

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/wtwm-vm.XXXXXX")
cleanup()
{
	rm -rf -- "$work_dir"
}
trap cleanup EXIT HUP INT TERM

mkdir -p -- "$output_dir"
base_image=$work_dir/base.qcow2
printf 'Downloading %s\n' "$WTWM_VM_IMAGE_URL"
curl --fail --location --proto '=https' --tlsv1.2 \
	--output "$base_image" "$WTWM_VM_IMAGE_URL"
printf '%s  %s\n' "$WTWM_VM_IMAGE_SHA512" "$base_image" |
	shasum -a 512 -c - >/dev/null

disk=$output_dir/wtwm-debian-arm64.qcow2
qemu-img convert -f qcow2 -O qcow2 "$base_image" "$disk"
qemu-img resize "$disk" "$WTWM_VM_DISK_SIZE" >/dev/null

seed_dir=$work_dir/seed
mkdir -p -- "$seed_dir"
cp "$script_dir/cloud-init/meta-data" "$seed_dir/meta-data"
cp "$script_dir/cloud-init/network-config" "$seed_dir/network-config"
awk -v ssh_key="$ssh_key" -v password_hash="$password_hash" \
	-v packages="$script_dir/packages.txt" '
	$0 == "@WTWM_PACKAGES@" {
		while ((getline package < packages) > 0) {
			if (package != "" && package !~ /^#/) print "  - " package
		}
		close(packages)
		next
	}
	{
		gsub(/@WTWM_SSH_PUBLIC_KEY@/, ssh_key)
		gsub(/@WTWM_PASSWORD_HASH@/, password_hash)
		print
	}
' "$script_dir/cloud-init/user-data.in" > "$seed_dir/user-data"

seed_iso=$(CDPATH= cd -- "$output_dir" && pwd)/wtwm-debian-arm64-seed.iso
(
	cd "$seed_dir"
	xorriso -as mkisofs -quiet -joliet -rock -volid cidata \
		-output "$seed_iso" user-data meta-data network-config
)
cp "$script_dir/image.env" "$output_dir/image.env"
cp "$script_dir/packages.txt" "$output_dir/packages.txt"
(
	cd "$output_dir"
	shasum -a 512 wtwm-debian-arm64.qcow2 wtwm-debian-arm64-seed.iso > SHA512SUMS
)

trap - EXIT HUP INT TERM
cleanup
printf 'Created UTM inputs in %s\n' "$output_dir"
