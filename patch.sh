#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null 2>&1 || {
    printf 'Ошибка: нужен Python 3.10 или новее.\n' >&2
    exit 1
}
exec python3 "$script_dir/horizon_ely.py" "$@"
