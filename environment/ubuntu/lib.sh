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
readonly MINIOS_CONTAINER_TASK_LABEL_KEY="${MINIOS_CONTAINER_TASK_LABEL%%=*}"
readonly MINIOS_CONTAINER_TASK_LABEL_VALUE="${MINIOS_CONTAINER_TASK_LABEL#*=}"
readonly MINIOS_CONTAINER_INTENT_LABEL_KEY='org.miniorangeos.intent'
readonly MINIOS_CONTAINER_STORAGE_ROOT="$MINIOS_ENV_ROOT/container-storage"
readonly MINIOS_CONTAINER_GRAPHROOT="$MINIOS_CONTAINER_STORAGE_ROOT/graphroot"
readonly MINIOS_CONTAINER_RUNTIME_BASE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
readonly MINIOS_CONTAINER_RUNROOT="$MINIOS_CONTAINER_RUNTIME_BASE/miniorangeos-t01"
readonly MINIOS_CONTAINER_BUILDER_PREFIX='miniorangeos-dev-builder-'
readonly MINIOS_CONTAINER_PODMAN_BUILDER='podman-rootless'
readonly MINIOS_CONTAINER_STATE_DIR="$MINIOS_ENV_ROOT/state"
readonly MINIOS_CONTAINER_STATE_FILE="$MINIOS_CONTAINER_STATE_DIR/container.env"
readonly MINIOS_CONTAINER_LOCK_FILE="$MINIOS_CONTAINER_STATE_DIR/container.lock"
readonly MINIOS_CONTAINERFILE="$MINIOS_REPO_ROOT/environment/Containerfile"

CONTAINER_BACKEND=''
CONTAINER_LIVE_REF=''
CONTAINER_IMAGE_PRESENT=0
CONTAINER_IMAGE_ID=''
CONTAINER_BUILDER_PRESENT=0
declare -a CONTAINER_COMMAND=()

container_fail() {
    minios_die "$*"
}

container_normalize_image_id() {
    local value="$1"
    local digest
    case "$value" in
        sha256:*) digest="${value#sha256:}" ;;
        *) digest="$value" ;;
    esac
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        container_fail "镜像 image ID 必须是 lowercase 64-hex sha256：${value:-missing}"
        return 1
    fi
    printf 'sha256:%s\n' "$digest"
}

container_validate_intent() {
    local intent="$1"
    if [[ ! "$intent" =~ ^[0-9a-f]{32}$ ]]; then
        container_fail "container intent 必须是 lowercase 128-bit nonce：${intent:-missing}"
        return 1
    fi
}

container_generate_intent() {
    local intent
    intent="$(/usr/bin/od -An -N16 -tx1 /dev/urandom \
        | /usr/bin/tr -d ' \n')" || return $?
    container_validate_intent "$intent" || return $?
    printf '%s\n' "$intent"
}

container_expected_builder() {
    local backend="$1"
    local intent="$2"
    container_validate_intent "$intent" || return $?
    case "$backend" in
        podman) printf '%s\n' "$MINIOS_CONTAINER_PODMAN_BUILDER" ;;
        docker) printf '%s%s\n' "$MINIOS_CONTAINER_BUILDER_PREFIX" "$intent" ;;
        *) container_fail "无法为未知 backend 派生 builder：$backend"; return 1 ;;
    esac
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

container_assert_runtime_path() {
    local candidate="$1"
    local expected="$2"

    container_assert_lexical_path "$MINIOS_CONTAINER_RUNTIME_BASE" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_RUNTIME_BASE" || return $?
    container_assert_lexical_path "$candidate" || return $?
    if [[ "$candidate" != "$expected" \
        || "$candidate" != "$MINIOS_CONTAINER_RUNTIME_BASE/"* ]]; then
        container_fail "容器 runtime 路径与固定边界不一致：actual=$candidate expected=$expected"
        return 1
    fi
}

container_prepare_runtime_directory() {
    local candidate="$1"
    local expected="$2"
    container_assert_runtime_path "$candidate" "$expected" || return $?
    mkdir -p -- "$candidate" || return $?
    container_assert_runtime_path "$candidate" "$expected" || return $?
    container_assert_directory_metadata "$candidate"
}

