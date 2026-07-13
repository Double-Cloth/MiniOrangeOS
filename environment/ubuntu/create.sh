#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/lib.sh"

[[ "$MINIOS_CONTAINER_STORAGE_ROOT" == "$MINIOS_ENV_ROOT/container-storage" ]] || exit 1
# runtime 边界无效时必须在 lifecycle lock 创建 state 目录前零残留失败。
container_preflight_runtime_boundary
container_acquire_lifecycle_lock "$0" "$@"
trap 'container_release_lifecycle_lock || true' EXIT

if [[ -e "$MINIOS_CONTAINER_STATE_FILE" || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
    container_load_state
    container_validate_loaded_state_boundaries
    case "$STATE_CONTAINER_PHASE" in
        ready)
            container_probe_loaded_resources
            if ((CONTAINER_OWNED_IMAGE_PRESENT == 1)) \
                && { [[ "$STATE_CONTAINER_BACKEND" != 'docker' ]] \
                    || ((CONTAINER_OWNED_BUILDER_PRESENT == 1)); }; then
                printf 'container_status=up-to-date backend=%s image=%s image_id=%s\n' \
                    "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_LIVE_REF" \
                    "$STATE_CONTAINER_IMAGE_ID"
                exit 0
            fi
            minios_log 'INFO' 'ready state 资源发生可验证漂移，自动清理后重建'
            container_transition_phase destroying
            container_cleanup_loaded_resources
            ;;
        destroying)
            container_fail 'container state 正在 destroying；请先重试 destroy.sh --all'
            exit 1
            ;;
        creating)
            container_recover_creating_state
            ;;
    esac
fi

if [[ -e "$MINIOS_CONTAINER_STORAGE_ROOT" || -L "$MINIOS_CONTAINER_STORAGE_ROOT" ]]; then
    container_fail 'container state 缺失但项目 storage 已存在，拒绝覆盖未知资源'
    exit 1
fi

container_select_backend
container_intent="$(container_generate_intent)" || exit $?
container_builder="$(container_expected_builder \
    "$CONTAINER_BACKEND" "$container_intent")" || exit $?
if [[ "$CONTAINER_BACKEND" == 'podman' ]]; then
    # canonical ref 只可能位于固定 project graphroot；storage 不存在即证明 ref 不存在。
    CONTAINER_IMAGE_PRESENT=0
else
    container_probe_image "$CONTAINER_LIVE_REF"
    if ((CONTAINER_IMAGE_PRESENT == 1)); then
        container_fail "container state 缺失但 canonical live ref 已存在：$CONTAINER_LIVE_REF"
        exit 1
    fi
    container_probe_docker_builder "$container_builder"
    if ((CONTAINER_BUILDER_PRESENT == 1)); then
        container_fail 'container state 缺失但固定 Buildx builder 已存在'
        exit 1
    fi
fi
if [[ -e "$MINIOS_CONTAINER_STORAGE_ROOT" || -L "$MINIOS_CONTAINER_STORAGE_ROOT" ]]; then
    container_fail 'backend 探测后出现未知项目 storage，拒绝覆盖'
    exit 1
fi
if [[ -e "$MINIOS_CONTAINER_STATE_FILE" || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
    container_fail 'backend 探测期间出现 container state，拒绝覆盖'
    exit 1
fi

container_write_state creating "$CONTAINER_BACKEND" "$CONTAINER_LIVE_REF" \
    pending "$container_intent" "$container_builder"
intent_active=1
iidfile=''
new_image_id=''

recover_create_on_exit() {
    local status=$?
    trap - EXIT
    if ((intent_active == 1)) \
        && [[ -e "$MINIOS_CONTAINER_STATE_FILE" \
            || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
        if container_load_state \
            && container_validate_loaded_state_boundaries \
            && [[ "$STATE_CONTAINER_PHASE" == 'creating' ]]; then
            if ! container_recover_creating_state; then
                minios_log 'FAIL' \
                    "create 原始失败 status=$status；creating recovery 未完成，state 已保留"
            fi
        else
            minios_log 'FAIL' \
                "create 原始失败 status=$status；creating state 无法可信加载，已保留"
        fi
    fi
    if ! container_release_lifecycle_lock; then
        minios_log 'FAIL' "create 原始失败 status=$status；lifecycle lock 释放失败"
    fi
    exit "$status"
}
trap recover_create_on_exit EXIT

container_prepare_project_paths
if [[ "$CONTAINER_BACKEND" == 'docker' ]]; then
    docker buildx create --name "$container_builder" \
        --driver docker-container >/dev/null
fi

iidfile="$(mktemp "$MINIOS_CONTAINER_STATE_DIR/container.iid.partial.XXXXXX")"
rm -f -- "$iidfile"
if [[ "$CONTAINER_BACKEND" == 'podman' ]]; then
    "${CONTAINER_COMMAND[@]}" build \
        --iidfile "$iidfile" \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --label "$MINIOS_CONTAINER_INTENT_LABEL_KEY=$container_intent" \
        --tag "$CONTAINER_LIVE_REF" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
else
    docker buildx build --builder "$container_builder" --load \
        --iidfile "$iidfile" \
        --label "$MINIOS_CONTAINER_LABEL" \
        --label "$MINIOS_CONTAINER_TASK_LABEL" \
        --label "$MINIOS_CONTAINER_SOURCE_LABEL" \
        --label "$MINIOS_CONTAINER_INTENT_LABEL_KEY=$container_intent" \
        --tag "$CONTAINER_LIVE_REF" \
        --file "$MINIOS_CONTAINERFILE" \
        "$MINIOS_REPO_ROOT"
fi

if [[ ! -f "$iidfile" || -L "$iidfile" ]]; then
    container_fail 'backend 构建成功但未生成可信 iidfile'
    exit 1
fi
new_image_id="$(container_normalize_image_id "$(<"$iidfile")")" || exit $?
container_write_state creating "$CONTAINER_BACKEND" \
    "$CONTAINER_LIVE_REF" "$new_image_id" \
    "$container_intent" "$container_builder"
container_inspect_image "$CONTAINER_LIVE_REF" "$container_intent" \
    "$new_image_id" >/dev/null
rm -f -- "$iidfile"
iidfile=''
container_write_state ready "$CONTAINER_BACKEND" "$CONTAINER_LIVE_REF" \
    "$new_image_id" "$container_intent" "$container_builder"

intent_active=0
trap - EXIT
container_release_lifecycle_lock
printf 'container_status=created backend=%s image=%s image_id=%s\n' \
    "$CONTAINER_BACKEND" "$CONTAINER_LIVE_REF" "$new_image_id"
