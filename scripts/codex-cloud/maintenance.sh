#!/usr/bin/env bash

set -euo pipefail

# Cached Codex Cloud containers resume after checking out the task branch.
# Reconfigure so Meson sees any build-definition changes on that branch.
bash scripts/codex-cloud/build.sh
