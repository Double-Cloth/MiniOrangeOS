#!/usr/bin/env bash
set -euo pipefail

# 从固定源码构建项目私有的 i686-elf Binutils/GCC 工具链。
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../environment/lib/common.sh
source "$SCRIPT_DIR/../environment/lib/common.sh" || exit $?
minios_load_versions || exit $?

print_plan=0
download_only=0
force_build=0

usage() {
    printf '用法：%s [--print-plan] [--download-only] [--force]\n' "${0##*/}" >&2
}

set_mode_once() {
    local mode_name="$1"
    local current_value="$2"
    if [[ "$current_value" == "1" ]]; then
        minios_die "重复参数：$mode_name"
        return 1
    fi
}

while (($# > 0)); do
    case "$1" in
        --print-plan)
            set_mode_once "$1" "$print_plan" || { usage; exit 2; }
            print_plan=1
            ;;
        --download-only)
            set_mode_once "$1" "$download_only" || { usage; exit 2; }
            download_only=1
            ;;
        --force)
            set_mode_once "$1" "$force_build" || { usage; exit 2; }
            force_build=1
            ;;
        *)
            minios_log "FAIL" "未知参数：$1"
            usage
            exit 2
            ;;
    esac
    shift
done

if ((print_plan + download_only + force_build > 1)); then
    minios_log "FAIL" "参数冲突：--print-plan、--download-only 和 --force 不能组合"
    usage
    exit 2
fi

readonly PREFIX="$MINIOS_ENV_ROOT/toolchain"
readonly DOWNLOAD_DIR="$MINIOS_ENV_ROOT/downloads"
readonly SOURCE_DIR="$MINIOS_ENV_ROOT/sources"
readonly BUILD_DIR="$MINIOS_ENV_ROOT/build"
readonly STATE_DIR="$MINIOS_ENV_ROOT/state"
readonly BINUTILS_ARCHIVE="$DOWNLOAD_DIR/binutils-$MINIOS_BINUTILS_VERSION.tar.xz"
readonly GCC_ARCHIVE="$DOWNLOAD_DIR/gcc-$MINIOS_GCC_VERSION.tar.xz"
readonly BINUTILS_SOURCE="$SOURCE_DIR/binutils-$MINIOS_BINUTILS_VERSION"
readonly GCC_SOURCE="$SOURCE_DIR/gcc-$MINIOS_GCC_VERSION"
readonly BINUTILS_BUILD="$BUILD_DIR/binutils-$MINIOS_BINUTILS_VERSION"
readonly GCC_BUILD="$BUILD_DIR/gcc-$MINIOS_GCC_VERSION"
readonly TOOLCHAIN_MARKER="$STATE_DIR/toolchain.env"

readonly -a BINUTILS_CONFIGURE_ARGS=(
    "--target=$MINIOS_TARGET"
    "--prefix=$PREFIX"
    --with-sysroot
    --disable-nls
    --disable-werror
)
readonly -a GCC_CONFIGURE_ARGS=(
    "--target=$MINIOS_TARGET"
    "--prefix=$PREFIX"
    --disable-nls
    --enable-languages=c
    --without-headers
    --disable-multilib
    --disable-shared
    --disable-threads
)
readonly -a GCC_BUILD_TARGETS=(all-gcc all-target-libgcc)
readonly -a GCC_INSTALL_TARGETS=(install-gcc install-target-libgcc)

print_build_plan() {
    printf 'target=%s\n' "$MINIOS_TARGET"
    printf 'binutils_version=%s\n' "$MINIOS_BINUTILS_VERSION"
    printf 'gcc_version=%s\n' "$MINIOS_GCC_VERSION"
    printf 'prefix=%s\n' "$PREFIX"
    printf 'binutils_configure=%s\n' "${BINUTILS_CONFIGURE_ARGS[*]}"
    printf 'gcc_configure=%s\n' "${GCC_CONFIGURE_ARGS[*]}"
    printf 'binutils_build_targets=all\n'
    printf 'binutils_install_targets=install\n'
    printf 'gcc_build_targets=%s\n' "${GCC_BUILD_TARGETS[*]}"
    printf 'gcc_install_targets=%s\n' "${GCC_INSTALL_TARGETS[*]}"
}