container_assert_optional_runtime_directory() {
    local candidate="$1"
    local expected="$2"
    container_assert_runtime_path "$candidate" "$expected" || return $?
    if [[ -e "$candidate" || -L "$candidate" ]]; then
        container_assert_directory_metadata "$candidate" || return $?
    fi
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
    container_assert_runtime_path "$MINIOS_CONTAINER_RUNROOT" \
        "$MINIOS_CONTAINER_RUNTIME_BASE/miniorangeos-t01" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_FILE" \
        "$MINIOS_ENV_ROOT/state/container.env" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_STORAGE_ROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_GRAPHROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_RUNROOT" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_STATE_DIR" || return $?
}

container_assert_optional_directory() {
    local candidate="$1"
    local expected="$2"
    container_assert_owned_path "$candidate" "$expected" || return $?
    if [[ -e "$candidate" || -L "$candidate" ]]; then
        container_assert_directory_metadata "$candidate" || return $?
    fi
}

container_validate_partial_storage_boundaries() {
    container_assert_optional_directory "$MINIOS_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_ENV_ROOT/container-storage" || return $?
    container_assert_optional_directory "$MINIOS_CONTAINER_GRAPHROOT" \
        "$MINIOS_ENV_ROOT/container-storage/graphroot" || return $?
    container_assert_optional_runtime_directory "$MINIOS_CONTAINER_RUNROOT" \
        "$MINIOS_CONTAINER_RUNTIME_BASE/miniorangeos-t01" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_STATE_FILE" \
        "$MINIOS_ENV_ROOT/state/container.env" || return $?
    container_assert_directory_metadata "$MINIOS_CONTAINER_STATE_DIR"
}

