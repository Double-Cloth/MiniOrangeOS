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
readonly PRODUCTION_WSL_IDENTITY_FILE='/etc/miniorangeos/instance.identity'
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
target_gid=''
target_home=''
environment_root=''
wsl_conf_file=''
test_root=''
runtime_probe_root=''
expected_distro=''
registration_id=''
base_path_sha256=''

usage() {
    printf '用法：%s [--system-only|--toolchain-only] [--target-user USER]\n' "${0##*/}" >&2
}

fail() {
    printf 'minios level=FAIL message=%s\n' "$*" >&2
    return 1
}

while (($# > 0)); do
    case "$1" in
        --system-only|--toolchain-only|--prepare-package-state|--write-package-lock|--provision-wsl-identity)
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
        --expected-distro)
            shift
            if (($# == 0)); then usage; exit 2; fi
            expected_distro="$1"
            ;;
        --registration-id)
            shift
            if (($# == 0)); then usage; exit 2; fi
            registration_id="$1"
            ;;
        --base-path-sha256)
            shift
            if (($# == 0)); then usage; exit 2; fi
            base_path_sha256="$1"
            ;;
        *)
            fail "未知参数：$1"
            usage
            exit 2
            ;;
    esac
    shift
done

if [[ "$mode" == 'provision-wsl-identity' ]]; then
    if [[ ! "$expected_distro" =~ $SAFE_WSL_NAME_PATTERN \
        || ! "$registration_id" =~ ^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$ \
        || ! "$base_path_sha256" =~ ^[0-9a-f]{64}$ ]]; then
        fail 'identity provision 参数格式无效'
        exit 2
    fi
elif [[ -n "$expected_distro$registration_id$base_path_sha256" ]]; then
    fail 'identity provision 参数只能与 --provision-wsl-identity 一起使用'
    exit 2
fi

is_test_path() {
    local path="$1"
    [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' \
        && -n "$test_root" \
        && ( "$path" == "$test_root" || "$path" == "$test_root"/* ) ]]
}

validate_test_configuration() {
    if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" != '1' ]]; then
        if [[ -n "${MINIOS_BOOTSTRAP_TEST_ROOT:-}${MINIOS_USERADD_EXECUTABLE:-}${MINIOS_EXPECTED_MINIOS_HOME:-}${MINIOS_RUNTIME_PROBE_ROOT:-}${MINIOS_WSL_IDENTITY_FILE:-}${MINIOS_PACKAGE_STATE_RACE_PHASE:-}${FAKE_RACE_STATE:-}${FAKE_RACE_ORIGINAL:-}${FAKE_RACE_OUTSIDE:-}" ]]; then
            fail '测试覆盖仅允许在 MINIOS_BOOTSTRAP_TEST_MODE=1 中使用'
            return 1
        fi
        return 0
    fi

    local requested_root="${MINIOS_BOOTSTRAP_TEST_ROOT:-}"
    local canonical_root
    local root_type
    local root_uid
    local root_mode
    if [[ -z "$requested_root" || -L "$requested_root" ]]; then
        fail '测试模式必须提供非 symlink 的 MINIOS_BOOTSTRAP_TEST_ROOT'
        return 1
    fi
    canonical_root="$(realpath -e -- "$requested_root")" || return $?
    if [[ "$requested_root" != "$canonical_root" \
        || ! "$canonical_root" =~ ^/tmp/minios-bootstrap-test-[A-Za-z0-9]{8}$ ]]; then
        fail "测试根必须是 mktemp 创建的规范路径：$requested_root"
        return 1
    fi
    IFS='|' read -r root_type root_uid root_mode < <(stat -c '%F|%u|%a' -- "$canonical_root")
    if [[ "$root_type" != 'directory' || "$root_uid" != '0' \
        || ! "$root_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$root_mode & 8#022)) -ne 0 ]]; then
        fail "测试根必须是 root 拥有且组/其他用户不可写的普通目录：$canonical_root"
        return 1
    fi
    test_root="$canonical_root"

    local requested_runtime_root="${MINIOS_RUNTIME_PROBE_ROOT:-}"
    local canonical_runtime_root
    if [[ -z "$requested_runtime_root" || -L "$requested_runtime_root" ]]; then
        fail '测试模式必须提供非 symlink 的 runtime probe root'
        return 1
    fi
    canonical_runtime_root="$(realpath -e -- "$requested_runtime_root")" || return $?
    if [[ "$requested_runtime_root" != "$canonical_runtime_root" ]] \
        || ! is_test_path "$canonical_runtime_root"; then
        fail "runtime probe root 必须是测试根内的规范路径：$requested_runtime_root"
        return 1
    fi
    validate_root_owned_safe_chain "$test_root" "$canonical_runtime_root" || return $?
    runtime_probe_root="$canonical_runtime_root"
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

mode_is_root_safe() {
    local mode="$1"
    [[ "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
    (( (8#$mode & 8#022) == 0 ))
}

validate_root_owned_safe_directory() {
    local path="$1"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -d "$path" || -L "$path" ]]; then
        fail "可信路径组件必须是非 symlink 普通目录：$path"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$path")
    if [[ "$item_type" != 'directory' || "$item_uid" != '0' ]] \
        || ! mode_is_root_safe "$item_mode"; then
        fail "可信路径组件必须 root 拥有且组/其他用户不可写：$path type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

validate_root_owned_safe_chain() {
    local base="$1"
    local candidate="$2"
    local current="$base"
    local relative
    local component
    if [[ "$base" == '/' ]]; then
        if [[ "$candidate" != /* ]]; then
            fail "可信路径不是绝对路径：$candidate"
            return 1
        fi
        relative="${candidate#/}"
    else
        if [[ "$candidate" != "$base" && "$candidate" != "$base"/* ]]; then
            fail "可信路径越过验证根：$candidate"
            return 1
        fi
        relative="${candidate#"$base"}"
        relative="${relative#/}"
    fi
    validate_root_owned_safe_directory "$base" || return $?
    IFS='/' read -r -a components <<<"$relative"
    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue
        current="${current%/}/$component"
        validate_root_owned_safe_directory "$current" || return $?
    done
}

validate_root_owned_safe_regular_file() {
    local path="$1"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -f "$path" || -L "$path" ]]; then
        fail "可信 os-release target 必须是非 symlink 普通文件：$path"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$path")
    if [[ "$item_type" != 'regular file' || "$item_uid" != '0' ]] \
        || ! mode_is_root_safe "$item_mode"; then
        fail "可信 os-release target 必须 root 拥有且组/其他用户不可写：$path type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

select_os_release_entry() {
    local override="${MINIOS_OS_RELEASE_FILE:-}"
    local requested="${override:-$PRODUCTION_OS_RELEASE_FILE}"
    local lexical_path
    lexical_path="$(realpath -ms -- "$requested")" || return $?
    if [[ "$requested" != "$lexical_path" ]]; then
        fail "os-release 必须使用规范绝对入口路径：$requested"
        return 1
    fi
    if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' ]]; then
        if [[ -z "$override" ]] || ! is_test_path "$lexical_path"; then
            fail "测试 os-release 必须位于已验证测试根内：$lexical_path"
            return 1
        fi
    elif [[ -n "$override" || "$lexical_path" != "$PRODUCTION_OS_RELEASE_FILE" ]]; then
        fail "生产 os-release 入口必须精确为 $PRODUCTION_OS_RELEASE_FILE"
        return 1
    fi
    printf '%s\n' "$lexical_path"
}

resolve_trusted_os_release() {
    local entry
    local chain_base
    local entry_parent
    local image_root
    local expected_target
    local resolved_target
    local link_text
    local link_type
    local link_uid
    local link_mode
    entry="$(select_os_release_entry)" || return $?

    if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' ]]; then
        chain_base="$test_root"
    else
        chain_base='/'
    fi
    entry_parent="${entry%/*}"
    validate_root_owned_safe_chain "$chain_base" "$entry_parent" || return $?

    if [[ ! -L "$entry" ]]; then
        if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' ]]; then
            fail '测试 os-release 只允许标准 etc/os-release 相对链接镜像'
            return 1
        fi
        validate_root_owned_safe_regular_file "$entry" || return $?
        printf '%s\n' "$entry"
        return
    fi

    IFS='|' read -r link_type link_uid link_mode < <(stat -c '%F|%u|%a' -- "$entry")
    if [[ "$link_type" != 'symbolic link' || "$link_uid" != '0' || "$link_mode" != '777' ]]; then
        fail "os-release symlink 元数据不可信：$entry type=$link_type uid=$link_uid mode=$link_mode"
        return 1
    fi
    link_text="$(readlink -- "$entry")" || return $?
    if [[ "$link_text" != '../usr/lib/os-release' ]]; then
        fail "os-release symlink 必须精确为 ../usr/lib/os-release：$link_text"
        return 1
    fi

    if [[ "$entry" == '/etc/os-release' ]]; then
        image_root=''
        expected_target='/usr/lib/os-release'
    elif [[ "$entry" == */etc/os-release ]]; then
        image_root="${entry%/etc/os-release}"
        if [[ -z "$image_root" ]] || ! is_test_path "$image_root"; then
            fail "测试 os-release 镜像根不可信：$image_root"
            return 1
        fi
        expected_target="$image_root/usr/lib/os-release"
    else
        fail "os-release symlink 入口必须位于精确 etc/os-release：$entry"
        return 1
    fi

    validate_root_owned_safe_chain "$chain_base" "${expected_target%/*}" || return $?
    resolved_target="$(realpath -e -- "$entry")" || {
        fail "os-release symlink target 缺失：$entry"
        return 1
    }
    if [[ "$resolved_target" != "$expected_target" ]]; then
        fail "os-release symlink target 不精确：$resolved_target"
        return 1
    fi
    validate_root_owned_safe_regular_file "$resolved_target" || return $?
    printf '%s\n' "$resolved_target"
}

validate_ubuntu_release() {
    local os_release_file
    local os_id
    local version_id
    os_release_file="$(resolve_trusted_os_release)" || return $?
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

runtime_probe_path() {
    local production_path="$1"
    if [[ -n "$runtime_probe_root" ]]; then
        printf '%s%s\n' "$runtime_probe_root" "$production_path"
    else
        printf '%s\n' "$production_path"
    fi
}

validate_runtime_probe_file() {
    local path="$1"
    local expected_owner="${2:-0}"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -f "$path" || -L "$path" ]]; then
        fail "runtime fact 必须是非 symlink 普通文件：$path"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$path")
    if [[ ( "$item_type" != 'regular file' && "$item_type" != 'regular empty file' ) \
        || "$item_uid" != "$expected_owner" \
        || ! "$item_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$item_mode & 8#022)) -ne 0 ]]; then
        fail "runtime fact owner/type/mode 不可信：$path type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

validate_wsl2_runtime_identity() {
    local osrelease_path
    local version_path
    local interop_path
    local osrelease
    local version
    osrelease_path="$(runtime_probe_path /proc/sys/kernel/osrelease)" || return $?
    version_path="$(runtime_probe_path /proc/version)" || return $?
    interop_path="$(runtime_probe_path /proc/sys/fs/binfmt_misc/WSLInterop)" || return $?
    validate_runtime_probe_file "$osrelease_path" || return $?
    validate_runtime_probe_file "$version_path" || return $?
    validate_runtime_probe_file "$interop_path" || return $?
    osrelease="$(<"$osrelease_path")"
    version="$(<"$version_path")"
    if [[ "${osrelease,,}" != *microsoft* \
        || "${osrelease,,}" != *wsl2* \
        || "${version,,}" != *microsoft* \
        || "${version,,}" != *wsl2* ]]; then
        fail "WSL identity 缺少 Microsoft WSL2 kernel/runtime 事实：osrelease=$osrelease"
        return 1
    fi
}

validate_container_runtime_identity() {
    local cgroup_path
    local mountinfo_path
    local docker_marker
    local podman_marker
    local marker=''
    local cgroup
    local mountinfo
    cgroup_path="$(runtime_probe_path /proc/1/cgroup)" || return $?
    mountinfo_path="$(runtime_probe_path /proc/1/mountinfo)" || return $?
    docker_marker="$(runtime_probe_path /.dockerenv)" || return $?
    podman_marker="$(runtime_probe_path /run/.containerenv)" || return $?
    validate_runtime_probe_file "$cgroup_path" || return $?
    validate_runtime_probe_file "$mountinfo_path" || return $?
    if [[ -f "$docker_marker" && ! -L "$docker_marker" ]]; then
        marker="$docker_marker"
    elif [[ -f "$podman_marker" && ! -L "$podman_marker" ]]; then
        marker="$podman_marker"
    else
        fail '容器 identity 缺少可信 /.dockerenv 或 /run/.containerenv marker'
        return 1
    fi
    validate_runtime_probe_file "$marker" || return $?
    cgroup="$(<"$cgroup_path")"
    mountinfo="$(<"$mountinfo_path")"
    if [[ ! "${cgroup,,}" =~ (docker|libpod|podman|containerd|kubepods) \
        && ! "${mountinfo,,}" =~ (\ -\ overlay\ |\ -\ fuse\.fuse-overlayfs\ |containers/storage) ]]; then
        fail '容器 identity 缺少 OCI cgroup 或容器 rootfs mount 事实'
        return 1
    fi
}

select_wsl_identity_file() {
    select_test_or_production_file \
        "${MINIOS_WSL_IDENTITY_FILE:-}" "$PRODUCTION_WSL_IDENTITY_FILE"
}

validate_wsl_identity_file_metadata() {
    local identity_file="$1"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -f "$identity_file" || -L "$identity_file" ]]; then
        fail "WSL identity record 必须是非 symlink 普通文件：$identity_file"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$identity_file")
    if [[ ( "$item_type" != 'regular file' && "$item_type" != 'regular empty file' ) \
        || "$item_uid" != '0' || "$item_mode" != '644' ]]; then
        fail "WSL identity record 必须 root-owned mode 0644：type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

read_wsl_identity_record() {
    local identity_file="$1"
    local -a lines
    validate_wsl_identity_file_metadata "$identity_file" || return $?
    mapfile -t lines <"$identity_file"
    if ((${#lines[@]} != 4)) \
        || [[ "${lines[0]}" != 'schema=1' \
            || "${lines[1]}" != distro=* \
            || ! "${lines[1]#distro=}" =~ $SAFE_WSL_NAME_PATTERN \
            || ! "${lines[2]}" =~ ^registration_id=\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$ \
            || ! "${lines[3]}" =~ ^base_path_sha256=[0-9a-f]{64}$ ]]; then
        fail 'WSL identity record schema/字段无效'
        return 1
    fi
    printf '%s\n' "${lines[1]#distro=}"
}

validate_wsl_instance_identity() {
    local identity_file
    local recorded_distro
    identity_file="$(select_wsl_identity_file)" || return $?
    recorded_distro="$(read_wsl_identity_record "$identity_file")" || return $?
    if [[ "$recorded_distro" != "${WSL_DISTRO_NAME:-}" ]]; then
        fail "WSL identity record 与当前发行版名不一致：record=$recorded_distro env=${WSL_DISTRO_NAME:-missing}"
        return 1
    fi
}

provision_wsl_identity() {
    validate_test_configuration || return $?
    validate_ubuntu_release || return $?
    validate_wsl2_runtime_identity || return $?
    if ((EUID != 0)); then
        fail 'identity provision 必须由 root 执行'
        return 1
    fi
    if [[ "${WSL_DISTRO_NAME:-}" != "$expected_distro" ]]; then
        fail "identity provision 的发行版环境不匹配：expected=$expected_distro actual=${WSL_DISTRO_NAME:-missing}"
        return 1
    fi
    local identity_file
    local identity_parent
    local partial=''
    local desired
    identity_file="$(select_wsl_identity_file)" || return $?
    identity_parent="${identity_file%/*}"
    if [[ "$identity_file" == "$PRODUCTION_WSL_IDENTITY_FILE" ]]; then
        validate_root_owned_safe_chain / /etc || return $?
        if [[ ! -e "$identity_parent" && ! -L "$identity_parent" ]]; then
            mkdir -m 0755 -- "$identity_parent" || return $?
        fi
        validate_root_owned_safe_chain / "$identity_parent" || return $?
    else
        validate_root_owned_safe_chain "$test_root" "$identity_parent" || return $?
    fi
    desired="$(printf '%s\n' \
        'schema=1' \
        "distro=$expected_distro" \
        "registration_id=$registration_id" \
        "base_path_sha256=$base_path_sha256")"
    if [[ -e "$identity_file" || -L "$identity_file" ]]; then
        validate_wsl_identity_file_metadata "$identity_file" || return $?
        if [[ "$(<"$identity_file")" != "$desired" ]]; then
            fail '已有 WSL identity record 与当前 Lxss ownership 不一致，拒绝覆盖'
            return 1
        fi
        printf 'identity_status=up-to-date\n'
        return 0
    fi
    partial="$(mktemp "$identity_parent/.instance.identity.partial.XXXXXX")" || return $?
    if ! printf '%s\n' "$desired" >"$partial"; then
        rm -f -- "$partial"
        return 1
    fi
    chmod 0644 "$partial" || { rm -f -- "$partial"; return 1; }
    sync -f "$partial" || { rm -f -- "$partial"; return 1; }
    if [[ -e "$identity_file" || -L "$identity_file" ]]; then
        rm -f -- "$partial"
        fail 'WSL identity record 创建期间出现并发目标'
        return 1
    fi
    mv -- "$partial" "$identity_file" || { rm -f -- "$partial"; return 1; }
    sync -f "$identity_parent" || return $?
    validate_wsl_identity_file_metadata "$identity_file" || return $?
    [[ "$(<"$identity_file")" == "$desired" ]] || {
        fail 'WSL identity record 原子写入后内容不一致'
        return 1
    }
    printf 'identity_status=created\n'
}

validate_isolation_identity() {
    if [[ "${MINIOS_CONTAINER:-}" == '1' ]]; then
        validate_container_runtime_identity || return $?
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
    validate_wsl2_runtime_identity || return $?
    validate_wsl_instance_identity || return $?
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
        || "$passwd_uid" == '0' || ! "$passwd_gid" =~ ^[0-9]+$ \
        || "$passwd_gid" == '0' ]]; then
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
    local home_type
    local home_uid
    local home_mode
    home_stat="$(stat -c '%F|%u|%a' -- "$passwd_home")" || {
        fail "无法读取目标用户 home 元数据：$passwd_home"
        return 1
    }
    IFS='|' read -r home_type home_uid home_mode <<<"$home_stat"
    if [[ "$home_type" != 'directory' || "$home_uid" != "$passwd_uid" ]] \
        || ! mode_is_root_safe "$home_mode"; then
        fail "目标用户 home owner/type/mode 不匹配：$passwd_home $home_stat"
        return 1
    fi
    target_uid="$passwd_uid"
    target_gid="$passwd_gid"
    target_home="$(realpath -e -- "$passwd_home")" || {
        fail "无法规范化目标用户 home：$passwd_home"
        return 1
    }
}

validate_target_user_name() {
    if [[ ! "$target_user" =~ ^[a-z_][a-z0-9_-]*$ || "$target_user" == 'root' ]]; then
        fail "拒绝无效或特权目标用户：$target_user"
        return 1
    fi
}

select_expected_minios_home() {
    local requested_home="${MINIOS_EXPECTED_MINIOS_HOME:-/home/minios}"
    local canonical_home
    canonical_home="$(realpath -m -- "$requested_home")" || return $?
    if [[ "$requested_home" != "$canonical_home" ]]; then
        fail "minios home 必须是规范绝对路径：$requested_home"
        return 1
    fi
    if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" == '1' ]]; then
        if ! is_test_path "$canonical_home"; then
            fail "测试 minios home 必须位于已验证测试根内：$canonical_home"
            return 1
        fi
    elif [[ "$canonical_home" != '/home/minios' ]]; then
        fail '生产 minios home 必须精确为 /home/minios'
        return 1
    fi
    printf '%s\n' "$canonical_home"
}

validate_minios_home_creation_path() {
    local expected_home="$1"
    local home_parent="${expected_home%/*}"
    local parent_type
    local parent_uid
    local parent_mode
    if [[ ! -d "$home_parent" || -L "$home_parent" ]]; then
        fail "minios home 父目录必须是现有普通目录：$home_parent"
        return 1
    fi
    assert_no_symlink_components "$home_parent" || return $?
    IFS='|' read -r parent_type parent_uid parent_mode < <(stat -c '%F|%u|%a' -- "$home_parent")
    if [[ "$parent_type" != 'directory' || "$parent_uid" != '0' \
        || ! "$parent_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$parent_mode & 8#022)) -ne 0 ]]; then
        fail "minios home 父目录必须 root 拥有且组/其他用户不可写：$home_parent"
        return 1
    fi
    if [[ -e "$expected_home" || -L "$expected_home" ]]; then
        fail "拒绝在已有 minios home 上执行 useradd：$expected_home"
        return 1
    fi
}

select_useradd_command() {
    local command='/usr/sbin/useradd'
    local canonical_command
    if [[ -n "${MINIOS_USERADD_EXECUTABLE:-}" ]]; then
        if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" != '1' ]]; then
            fail '生产模式禁止覆盖 useradd'
            return 1
        fi
        canonical_command="$(realpath -e -- "$MINIOS_USERADD_EXECUTABLE")" || return $?
        if [[ "$MINIOS_USERADD_EXECUTABLE" != "$canonical_command" \
            || ! -f "$canonical_command" || -L "$MINIOS_USERADD_EXECUTABLE" \
            || ! -x "$canonical_command" ]]; then
            fail "测试 useradd 必须是测试根内的可信可执行普通文件：$MINIOS_USERADD_EXECUTABLE"
            return 1
        fi
        if ! is_test_path "$canonical_command"; then
            fail "测试 useradd 越过已验证测试根：$canonical_command"
            return 1
        fi
        assert_no_symlink_components "$canonical_command" || return $?
        command="$canonical_command"
    fi
    printf '%s\n' "$command"
}

ensure_target_user() {
    local expected_home
    local useradd_command
    validate_target_user_name || return $?
    if getent passwd "$target_user" >/dev/null 2>&1; then
        resolve_target_user
        return
    fi
    if [[ "$target_user" != 'minios' || "$environment_kind" != 'wsl' \
        || ( "$mode" != 'system-only' && "$mode" != 'all' ) || EUID -ne 0 ]]; then
        fail "目标用户不存在且当前阶段禁止创建：$target_user mode=$mode kind=$environment_kind uid=$EUID"
        return 1
    fi
    expected_home="$(select_expected_minios_home)" || return $?
    validate_minios_home_creation_path "$expected_home" || return $?
    useradd_command="$(select_useradd_command)" || return $?
    if ! "$useradd_command" --create-home --shell /bin/bash -- minios; then
        fail '创建 minios 用户失败'
        return 1
    fi
    resolve_target_user || return $?
    if [[ "$target_home" != "$expected_home" ]]; then
        fail "新建 minios home 与固定路径不一致：$target_home"
        return 1
    fi
}

validate_user_owned_existing_components() {
    local base="$1"
    local candidate="$2"
    local current="$base"
    local relative="${candidate#"$base"}"
    local component
    local item_stat
    local item_type
    local item_uid
    local item_mode
    assert_no_symlink_components "$base" || return $?
    item_stat="$(stat -c '%F|%u|%a' -- "$base")" || {
        fail "无法重新读取目标用户 home 元数据：$base"
        return 1
    }
    IFS='|' read -r item_type item_uid item_mode <<<"$item_stat"
    if [[ "$item_type" != 'directory' || "$item_uid" != "$target_uid" ]] \
        || ! mode_is_root_safe "$item_mode"; then
        fail "目标用户 home 必须保持 target-owned 且不可由组/其他用户写：$base $item_stat"
        return 1
    fi
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
            item_stat="$(stat -c '%F|%u|%a' -- "$current")" || {
                fail "无法读取用户路径组件元数据：$current"
                return 1
            }
            IFS='|' read -r item_type item_uid item_mode <<<"$item_stat"
            if [[ "$item_type" != 'directory' ]] || ! mode_is_root_safe "$item_mode"; then
                fail "用户路径组件必须是不可由组/其他用户写的普通目录：$current $item_stat"
                return 1
            fi
            if [[ "$current" == "$candidate" ]]; then
                if [[ "$item_uid" != "$target_uid" ]]; then
                    fail "最终 environment root 必须由目标用户拥有：$current $item_stat"
                    return 1
                fi
            elif [[ "$item_uid" != "$target_uid" && "$item_uid" != '0' ]]; then
                fail "用户路径中间组件只能由目标用户或 UID0 拥有：$current $item_stat"
                return 1
            fi
        fi
    done
}

validate_environment_root() {
    local requested_root
    local lexical_root
    local resolved_root
    if [[ ${MINIOS_ENV_ROOT+x} == x && -z "${MINIOS_ENV_ROOT}" ]]; then
        fail 'MINIOS_ENV_ROOT 不能是空值'
        return 1
    fi
    if [[ "$environment_kind" == 'container' ]]; then
        requested_root="${MINIOS_ENV_ROOT:-/opt/miniorangeos-dev}"
    else
        requested_root="${MINIOS_ENV_ROOT:-$target_home/.local/share/miniorangeos-dev}"
    fi
    if [[ "$requested_root" != /* ]]; then
        fail "MINIOS_ENV_ROOT 必须是绝对路径：$requested_root"
        return 1
    fi
    lexical_root="$(realpath -ms -- "$requested_root")" || {
        fail "需要支持 -ms 的 GNU realpath 才能词法校验 MINIOS_ENV_ROOT：$requested_root"
        return 1
    }
    if [[ "$requested_root" != "$lexical_root" ]]; then
        fail "MINIOS_ENV_ROOT 必须是无点段、无重复分隔符的规范绝对路径：$requested_root"
        return 1
    fi
    environment_root="$lexical_root"
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
        local root_type
        local root_uid
        local root_mode
        root_stat="$(stat -c '%F|%u|%a' -- "$environment_root")" || {
            fail "无法读取容器 environment root 元数据：$environment_root"
            return 1
        }
        IFS='|' read -r root_type root_uid root_mode <<<"$root_stat"
        if [[ "$root_type" != 'directory' || "$root_uid" != "$target_uid" ]] \
            || ! mode_is_root_safe "$root_mode"; then
            fail "容器 environment root owner/type/mode 不匹配：$root_stat"
            return 1
        fi
    fi
    assert_no_symlink_components "$environment_root" || return $?
    if [[ -e "$environment_root" || -L "$environment_root" ]]; then
        resolved_root="$(realpath -e -- "$environment_root")" || {
            fail "无法解析现有 MINIOS_ENV_ROOT：$environment_root"
            return 1
        }
    else
        resolved_root="$(realpath -m -- "$environment_root")" || {
            fail "无法解析缺失的 MINIOS_ENV_ROOT：$environment_root"
            return 1
        }
    fi
    if [[ "$resolved_root" != "$environment_root" ]]; then
        fail "MINIOS_ENV_ROOT 解析结果与词法路径不一致：lexical=$environment_root resolved=$resolved_root"
        return 1
    fi
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
    validate_test_configuration || return $?
    validate_ubuntu_release || return $?
    validate_isolation_identity || return $?
    ensure_target_user || return $?
    validate_environment_root || return $?
    validate_wsl_configuration_path || return $?
}

validate_package_state_directory() {
    local state_directory="$environment_root/state"
    local resolved_state
    local item_type
    local item_uid
    local item_mode
    if [[ ! -e "$state_directory" && ! -L "$state_directory" ]]; then
        fail "package state 目录不存在：$state_directory"
        return 1
    fi
    if [[ ! -d "$state_directory" || -L "$state_directory" ]]; then
        fail "package state 必须是非 symlink 普通目录：$state_directory"
        return 1
    fi
    assert_no_symlink_components "$state_directory" || return $?
    resolved_state="$(realpath -e -- "$state_directory")" || return $?
    if [[ "$resolved_state" != "$state_directory" \
        || "$state_directory" != "$environment_root/state" ]]; then
        fail "package state canonical 边界不匹配：$state_directory"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$state_directory")
    if [[ "$item_type" != 'directory' || "$item_uid" != "$target_uid" \
        || ! "$item_mode" =~ ^[0-7]{3,4}$ \
        || $((8#$item_mode & 8#022)) -ne 0 ]]; then
        fail "package state 必须 target-owned 且组/其他用户不可写：type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

validate_package_lock_at() {
    local state_anchor="$1"
    local lock_path="$state_anchor/apt-packages.lock"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -e "$lock_path" && ! -L "$lock_path" ]]; then
        return 0
    fi
    if [[ ! -f "$lock_path" || -L "$lock_path" ]]; then
        fail "package lock 必须是非 symlink 普通文件：$lock_path"
        return 1
    fi
    IFS='|' read -r item_type item_uid item_mode < <(stat -c '%F|%u|%a' -- "$lock_path")
    if [[ ( "$item_type" != 'regular file' && "$item_type" != 'regular empty file' ) \
        || "$item_uid" != "$target_uid" || "$item_mode" != '644' ]]; then
        fail "package lock owner/type/mode 不匹配：type=$item_type uid=$item_uid mode=$item_mode"
        return 1
    fi
}

reject_existing_package_lock_partials_at() {
    local state_anchor="$1"
    local partial
    for partial in "$state_anchor"/apt-packages.lock.partial.*; do
        if [[ -e "$partial" || -L "$partial" ]]; then
            fail "拒绝预存 package lock partial（普通文件或 symlink）：$partial"
            return 1
        fi
    done
}

prepare_package_state_as_target() {
    if ((EUID == 0)) || [[ "$(id -u)" != "$target_uid" || "$(id -un)" != "$target_user" ]]; then
        fail 'package state 准备阶段必须由目标普通用户执行'
        return 1
    fi
    validate_environment_root || return $?
    local state_directory="$environment_root/state"
    if [[ ! -e "$environment_root" && ! -L "$environment_root" ]]; then
        (umask 022; mkdir -m 0755 -- "$environment_root") || return $?
        validate_environment_root || return $?
    fi
    if [[ ! -e "$state_directory" && ! -L "$state_directory" ]]; then
        (umask 022; mkdir -m 0755 -- "$state_directory") || return $?
    fi
    validate_environment_root || return $?
    validate_package_state_directory || return $?
    validate_package_lock_at "$state_directory" || return $?
    reject_existing_package_lock_partials_at "$state_directory"
}

recover_package_state_after_crash() {
    local state_directory="$environment_root/state"
    local item_type
    local item_uid
    local item_mode
    if [[ ! -e "$state_directory" && ! -L "$state_directory" ]]; then
        return 0
    fi
    IFS='|' read -r item_type item_uid item_mode \
        < <(stat -c '%F|%u|%a' -- "$state_directory") || return $?
    if [[ "$item_type" == 'directory' && "$item_uid" == '0' \
        && "$item_mode" == '700' ]]; then
        /usr/bin/python3 -I -B "$SCRIPT_DIR/lib/package_state_writer.py" \
            --recover-only \
            --environment-root "$environment_root" \
            --target-uid "$target_uid" \
            --target-gid "$target_gid"
    fi
}

write_package_lock_with_helper() {
    if ((EUID != 0)); then
        fail 'package lock helper 必须由 root phase 执行'
        return 1
    fi
    local package
    local package_lock_content
    local -a helper_arguments=(
        --environment-root "$environment_root"
        --target-uid "$target_uid"
        --target-gid "$target_gid"
    )
    if ! package_lock_content="$({
        for package in "${APPROVED_PACKAGES[@]}"; do
            dpkg-query -W -f='${Package}=${Version}\n' "$package"
        done
    })"; then
        fail '无法收集 approved package 版本'
        return 1
    fi
    if [[ -n "${MINIOS_PACKAGE_STATE_RACE_PHASE:-}" ]]; then
        if [[ "${MINIOS_BOOTSTRAP_TEST_MODE:-}" != '1' ]]; then
            fail 'package state race 仅允许显式测试模式'
            return 1
        fi
        helper_arguments+=(
            --test-root "$test_root"
            --race-phase "$MINIOS_PACKAGE_STATE_RACE_PHASE"
            --race-state "${FAKE_RACE_STATE:-}"
            --race-original "${FAKE_RACE_ORIGINAL:-}"
            --race-outside "${FAKE_RACE_OUTSIDE:-}"
        )
    fi
    printf '%s\n' "$package_lock_content" \
        | /usr/bin/python3 -I -B "$SCRIPT_DIR/lib/package_state_writer.py" "${helper_arguments[@]}"
}

identity_environment_arguments() {
    printf '%s\0' \
        "MINIOS_ENV_ROOT=$environment_root" \
        "WSL_DISTRO_NAME=${WSL_DISTRO_NAME:-}" \
        "MINIOS_CONTAINER=${MINIOS_CONTAINER:-}" \
        "MINIOS_BOOTSTRAP_TEST_MODE=${MINIOS_BOOTSTRAP_TEST_MODE:-}" \
        "MINIOS_BOOTSTRAP_TEST_ROOT=${MINIOS_BOOTSTRAP_TEST_ROOT:-}" \
        "MINIOS_USERADD_EXECUTABLE=${MINIOS_USERADD_EXECUTABLE:-}" \
        "MINIOS_EXPECTED_MINIOS_HOME=${MINIOS_EXPECTED_MINIOS_HOME:-}" \
        "MINIOS_OS_RELEASE_FILE=${MINIOS_OS_RELEASE_FILE:-}" \
        "MINIOS_WSL_CONF_PATH=${MINIOS_WSL_CONF_PATH:-}" \
        "MINIOS_RUNTIME_PROBE_ROOT=${MINIOS_RUNTIME_PROBE_ROOT:-}" \
        "MINIOS_WSL_IDENTITY_FILE=${MINIOS_WSL_IDENTITY_FILE:-}" \
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
    preflight || return $?
    if ((EUID != 0)); then
        fail '--system-only 必须由 root 执行'
        return 1
    fi
    recover_package_state_after_crash || return $?
    run_as_target "$SCRIPT_DIR/bootstrap-inside.sh" --prepare-package-state --target-user "$target_user" || return $?
    validate_package_state_directory || return $?
    validate_package_lock_at "$environment_root/state" || return $?
    reject_existing_package_lock_partials_at "$environment_root/state" || return $?
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${APPROVED_PACKAGES[@]}"
    write_package_lock_with_helper || return $?
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
    provision-wsl-identity)
        provision_wsl_identity
        ;;
    system-only)
        run_system_phase
        ;;
    toolchain-only)
        run_toolchain_phase
        ;;
    write-package-lock)
        fail '--write-package-lock 已由单进程 openat helper 取代'
        exit 2
        ;;
    prepare-package-state)
        preflight
        prepare_package_state_as_target
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
