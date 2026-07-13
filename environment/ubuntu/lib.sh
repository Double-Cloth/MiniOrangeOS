#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 容器入口共用的 backend、状态和路径边界。
readonly MINIOS_UBUNTU_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly MINIOS_UBUNTU_REQUESTED_ENV_ROOT="${MINIOS_ENV_ROOT:-}"
# shellcheck source=../lib/common.sh
source "$MINIOS_UBUNTU_LIB_DIR/../lib/common.sh"
minios_load_versions

if [[ -n "$MINIOS_UBUNTU_REQUESTED_ENV_ROOT" \
    && "$MINIOS_UBUNTU_REQUESTED_ENV_ROOT" != "$MINIOS_ENV_ROOT" ]]; then
    minios_die "MINIOS_ENV_ROOT 不得经过 symlink 或非规范路径：$MINIOS_UBUNTU_REQUESTED_ENV_ROOT"
    return 1
fi

readonly MINIOS_CONTAINER_NAME='miniorangeos-dev'
readonly MINIOS_CONTAINER_SOURCE_VERSION='T01'
readonly MINIOS_CONTAINER_TASK_LABEL='org.miniorangeos.task=T01'
readonly MINIOS_CONTAINER_SOURCE_LABEL='org.miniorangeos.source-version=T01'
readonly MINIOS_CONTAINER_LABEL_KEY="${MINIOS_CONTAINER_LABEL%%=*}"
readonly MINIOS_CONTAINER_LABEL_VALUE="${MINIOS_CONTAINER_LABEL#*=}"
readonly MINIOS_CONTAINER_STORAGE_ROOT="$MINIOS_ENV_ROOT/container-storage"
readonly MINIOS_CONTAINER_GRAPHROOT="$MINIOS_CONTAINER_STORAGE_ROOT/graphroot"
readonly MINIOS_CONTAINER_RUNROOT="$MINIOS_CONTAINER_STORAGE_ROOT/runroot"
readonly MINIOS_CONTAINER_BUILDER='miniorangeos-dev-builder'
readonly MINIOS_CONTAINER_STATE_DIR="$MINIOS_ENV_ROOT/state"
readonly MINIOS_CONTAINER_STATE_FILE="$MINIOS_CONTAINER_STATE_DIR/container.env"
readonly MINIOS_CONTAINERFILE="$MINIOS_REPO_ROOT/environment/Containerfile"

CONTAINER_BACKEND=''
declare -a CONTAINER_COMMAND=()

container_fail() {
    minios_die "$*"
}

