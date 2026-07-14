#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_ROOT="${MINIOS_CI_SOURCE_ROOT:-/source}"
readonly ARTIFACT_ROOT="${MINIOS_CI_ARTIFACT_ROOT:-/artifacts}"

if [[ ! -d "$SOURCE_ROOT" || -L "$SOURCE_ROOT" ]]; then
    printf 'ci-run: 源码根目录无效：%s\n' "$SOURCE_ROOT" >&2
    exit 2
fi
if [[ ! -d "$ARTIFACT_ROOT" || -L "$ARTIFACT_ROOT" ]]; then
    printf 'ci-run: 失败产物目录无效：%s\n' "$ARTIFACT_ROOT" >&2
    exit 2
fi

readonly source_root="$(realpath -e -- "$SOURCE_ROOT")"
readonly artifact_root="$(realpath -e -- "$ARTIFACT_ROOT")"
workspace="$(mktemp -d /tmp/miniorangeos-ci.XXXXXX)"
wrapper_directory="$(mktemp -d /tmp/miniorangeos-ci-bin.XXXXXX)"
readonly workspace wrapper_directory

cleanup() {
    rm -rf -- "$workspace" "$wrapper_directory"
}
trap cleanup EXIT

cp -a "$source_root/." "$workspace/"

readonly real_qemu="$(command -v qemu-system-i386)"
if [[ -z "$real_qemu" || ! -x "$real_qemu" ]]; then
    printf '%s\n' 'ci-run: 找不到真实 qemu-system-i386' >&2
    exit 1
fi

cat >"$wrapper_directory/qemu-system-i386" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
{
    printf '%q' "$MINIOS_REAL_QEMU"
    printf ' %q' "$@"
    printf '\n'
} >>"$MINIOS_QEMU_COMMAND_LOG"
exec "$MINIOS_REAL_QEMU" "$@"
EOF
chmod 0700 "$wrapper_directory/qemu-system-i386"

export MINIOS_REAL_QEMU="$real_qemu"
export MINIOS_QEMU_COMMAND_LOG="$artifact_root/qemu-command-lines.txt"
export PATH="$wrapper_directory:$PATH"
: >"$MINIOS_QEMU_COMMAND_LOG"

set +e
(
    set -e
    cd "$workspace"
    ./environment/verify.sh
    ./environment/with-env.sh make test
) 2>&1 | tee "$artifact_root/ci-output.log"
status=${PIPESTATUS[0]}
set -e

if ((status != 0)); then
    cp -- "$workspace/config/image-layout.json" "$artifact_root/image-layout.json"
    {
        printf 'layout_sha256  '
        sha256sum "$workspace/config/image-layout.json" | cut -d' ' -f1
        printf '\nimage artifacts remaining after failure:\n'
        while IFS= read -r -d '' image; do
            relative="${image#"$workspace"/}"
            printf '%s  size=%s  sha256=' "$relative" "$(stat -c '%s' -- "$image")"
            sha256sum "$image" | cut -d' ' -f1
        done < <(find "$workspace" -type f -name '*.img' -size -128M -print0)
    } >"$artifact_root/image-layout-summary.txt"

    while IFS= read -r -d '' log; do
        relative="${log#"$workspace"/}"
        target="$artifact_root/logs/$relative"
        mkdir -p -- "$(dirname -- "$target")"
        cp -- "$log" "$target"
    done < <(find "$workspace" -type f -name '*.log' -size -8M -print0)
fi

chmod -R a+rX -- "$artifact_root"
exit "$status"