if ((print_plan == 1)); then
    print_build_plan
    exit 0
fi

if [[ "${MINIOS_BUILD_JOBS:-}" =~ ^[1-9][0-9]*$ ]]; then
    build_jobs="$MINIOS_BUILD_JOBS"
elif [[ -n "${MINIOS_BUILD_JOBS:-}" ]]; then
    minios_log "FAIL" "MINIOS_BUILD_JOBS 必须是正整数：$MINIOS_BUILD_JOBS"
    exit 2
elif build_jobs="$(nproc)"; then
    if [[ ! "$build_jobs" =~ ^[1-9][0-9]*$ ]]; then
        minios_log "FAIL" "nproc 返回无效并行度：$build_jobs"
        exit 1
    fi
else
    status=$?
    minios_log "FAIL" "无法确定构建并行度：status=$status"
    exit "$status"
fi
readonly build_jobs

assert_owned_path_without_symlink() {
    local candidate="$1"
    local checked_path
    local relative_path
    local component
    local status

    if checked_path="$(minios_assert_path_within_environment_root "$candidate")"; then
        :
    else
        status=$?
        return "$status"
    fi
    if [[ "$checked_path" == "$MINIOS_ENV_ROOT" ]]; then
        minios_die "拒绝把 environment root 作为 Task 3 清理目标"
        return 1
    fi

    relative_path="${candidate#"$MINIOS_ENV_ROOT"/}"
    checked_path="$MINIOS_ENV_ROOT"
    IFS='/' read -r -a path_components <<<"$relative_path"
    for component in "${path_components[@]}"; do
        checked_path="$checked_path/$component"
        if [[ -L "$checked_path" ]]; then
            minios_die "拒绝符号链接清理边界：$checked_path"
            return 1
        fi
    done
}

remove_owned_path() {
    local candidate="$1"
    local status
    if rm -rf -- "$candidate"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法清理 Task 3 路径：$candidate status=$status"
        return "$status"
    fi
}

force_cleanup() {
    local candidate
    local status
    local -a cleanup_paths=("$BINUTILS_BUILD" "$GCC_BUILD" "$PREFIX")

    # 先完成全部预检，避免后续路径越界时已经发生部分删除。
    for candidate in "${cleanup_paths[@]}"; do
        if assert_owned_path_without_symlink "$candidate"; then
            :
        else
            status=$?
            return "$status"
        fi
    done
    for candidate in "${cleanup_paths[@]}"; do
        remove_owned_path "$candidate" || return $?
    done
    minios_log "INFO" "已定向清理工具链构建目录和 prefix"
}

if ((force_build == 1)); then
    force_cleanup || exit $?
fi

download_sources() {
    minios_download_verified \
        "$MINIOS_BINUTILS_URL" \
        "$MINIOS_BINUTILS_SHA256" \
        "$BINUTILS_ARCHIVE" || return $?
    minios_download_verified \
        "$MINIOS_GCC_URL" \
        "$MINIOS_GCC_SHA256" \
        "$GCC_ARCHIVE" || return $?
}

download_sources || exit $?
if ((download_only == 1)); then
    printf 'download_status=complete\n'
    exit 0
fi

validate_archive_members() {
    local archive="$1"
    local expected_name="$2"
    local status
    if python3 - "$archive" "$expected_name" <<'PY'
import posixpath
import sys
import tarfile

archive, expected = sys.argv[1:]

def reject(member: tarfile.TarInfo, reason: str) -> None:
    print(f"unsafe archive member: {member.name!r}: {reason}", file=sys.stderr)
    raise SystemExit(1)

with tarfile.open(archive, "r:*") as source:
    for member in source:
        name = member.name.rstrip("/")
        normalized = posixpath.normpath(name)
        if not name or name.startswith("/") or normalized in {"", ".", ".."}:
            reject(member, "absolute or empty path")
        if normalized.startswith("../") or normalized.split("/", 1)[0] != expected:
            reject(member, "path escapes expected top-level directory")
        if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
            reject(member, "unsupported special member type")
        if member.issym() or member.islnk():
            target = member.linkname
            if not target or target.startswith("/"):
                reject(member, "absolute or empty link target")
            if member.issym():
                resolved = posixpath.normpath(
                    posixpath.join(posixpath.dirname(normalized), target)
                )
            else:
                resolved = posixpath.normpath(target)
            if resolved.startswith("../") or resolved.split("/", 1)[0] != expected:
                reject(member, "link target escapes expected top-level directory")
PY
    then
        :
    else
        status=$?
        minios_log "FAIL" "归档成员预检失败：$archive status=$status"
        return "$status"
    fi
}