container_assert_lexical_path() {
    local candidate="$1"
    local lexical
    local current='/'
    local relative
    local component

    if [[ "$candidate" != /* ]]; then
        container_fail "容器资源路径必须是绝对路径：$candidate"
        return 1
    fi
    lexical="$(realpath -ms -- "$candidate")" || return $?
    if [[ "$lexical" != "$candidate" ]]; then
        container_fail "容器资源路径必须是规范路径：$candidate"
        return 1
    fi
    relative="${candidate#/}"
    IFS='/' read -r -a components <<<"$relative"
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current="${current%/}/$component"
        if [[ -L "$current" ]]; then
            container_fail "容器资源路径包含 symlink：$current"
            return 1
        fi
    done
}

container_assert_owned_path() {
    local candidate="$1"
    local expected="$2"
    local bounded

    container_assert_lexical_path "$candidate" || return $?
    if [[ "$candidate" != "$expected" ]]; then
        container_fail "容器资源路径与固定边界不一致：actual=$candidate expected=$expected"
        return 1
    fi
    bounded="$(minios_assert_path_within_environment_root "$candidate")" || return $?
    if [[ "$bounded" != "$candidate" ]]; then
        container_fail "容器资源路径解析结果不一致：$candidate"
        return 1
    fi
}

container_prepare_directory() {
    local candidate="$1"
    local expected="$2"
    container_assert_owned_path "$candidate" "$expected" || return $?
    mkdir -p -- "$candidate" || return $?
    container_assert_owned_path "$candidate" "$expected" || return $?
    container_assert_directory_metadata "$candidate"
}

container_assert_directory_metadata() {
    local candidate="$1"
    local item_type
    local item_uid
    local item_mode
    local current_uid

    current_uid="$(id -u)" || return $?
    IFS='|' read -r item_type item_uid item_mode < <(
        stat -c '%F|%u|%a' -- "$candidate"
    )
    if [[ "$item_type" != 'directory' || "$item_uid" != "$current_uid" \
        || ! "$item_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$item_mode & 8#022)) -ne 0 ]]; then
        container_fail "项目目录必须由当前用户拥有且不可由组/其他用户写：$candidate"
        return 1
    fi
}

container_validate_resource_boundaries() {
    container_assert_owned_path "$MINIOS_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_ENV_ROOT/container-storage" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_GRAPHROOT" \
        "$MINIOS_ENV_ROOT/container-storage/graphroot" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_RUNROOT" \
        "$MINIOS_ENV_ROOT/container-storage/runroot" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_FILE" \
        "$MINIOS_ENV_ROOT/state/container.env" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_STORAGE_ROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_GRAPHROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_RUNROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_STATE_DIR" || return $?
}

container_assert_state_metadata() {
    local file_type
    local file_uid
    local file_mode
    local directory_type
    local directory_uid
    local directory_mode
    local current_uid

    current_uid="$(id -u)" || return $?
    IFS='|' read -r directory_type directory_uid directory_mode < <(
        stat -c '%F|%u|%a' -- "$MINIOS_CONTAINER_STATE_DIR"
    )
    if [[ "$directory_type" != 'directory' || "$directory_uid" != "$current_uid" \
        || ! "$directory_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$directory_mode & 8#022)) -ne 0 ]]; then
        container_fail "container state 父目录 owner/type/mode 不安全"
        return 1
    fi
    IFS='|' read -r file_type file_uid file_mode < <(
        stat -c '%F|%u|%a' -- "$MINIOS_CONTAINER_STATE_FILE"
    )
    if [[ "$file_type" != 'regular file' || "$file_uid" != "$current_uid" \
        || ! "$file_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$file_mode & 8#022)) -ne 0 ]]; then
        container_fail "container state 必须是当前用户拥有且不可由组/其他用户写的普通文件"
        return 1
    fi
}

container_prepare_project_paths() {
    container_prepare_directory "$MINIOS_ENV_ROOT" "$MINIOS_ENV_ROOT" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_ENV_ROOT/container-storage" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_GRAPHROOT" \
        "$MINIOS_ENV_ROOT/container-storage/graphroot" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_RUNROOT" \
        "$MINIOS_ENV_ROOT/container-storage/runroot" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
}

container_try_podman() {
    local rootless
    command -v podman >/dev/null 2>&1 || return 1
    if [[ "$(id -u)" == '0' ]]; then
        minios_log 'INFO' '拒绝以 UID 0 使用 Podman；需要 rootless Podman'
        return 1
    fi
    if rootless="$(podman --root "$MINIOS_CONTAINER_GRAPHROOT" \
        --runroot "$MINIOS_CONTAINER_RUNROOT" info \
        --format '{{.Host.Security.Rootless}}' 2>/dev/null)"; then
        :
    else
        return $?
    fi
    if [[ "${rootless,,}" != 'true' ]]; then
        minios_log 'INFO' 'Podman 可执行但不是 rootless backend'
        return 1
    fi
    CONTAINER_BACKEND='podman'
    CONTAINER_COMMAND=(
        podman --root "$MINIOS_CONTAINER_GRAPHROOT"
        --runroot "$MINIOS_CONTAINER_RUNROOT"
    )
}

container_try_docker() {
    command -v docker >/dev/null 2>&1 || return 1
    docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || return $?
    CONTAINER_BACKEND='docker'
    CONTAINER_COMMAND=(docker)
}

container_select_backend() {
    local requested="${1:-${MINIOS_CONTAINER_BACKEND:-}}"
    case "$requested" in
        podman)
            if ! container_try_podman; then
                container_fail '指定的 rootless Podman backend 不可用或未启动'
                return 1
            fi
            ;;
        docker)
            if ! container_try_docker; then
                container_fail '指定的 Docker backend 不可用或未启动'
                return 1
            fi
            ;;
        '')
            if container_try_podman; then
                return 0
            fi
            minios_log 'INFO' 'rootless Podman backend 不可用，检查已有 Docker'
            if container_try_docker; then
                return 0
            fi
            container_fail '容器 backend 不可用：未找到可工作的 rootless Podman 或 Docker'
            return 1
            ;;
        *)
            container_fail "MINIOS_CONTAINER_BACKEND 只允许 podman 或 docker：$requested"
            return 1
            ;;
    esac
}

container_inspect_image() {
    local expected_id="${1:-}"
    local actual_id
    local actual_label
    local actual_names

    actual_id="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{.Id}}' "$MINIOS_CONTAINER_IMAGE")" || return $?
    actual_label="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format "{{ index .Config.Labels \"$MINIOS_CONTAINER_LABEL_KEY\" }}" \
        "$MINIOS_CONTAINER_IMAGE")" || return $?
    actual_names="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{join .RepoTags "\n"}}' "$MINIOS_CONTAINER_IMAGE")" || return $?

    if [[ -z "$actual_id" || "$actual_id" =~ [[:space:]] ]]; then
        container_fail "镜像 inspect 未返回单一 image ID：${actual_id:-missing}"
        return 1
    fi
    if [[ "$actual_label" != "$MINIOS_CONTAINER_LABEL_VALUE" ]]; then
        container_fail "镜像 OCI label 不属于项目：${actual_label:-missing}"
        return 1
    fi
    if ! grep -Fqx -- "$MINIOS_CONTAINER_IMAGE" <<<"$actual_names"; then
        container_fail "镜像名称不匹配：${actual_names:-missing}"
        return 1
    fi
    if [[ -n "$expected_id" && "$actual_id" != "$expected_id" ]]; then
        container_fail "live image ID 与记录不一致：actual=$actual_id expected=$expected_id"
        return 1
    fi
    printf '%s\n' "$actual_id"
}

STATE_CONTAINER_BACKEND=''
STATE_CONTAINER_NAME=''
STATE_CONTAINER_IMAGE=''
STATE_CONTAINER_LABEL=''
STATE_CONTAINER_IMAGE_ID=''
STATE_CONTAINER_BASE_DIGEST=''
STATE_CONTAINER_STORAGE_ROOT=''
STATE_CONTAINER_GRAPHROOT=''
STATE_CONTAINER_RUNROOT=''
STATE_CONTAINER_BUILDER=''
STATE_CONTAINER_SOURCE_VERSION=''

container_load_state() {
    local line
    local key
    local value
    local seen='|'

    container_assert_owned_path "$MINIOS_CONTAINER_STATE_FILE" \
        "$MINIOS_ENV_ROOT/state/container.env" || return $?
    if [[ ! -f "$MINIOS_CONTAINER_STATE_FILE" || -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
        container_fail "缺少普通 container state：$MINIOS_CONTAINER_STATE_FILE"
        return 1
    fi
    container_assert_state_metadata || return $?
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" != *=* || "$line" == *$'\r'* ]]; then
            container_fail 'container state 含非法行'
            return 1
        fi
        key="${line%%=*}"
        value="${line#*=}"
        if [[ "$seen" == *"|$key|"* ]]; then
            container_fail "container state 字段重复：$key"
            return 1
        fi
        seen+="$key|"
        case "$key" in
            MINIOS_CONTAINER_BACKEND) STATE_CONTAINER_BACKEND="$value" ;;
            MINIOS_CONTAINER_NAME) STATE_CONTAINER_NAME="$value" ;;
            MINIOS_CONTAINER_IMAGE) STATE_CONTAINER_IMAGE="$value" ;;
            MINIOS_CONTAINER_LABEL) STATE_CONTAINER_LABEL="$value" ;;
            MINIOS_CONTAINER_IMAGE_ID) STATE_CONTAINER_IMAGE_ID="$value" ;;
            MINIOS_CONTAINER_BASE_DIGEST) STATE_CONTAINER_BASE_DIGEST="$value" ;;
            MINIOS_CONTAINER_STORAGE_ROOT) STATE_CONTAINER_STORAGE_ROOT="$value" ;;
            MINIOS_CONTAINER_GRAPHROOT) STATE_CONTAINER_GRAPHROOT="$value" ;;
            MINIOS_CONTAINER_RUNROOT) STATE_CONTAINER_RUNROOT="$value" ;;
            MINIOS_CONTAINER_BUILDER) STATE_CONTAINER_BUILDER="$value" ;;
            MINIOS_CONTAINER_SOURCE_VERSION) STATE_CONTAINER_SOURCE_VERSION="$value" ;;
            *) container_fail "container state 含未知字段：$key"; return 1 ;;
        esac
    done <"$MINIOS_CONTAINER_STATE_FILE"

    local required
    for required in \
        STATE_CONTAINER_BACKEND STATE_CONTAINER_NAME STATE_CONTAINER_IMAGE \
        STATE_CONTAINER_LABEL STATE_CONTAINER_IMAGE_ID \
        STATE_CONTAINER_BASE_DIGEST STATE_CONTAINER_STORAGE_ROOT \
        STATE_CONTAINER_GRAPHROOT STATE_CONTAINER_RUNROOT \
        STATE_CONTAINER_BUILDER STATE_CONTAINER_SOURCE_VERSION; do
        if [[ -z "${!required}" ]]; then
            container_fail "container state 缺少字段：$required"
            return 1
        fi
    done
}

container_validate_loaded_state_boundaries() {
    if [[ "$STATE_CONTAINER_BACKEND" != 'podman' \
        && "$STATE_CONTAINER_BACKEND" != 'docker' ]]; then
        container_fail "container state backend 非法：$STATE_CONTAINER_BACKEND"
        return 1
    fi
    if [[ -n "${MINIOS_CONTAINER_BACKEND:-}" \
        && "$MINIOS_CONTAINER_BACKEND" != "$STATE_CONTAINER_BACKEND" ]]; then
        container_fail "请求 backend 与 container state 不一致"
        return 1
    fi
    if [[ "$STATE_CONTAINER_NAME" != "$MINIOS_CONTAINER_NAME" \
        || "$STATE_CONTAINER_BASE_DIGEST" != "$MINIOS_CONTAINER_BASE_DIGEST" \
        || "$STATE_CONTAINER_SOURCE_VERSION" != "$MINIOS_CONTAINER_SOURCE_VERSION" \
        || "$STATE_CONTAINER_BUILDER" != "$MINIOS_CONTAINER_BUILDER" ]]; then
        container_fail 'container state 固定标识不匹配'
        return 1
    fi
    container_assert_owned_path "$STATE_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_CONTAINER_STORAGE_ROOT" || return $?
    container_assert_owned_path "$STATE_CONTAINER_GRAPHROOT" \
        "$MINIOS_CONTAINER_GRAPHROOT" || return $?
    container_assert_owned_path "$STATE_CONTAINER_RUNROOT" \
        "$MINIOS_CONTAINER_RUNROOT" || return $?
}

container_verify_state_ownership() {
    local live_id
    live_id="$(container_inspect_image "$STATE_CONTAINER_IMAGE_ID")" || return $?
    if [[ "$STATE_CONTAINER_IMAGE" != "$MINIOS_CONTAINER_IMAGE" \
        || "$STATE_CONTAINER_LABEL" != "$MINIOS_CONTAINER_LABEL" ]]; then
        container_fail 'container state 的 image name 或 OCI label 不匹配'
        return 1
    fi
    [[ "$live_id" == "$STATE_CONTAINER_IMAGE_ID" ]]
}

container_write_state() {
    local backend="$1"
    local image_id="$2"
    local partial
    container_prepare_directory "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    if [[ -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
        container_fail 'container state 不能是 symlink'
        return 1
    fi
    partial="$(mktemp "$MINIOS_CONTAINER_STATE_DIR/container.env.partial.XXXXXX")" || return $?
    if ! printf '%s\n' \
        "MINIOS_CONTAINER_BACKEND=$backend" \
        "MINIOS_CONTAINER_NAME=$MINIOS_CONTAINER_NAME" \
        "MINIOS_CONTAINER_IMAGE=$MINIOS_CONTAINER_IMAGE" \
        "MINIOS_CONTAINER_LABEL=$MINIOS_CONTAINER_LABEL" \
        "MINIOS_CONTAINER_IMAGE_ID=$image_id" \
        "MINIOS_CONTAINER_BASE_DIGEST=$MINIOS_CONTAINER_BASE_DIGEST" \
        "MINIOS_CONTAINER_STORAGE_ROOT=$MINIOS_CONTAINER_STORAGE_ROOT" \
        "MINIOS_CONTAINER_GRAPHROOT=$MINIOS_CONTAINER_GRAPHROOT" \
        "MINIOS_CONTAINER_RUNROOT=$MINIOS_CONTAINER_RUNROOT" \
        "MINIOS_CONTAINER_BUILDER=$MINIOS_CONTAINER_BUILDER" \
        "MINIOS_CONTAINER_SOURCE_VERSION=$MINIOS_CONTAINER_SOURCE_VERSION" \
        >"$partial"; then
        rm -f -- "$partial"
        return 1
    fi
    chmod 0644 "$partial" || { rm -f -- "$partial"; return 1; }
    mv -f -- "$partial" "$MINIOS_CONTAINER_STATE_FILE" || {
        rm -f -- "$partial"
        return 1
    }
}
