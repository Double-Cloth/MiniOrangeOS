#!/usr/bin/env bash
set -euo pipefail

# 所有 Linux 入口共用的路径、锁文件和校验逻辑。
MINIOS_COMMON_SOURCE_DIRECTORY="${BASH_SOURCE[0]%/*}"
if [[ "$MINIOS_COMMON_SOURCE_DIRECTORY" == "${BASH_SOURCE[0]}" ]]; then
    MINIOS_COMMON_SOURCE_DIRECTORY="."
fi
readonly MINIOS_COMMON_SOURCE_DIRECTORY
if MINIOS_COMMON_DIR="$(cd -- "$MINIOS_COMMON_SOURCE_DIRECTORY" && pwd -P)"; then
    readonly MINIOS_COMMON_DIR
else
    common_status=$?
    printf 'minios level=FAIL message=无法定位公共脚本目录\n' >&2
    return "$common_status"
fi
if MINIOS_REPO_ROOT="$(realpath -m -- "$MINIOS_COMMON_DIR/../..")"; then
    readonly MINIOS_REPO_ROOT
else
    common_status=$?
    printf 'minios level=FAIL message=无法定位仓库根目录\n' >&2
    return "$common_status"
fi
readonly MINIOS_VERSIONS_FILE="$MINIOS_REPO_ROOT/environment/versions.env"
readonly MINIOS_FORBIDDEN_ENV_ROOTS=("/" "/usr" "/usr/local")
readonly MINIOS_REQUIRED_VERSION_KEYS=(
    MINIOS_TARGET
    MINIOS_WSL_DISTRO
    MINIOS_WSL_IMAGE_VERSION
    MINIOS_WSL_IMAGE_URL
    MINIOS_WSL_IMAGE_SHA256
    MINIOS_CONTAINER_IMAGE
    MINIOS_CONTAINER_LABEL
    MINIOS_CONTAINER_BASE_IMAGE
    MINIOS_CONTAINER_BASE_DIGEST
    MINIOS_BINUTILS_VERSION
    MINIOS_BINUTILS_URL
    MINIOS_BINUTILS_SHA256
    MINIOS_GCC_VERSION
    MINIOS_GCC_URL
    MINIOS_GCC_SHA256
)

minios_log() {
    local level="$1"
    shift
    printf 'minios level=%s message=%s\n' "$level" "$*" >&2
}

minios_die() {
    minios_log "FAIL" "$*"
    return 1
}

