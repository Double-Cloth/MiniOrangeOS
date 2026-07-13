#!/usr/bin/env bash
set -euo pipefail

if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" != '1' ]]; then
    PATH='/usr/sbin:/usr/bin:/sbin:/bin'
    export PATH
fi

# 专用 WSL/容器内部的两阶段 bootstrap；root 不在目标用户路径中写文件。
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(realpath -m -- "$SCRIPT_DIR/..")"
readonly PRODUCTION_OS_RELEASE_FILE='/etc/os-release'
readonly PRODUCTION_WSL_CONF_FILE='/etc/wsl.conf'
readonly SAFE_WSL_NAME_PATTERN='^MiniOrangeOS-Dev(-Test-[A-Za-z0-9][A-Za-z0-9_-]*)?$'
readonly -a APPROVED_PACKAGES=(
    build-essential bison flex libgmp-dev libmpfr-dev libmpc-dev texinfo
    nasm qemu-system-x86 qemu-utils gdb python3 python3-venv
    ca-certificates curl xz-utils sudo
)

mode='all'
target_user="${MINIOS_TARGET_USER:-minios}"
environment_kind=''
target_uid=''
target_home=''
environment_root=''
wsl_conf_file=''
package_lock_partial=''

usage() {
    printf '用法：%s [--system-only|--toolchain-only] [--target-user USER]\n' "${0##*/}" >&2
}

fail() {
    printf 'minios level=FAIL message=%s\n' "$*" >&2
    return 1
}

cleanup_package_lock_partial() {
    if [[ -n "$package_lock_partial" ]]; then
        rm -f -- "$package_lock_partial"
    fi
}
trap cleanup_package_lock_partial EXIT

