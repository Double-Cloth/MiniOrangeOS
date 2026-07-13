#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
if source "$SCRIPT_DIR/lib/common.sh"; then
    :
else
    status=$?
    exit "$status"
fi
if minios_load_versions; then
    :
else
    status=$?
    exit "$status"
fi

if [[ $# -eq 0 ]]; then
    minios_die "用法：environment/with-env.sh <命令> [参数...]"
    exit 2
fi

readonly TOOLCHAIN_BIN="$MINIOS_ENV_ROOT/toolchain/bin"
readonly VENV_BIN="$MINIOS_ENV_ROOT/venv/bin"
if [[ ! -d "$TOOLCHAIN_BIN" ]]; then
    minios_die "工具链目录不存在：$TOOLCHAIN_BIN"
    exit 1
fi

if [[ -d "$VENV_BIN" ]]; then
    PATH="$TOOLCHAIN_BIN:$VENV_BIN:$PATH"
else
    PATH="$TOOLCHAIN_BIN:$PATH"
fi
export PATH

requested_command="$1"
requested_basename="${requested_command##*/}"
if [[ "$requested_basename" == "${MINIOS_TARGET}-"* ]]; then
    if resolved_command="$(command -v -- "$requested_command" 2>/dev/null)"; then
        :
    else
        status=$?
        minios_log "FAIL" "项目交叉工具不存在：$requested_command status=$status"
        exit "$status"
    fi
    if resolved_command="$(realpath -m -- "$resolved_command")"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法解析交叉工具路径：$requested_command status=$status"
        exit "$status"
    fi
    case "$resolved_command" in
        "$TOOLCHAIN_BIN"/*)
            if [[ ! -f "$resolved_command" || ! -x "$resolved_command" ]]; then
                minios_die "项目交叉工具不可执行：$resolved_command"
                exit 1
            fi
            ;;
        *)
            minios_die "拒绝执行项目工具链之外的交叉工具：$resolved_command"
            exit 1
            ;;
    esac
fi

exec "$@"