container_remove_storage_components() {
    local candidate
    for candidate in \
        "$MINIOS_CONTAINER_GRAPHROOT" \
        "$MINIOS_CONTAINER_STORAGE_ROOT"; do
        if [[ -e "$candidate" || -L "$candidate" ]]; then
            rm -rf -- "$candidate" || return $?
        fi
    done
    if [[ -e "$MINIOS_CONTAINER_RUNROOT" || -L "$MINIOS_CONTAINER_RUNROOT" ]]; then
        container_assert_runtime_path "$MINIOS_CONTAINER_RUNROOT" \
            "$MINIOS_CONTAINER_RUNTIME_BASE/miniorangeos-t01" || return $?
        rm -rf -- "$MINIOS_CONTAINER_RUNROOT" || return $?
    fi
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

container_assert_lock_metadata() {
    local file_type
    local file_uid
    local file_mode
    local current_uid

    current_uid="$(id -u)" || return $?
    IFS='|' read -r file_type file_uid file_mode < <(
        stat -c '%F|%u|%a' -- "$MINIOS_CONTAINER_LOCK_FILE"
    )
    if [[ "$file_type" != 'regular file' \
        && "$file_type" != 'regular empty file' ]]; then
        container_fail 'container lifecycle lock 必须是普通文件'
        return 1
    fi
    if [[ "$file_uid" != "$current_uid" \
        || "$file_mode" != '600' ]]; then
        container_fail 'container lifecycle lock 必须是当前用户拥有、mode 0600 的普通文件'
        return 1
    fi
}

container_assert_parent_lifecycle_lock() {
    local expected_flock
    local parent_executable
    local descriptor
    local descriptor_target
    local lock_fd_present=0
    local status

    expected_flock="$(readlink -e -- "$(command -v flock)")" || return $?
    parent_executable="$(readlink -e -- "/proc/$PPID/exe")" || return $?
    if [[ "$parent_executable" != "$expected_flock" ]]; then
        container_fail '拒绝未由可信 flock 父进程持锁的 lifecycle 重入'
        return 1
    fi
    for descriptor in "/proc/$PPID/fd/"*; do
        descriptor_target="$(readlink -e -- "$descriptor" 2>/dev/null || true)"
        if [[ "$descriptor_target" == "$MINIOS_CONTAINER_LOCK_FILE" ]]; then
            lock_fd_present=1
            break
        fi
    done
    if ((lock_fd_present == 0)); then
        container_fail 'flock 父进程未持有精确 lifecycle lock 文件'
        return 1
    fi
    if flock --exclusive --nonblock "$MINIOS_CONTAINER_LOCK_FILE" \
        /usr/bin/true 2>/dev/null; then
        container_fail 'lifecycle 重入时预期锁未被持有'
        return 1
    else
        status=$?
        if ((status != 1)); then
            container_fail "验证 lifecycle lock 持有状态失败：status=$status"
            return "$status"
        fi
    fi
}

container_acquire_lifecycle_lock() {
    local lifecycle_script="${1:-}"

    container_prepare_directory "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    container_assert_owned_path "$MINIOS_CONTAINER_LOCK_FILE" \
        "$MINIOS_ENV_ROOT/state/container.lock" || return $?
    if [[ -L "$MINIOS_CONTAINER_LOCK_FILE" ]]; then
        container_fail 'container lifecycle lock 不能是 symlink'
        return 1
    fi
    if [[ ! -e "$MINIOS_CONTAINER_LOCK_FILE" ]]; then
        if ! (umask 077; set -o noclobber; : >"$MINIOS_CONTAINER_LOCK_FILE") \
            2>/dev/null; then
            if [[ ! -e "$MINIOS_CONTAINER_LOCK_FILE" \
                || -L "$MINIOS_CONTAINER_LOCK_FILE" ]]; then
                container_fail '无法安全创建 container lifecycle lock'
                return 1
            fi
        fi
    fi
    container_assert_lock_metadata || return $?

    # flock、lifecycle Bash 与同步 backend 进程树继承同一锁 open-file-description。
    # 任一祖先进程遭 SIGKILL 时，只要同步后代仍运行，锁就继续阻止并发 lifecycle；
    # 全部同步后代退出后由内核自动释放。create/run/destroy 禁止后台启动 backend。
    if [[ "${MINIOS_CONTAINER_LIFECYCLE_LOCKED:-0}" == '1' ]]; then
        container_assert_parent_lifecycle_lock
        return $?
    fi
    if [[ -z "$lifecycle_script" ]]; then
        container_fail 'container lifecycle lock 缺少重入脚本路径'
        return 2
    fi
    lifecycle_script="$(realpath -e -- "$lifecycle_script")" || return $?
    exec flock --exclusive --nonblock --verbose \
        "$MINIOS_CONTAINER_LOCK_FILE" \
        /usr/bin/env MINIOS_CONTAINER_LIFECYCLE_LOCKED=1 \
        /usr/bin/bash "$lifecycle_script" "${@:2}"
}

container_release_lifecycle_lock() {
    # flock 与同步后代共享锁；整棵同步进程树退出时由内核自动释放。
    return 0
}

container_prepare_project_paths() {
    container_prepare_directory "$MINIOS_ENV_ROOT" "$MINIOS_ENV_ROOT" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_ENV_ROOT/container-storage" || return $?
    container_prepare_directory "$MINIOS_CONTAINER_GRAPHROOT" \
        "$MINIOS_ENV_ROOT/container-storage/graphroot" || return $?
    container_prepare_runtime_directory "$MINIOS_CONTAINER_RUNROOT" \
        "$MINIOS_CONTAINER_RUNTIME_BASE/miniorangeos-t01" || return $?
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
    # backend 能力探测不得先于 creating intent 初始化项目 storage。
    if rootless="$(podman info \
        --format '{{.Host.Security.Rootless}}' 2>/dev/null)"; then
        :
    else
        return $?
    fi
    if [[ "${rootless,,}" != 'true' ]]; then
        minios_log 'INFO' 'Podman 可执行但不是 rootless backend'
        return 1
    fi
    if ((${#MINIOS_CONTAINER_RUNROOT} > 50)); then
        container_fail "Podman runroot 超过 50 字符：$MINIOS_CONTAINER_RUNROOT"
        return 1
    fi
    CONTAINER_BACKEND='podman'
    CONTAINER_LIVE_REF="localhost/$MINIOS_CONTAINER_IMAGE"
    CONTAINER_COMMAND=(
        podman --root "$MINIOS_CONTAINER_GRAPHROOT"
        --runroot "$MINIOS_CONTAINER_RUNROOT"
    )
}

container_try_docker() {
    command -v docker >/dev/null 2>&1 || return 1
    docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || return $?
    CONTAINER_BACKEND='docker'
    CONTAINER_LIVE_REF="$MINIOS_CONTAINER_IMAGE"
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

container_expected_live_ref() {
    local backend="$1"
    case "$backend" in
        podman) printf 'localhost/%s\n' "$MINIOS_CONTAINER_IMAGE" ;;
        docker) printf '%s\n' "$MINIOS_CONTAINER_IMAGE" ;;
        *) container_fail "无法为未知 backend 生成 live ref：$backend"; return 1 ;;
    esac
}

container_inspect_image() {
    local live_ref="$1"
    local expected_intent="$2"
    local expected_id="${3:-}"
    local actual_id
    local actual_label
    local actual_task_label
    local actual_intent_label
    local actual_names
    local normalized_expected=''

    actual_id="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{.Id}}' "$live_ref")" || return $?
    actual_id="$(container_normalize_image_id "$actual_id")" || return $?
    actual_label="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format "{{ index .Config.Labels \"$MINIOS_CONTAINER_LABEL_KEY\" }}" \
        "$live_ref")" || return $?
    actual_task_label="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format "{{ index .Config.Labels \"$MINIOS_CONTAINER_TASK_LABEL_KEY\" }}" \
        "$live_ref")" || return $?
    actual_intent_label="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format "{{ index .Config.Labels \"$MINIOS_CONTAINER_INTENT_LABEL_KEY\" }}" \
        "$live_ref")" || return $?
    actual_names="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{join .RepoTags "\n"}}' "$live_ref")" || return $?

    if [[ "$actual_label" != "$MINIOS_CONTAINER_LABEL_VALUE" ]]; then
        container_fail "镜像 OCI label 不属于项目：${actual_label:-missing}"
        return 1
    fi
    if [[ "$actual_task_label" != "$MINIOS_CONTAINER_TASK_LABEL_VALUE" ]]; then
        container_fail "镜像 task label 不属于当前任务：${actual_task_label:-missing}"
        return 1
    fi
    container_validate_intent "$expected_intent" || return $?
    if [[ "$actual_intent_label" != "$expected_intent" ]]; then
        container_fail "镜像 intent label 与 state nonce 不一致：actual=${actual_intent_label:-missing}"
        return 1
    fi
    if ! grep -Fqx -- "$live_ref" <<<"$actual_names"; then
        container_fail "镜像名称不匹配：${actual_names:-missing}"
        return 1
    fi
    if [[ -n "$expected_id" ]]; then
        normalized_expected="$(container_normalize_image_id "$expected_id")" \
            || return $?
        if [[ "$actual_id" != "$normalized_expected" ]]; then
            container_fail "live image ID 与记录不一致：actual=$actual_id expected=$normalized_expected"
            return 1
        fi
    fi
    printf '%s\n' "$actual_id"
}

container_probe_image() {
    local live_ref="$1"
    local status
    local image_ids
    CONTAINER_IMAGE_PRESENT=0
    CONTAINER_IMAGE_ID=''
    if [[ "$CONTAINER_BACKEND" == 'podman' ]]; then
        if "${CONTAINER_COMMAND[@]}" image exists "$live_ref"; then
            CONTAINER_IMAGE_PRESENT=1
        else
            status=$?
            if ((status == 1)); then
                return 0
            fi
            container_fail "Podman image exists 探测失败：status=$status"
            return "$status"
        fi
    else
        if image_ids="$(docker image ls --quiet --no-trunc "$live_ref")"; then
            :
        else
            status=$?
            container_fail "Docker image ls 探测失败：status=$status"
            return "$status"
        fi
        if [[ -z "$image_ids" ]]; then
            return 0
        fi
        CONTAINER_IMAGE_PRESENT=1
        CONTAINER_IMAGE_ID="$(container_normalize_image_id "$image_ids")" \
            || return $?
        return 0
    fi
    CONTAINER_IMAGE_ID="$("${CONTAINER_COMMAND[@]}" image inspect \
        --format '{{.Id}}' "$live_ref")" || return $?
    CONTAINER_IMAGE_ID="$(container_normalize_image_id "$CONTAINER_IMAGE_ID")" \
        || return $?
}

container_probe_docker_builder() {
    local builder="$1"
    local names
    local matches
    local status
    if [[ ! "$builder" =~ ^miniorangeos-dev-builder-[0-9a-f]{32}$ ]]; then
        container_fail "Docker builder 名称不符合 nonce 派生规则：$builder"
        return 1
    fi
    CONTAINER_BUILDER_PRESENT=0
    if names="$(docker buildx ls --format '{{.Name}}')"; then
        :
    else
        status=$?
        container_fail "Docker Buildx builder 探测失败：status=$status"
        return "$status"
    fi
    matches="$(grep -Fxc -- "$builder" <<<"$names" || true)"
    if [[ "$matches" == '0' ]]; then
        return 0
    fi
    if [[ "$matches" != '1' ]]; then
        container_fail "nonce 派生 Buildx builder 名称出现多次：$builder"
        return 1
    fi
    docker buildx inspect "$builder" >/dev/null || {
        status=$?
        container_fail "Docker Buildx builder inspect 失败：builder=$builder status=$status"
        return "$status"
    }
    CONTAINER_BUILDER_PRESENT=1
}

STATE_CONTAINER_PHASE=''
STATE_CONTAINER_BACKEND=''
STATE_CONTAINER_NAME=''
STATE_CONTAINER_IMAGE=''
STATE_CONTAINER_LIVE_REF=''
STATE_CONTAINER_LABEL=''
STATE_CONTAINER_INTENT=''
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

    STATE_CONTAINER_PHASE=''
    STATE_CONTAINER_BACKEND=''
    STATE_CONTAINER_NAME=''
    STATE_CONTAINER_IMAGE=''
    STATE_CONTAINER_LIVE_REF=''
    STATE_CONTAINER_LABEL=''
    STATE_CONTAINER_INTENT=''
    STATE_CONTAINER_IMAGE_ID=''
    STATE_CONTAINER_BASE_DIGEST=''
    STATE_CONTAINER_STORAGE_ROOT=''
    STATE_CONTAINER_GRAPHROOT=''
    STATE_CONTAINER_RUNROOT=''
    STATE_CONTAINER_BUILDER=''
    STATE_CONTAINER_SOURCE_VERSION=''

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
            MINIOS_CONTAINER_PHASE) STATE_CONTAINER_PHASE="$value" ;;
            MINIOS_CONTAINER_BACKEND) STATE_CONTAINER_BACKEND="$value" ;;
            MINIOS_CONTAINER_NAME) STATE_CONTAINER_NAME="$value" ;;
            MINIOS_CONTAINER_IMAGE) STATE_CONTAINER_IMAGE="$value" ;;
            MINIOS_CONTAINER_LIVE_REF) STATE_CONTAINER_LIVE_REF="$value" ;;
            MINIOS_CONTAINER_LABEL) STATE_CONTAINER_LABEL="$value" ;;
            MINIOS_CONTAINER_INTENT) STATE_CONTAINER_INTENT="$value" ;;
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
        STATE_CONTAINER_PHASE STATE_CONTAINER_BACKEND STATE_CONTAINER_NAME \
        STATE_CONTAINER_IMAGE STATE_CONTAINER_LIVE_REF \
        STATE_CONTAINER_LABEL STATE_CONTAINER_INTENT STATE_CONTAINER_IMAGE_ID \
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
    local expected_live_ref
    local expected_builder
    local normalized_image_id
    if [[ "$STATE_CONTAINER_PHASE" != 'creating' \
        && "$STATE_CONTAINER_PHASE" != 'ready' \
        && "$STATE_CONTAINER_PHASE" != 'destroying' ]]; then
        container_fail "container state phase 非法：$STATE_CONTAINER_PHASE"
        return 1
    fi
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
        || "$STATE_CONTAINER_IMAGE" != "$MINIOS_CONTAINER_IMAGE" \
        || "$STATE_CONTAINER_LABEL" != "$MINIOS_CONTAINER_LABEL" \
        || "$STATE_CONTAINER_BASE_DIGEST" != "$MINIOS_CONTAINER_BASE_DIGEST" \
        || "$STATE_CONTAINER_SOURCE_VERSION" != "$MINIOS_CONTAINER_SOURCE_VERSION" ]]; then
        container_fail 'container state 固定标识不匹配'
        return 1
    fi
    container_validate_intent "$STATE_CONTAINER_INTENT" || return $?
    expected_builder="$(container_expected_builder \
        "$STATE_CONTAINER_BACKEND" "$STATE_CONTAINER_INTENT")" || return $?
    if [[ "$STATE_CONTAINER_BUILDER" != "$expected_builder" ]]; then
        container_fail "container builder 不是 state intent 的精确派生值：actual=$STATE_CONTAINER_BUILDER expected=$expected_builder"
        return 1
    fi
    if [[ "$STATE_CONTAINER_PHASE" == 'creating' \
        && "$STATE_CONTAINER_IMAGE_ID" == 'pending' ]]; then
        :
    else
        if [[ "$STATE_CONTAINER_IMAGE_ID" == 'pending' ]]; then
            container_fail "pending image ID 只允许 creating phase"
            return 1
        fi
        normalized_image_id="$(container_normalize_image_id \
            "$STATE_CONTAINER_IMAGE_ID")" || return $?
        if [[ "$STATE_CONTAINER_IMAGE_ID" != "$normalized_image_id" ]]; then
            container_fail 'container state image ID 必须使用 canonical sha256 前缀'
            return 1
        fi
        STATE_CONTAINER_IMAGE_ID="$normalized_image_id"
    fi
    expected_live_ref="$(container_expected_live_ref "$STATE_CONTAINER_BACKEND")" || return $?
    if [[ "$STATE_CONTAINER_LIVE_REF" != "$expected_live_ref" ]]; then
        container_fail "container live ref 不是 backend canonical 值：actual=$STATE_CONTAINER_LIVE_REF expected=$expected_live_ref"
        return 1
    fi
    container_assert_owned_path "$STATE_CONTAINER_STORAGE_ROOT" \
        "$MINIOS_CONTAINER_STORAGE_ROOT" || return $?
    container_assert_owned_path "$STATE_CONTAINER_GRAPHROOT" \
        "$MINIOS_CONTAINER_GRAPHROOT" || return $?
    container_assert_runtime_path "$STATE_CONTAINER_RUNROOT" \
        "$MINIOS_CONTAINER_RUNROOT" || return $?
}

