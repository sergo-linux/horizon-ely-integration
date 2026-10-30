#!/usr/bin/env python3
"""Загрузка исходного пакета из GitHub Release с обязательной SHA-256."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password or
                not (host == 'github.com' or host.endswith('.githubusercontent.com'))):
            raise ValueError('Неожиданное перенаправление GitHub.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, help='ВЛАДЕЛЕЦ/РЕПОЗИТОРИЙ')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        parser.error('Недопустимое имя репозитория.')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', args.sha256):
        parser.error('Нужна SHA-256 из 64 шестнадцатеричных символов.')
    destination = args.destination.expanduser().absolute()
    if destination.exists():
        parser.error('Каталог назначения уже существует.')
    tag = urllib.parse.quote(args.tag, safe='')
    url = f'https://github.com/{args.repo}/releases/download/{tag}/horizon-elyby-integration.zip'
    with urllib.request.build_opener(GitHubRedirects).open(url, timeout=30) as response:
        data = response.read((20 << 20) + 1)
    if len(data) > 20 << 20:
        raise ValueError('Архив слишком большой.')
    if hashlib.sha256(data).hexdigest() != args.sha256.lower():
        raise ValueError('SHA-256 архива не совпадает. Распаковка отменена.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.ely-download-', dir=destination.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if sum(m.file_size for m in members) > 32 << 20:
                raise ValueError('Распакованный пакет слишком большой.')
            seen = set()
            for member in members:
                p = PurePosixPath(member.filename)
                if (p.is_absolute() or '..' in p.parts or '\\' in member.filename or
                        ':' in member.filename or not p.parts or
                        any(part.endswith((' ', '.')) for part in p.parts) or
                        any(part.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL',
                            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
                            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
                            for part in p.parts) or
                        p.parts[0] != 'horizon-elyby-integration' or
                        stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError('Недопустимый путь в архиве.')
                key = member.filename.casefold()
                if key in seen:
                    raise ValueError('Дублирующийся путь в архиве.')
                seen.add(key)
                target = temporary.joinpath(*p.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
        package = temporary / 'horizon-elyby-integration'
        if not (package / 'compatibility.json').is_file() or not (package / 'horizon_ely.py').is_file():
            raise ValueError('В архиве нет обязательных файлов пакета.')
        if destination.exists():
            raise ValueError('Каталог назначения появился во время загрузки.')
        package.rename(destination)
    finally:
        shutil.rmtree(temporary)
    print('Исходный пакет проверен и сохранён:', destination)
    print('Патч не применялся. Сначала выполните команду check из README.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Ошибка: ' + str(error))
