#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
minios_load_versions

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

exec "$@"