container_verify_state_ownership() {
    local live_id
    live_id="$(container_inspect_image \
        "$STATE_CONTAINER_LIVE_REF" "$STATE_CONTAINER_INTENT" \
        "$STATE_CONTAINER_IMAGE_ID")" || return $?
    if [[ "$STATE_CONTAINER_IMAGE" != "$MINIOS_CONTAINER_IMAGE" \
        || "$STATE_CONTAINER_LABEL" != "$MINIOS_CONTAINER_LABEL" ]]; then
        container_fail 'container state 的 image name 或 OCI label 不匹配'
        return 1
    fi
    [[ "$live_id" == "$STATE_CONTAINER_IMAGE_ID" ]]
}

container_write_state() {
    local phase="$1"
    local backend="$2"
    local live_ref="$3"
    local image_id="$4"
    local intent="$5"
    local builder="$6"
    local partial
    local expected_builder
    container_validate_intent "$intent" || return $?
    expected_builder="$(container_expected_builder "$backend" "$intent")" \
        || return $?
    if [[ "$builder" != "$expected_builder" ]]; then
        container_fail "拒绝写入非 intent 派生 builder：actual=$builder expected=$expected_builder"
        return 1
    fi
    case "$phase" in
        creating)
            if [[ "$image_id" != 'pending' ]]; then
                image_id="$(container_normalize_image_id "$image_id")" \
                    || return $?
            fi
            ;;
        ready|destroying)
            if [[ "$image_id" == 'pending' ]]; then
                container_fail "pending image ID 不能写入 $phase phase"
                return 1
            fi
            image_id="$(container_normalize_image_id "$image_id")" \
                || return $?
            ;;
        *)
            container_fail "拒绝写入未知 container phase：$phase"
            return 1
            ;;
    esac
    container_prepare_directory "$MINIOS_CONTAINER_STATE_DIR" \
        "$MINIOS_ENV_ROOT/state" || return $?
    if [[ -L "$MINIOS_CONTAINER_STATE_FILE" ]]; then
        container_fail 'container state 不能是 symlink'
        return 1
    fi
    partial="$(mktemp "$MINIOS_CONTAINER_STATE_DIR/container.env.partial.XXXXXX")" || return $?
    if ! printf '%s\n' \
        "MINIOS_CONTAINER_PHASE=$phase" \
        "MINIOS_CONTAINER_BACKEND=$backend" \
        "MINIOS_CONTAINER_NAME=$MINIOS_CONTAINER_NAME" \
        "MINIOS_CONTAINER_IMAGE=$MINIOS_CONTAINER_IMAGE" \
        "MINIOS_CONTAINER_LIVE_REF=$live_ref" \
        "MINIOS_CONTAINER_LABEL=$MINIOS_CONTAINER_LABEL" \
        "MINIOS_CONTAINER_INTENT=$intent" \
        "MINIOS_CONTAINER_IMAGE_ID=$image_id" \
        "MINIOS_CONTAINER_BASE_DIGEST=$MINIOS_CONTAINER_BASE_DIGEST" \
        "MINIOS_CONTAINER_STORAGE_ROOT=$MINIOS_CONTAINER_STORAGE_ROOT" \
        "MINIOS_CONTAINER_GRAPHROOT=$MINIOS_CONTAINER_GRAPHROOT" \
        "MINIOS_CONTAINER_RUNROOT=$MINIOS_CONTAINER_RUNROOT" \
        "MINIOS_CONTAINER_BUILDER=$builder" \
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

