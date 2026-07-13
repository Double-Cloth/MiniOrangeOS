#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

if (($# == 0)); then
    container_fail '用法：run.sh COMMAND [ARG ...]'
    exit 2
fi

container_load_state
container_validate_loaded_state_boundaries
container_select_backend "$STATE_CONTAINER_BACKEND"
container_verify_state_ownership

readonly run_name="$MINIOS_CONTAINER_NAME-run-$$"
"${CONTAINER_COMMAND[@]}" run --rm \
    --name "$run_name" \
    --label "$MINIOS_CONTAINER_LABEL" \
    --volume "$MINIOS_REPO_ROOT:/workspace:ro" \
    --workdir /workspace \
    "$MINIOS_CONTAINER_IMAGE" "$@"
