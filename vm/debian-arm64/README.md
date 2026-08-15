# Debian ARM64 UTM platform

This definition creates the interactive Debian 13 ARM64 reference/development
guest used for nested, headless, and DRM/login checks.  The base qcow2 is an
immutable Debian cloud build whose SHA-512 is pinned in `image.env`.  No login
password or repository credential is stored in the tree.

## Create the guest

On the Apple Silicon host, install UTM, QEMU tools, and `xorriso`, then run:

```sh
vm/debian-arm64/prepare-image.sh ~/.ssh/id_ed25519.pub /path/to/wtwm-vm-inputs
```

The destination must not exist; this prevents accidentally overwriting a VM.
Create a UTM **Virtualize / Linux / Other** VM with four CPU cores, 8 GiB RAM,
UEFI boot, a VirtIO-GPU display, a VirtIO network adapter, and a serial device.
Import `wtwm-debian-arm64.qcow2` as the first VirtIO drive and attach
`wtwm-debian-arm64-seed.iso` as removable media.  Disable shared clipboard and
shared directories for reference captures.  Boot, wait for cloud-init's final
message, then SSH as `wtwm`.  Detach the seed ISO after the first successful
boot so the instance ID cannot be reapplied.

UTM does not have a stable, supported text format across its Apple
Virtualization and QEMU backends.  The checked-in, hash-verified disk and
NoCloud seed are therefore the reproducible machine definition; the explicit
device list above is the small UTM-specific layer.

After copying or cloning this repository into the guest, rerun provisioning to
verify the OS and architecture and refresh the package evidence:

```sh
sudo vm/debian-arm64/provision.sh
```

`/var/lib/wtwm-platform/packages.tsv` records every resolved package version,
and `/var/lib/wtwm-platform/definition.sha512` identifies the definition used.
The base image is byte-reproducible; Debian package mirrors evolve, so an
evidence bundle is reproducible only together with its recorded package list
or an archive of the corresponding `.deb` files.

Take a powered-off snapshot named `clean-provisioned` before installing wtwm.
Always restore that snapshot for package lifecycle tests.  Never use a personal
desktop or a VM containing irreplaceable data for those tests.