container_transition_phase() {
    local phase="$1"
    container_write_state "$phase" "$STATE_CONTAINER_BACKEND" \
        "$STATE_CONTAINER_LIVE_REF" "$STATE_CONTAINER_IMAGE_ID" \
        "$STATE_CONTAINER_INTENT" "$STATE_CONTAINER_BUILDER" || return $?
    STATE_CONTAINER_PHASE="$phase"
}

container_require_ready_phase() {
    if [[ "$STATE_CONTAINER_PHASE" != 'ready' ]]; then
        container_fail "container state phase 必须为 ready，实际 $STATE_CONTAINER_PHASE"
        return 1
    fi
}

container_remove_state_partials() {
    local partial
    for partial in \
        "$MINIOS_CONTAINER_STATE_DIR"/container.iid.partial.* \
        "$MINIOS_CONTAINER_STATE_DIR"/container.env.partial.*; do
        if [[ -e "$partial" || -L "$partial" ]]; then
            container_assert_lexical_path "$partial" || return $?
            case "$partial" in
                "$MINIOS_CONTAINER_STATE_DIR"/container.iid.partial.*|\
                "$MINIOS_CONTAINER_STATE_DIR"/container.env.partial.*) ;;
                *) container_fail "拒绝清理越界 state partial：$partial"; return 1 ;;
            esac
            rm -f -- "$partial" || return $?
        fi
    done
}

