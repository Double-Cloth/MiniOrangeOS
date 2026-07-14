#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"
minios_load_versions
readonly MINIOS_WSL_IDENTITY_FILE='/etc/miniorangeos/instance.identity'

failure_count=0

record_pass() {
    local check_name="$1"
    local detail="$2"
    printf 'check=%s status=PASS detail=%s\n' "$check_name" "$detail"
}

record_fail() {
    local check_name="$1"
    local detail="$2"
    printf 'check=%s status=FAIL detail=%s\n' "$check_name" "$detail" >&2
    failure_count=$((failure_count + 1))
}

runtime_fact_is_trusted() {
    local path="$1"
    local expected_owner="${2:-0}"
    local item_type
    local item_uid
    local item_mode
    [[ -f "$path" && ! -L "$path" ]] || return 1
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$path") || return $?
    [[ ( "$item_type" == 'regular file' || "$item_type" == 'regular empty file' ) \
        && "$item_uid" == "$expected_owner" \
        && "$item_mode" =~ ^[0-7]{3,4}$ \
        && $((8#$item_mode & 8#022)) -eq 0 ]]
}

trusted_runtime_process_owner() {
    local item_type
    local item_uid
    local item_mode
    local filesystem_type
    [[ -d /proc/1 && ! -L /proc/1 ]] || return 1
    IFS='|' read -r item_type item_uid item_mode < <(
        stat -c '%F|%u|%a' -- /proc/1
    ) || return $?
    filesystem_type="$(stat -f -c %T -- /proc/1)" || return $?
    [[ "$item_type" == 'directory' \
        && "$item_uid" =~ ^[0-9]+$ \
        && "$item_mode" =~ ^[0-7]{3,4}$ \
        && $((8#$item_mode & 8#022)) -eq 0 \
        && "$filesystem_type" == 'proc' ]] || return 1
    printf '%s\n' "$item_uid"
}

runtime_process_fact_is_trusted() {
    local path="$1"
    local expected_owner="$2"
    runtime_fact_is_trusted "$path" "$expected_owner" \
        && [[ "$(stat -f -c %T -- "$path")" == 'proc' ]]
}

verify_wsl2_runtime_identity() {
    local osrelease
    local version
    runtime_fact_is_trusted /proc/sys/kernel/osrelease || return 1
    runtime_fact_is_trusted /proc/version || return 1
    runtime_fact_is_trusted /proc/sys/fs/binfmt_misc/WSLInterop || return 1
    osrelease="$(</proc/sys/kernel/osrelease)"
    version="$(</proc/version)"
    [[ "${osrelease,,}" == *microsoft* \
        && "${osrelease,,}" == *wsl2* \
        && "${version,,}" == *microsoft* \
        && "${version,,}" == *wsl2* ]]
}

verify_wsl_instance_identity() {
    local -a lines
    runtime_fact_is_trusted "$MINIOS_WSL_IDENTITY_FILE" || return 1
    [[ "$(stat -c %a -- "$MINIOS_WSL_IDENTITY_FILE")" == '644' ]] || return 1
    mapfile -t lines <"$MINIOS_WSL_IDENTITY_FILE"
    ((${#lines[@]} == 4)) \
        && [[ "${lines[0]}" == 'schema=1' \
            && "${lines[1]}" == "distro=${WSL_DISTRO_NAME:-}" \
            && "${lines[2]}" =~ ^registration_id=\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$ \
            && "${lines[3]}" =~ ^base_path_sha256=[0-9a-f]{64}$ ]]
}

verify_container_runtime_identity() {
    local marker=''
    local process_owner
    local cgroup
    local mountinfo
    process_owner="$(trusted_runtime_process_owner)" || return 1
    runtime_process_fact_is_trusted /proc/1/cgroup "$process_owner" || return 1
    runtime_process_fact_is_trusted /proc/1/mountinfo "$process_owner" || return 1
    if runtime_fact_is_trusted /.dockerenv; then
        marker='/.dockerenv'
    elif runtime_fact_is_trusted /run/.containerenv; then
        marker='/run/.containerenv'
    else
        return 1
    fi
    cgroup="$(</proc/1/cgroup)"
    mountinfo="$(</proc/1/mountinfo)"
    [[ -n "$marker" \
        && ( "${cgroup,,}" =~ (docker|libpod|podman|containerd|kubepods) \
            || "${mountinfo,,}" =~ (\ -\ overlay\ |\ -\ fuse\.fuse-overlayfs\ |containers/storage) ) ]]
}

readonly TOOLCHAIN_BIN="$MINIOS_ENV_ROOT/toolchain/bin"
PATH="$TOOLCHAIN_BIN:$PATH"
export PATH

printf 'repo_root=%s\n' "$MINIOS_REPO_ROOT"
printf 'environment_root=%s\n' "$MINIOS_ENV_ROOT"
printf 'target=%s\n' "$MINIOS_TARGET"
printf 'host_os=%s\n' "$(uname -s)"

ubuntu_version="unknown"
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    ubuntu_version="${VERSION_ID:-unknown}"
fi
printf 'ubuntu_version=%s\n' "$ubuntu_version"
if [[ "${ID:-}" == "ubuntu" && "$ubuntu_version" == "24.04" ]]; then
    record_pass "ubuntu" "$ubuntu_version"
else
    record_fail "ubuntu" "需要 Ubuntu 24.04，实际 ${ID:-unknown} $ubuntu_version"
fi

if [[ "${MINIOS_CONTAINER:-}" == "1" ]] && verify_container_runtime_identity; then
    environment_kind="container"
    record_pass "isolation" "project-container"
elif [[ -z "${MINIOS_CONTAINER:-}" \
    && "${WSL_DISTRO_NAME:-}" =~ ^MiniOrangeOS-Dev(-Test-[A-Za-z0-9][A-Za-z0-9_-]*)?$ ]] \
    && verify_wsl2_runtime_identity \
    && verify_wsl_instance_identity; then
    environment_kind="wsl"
    record_pass "isolation" "$WSL_DISTRO_NAME"
else
    environment_kind="unknown"
    record_fail "isolation" "需要可信 $MINIOS_WSL_DISTRO WSL2 或真实 OCI container runtime"
fi
printf 'environment_kind=%s\n' "$environment_kind"

gcc_path="$(command -v "${MINIOS_TARGET}-gcc" || true)"
ld_path="$(command -v "${MINIOS_TARGET}-ld" || true)"
gcc_owned=0
if [[ "$gcc_path" == "$TOOLCHAIN_BIN/${MINIOS_TARGET}-gcc" ]]; then
    gcc_owned=1
    record_pass "cross-gcc-path" "$gcc_path"
else
    record_fail "cross-gcc-path" "工具缺失或不属于项目工具链：${gcc_path:-missing}"
fi
if [[ "$ld_path" == "$TOOLCHAIN_BIN/${MINIOS_TARGET}-ld" ]]; then
    record_pass "cross-ld-path" "$ld_path"
else
    record_fail "cross-ld-path" "工具缺失或不属于项目工具链：${ld_path:-missing}"
fi

if ((gcc_owned == 1)); then
    gcc_target="$("$gcc_path" -dumpmachine 2>/dev/null || true)"
    if [[ "$gcc_target" == "$MINIOS_TARGET" ]]; then
        record_pass "cross-gcc-target" "$gcc_target"
    else
        record_fail "cross-gcc-target" "期望 $MINIOS_TARGET，实际 ${gcc_target:-unknown}"
    fi

    verify_directory="$(mktemp -d "${TMPDIR:-/tmp}/miniorangeos-verify.XXXXXX")"
    trap 'rm -rf -- "$verify_directory"' EXIT
    printf '%s\n' 'void minios_verify(void) {}' >"$verify_directory/verify.c"
    if "$gcc_path" -ffreestanding -fno-pie -c "$verify_directory/verify.c" -o "$verify_directory/verify.o"; then
        if [[ -f "$verify_directory/verify.o" && ! -L "$verify_directory/verify.o" && -s "$verify_directory/verify.o" ]]; then
            record_pass "freestanding-compile" "nonempty-object-created"
        else
            record_fail "freestanding-compile" "编译器未生成非空普通对象文件"
        fi
    else
        record_fail "freestanding-compile" "交叉编译失败"
    fi
else
    record_fail "cross-gcc-target" "${MINIOS_TARGET}-gcc missing"
    record_fail "freestanding-compile" "${MINIOS_TARGET}-gcc missing"
fi

nasm_fingerprint="missing"
qemu_fingerprint="missing"
gdb_fingerprint="missing"
python_fingerprint="missing"
for required_tool in nasm qemu-system-i386 gdb python3; do
    tool_path="$(command -v "$required_tool" || true)"
    if [[ -z "$tool_path" ]]; then
        record_fail "$required_tool" "missing"
        continue
    fi

    if [[ "$required_tool" == "nasm" ]]; then
        tool_version="$("$tool_path" -v 2>/dev/null || true)"
    else
        tool_version="$("$tool_path" --version 2>/dev/null || true)"
    fi
    tool_version="${tool_version%%$'\n'*}"
    if [[ -z "$tool_version" ]]; then
        record_fail "$required_tool" "无法读取版本：$tool_path"
        continue
    fi
    record_pass "$required_tool" "$tool_path"
    case "$required_tool" in
        nasm) nasm_fingerprint="$tool_version" ;;
        qemu-system-i386) qemu_fingerprint="$tool_version" ;;
        gdb) gdb_fingerprint="$tool_version" ;;
        python3) python_fingerprint="$tool_version" ;;
    esac
done

if ((gcc_owned == 1)); then
    gcc_fingerprint="$gcc_path"
else
    gcc_fingerprint="missing"
fi
if [[ -n "$ld_path" ]]; then
    ld_fingerprint="$ld_path"
else
    ld_fingerprint="missing"
fi

printf 'wsl_distro=%s\n' "${WSL_DISTRO_NAME:-none}"
printf 'tool_root=%s\n' "$MINIOS_ENV_ROOT/toolchain"
printf 'i686_elf_gcc=%s\n' "$gcc_fingerprint"
printf 'i686_elf_ld=%s\n' "$ld_fingerprint"
printf 'nasm=%s\n' "$nasm_fingerprint"
printf 'qemu_system_i386=%s\n' "$qemu_fingerprint"
printf 'gdb=%s\n' "$gdb_fingerprint"
printf 'python=%s\n' "$python_fingerprint"

if compgen -G '/usr/local/bin/i686-elf-*' > /dev/null; then
    linux_global_pollution="detected"
    record_fail "global-toolchain-pollution" "发现全局 i686-elf 工具"
else
    linux_global_pollution="none"
    record_pass "global-toolchain-pollution" "none"
fi
windows_path_pollution="none"
case "$gcc_path:$ld_path" in
    *:/mnt/?/*|/mnt/?/*:*) windows_path_pollution="detected" ;;
esac
printf 'windows_path_pollution=%s\n' "$windows_path_pollution"
printf 'linux_global_pollution=%s\n' "$linux_global_pollution"

if ((failure_count > 0)); then
    printf 'result=FAIL\n' >&2
    exit 1
fi

printf 'result=PASS\n'