minios_canonicalize_path() {
    local path="$1"
    local canonical_path
    local status
    if [[ -z "$path" ]]; then
        minios_die "环境根不能为空"
        return 1
    fi
    if [[ "$path" != /* ]]; then
        minios_die "environment root 必须是绝对路径：$path"
        return 1
    fi
    if canonical_path="$(realpath -m -- "$path")"; then
        printf '%s\n' "$canonical_path"
    else
        status=$?
        minios_log "FAIL" "路径规范化失败：$path status=$status"
        return "$status"
    fi
}

minios_paths_overlap() {
    local first="$1"
    local second="$2"
    [[ "$first" == "$second" || "$first" == "$second/"* || "$second" == "$first/"* ]]
}

minios_assert_environment_root() {
    local requested_root="$1"
    local canonical_root
    local forbidden_root
    local canonical_home
    local status

    if canonical_root="$(minios_canonicalize_path "$requested_root")"; then
        :
    else
        status=$?
        return "$status"
    fi
    for forbidden_root in "${MINIOS_FORBIDDEN_ENV_ROOTS[@]}"; do
        if [[ "$canonical_root" == "$forbidden_root" ]]; then
            minios_die "拒绝危险 environment root：$canonical_root"
            return 1
        fi
    done

    if canonical_home="$(realpath -m -- "${HOME:?HOME 未设置}")"; then
        :
    else
        status=$?
        minios_log "FAIL" "用户主目录规范化失败：status=$status"
        return "$status"
    fi
    if [[ "$canonical_root" == "$canonical_home" ]]; then
        minios_die "拒绝把用户主目录用作 environment root：$canonical_root"
        return 1
    fi
    if minios_paths_overlap "$canonical_root" "$MINIOS_REPO_ROOT"; then
        minios_die "拒绝与仓库工作树重叠的 environment root：$canonical_root"
        return 1
    fi

    printf '%s\n' "$canonical_root"
}

minios_assert_path_within_environment_root() {
    local candidate="$1"
    local canonical_candidate
    local status

    if canonical_candidate="$(minios_canonicalize_path "$candidate")"; then
        :
    else
        status=$?
        return "$status"
    fi
    case "$canonical_candidate" in
        "$MINIOS_ENV_ROOT"|"$MINIOS_ENV_ROOT"/*)
            printf '%s\n' "$canonical_candidate"
            ;;
        *)
            minios_die "路径越过 environment root：$canonical_candidate"
            return 1
            ;;
    esac
}

minios_load_versions() {
    local key
    local status

    if [[ ! -f "$MINIOS_VERSIONS_FILE" ]]; then
        minios_die "缺少版本锁文件：$MINIOS_VERSIONS_FILE"
        return 1
    fi
    # shellcheck disable=SC1090
    if source "$MINIOS_VERSIONS_FILE"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法加载版本锁文件：$MINIOS_VERSIONS_FILE status=$status"
        return "$status"
    fi
    for key in "${MINIOS_REQUIRED_VERSION_KEYS[@]}"; do
        if [[ -z "${!key:-}" ]]; then
            minios_die "版本锁文件缺少字段：$key"
            return 1
        fi
    done
}

minios_sha256() {
    local path="$1"
    sha256sum -- "$path" | cut -d ' ' -f 1
}

minios_verify_sha256() {
    local path="$1"
    local expected="$2"
    local actual
    local status

    if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
        minios_die "无效的 SHA-256：$expected"
        return 1
    fi
    if [[ ! -f "$path" ]]; then
        minios_die "待校验文件不存在：$path"
        return 1
    fi
    if actual="$(minios_sha256 "$path")"; then
        :
    else
        status=$?
        minios_log "FAIL" "SHA-256 计算失败：path=$path status=$status"
        return "$status"
    fi
    if [[ "$actual" != "$expected" ]]; then
        minios_die "SHA-256 不匹配：path=$path expected=$expected actual=$actual"
        return 1
    fi
}

minios_download_verified() {
    local url="$1"
    local expected_sha256="$2"
    local requested_destination="$3"
    local destination
    local partial
    local status
    local cleanup_status

    if destination="$(minios_assert_path_within_environment_root "$requested_destination")"; then
        :
    else
        status=$?
        return "$status"
    fi
    partial="${destination}.partial"
    if minios_assert_path_within_environment_root "$partial" >/dev/null; then
        :
    else
        status=$?
        return "$status"
    fi
    if mkdir -p -- "${destination%/*}"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法创建下载目录：${destination%/*} status=$status"
        return "$status"
    fi

    if [[ -f "$destination" ]]; then
        if minios_verify_sha256 "$destination" "$expected_sha256"; then
            minios_log "INFO" "复用已校验下载：$destination"
            return 0
        else
            status=$?
            return "$status"
        fi
    fi

    if rm -f -- "$partial"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法清理下载临时文件：$partial status=$status"
        return "$status"
    fi
    minios_log "INFO" "下载固定来源：$url"
    if curl --fail --location --retry 3 --output "$partial" -- "$url"; then
        :
    else
        status=$?
        if rm -f -- "$partial"; then
            :
        else
            cleanup_status=$?
            minios_log "FAIL" "下载失败后无法清理临时文件：$partial status=$cleanup_status"
        fi
        minios_log "FAIL" "下载失败：$url status=$status"
        return "$status"
    fi
    if minios_verify_sha256 "$partial" "$expected_sha256"; then
        :
    else
        status=$?
        if rm -f -- "$partial"; then
            :
        else
            cleanup_status=$?
            minios_log "FAIL" "校验失败后无法清理临时文件：$partial status=$cleanup_status"
        fi
        return "$status"
    fi
    if mv -f -- "$partial" "$destination"; then
        :
    else
        status=$?
        if rm -f -- "$partial"; then
            :
        else
            cleanup_status=$?
            minios_log "FAIL" "移动失败后无法清理临时文件：$partial status=$cleanup_status"
        fi
        minios_log "FAIL" "无法原子移动下载文件：$destination status=$status"
        return "$status"
    fi
    minios_log "INFO" "下载校验完成：$destination"
}

if [[ ${MINIOS_ENV_ROOT+x} != "x" ]]; then
    MINIOS_ENV_ROOT="${HOME:?HOME 未设置}/.local/share/miniorangeos-dev"
fi
if canonical_environment_root="$(minios_assert_environment_root "$MINIOS_ENV_ROOT")"; then
    MINIOS_ENV_ROOT="$canonical_environment_root"
else
    common_status=$?
    return "$common_status"
fi
export MINIOS_ENV_ROOT