source_stamp_matches() {
    local stamp="$1"
    local component="$2"
    local version="$3"
    local archive_sha256="$4"
    local expected_name="$5"
    local line_count

    if [[ ! -f "$stamp" || -L "$stamp" ]]; then
        return 1
    fi
    if line_count="$(wc -l <"$stamp")"; then
        :
    else
        return $?
    fi
    [[ "$line_count" == "4" ]] || return 1
    grep -Fqx -- "component=$component" "$stamp" || return 1
    grep -Fqx -- "version=$version" "$stamp" || return 1
    grep -Fqx -- "archive_sha256=$archive_sha256" "$stamp" || return 1
    grep -Fqx -- "expected_top_level=$expected_name" "$stamp" || return 1
}

write_source_stamp() {
    local stamp="$1"
    local component="$2"
    local version="$3"
    local archive_sha256="$4"
    local expected_name="$5"
    local partial_stamp="$stamp.partial"
    local status

    assert_owned_path_without_symlink "$stamp" || return $?
    assert_owned_path_without_symlink "$partial_stamp" || return $?
    if rm -f -- "$partial_stamp"; then :; else return $?; fi
    if printf '%s\n' \
        "component=$component" \
        "version=$version" \
        "archive_sha256=$archive_sha256" \
        "expected_top_level=$expected_name" >"$partial_stamp"; then
        :
    else
        status=$?
        rm -f -- "$partial_stamp" || true
        return "$status"
    fi
    if mv -f -- "$partial_stamp" "$stamp"; then
        :
    else
        status=$?
        rm -f -- "$partial_stamp" || true
        return "$status"
    fi
}

extract_source() {
    local archive="$1"
    local final_directory="$2"
    local component="$3"
    local version="$4"
    local archive_sha256="$5"
    local expected_name="${final_directory##*/}"
    local partial_directory="$SOURCE_DIR/.extract-$expected_name.partial"
    local extracted_directory="$partial_directory/$expected_name"
    local source_stamp="$final_directory/.minios-source.env"
    local extracted_stamp="$extracted_directory/.minios-source.env"
    local status

    assert_owned_path_without_symlink "$final_directory" || return $?
    assert_owned_path_without_symlink "$partial_directory" || return $?
    if mkdir -p -- "$SOURCE_DIR"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法创建源码根目录：$SOURCE_DIR status=$status"
        return "$status"
    fi
    remove_owned_path "$partial_directory" || return $?
    if [[ -e "$final_directory" || -L "$final_directory" ]]; then
        if [[ -d "$final_directory" \
            && -f "$final_directory/configure" \
            && -x "$final_directory/configure" \
            && ! -L "$final_directory/configure" ]] \
            && source_stamp_matches \
                "$source_stamp" "$component" "$version" \
                "$archive_sha256" "$expected_name"; then
            return 0
        fi
        minios_die "源码缓存缺少或不匹配项目 stamp，拒绝复用：$final_directory"
        return 1
    fi
    validate_archive_members "$archive" "$expected_name" || return $?
    if mkdir -p -- "$partial_directory"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法创建解包临时目录：$partial_directory status=$status"
        return "$status"
    fi
    if tar -xf "$archive" -C "$partial_directory"; then
        :
    else
        status=$?
        remove_owned_path "$partial_directory" || true
        minios_log "FAIL" "源码解包失败：$archive status=$status"
        return "$status"
    fi
    if [[ ! -f "$extracted_directory/configure" \
        || ! -x "$extracted_directory/configure" \
        || -L "$extracted_directory/configure" ]]; then
        remove_owned_path "$partial_directory" || true
        minios_die "源码包缺少可信 configure：$archive"
        return 1
    fi
    if write_source_stamp \
        "$extracted_stamp" "$component" "$version" \
        "$archive_sha256" "$expected_name"; then
        :
    else
        status=$?
        remove_owned_path "$partial_directory" || true
        minios_log "FAIL" "无法写入源码缓存 stamp：$extracted_stamp status=$status"
        return "$status"
    fi
    if mv -- "$extracted_directory" "$final_directory"; then
        :
    else
        status=$?
        remove_owned_path "$partial_directory" || true
        minios_log "FAIL" "无法原子就位源码目录：$final_directory status=$status"
        return "$status"
    fi
    remove_owned_path "$partial_directory" || return $?
}

