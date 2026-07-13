#!/usr/bin/env bash
set -euo pipefail

# 仅在专用 WSL/容器内部安装系统依赖，并以普通用户构建项目工具链。
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(realpath -m -- "$SCRIPT_DIR/..")"
mode="all"
target_user="${MINIOS_TARGET_USER:-minios}"
bootstrap_partial=''

cleanup_bootstrap_partial() {
    if [[ -n "$bootstrap_partial" ]]; then
        rm -f -- "$bootstrap_partial"
    fi
}
trap cleanup_bootstrap_partial EXIT

usage() {
    printf '用法：%s [--system-only|--toolchain-only] [--target-user USER]\n' "${0##*/}" >&2
}

while (($# > 0)); do
    case "$1" in
        --system-only|--toolchain-only)
            if [[ "$mode" != "all" ]]; then
                printf 'minios level=FAIL message=重复或冲突的阶段参数：%s\n' "$1" >&2
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
            printf 'minios level=FAIL message=未知参数：%s\n' "$1" >&2
            usage
            exit 2
            ;;
    esac
    shift
done

if [[ ! "$target_user" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    printf 'minios level=FAIL message=无效目标用户：%s\n' "$target_user" >&2
    exit 2
fi

readonly -a APPROVED_PACKAGES=(
    build-essential bison flex libgmp-dev libmpfr-dev libmpc-dev texinfo
    nasm qemu-system-x86 qemu-utils gdb python3 python3-venv
    ca-certificates curl xz-utils sudo
)

run_system_phase() {
    if ((EUID != 0)); then
        printf 'minios level=FAIL message=--system-only 必须由 root 执行\n' >&2
        return 1
    fi
    if ! getent passwd "$target_user" >/dev/null; then
        useradd --create-home --shell /bin/bash "$target_user"
    fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${APPROVED_PACKAGES[@]}"

    local target_home
    target_home="$(getent passwd "$target_user" | cut -d: -f6)"
    local environment_root="$target_home/.local/share/miniorangeos-dev"
    local state_directory="$environment_root/state"
    local lock_path="$state_directory/apt-packages.lock"
    local partial_path
    install -d -m 0755 -o "$target_user" -g "$target_user" "$environment_root" "$state_directory"
    partial_path="$(mktemp "$state_directory/apt-packages.lock.partial.XXXXXX")"
    bootstrap_partial="$partial_path"
    local package
    for package in "${APPROVED_PACKAGES[@]}"; do
        dpkg-query -W -f='${Package}=${Version}\n' "$package" >>"$partial_path"
    done
    chown "$target_user:$target_user" "$partial_path"
    chmod 0644 "$partial_path"
    mv -- "$partial_path" "$lock_path"
    bootstrap_partial=''

    local wsl_conf_partial
    wsl_conf_partial="$(mktemp /etc/wsl.conf.miniorangeos.partial.XXXXXX)"
    bootstrap_partial="$wsl_conf_partial"
    printf '%s\n' \
        '[automount]' \
        'enabled=true' \
        'options=metadata' \
        '' \
        '[user]' \
        "default=$target_user" >"$wsl_conf_partial"
    chmod 0644 "$wsl_conf_partial"
    mv -- "$wsl_conf_partial" /etc/wsl.conf
    bootstrap_partial=''
    printf 'system_status=complete\n'
}

run_toolchain_phase() {
    if ((EUID == 0)); then
        printf 'minios level=FAIL message=--toolchain-only 必须由目标普通用户执行\n' >&2
        return 1
    fi
    if [[ "$(id -un)" != "$target_user" ]]; then
        printf 'minios level=FAIL message=当前用户必须是目标用户：%s\n' "$target_user" >&2
        return 1
    fi
    "$REPO_ROOT/tools/build_toolchain.sh"
}

case "$mode" in
    system-only)
        run_system_phase
        ;;
    toolchain-only)
        run_toolchain_phase
        ;;
    all)
        if ((EUID == 0)); then
            run_system_phase
            runuser -u "$target_user" -- "$SCRIPT_DIR/bootstrap-inside.sh" --toolchain-only --target-user "$target_user"
        elif sudo -n true 2>/dev/null; then
            sudo -n "$SCRIPT_DIR/bootstrap-inside.sh" --system-only --target-user "$target_user"
            run_toolchain_phase
        else
            printf 'minios level=FAIL message=当前用户没有无密码 sudo；请依次执行：\n' >&2
            printf 'wsl.exe -d MiniOrangeOS-Dev -u root -- bash %q --system-only --target-user %q\n' "$SCRIPT_DIR/bootstrap-inside.sh" "$target_user" >&2
            printf 'wsl.exe -d MiniOrangeOS-Dev -u %s -- bash %q --toolchain-only --target-user %q\n' "$target_user" "$SCRIPT_DIR/bootstrap-inside.sh" "$target_user" >&2
            exit 1
        fi
        ;;
esac
