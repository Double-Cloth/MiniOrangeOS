#!/usr/bin/env bash
set -euo pipefail

if (($# == 0)); then
    printf '%s\n' 'run-inside: 缺少要执行的命令' >&2
    exit 2
fi

readonly SOURCE_ROOT='/source'
workspace="$(mktemp -d /tmp/miniorangeos-run.XXXXXX)"
readonly workspace

cp -a "$SOURCE_ROOT/." "$workspace/"
cd "$workspace"
exec "$@"
