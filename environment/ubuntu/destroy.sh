#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

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

# 这些显式比较使 destructive 入口本身保留固定四重边界。
[[ "$STATE_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
[[ "$STATE_CONTAINER_GRAPHROOT" == "$MINIOS_ENV_ROOT/container-storage/graphroot" ]] || exit 1
[[ "$STATE_CONTAINER_RUNROOT" == "$MINIOS_ENV_ROOT/container-storage/runroot" ]] || exit 1
[[ "$STATE_CONTAINER_BUILDER" == 'miniorangeos-dev-builder' ]] || exit 1
[[ "$MINIOS_CONTAINER_STATE_FILE" == "$MINIOS_ENV_ROOT/state/container.env" ]] || exit 1

if ((apply == 0)); then
    printf 'container_destroy=preview backend=%s image=%s image_id=%s storage=%s buildx=%s\n' \
        "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_IMAGE" \
        "$STATE_CONTAINER_IMAGE_ID" "$STATE_CONTAINER_STORAGE_ROOT" \
        "$STATE_CONTAINER_BUILDER"
    exit 0
fi

# --all 的所有 destructive 操作必须排在完整状态、路径、backend 与 live inspect 之后。
container_validate_resource_boundaries
container_select_backend "$STATE_CONTAINER_BACKEND"
container_verify_state_ownership
if [[ "$STATE_CONTAINER_IMAGE" != 'miniorangeos-dev:ubuntu-24.04' \
    || "$STATE_CONTAINER_LABEL" != 'org.miniorangeos.project=MiniOrangeOS' ]]; then
    container_fail 'container state 的固定镜像名或项目 label 不匹配'
    exit 1
fi
if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
    docker buildx inspect "$MINIOS_CONTAINER_BUILDER" >/dev/null
fi

if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
    docker buildx rm --force "$MINIOS_CONTAINER_BUILDER"
    docker image rmi "$MINIOS_CONTAINER_IMAGE"
else
    "${CONTAINER_COMMAND[@]}" image rmi "$MINIOS_CONTAINER_IMAGE"
fi

rm -rf -- "$MINIOS_CONTAINER_STORAGE_ROOT"
rm -f -- "$MINIOS_CONTAINER_STATE_FILE"
printf 'container_destroy=complete backend=%s image=%s\n' \
    "$STATE_CONTAINER_BACKEND" "$MINIOS_CONTAINER_IMAGE"