extract_source \
    "$BINUTILS_ARCHIVE" "$BINUTILS_SOURCE" binutils \
    "$MINIOS_BINUTILS_VERSION" "$MINIOS_BINUTILS_SHA256" || exit $?
extract_source \
    "$GCC_ARCHIVE" "$GCC_SOURCE" gcc \
    "$MINIOS_GCC_VERSION" "$MINIOS_GCC_SHA256" || exit $?

if lock_fingerprint="$(
    printf '%s\n' \
        "target=$MINIOS_TARGET" \
        "binutils_version=$MINIOS_BINUTILS_VERSION" \
        "binutils_sha256=$MINIOS_BINUTILS_SHA256" \
        "gcc_version=$MINIOS_GCC_VERSION" \
        "gcc_sha256=$MINIOS_GCC_SHA256" \
        "prefix=$PREFIX" \
        "binutils_configure=${BINUTILS_CONFIGURE_ARGS[*]}" \
        "gcc_configure=${GCC_CONFIGURE_ARGS[*]}" \
        "gcc_build_targets=${GCC_BUILD_TARGETS[*]}" \
        "gcc_install_targets=${GCC_INSTALL_TARGETS[*]}" |
        sha256sum | cut -d ' ' -f 1
)"; then
    readonly lock_fingerprint
else
    status=$?
    minios_log "FAIL" "无法计算工具链锁指纹：status=$status"
    exit "$status"
fi

cleanup_stale_selfchecks() {
    local candidate
    local nullglob_was_set=0
    local status
    local -a stale_directories

    if shopt -q nullglob; then nullglob_was_set=1; fi
    shopt -s nullglob
    stale_directories=("$MINIOS_ENV_ROOT"/.toolchain-selfcheck.*)
    if ((nullglob_was_set == 0)); then shopt -u nullglob; fi
    for candidate in "${stale_directories[@]}"; do
        if assert_owned_path_without_symlink "$candidate"; then :; else return $?; fi
        if remove_owned_path "$candidate"; then
            :
        else
            status=$?
            return "$status"
        fi
    done
}

