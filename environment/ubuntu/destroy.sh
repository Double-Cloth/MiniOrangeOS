#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

container_acquire_lifecycle_lock "$0" "$@"
trap 'container_release_lifecycle_lock || true' EXIT

apply=0
case "${1:-}" in
    '') ;;
    --all) apply=1 ;;
    *) container_fail '用法：destroy.sh [--all]'; exit 2 ;;
esac
if (($# > 1)); then
    container_fail '用法：destroy.sh [--all]'
    exit 2
fi

container_load_state
container_validate_loaded_state_boundaries

if [[ "$STATE_CONTAINER_PHASE" == 'creating' ]]; then
    container_fail 'container state 正在 creating；请运行 create.sh 执行自动 recovery'
    exit 1
fi

[[ "$STATE_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
[[ "$STATE_CONTAINER_GRAPHROOT" == "$MINIOS_ENV_ROOT/container-storage/graphroot" ]] || exit 1
[[ "$STATE_CONTAINER_RUNROOT" == "$MINIOS_CONTAINER_RUNROOT" ]] || exit 1
[[ "$MINIOS_CONTAINER_STATE_FILE" == "$MINIOS_ENV_ROOT/state/container.env" ]] || exit 1

if ((apply == 0)); then
    printf 'container_destroy=preview phase=%s backend=%s image=%s image_id=%s storage=%s buildx=%s\n' \
        "$STATE_CONTAINER_PHASE" "$STATE_CONTAINER_BACKEND" \
        "$STATE_CONTAINER_LIVE_REF" "$STATE_CONTAINER_IMAGE_ID" \
        "$STATE_CONTAINER_STORAGE_ROOT" "$STATE_CONTAINER_BUILDER"
    exit 0
fi

container_probe_loaded_resources
if [[ "$STATE_CONTAINER_PHASE" == 'ready' ]]; then
    container_transition_phase destroying
fi

if [[ "$STATE_CONTAINER_IMAGE" != 'miniorangeos-dev:ubuntu-24.04' \
    || "$STATE_CONTAINER_LABEL" != 'org.miniorangeos.project=MiniOrangeOS' ]]; then
    container_fail 'container state 的固定镜像名或项目 label 不匹配'
    exit 1
fi

container_cleanup_loaded_resources
printf 'container_destroy=complete backend=%s image=%s\n' \
    "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_LIVE_REF"
