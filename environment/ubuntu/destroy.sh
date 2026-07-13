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

[[ "$STATE_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
[[ "$STATE_CONTAINER_GRAPHROOT" == "$MINIOS_ENV_ROOT/container-storage/graphroot" ]] || exit 1
[[ "$STATE_CONTAINER_RUNROOT" == "$MINIOS_ENV_ROOT/container-storage/runroot" ]] || exit 1
[[ "$STATE_CONTAINER_BUILDER" == 'miniorangeos-dev-builder' ]] || exit 1
[[ "$MINIOS_CONTAINER_STATE_FILE" == "$MINIOS_ENV_ROOT/state/container.env" ]] || exit 1

if ((apply == 0)); then
    printf 'container_destroy=preview phase=%s backend=%s image=%s image_id=%s storage=%s buildx=%s\n' \
        "$STATE_CONTAINER_PHASE" "$STATE_CONTAINER_BACKEND" \
        "$STATE_CONTAINER_LIVE_REF" "$STATE_CONTAINER_IMAGE_ID" \
        "$STATE_CONTAINER_STORAGE_ROOT" "$STATE_CONTAINER_BUILDER"
    exit 0
fi

image_present=0
builder_present=0

if [[ "$STATE_CONTAINER_PHASE" == 'ready' ]]; then
    container_validate_resource_boundaries
    container_select_backend "$STATE_CONTAINER_BACKEND"
    container_probe_image "$STATE_CONTAINER_LIVE_REF"
    if ((CONTAINER_IMAGE_PRESENT == 0)); then
        container_fail 'ready state 的项目镜像缺失，拒绝开始 destroy'
        exit 1
    fi
    container_verify_state_ownership
    image_present=1
    if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
        container_probe_docker_builder
        if ((CONTAINER_BUILDER_PRESENT == 0)); then
            container_fail 'ready state 的固定 Buildx builder 缺失'
            exit 1
        fi
        builder_present=1
    fi
    container_transition_phase destroying
else
    if [[ "$STATE_CONTAINER_BACKEND" == 'podman' \
        && ! -e "$MINIOS_CONTAINER_STORAGE_ROOT" \
        && ! -L "$MINIOS_CONTAINER_STORAGE_ROOT" ]]; then
        rm -f -- "$MINIOS_CONTAINER_STATE_FILE"
        printf 'container_destroy=complete backend=podman image=%s\n' \
            "$STATE_CONTAINER_LIVE_REF"
        exit 0
    fi
    container_validate_destroying_boundaries
    container_select_backend "$STATE_CONTAINER_BACKEND"
    container_probe_image "$STATE_CONTAINER_LIVE_REF"
    if ((CONTAINER_IMAGE_PRESENT == 1)); then
        container_verify_state_ownership
        image_present=1
    fi
    if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
        container_probe_docker_builder
        if ((CONTAINER_BUILDER_PRESENT == 1)); then
            builder_present=1
        fi
    fi
fi

if [[ "$STATE_CONTAINER_IMAGE" != 'miniorangeos-dev:ubuntu-24.04' \
    || "$STATE_CONTAINER_LABEL" != 'org.miniorangeos.project=MiniOrangeOS' ]]; then
    container_fail 'container state 的固定镜像名或项目 label 不匹配'
    exit 1
fi

if [[ "$STATE_CONTAINER_BACKEND" == 'docker' && $builder_present -eq 1 ]]; then
    docker buildx rm --force "$MINIOS_CONTAINER_BUILDER"
fi
if ((image_present == 1)); then
    "${CONTAINER_COMMAND[@]}" image rmi "$STATE_CONTAINER_IMAGE_ID"
fi
rm -rf -- "$MINIOS_CONTAINER_STORAGE_ROOT"
rm -f -- "$MINIOS_CONTAINER_STATE_FILE"
printf 'container_destroy=complete backend=%s image=%s\n' \
    "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_LIVE_REF"