container_recover_creating_state() {
    local image_present=0
    local builder_present=0

    if [[ "$STATE_CONTAINER_PHASE" != 'creating' ]]; then
        container_fail "creating recovery 收到错误 phase：$STATE_CONTAINER_PHASE"
        return 1
    fi
    container_validate_partial_storage_boundaries || return $?
    container_select_backend "$STATE_CONTAINER_BACKEND" || return $?
    container_probe_image "$STATE_CONTAINER_LIVE_REF" || return $?
    if ((CONTAINER_IMAGE_PRESENT == 1)); then
        if [[ "$STATE_CONTAINER_IMAGE_ID" == 'pending' ]]; then
            container_inspect_image "$STATE_CONTAINER_LIVE_REF" \
                "$STATE_CONTAINER_INTENT" >/dev/null || return $?
        else
            container_inspect_image "$STATE_CONTAINER_LIVE_REF" \
                "$STATE_CONTAINER_INTENT" "$STATE_CONTAINER_IMAGE_ID" \
                >/dev/null || return $?
        fi
        image_present=1
    fi
    if [[ "$STATE_CONTAINER_BACKEND" == 'docker' ]]; then
        container_probe_docker_builder "$STATE_CONTAINER_BUILDER" || return $?
        if ((CONTAINER_BUILDER_PRESENT == 1)); then
            builder_present=1
        fi
    fi

    # backend 探测可能触碰路径；任何删除前重新验证每个仍存在的固定目录。
    container_validate_partial_storage_boundaries || return $?
    if ((image_present == 1)); then
        "${CONTAINER_COMMAND[@]}" image rmi "$STATE_CONTAINER_LIVE_REF" \
            || return $?
    fi
    if ((builder_present == 1)); then
        docker buildx rm --force "$STATE_CONTAINER_BUILDER" || return $?
    fi
    container_remove_storage_components || return $?
    container_remove_state_partials || return $?
    rm -f -- "$MINIOS_CONTAINER_STATE_FILE" || return $?
    minios_log 'INFO' '已恢复并清理未完成的 creating intent'
}