read_tool_versions() {
    local gcc_path="$PREFIX/bin/$MINIOS_TARGET-gcc"
    local ld_path="$PREFIX/bin/$MINIOS_TARGET-ld"
    local selfcheck_directory
    local selfcheck_source
    local selfcheck_object
    local selfcheck_status=0
    local cleanup_status
    local status

    cleanup_stale_selfchecks || return $?
    assert_owned_path_without_symlink "$gcc_path" || return $?
    assert_owned_path_without_symlink "$ld_path" || return $?
    if [[ ! -f "$gcc_path" || ! -x "$gcc_path" || -L "$gcc_path" ]]; then
        return 1
    fi
    if [[ ! -f "$ld_path" || ! -x "$ld_path" || -L "$ld_path" ]]; then
        return 1
    fi
    if gcc_dumpmachine="$($gcc_path -dumpmachine)"; then
        :
    else
        status=$?
        return "$status"
    fi
    if [[ "$gcc_dumpmachine" != "$MINIOS_TARGET" ]]; then
        return 1
    fi
    if gcc_version_output="$($gcc_path --version)"; then
        gcc_version_output="${gcc_version_output%%$'\n'*}"
    else
        status=$?
        return "$status"
    fi
    if ld_version_output="$($ld_path --version)"; then
        ld_version_output="${ld_version_output%%$'\n'*}"
    else
        status=$?
        return "$status"
    fi
    if [[ -z "$gcc_version_output" || -z "$ld_version_output" ]]; then
        return 1
    fi
    if [[ " $gcc_version_output " != *" $MINIOS_GCC_VERSION "* ]]; then
        minios_log "FAIL" "GCC 版本与锁文件不匹配：$gcc_version_output"
        return 1
    fi
    if [[ " $ld_version_output " != *" $MINIOS_BINUTILS_VERSION "* ]]; then
        minios_log "FAIL" "Binutils 版本与锁文件不匹配：$ld_version_output"
        return 1
    fi
    if libgcc_path="$($gcc_path -print-libgcc-file-name)"; then
        libgcc_path="${libgcc_path%%$'\n'*}"
    else
        status=$?
        return "$status"
    fi
    case "$libgcc_path" in
        "$PREFIX"/*) ;;
        *)
            minios_log "FAIL" "libgcc 不属于项目 prefix：${libgcc_path:-missing}"
            return 1
            ;;
    esac
    assert_owned_path_without_symlink "$libgcc_path" || return $?
    if [[ ! -f "$libgcc_path" || -L "$libgcc_path" || ! -s "$libgcc_path" ]]; then
        minios_log "FAIL" "libgcc 必须是 prefix 内非空普通文件：$libgcc_path"
        return 1
    fi

    if selfcheck_directory="$(mktemp -d "$MINIOS_ENV_ROOT/.toolchain-selfcheck.XXXXXX")"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法创建工具链自检临时目录：status=$status"
        return "$status"
    fi
    if assert_owned_path_without_symlink "$selfcheck_directory"; then
        :
    else
        selfcheck_status=$?
    fi
    selfcheck_source="$selfcheck_directory/verify.c"
    selfcheck_object="$selfcheck_directory/verify.o"
    if ((selfcheck_status == 0)); then
        if printf '%s\n' 'void minios_toolchain_verify(void) {}' >"$selfcheck_source"; then
            :
        else
            selfcheck_status=$?
        fi
    fi
    if ((selfcheck_status == 0)); then
        if "$gcc_path" -ffreestanding -fno-pie -c \
            "$selfcheck_source" -o "$selfcheck_object"; then
            :
        else
            selfcheck_status=$?
        fi
    fi
    if ((selfcheck_status == 0)) \
        && [[ ! -f "$selfcheck_object" \
            || -L "$selfcheck_object" \
            || ! -s "$selfcheck_object" ]]; then
        minios_log "FAIL" "交叉编译器未生成非空普通对象文件"
        selfcheck_status=1
    fi
    if remove_owned_path "$selfcheck_directory"; then
        :
    else
        cleanup_status=$?
        if ((selfcheck_status == 0)); then
            selfcheck_status=$cleanup_status
        else
            minios_log "FAIL" "自检失败后清理临时目录也失败：status=$cleanup_status"
        fi
    fi
    if ((selfcheck_status != 0)); then
        return "$selfcheck_status"
    fi
}

marker_has_line() {
    local expected_line="$1"
    grep -Fqx -- "$expected_line" "$TOOLCHAIN_MARKER"
}

toolchain_is_current() {
    assert_owned_path_without_symlink "$STATE_DIR" || return $?
    assert_owned_path_without_symlink "$TOOLCHAIN_MARKER" || return $?
    if [[ ! -f "$TOOLCHAIN_MARKER" || -L "$TOOLCHAIN_MARKER" ]]; then
        return 1
    fi
    if ! read_tool_versions; then
        return 1
    fi
    marker_has_line "lock_fingerprint=$lock_fingerprint" || return 1
    marker_has_line "target=$MINIOS_TARGET" || return 1
    marker_has_line "prefix=$PREFIX" || return 1
    marker_has_line "gcc_dumpmachine=$gcc_dumpmachine" || return 1
    marker_has_line "gcc_version=$gcc_version_output" || return 1
    marker_has_line "ld_version=$ld_version_output" || return 1
    marker_has_line "libgcc_path=$libgcc_path" || return 1
    marker_has_line "binutils_configure=${BINUTILS_CONFIGURE_ARGS[*]}" || return 1
    marker_has_line "gcc_configure=${GCC_CONFIGURE_ARGS[*]}" || return 1
    marker_has_line "gcc_build_targets=${GCC_BUILD_TARGETS[*]}" || return 1
    marker_has_line "gcc_install_targets=${GCC_INSTALL_TARGETS[*]}" || return 1
}

assert_owned_path_without_symlink "$STATE_DIR" || exit $?
assert_owned_path_without_symlink "$TOOLCHAIN_MARKER" || exit $?
if toolchain_is_current; then
    printf 'toolchain_status=up-to-date\n'
    exit 0
fi

run_in_directory() {
    local directory="$1"
    shift
    local status
    if (cd -- "$directory" && "$@"); then
        :
    else
        status=$?
        minios_log "FAIL" "命令执行失败：cwd=$directory command=$* status=$status"
        return "$status"
    fi
}

prepare_build_directory() {
    local directory="$1"
    local status
    assert_owned_path_without_symlink "$directory" || return $?
    if mkdir -p -- "$directory"; then
        :
    else
        status=$?
        minios_log "FAIL" "无法创建构建目录：$directory status=$status"
        return "$status"
    fi
}

prepare_build_directory "$BINUTILS_BUILD" || exit $?
run_in_directory "$BINUTILS_BUILD" \
    "$BINUTILS_SOURCE/configure" "${BINUTILS_CONFIGURE_ARGS[@]}" || exit $?
run_in_directory "$BINUTILS_BUILD" make -j "$build_jobs" all || exit $?
run_in_directory "$BINUTILS_BUILD" make -j "$build_jobs" install || exit $?

prepare_build_directory "$GCC_BUILD" || exit $?
PATH="$PREFIX/bin:$PATH"
export PATH
run_in_directory "$GCC_BUILD" \
    "$GCC_SOURCE/configure" "${GCC_CONFIGURE_ARGS[@]}" || exit $?
run_in_directory "$GCC_BUILD" \
    make -j "$build_jobs" "${GCC_BUILD_TARGETS[@]}" || exit $?
run_in_directory "$GCC_BUILD" \
    make -j "$build_jobs" "${GCC_INSTALL_TARGETS[@]}" || exit $?

if read_tool_versions; then
    :
else
    status=$?
    minios_log "FAIL" "工具链构建后自检失败：target=$MINIOS_TARGET status=$status"
    exit "$status"
fi

assert_owned_path_without_symlink "$TOOLCHAIN_MARKER" || exit $?
if mkdir -p -- "$STATE_DIR"; then
    :
else
    status=$?
    minios_log "FAIL" "无法创建状态目录：$STATE_DIR status=$status"
    exit "$status"
fi
marker_partial="$TOOLCHAIN_MARKER.partial"
readonly marker_partial
assert_owned_path_without_symlink "$marker_partial" || exit $?
if rm -f -- "$marker_partial"; then
    :
else
    status=$?
    minios_log "FAIL" "无法清理状态临时文件：$marker_partial status=$status"
    exit "$status"
fi
if printf '%s\n' \
    "lock_fingerprint=$lock_fingerprint" \
    "target=$MINIOS_TARGET" \
    "prefix=$PREFIX" \
    "binutils_version=$MINIOS_BINUTILS_VERSION" \
    "binutils_sha256=$MINIOS_BINUTILS_SHA256" \
    "gcc_source_version=$MINIOS_GCC_VERSION" \
    "gcc_source_sha256=$MINIOS_GCC_SHA256" \
    "binutils_configure=${BINUTILS_CONFIGURE_ARGS[*]}" \
    "gcc_configure=${GCC_CONFIGURE_ARGS[*]}" \
    "gcc_build_targets=${GCC_BUILD_TARGETS[*]}" \
    "gcc_install_targets=${GCC_INSTALL_TARGETS[*]}" \
    "gcc_dumpmachine=$gcc_dumpmachine" \
    "gcc_version=$gcc_version_output" \
    "ld_version=$ld_version_output" \
    "libgcc_path=$libgcc_path" >"$marker_partial"; then
    :
else
    status=$?
    rm -f -- "$marker_partial" || true
    minios_log "FAIL" "无法写入工具链状态：$marker_partial status=$status"
    exit "$status"
fi
if mv -f -- "$marker_partial" "$TOOLCHAIN_MARKER"; then
    :
else
    status=$?
    rm -f -- "$marker_partial" || true
    minios_log "FAIL" "无法原子更新工具链状态：$TOOLCHAIN_MARKER status=$status"
    exit "$status"
fi

printf 'toolchain_status=built\n'