while (($# > 0)); do
    case "$1" in
        --system-only|--toolchain-only|--write-package-lock)
            if [[ "$mode" != 'all' ]]; then
                fail "重复或冲突的阶段参数：$1"
                exit 2
            fi
            mode="${1#--}"
            ;;
        --target-user)
            shift
            if (($# == 0)); then usage; exit 2; fi
            target_user="$1"
            ;;
        *)
            fail "未知参数：$1"
            usage
            exit 2
            ;;
    esac
    shift
done

is_test_path() {
    local path="$1"
    [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' \
        && "$path" == /tmp/minios-bootstrap-test-* ]]
}

select_test_or_production_file() {
    local override="$1"
    local production="$2"
    local canonical_override
    if [[ -z "$override" ]]; then
        printf '%s\n' "$production"
        return
    fi
    canonical_override="$(realpath -m -- "$override")" || return $?
    if [[ "$override" != "$canonical_override" ]] || ! is_test_path "$canonical_override"; then
        fail "拒绝非测试临时路径覆盖：$override"
        return 1
    fi
    printf '%s\n' "$canonical_override"
}

read_os_value() {
    local file="$1"
    local key="$2"
    local line
    line="$(grep -E "^${key}=" "$file" | tail -n 1)" || return 1
    line="${line#*=}"
    line="${line%\"}"
    line="${line#\"}"
    printf '%s\n' "$line"
}

lstat_path() {
    local path="$1"
    stat -c '%F|%u' -- "$path"
}

assert_no_symlink_components() {
    local candidate="$1"
    local current='/'
    local relative="${candidate#/}"
    local component
    IFS='/' read -r -a components <<<"$relative"
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current="${current%/}/$component"
        if [[ -L "$current" ]]; then
            fail "路径组件是 symlink：$current"
            return 1
        fi
    done
}

validate_ubuntu_release() {
    local os_release_file
    local os_id
    local version_id
    os_release_file="$(select_test_or_production_file \
        "${MINIOS_OS_RELEASE_FILE:-}" "$PRODUCTION_OS_RELEASE_FILE")" || return $?
    if [[ ! -f "$os_release_file" || -L "$os_release_file" ]]; then
        fail "缺少可信 os-release：$os_release_file"
        return 1
    fi
    os_id="$(read_os_value "$os_release_file" ID)" || {
        fail 'os-release 缺少 ID'
        return 1
    }
    version_id="$(read_os_value "$os_release_file" VERSION_ID)" || {
        fail 'os-release 缺少 VERSION_ID'
        return 1
    }
    if [[ "$os_id" != 'ubuntu' || "$version_id" != '24.04' ]]; then
        fail "只允许 Ubuntu 24.04：ID=$os_id VERSION_ID=$version_id"
        return 1
    fi
}

validate_isolation_identity() {
    if [[ "${MINIOS_CONTAINER:-}" == '1' ]]; then
        environment_kind='container'
        return
    fi
    if [[ -n "${MINIOS_CONTAINER:-}" ]]; then
        fail "MINIOS_CONTAINER 只能是 1"
        return 1
    fi
    if [[ -z "${WSL_DISTRO_NAME:-}" \
        || ! "${WSL_DISTRO_NAME}" =~ $SAFE_WSL_NAME_PATTERN ]]; then
        fail "只允许项目 WSL 发行版或 MINIOS_CONTAINER=1：${WSL_DISTRO_NAME:-missing}"
        return 1
    fi
    environment_kind='wsl'
}

resolve_target_user() {
    local passwd_entry
    local passwd_name
    local passwd_uid
    local passwd_gid
    local passwd_gecos
    local passwd_home
    local passwd_shell
    local actual_uid

    if [[ ! "$target_user" =~ ^[a-z_][a-z0-9_-]*$ || "$target_user" == 'root' ]]; then
        fail "拒绝无效或特权目标用户：$target_user"
        return 1
    fi
    passwd_entry="$(getent passwd "$target_user")" || {
        fail "目标用户不存在：$target_user"
        return 1
    }
    if [[ "$passwd_entry" == *$'\n'* ]]; then
        fail "目标用户解析结果不唯一：$target_user"
        return 1
    fi
    IFS=':' read -r passwd_name _ passwd_uid passwd_gid passwd_gecos passwd_home passwd_shell <<<"$passwd_entry"
    if [[ "$passwd_name" != "$target_user" || ! "$passwd_uid" =~ ^[0-9]+$ \
        || "$passwd_uid" == '0' ]]; then
        fail "目标用户必须是非 UID0 普通用户：$target_user uid=${passwd_uid:-missing}"
        return 1
    fi
    actual_uid="$(id -u "$target_user")" || {
        fail "无法解析目标用户 UID：$target_user"
        return 1
    }
    if [[ "$actual_uid" != "$passwd_uid" ]]; then
        fail "目标用户 UID 来源不一致：getent=$passwd_uid id=$actual_uid"
        return 1
    fi
    if [[ "$passwd_home" != /* || ! -d "$passwd_home" || -L "$passwd_home" ]]; then
        fail "目标用户 home 必须是现有普通目录：$passwd_home"
        return 1
    fi
    assert_no_symlink_components "$passwd_home" || return $?
    local home_stat
    home_stat="$(lstat_path "$passwd_home")" || return $?
    if [[ "$home_stat" != "directory|$passwd_uid" ]]; then
        fail "目标用户 home owner/type 不匹配：$passwd_home $home_stat"
        return 1
    fi
    target_uid="$passwd_uid"
    target_home="$(realpath -e -- "$passwd_home")"
}

validate_user_owned_existing_components() {
    local base="$1"
    local candidate="$2"
    local current="$base"
    local relative="${candidate#"$base"}"
    local component
    local item_stat
    relative="${relative#/}"
    IFS='/' read -r -a components <<<"$relative"
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current="$current/$component"
        if [[ -e "$current" || -L "$current" ]]; then
            if [[ -L "$current" ]]; then
                fail "用户路径组件是 symlink：$current"
                return 1
            fi
            item_stat="$(lstat_path "$current")" || return $?
            if [[ "$item_stat" != "directory|$target_uid" ]]; then
                fail "用户路径组件 owner/type 不匹配：$current $item_stat"
                return 1
            fi
        fi
    done
}

validate_environment_root() {
    local requested_root
    if [[ "$environment_kind" == 'container' ]]; then
        requested_root="${MINIOS_ENV_ROOT:-/opt/miniorangeos-dev}"
    else
        requested_root="${MINIOS_ENV_ROOT:-$target_home/.local/share/miniorangeos-dev}"
    fi
    if [[ "$requested_root" != /* ]]; then
        fail "MINIOS_ENV_ROOT 必须是绝对路径：$requested_root"
        return 1
    fi
    environment_root="$(realpath -m -- "$requested_root")"
    if [[ "$environment_kind" == 'container' \
        && "$environment_root" != '/opt/miniorangeos-dev' ]] \
        && ! is_test_path "$environment_root"; then
        fail "容器 environment root 必须精确为 /opt/miniorangeos-dev"
        return 1
    fi
    if [[ "$environment_kind" == 'wsl' ]]; then
        case "$environment_root" in
            "$target_home"/*) ;;
            *) fail "WSL environment root 必须位于目标用户 home 内：$environment_root"; return 1 ;;
        esac
        validate_user_owned_existing_components "$target_home" "$environment_root" || return $?
    else
        if [[ ! -d "$environment_root" || -L "$environment_root" ]]; then
            fail "容器 environment root 必须预创建为普通目录：$environment_root"
            return 1
        fi
        assert_no_symlink_components "$environment_root" || return $?
        local root_stat
        root_stat="$(lstat_path "$environment_root")" || return $?
        if [[ "$root_stat" != "directory|$target_uid" ]]; then
            fail "容器 environment root owner/type 不匹配：$root_stat"
            return 1
        fi
    fi
    assert_no_symlink_components "$environment_root" || return $?
    export MINIOS_ENV_ROOT="$environment_root"
}

validate_wsl_configuration_path() {
    wsl_conf_file=''
    [[ "$environment_kind" == 'wsl' ]] || return 0
    wsl_conf_file="$(select_test_or_production_file \
        "${MINIOS_WSL_CONF_PATH:-}" "$PRODUCTION_WSL_CONF_FILE")" || return $?
    assert_no_symlink_components "${wsl_conf_file%/*}" || return $?
    if [[ -L "$wsl_conf_file" ]]; then
        fail "wsl.conf 目标不能是 symlink：$wsl_conf_file"
        return 1
    fi
}

preflight() {
    validate_ubuntu_release
    validate_isolation_identity
    resolve_target_user
    validate_environment_root
    validate_wsl_configuration_path
}

write_package_lock_as_target() {
    if ((EUID == 0)); then
        fail '--write-package-lock 禁止 root 执行'
        return 1
    fi
    if [[ "$(id -u)" != "$target_uid" || "$(id -un)" != "$target_user" ]]; then
        fail '包锁写入阶段必须是目标普通用户'
        return 1
    fi
    validate_environment_root
    mkdir -p -- "$environment_root/state"
    validate_environment_root
    local state_directory="$environment_root/state"
    local lock_path="$state_directory/apt-packages.lock"
    package_lock_partial="$(mktemp "$state_directory/apt-packages.lock.partial.XXXXXX")"
    local package
    for package in "${APPROVED_PACKAGES[@]}"; do
        dpkg-query -W -f='${Package}=${Version}\n' "$package" >>"$package_lock_partial"
    done
    chmod 0644 "$package_lock_partial"
    mv -- "$package_lock_partial" "$lock_path"
    package_lock_partial=''
}

identity_environment_arguments() {
    printf '%s\0' \
        "MINIOS_ENV_ROOT=$environment_root" \
        "WSL_DISTRO_NAME=${WSL_DISTRO_NAME:-}" \
        "MINIOS_CONTAINER=${MINIOS_CONTAINER:-}" \
        "MINIOS_BOOTSTRAP_TEST_MODE=${MINIOS_BOOTSTRAP_TEST_MODE:-}" \
        "MINIOS_OS_RELEASE_FILE=${MINIOS_OS_RELEASE_FILE:-}" \
        "MINIOS_WSL_CONF_PATH=${MINIOS_WSL_CONF_PATH:-}" \
        "PATH=$PATH"
}

run_as_target() {
    local -a environment_arguments
    mapfile -d '' -t environment_arguments < <(identity_environment_arguments)
    runuser -u "$target_user" -- env "${environment_arguments[@]}" "$@"
}

write_wsl_configuration() {
    [[ "$environment_kind" == 'wsl' ]] || return 0
    local wsl_conf_parent
    local wsl_conf_partial
    wsl_conf_parent="${wsl_conf_file%/*}"
    assert_no_symlink_components "$wsl_conf_parent" || return $?
    wsl_conf_partial="$(mktemp "$wsl_conf_parent/.wsl.conf.miniorangeos.partial.XXXXXX")"
    if ! printf '%s\n' \
        '[automount]' \
        'enabled=true' \
        'options=metadata' \
        '' \
        '[user]' \
        "default=$target_user" >"$wsl_conf_partial"; then
        rm -f -- "$wsl_conf_partial"
        return 1
    fi
    chmod 0644 "$wsl_conf_partial"
    mv -- "$wsl_conf_partial" "$wsl_conf_file"
}

run_system_phase() {
    preflight
    if ((EUID != 0)); then
        fail '--system-only 必须由 root 执行'
        return 1
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${APPROVED_PACKAGES[@]}"
    run_as_target "$SCRIPT_DIR/bootstrap-inside.sh" --write-package-lock --target-user "$target_user"
    write_wsl_configuration
    printf 'system_status=complete\n'
}

run_toolchain_phase() {
    preflight
    if ((EUID == 0)); then
        fail '--toolchain-only 必须由目标普通用户执行'
        return 1
    fi
    if [[ "$(id -u)" != "$target_uid" || "$(id -un)" != "$target_user" ]]; then
        fail "当前用户必须是目标用户：$target_user"
        return 1
    fi
    MINIOS_ENV_ROOT="$environment_root" "$REPO_ROOT/tools/build_toolchain.sh"
}

case "$mode" in
    system-only)
        run_system_phase
        ;;
    toolchain-only)
        run_toolchain_phase
        ;;
    write-package-lock)
        preflight
        write_package_lock_as_target
        ;;
    all)
        preflight
        if ((EUID == 0)); then
            run_system_phase
            run_as_target "$SCRIPT_DIR/bootstrap-inside.sh" --toolchain-only --target-user "$target_user"
        elif sudo -n true 2>/dev/null; then
            local_env=(
                "MINIOS_ENV_ROOT=$environment_root"
                "WSL_DISTRO_NAME=${WSL_DISTRO_NAME:-}"
                "MINIOS_CONTAINER=${MINIOS_CONTAINER:-}"
            )
            sudo -n env "${local_env[@]}" "$SCRIPT_DIR/bootstrap-inside.sh" --system-only --target-user "$target_user"
            run_toolchain_phase
        else
            printf 'minios level=FAIL message=当前用户没有无密码 sudo；请依次执行：\n' >&2
            printf 'wsl.exe -d %s -u root -- env MINIOS_ENV_ROOT=%q bash %q --system-only --target-user %q\n' \
                "${WSL_DISTRO_NAME:-MiniOrangeOS-Dev}" "$environment_root" "$SCRIPT_DIR/bootstrap-inside.sh" "$target_user" >&2
            printf 'wsl.exe -d %s -u %s -- env MINIOS_ENV_ROOT=%q bash %q --toolchain-only --target-user %q\n' \
                "${WSL_DISTRO_NAME:-MiniOrangeOS-Dev}" "$target_user" "$environment_root" "$SCRIPT_DIR/bootstrap-inside.sh" "$target_user" >&2
            exit 1
        fi
        ;;
esac
