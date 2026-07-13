#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

[[ "$MINIOS_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
[[ "$MINIOS_CONTAINER_BUILDER" == 'miniorangeos-dev-builder' ]] || exit 1

if [[ -e "$MINIOS_CONTAINER_STATE_FILE" || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
    container_load_state
    container_validate_loaded_state_boundaries
    container_require_ready_phase
    container_validate_resource_boundaries
    container_select_backend "$STATE_CONTAINER_BACKEND"
    container_verify_state_ownership
    if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
        container_probe_docker_builder
        if ((CONTAINER_BUILDER_PRESENT == 0)); then
            container_fail 'ready state 的固定 Buildx builder 缺失'
            exit 1
        fi
    fi
    printf 'container_status=up-to-date backend=%s image=%s image_id=%s\n' \
        "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_LIVE_REF" \
        "$STATE_CONTAINER_IMAGE_ID"
    exit 0
fi

if [[ -e "$MINIOS_CONTAINER_STORAGE_ROOT" || -L "$MINIOS_CONTAINER_STORAGE_ROOT" ]]; then
    container_fail 'container state 缺失但项目 storage 已存在，拒绝覆盖未知资源'
    exit 1
fi

container_prepare_project_paths
created_storage=1
created_builder=0
build_completed=0
new_image_id=''
iidfile=''

rollback_create() {
    local status=$?
    local rollback_failed=0
    trap - EXIT
    if ((build_completed == 1)); then
        if ! "${CONTAINER_COMMAND[@]}" image rmi "$new_image_id"; then
            minios_log 'FAIL' "无法回滚本次新建的精确 image ID：$new_image_id"
            rollback_failed=1
        fi
    fi
    if ((created_builder == 1)); then
        if ! docker buildx rm --force "$MINIOS_CONTAINER_BUILDER" >/dev/null; then
            minios_log 'FAIL' '无法回滚本次创建的项目 Buildx builder'
            rollback_failed=1
        fi
    fi
    if ((created_storage == 1)); then
        if container_assert_owned_path "$MINIOS_CONTAINER_STORAGE_ROOT" \
            "$MINIOS_ENV_ROOT/container-storage"; then
            if ! rm -rf -- "$MINIOS_CONTAINER_STORAGE_ROOT"; then
                minios_log 'FAIL' '无法回滚本次创建的项目 container storage'
                rollback_failed=1
            fi
        else
            rollback_failed=1
        fi
    fi
    if [[ -n "$iidfile" ]] && ! rm -f -- "$iidfile"; then
        minios_log 'FAIL' '无法清理 image ID 临时文件'
        rollback_failed=1
    fi
    if ((rollback_failed == 1)); then
        minios_log 'FAIL' "create 原始失败 status=$status，且 rollback 不完整"
    fi
    exit "$status"
}
trap rollback_create EXIT

container_select_backend
container_probe_image "$CONTAINER_LIVE_REF"
if ((CONTAINER_IMAGE_PRESENT == 1)); then
    container_fail "container state 缺失但 canonical live ref 已存在：$CONTAINER_LIVE_REF"
    exit 1
fi

if [[ "$CONTAINER_BACKEND" == 'docker' ]]; then
    container_probe_docker_builder
    if ((CONTAINER_BUILDER_PRESENT == 1)); then
        container_fail 'container state 缺失但固定 Buildx builder 已存在'
        exit 1
    fi
    docker buildx create --name "$MINIOS_CONTAINER_BUILDER" \
        --driver docker-container >/dev/null
    created_builder=1
fi

iidfile="$(mktemp "$MINIOS_CONTAINER_STATE_DIR/container.iid.partial.XXXXXX")"
rm -f -- "$iidfile"
if [[ "$CONTAINER_BACKEND" == 'podman' ]]; then
    "${CONTAINER_COMMAND[@]}" build \
        --iidfile "$iidfile" \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --tag "$CONTAINER_LIVE_REF" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
else
    docker buildx build --builder "$MINIOS_CONTAINER_BUILDER" --load \
        --iidfile "$iidfile" \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --tag "$CONTAINER_LIVE_REF" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
fi

if [[ -f "$iidfile" && ! -L "$iidfile" ]]; then
    new_image_id="$(<"$iidfile")"
fi
if [[ "$new_image_id" != sha256:* || "$new_image_id" =~ [[:space:]] ]]; then
    new_image_id="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{.Id}}' "$CONTAINER_LIVE_REF")" || {
        container_fail 'backend 构建成功但无法恢复精确新 image ID'
        exit 1
    }
    if [[ "$new_image_id" != sha256:* || "$new_image_id" =~ [[:space:]] ]]; then
        container_fail "backend 构建成功但恢复的 image ID 非法：${new_image_id:-missing}"
        exit 1
    fi
    build_completed=1
    container_fail 'backend 未生成可信 iidfile，已捕获精确新 image ID 并进入回滚'
    exit 1
fi
build_completed=1
container_inspect_image "$CONTAINER_LIVE_REF" "$new_image_id" >/dev/null
rm -f -- "$iidfile"
iidfile=''
container_write_state ready "$CONTAINER_BACKEND" "$CONTAINER_LIVE_REF" "$new_image_id"

created_storage=0
created_builder=0
build_completed=0
trap - EXIT
printf 'container_status=created backend=%s image=%s image_id=%s\n' \
    "$CONTAINER_BACKEND" "$CONTAINER_LIVE_REF" "$new_image_id"
