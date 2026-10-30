#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 4 ]; then
    printf 'Использование: bootstrap.sh OWNER/REPO TAG SHA256 НОВЫЙ_КАТАЛОГ\n' >&2
    exit 1
fi
repo="$1"; tag="$2"; digest="$3"; destination="$4"
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || exit 1
[[ "$tag" =~ ^[A-Za-z0-9_.-]+$ ]] || exit 1
command -v python3 >/dev/null 2>&1 || { printf 'Нужен Python 3.10+.\n' >&2; exit 1; }
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
curl --proto '=https' --proto-redir '=https' -fL \
    "https://raw.githubusercontent.com/$repo/$tag/bootstrap.py" \
    -o "$temporary/bootstrap.py"
python3 "$temporary/bootstrap.py" --repo "$repo" --tag "$tag" \
    --sha256 "$digest" --destination "$destination"
