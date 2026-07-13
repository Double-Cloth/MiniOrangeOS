#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

[[ "$MINIOS_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
[[ "$MINIOS_CONTAINER_BUILDER" == 'miniorangeos-dev-builder' ]] || exit 1
container_prepare_project_paths
created_builder=0

cleanup_new_builder_on_failure() {
    local status=$?
    trap - EXIT
    if ((status != 0 && created_builder == 1)); then
        if ! docker buildx rm --force "$MINIOS_CONTAINER_BUILDER" >/dev/null 2>&1; then
            minios_log 'FAIL' '构建失败后无法清理本次创建的项目 Buildx builder'
        fi
    fi
    exit "$status"
}
trap cleanup_new_builder_on_failure EXIT

if [[ -e "$MINIOS_CONTAINER_STATE_FILE" || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
    container_load_state
    container_validate_loaded_state_boundaries
    container_select_backend "$STATE_CONTAINER_BACKEND"
    container_verify_state_ownership
else
    container_select_backend
fi

if [[ "$CONTAINER_BACKEND" == 'podman' ]]; then
    "${CONTAINER_COMMAND[@]}" build \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --tag "$MINIOS_CONTAINER_IMAGE" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
else
    if [[ -e "$MINIOS_CONTAINER_STATE_FILE" ]]; then
        docker buildx inspect "$MINIOS_CONTAINER_BUILDER" >/dev/null
    else
        docker buildx create --name "$MINIOS_CONTAINER_BUILDER" \
            --driver docker-container >/dev/null
        created_builder=1
    fi
    docker buildx build --builder "$MINIOS_CONTAINER_BUILDER" --load \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --tag "$MINIOS_CONTAINER_IMAGE" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
fi

image_id="$(container_inspect_image)"
container_write_state "$CONTAINER_BACKEND" "$image_id"
created_builder=0
trap - EXIT
printf 'container_status=created backend=%s image=%s image_id=%s\n' \
    "$CONTAINER_BACKEND" "$MINIOS_CONTAINER_IMAGE" "$image_id"
