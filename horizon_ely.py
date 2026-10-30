#!/usr/bin/env python3
"""Патчер исходников Horizon. Не запускает лаунчер и не устанавливает ПО."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse

PACKAGE = Path(__file__).resolve().parent
STATE = '.horizon-ely-patch'


def configure_output() -> None:
    # Windows pipes may otherwise use cp1252 and reject Russian messages.
    if os.name == 'nt':
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='backslashreplace')


configure_output()


class PatchError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise PatchError('Git: ' + result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout.decode('utf-8', errors='replace').strip()


def safe_path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in ('..', '.', '') for p in parts.parts):
        raise PatchError('Недопустимый путь в манифесте.')
    if '\\' in relative or ':' in relative:
        raise PatchError('Недопустимый путь в манифесте.')
    path = root.joinpath(*parts.parts)
    node = path
    while node != root:
        if node.is_symlink():
            raise PatchError(f'Символическая ссылка не поддерживается: {node}')
        node = node.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise PatchError('Путь выходит за пределы исходников.')
    return path


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    fd, temp = tempfile.mkstemp(prefix='.ely-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_package() -> dict:
    manifest = json.loads((PACKAGE / 'compatibility.json').read_text('utf-8'))
    for entry in manifest['files']:
        source = safe_path(PACKAGE, 'payload/' + entry['path'])
        if digest(source.read_bytes()) != entry['after']:
            raise PatchError(f"Повреждён пакет: {entry['path']}")
    return manifest


def current_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise PatchError(f'Ожидался обычный файл: {path}')
    return digest(path.read_bytes())


def check(root: Path, manifest: dict) -> None:
    if git(root, 'rev-parse', 'HEAD') != manifest['base_commit']:
        raise PatchError('Ревизия не поддерживается. Нужен commit ' + manifest['base_commit'])
    if (root / STATE).exists():
        raise PatchError('Найдена предыдущая операция. Используйте status или rollback.')
    if (root / (STATE + '-restored')).exists():
        raise PatchError('Переместите архив предыдущего отката перед новой операцией.')
    for entry in manifest['files']:
        path = safe_path(root, entry['path'])
        if current_hash(path) != entry['before']:
            raise PatchError(f"Исходник отличается от проверенного: {entry['path']}")
    print('Ревизия и все изменяемые файлы соответствуют манифесту.')


def restore(root: Path, state: dict) -> None:
    state_dir = root / STATE
    # Verify every backup before touching any target.
    for entry in state['files']:
        if entry['before'] is not None:
            backup = safe_path(state_dir, 'backup/' + entry['path'])
            if current_hash(backup) != entry['before']:
                raise PatchError('Резервная копия повреждена: ' + entry['path'])
    for entry in state['files']:
        path = safe_path(root, entry['path'])
        if entry['before'] is None:
            if path.exists():
                path.unlink()
        else:
            atomic_write(path, safe_path(state_dir, 'backup/' + entry['path']).read_bytes())


def apply(root: Path, manifest: dict) -> None:
    check(root, manifest)
    state_dir = root / STATE
    state_dir.mkdir(mode=0o700)
    state = {'base_commit': manifest['base_commit'], 'files': manifest['files'], 'phase': 'backup'}
    # No target writes until all backups and the state journal are complete.
    try:
        for entry in state['files']:
            if entry['before'] is not None:
                path = safe_path(root, entry['path'])
                atomic_write(safe_path(state_dir, 'backup/' + entry['path']), path.read_bytes())
        state['phase'] = 'applying'
        atomic_write(state_dir / 'state.json', json.dumps(state, indent=2).encode())
    except BaseException:
        shutil.rmtree(state_dir)
        raise
    try:
        for entry in state['files']:
            path = safe_path(root, entry['path'])
            if current_hash(path) != entry['before']:
                raise PatchError('Файл изменился во время операции: ' + entry['path'])
            atomic_write(path, safe_path(PACKAGE, 'payload/' + entry['path']).read_bytes())
        state['phase'] = 'applied'
        atomic_write(state_dir / 'state.json', json.dumps(state, indent=2).encode())
    except BaseException:
        # Keep the journal: rollback can recover an interrupted application.
        print('Операция прервана. Резервные копии сохранены; используйте rollback.', file=sys.stderr)
        raise
    print('Патч применён к исходникам. Теперь требуется сборка обоих компонентов.')


def read_state(root: Path) -> dict:
    path = root / STATE / 'state.json'
    if not path.is_file() or path.is_symlink() or (root / STATE).is_symlink():
        raise PatchError('Журнал патча не найден или является ссылкой.')
    state = json.loads(path.read_text('utf-8'))
    expected = load_package()
    if state.get('files') != expected['files'] or state.get('base_commit') != expected['base_commit']:
        raise PatchError('Журнал не соответствует этой версии пакета.')
    return state


def status(root: Path) -> None:
    state = read_state(root)
    changed = [e['path'] for e in state['files']
               if current_hash(safe_path(root, e['path'])) != e['after']]
    print('Состояние:', state['phase'])
    print('Изменено файлов:', len(state['files']))
    if changed:
        print('Файлы, отличающиеся от результата патча:')
        for name in changed:
            print('  ' + name)
    else:
        print('Все файлы соответствуют результату патча.')


def rollback(root: Path) -> None:
    state = read_state(root)
    archive = root / (STATE + '-restored')
    if archive.exists():
        raise PatchError('Архив предыдущего отката уже существует: ' + str(archive))
    for entry in state['files']:
        found = current_hash(safe_path(root, entry['path']))
        if found not in (entry['before'], entry['after']):
            raise PatchError('Есть последующие изменения; откат остановлен: ' + entry['path'])
    restore(root, state)
    # Retain the snapshot outside the active state directory for manual recovery.
    (root / STATE).rename(archive)
    print('Исходники восстановлены. Копии сохранены:', archive)
    print('Скомпилированные программы и пользовательские аккаунты не изменялись.')


def bundle(root: Path, destination: Path, target: str | None) -> None:
    state = read_state(root)
    for e in state['files']:
        if current_hash(safe_path(root, e['path'])) != e['after']:
            raise PatchError('Исходники изменились после патча: ' + e['path'])
    suffix = '.exe' if (target and 'windows' in target) or (not target and os.name == 'nt') else ''
    relative = Path(target) / 'release' if target else Path('release')
    launcher = root / 'launcher/target' / relative / ('horizon-launcher' + suffix)
    client = root / 'target' / relative / ('horizon-client' + suffix)
    if not launcher.is_file() or not client.is_file():
        raise PatchError('Не найдены обе release-сборки. Сначала соберите лаунчер и клиент.')
    marker = b'HORIZON_ELY_NATIVE_V1'
    if marker not in client.read_bytes() or marker not in launcher.read_bytes():
        raise PatchError('В бинарных файлах нет маркера интеграции. Нужна пересборка.')
    if destination.exists():
        raise PatchError('Каталог назначения уже существует. Выберите новый каталог.')
    destination.mkdir(parents=True)
    for path in (launcher, client):
        shutil.copy2(path, destination / path.name)
    shutil.copy2(PACKAGE / 'THIRD_PARTY_NOTICES.md', destination)
    shutil.copy2(PACKAGE / 'LICENSE', destination)
    print('Два бинарных файла собраны в:', destination)
    print('Программа не запускалась. Это не установщик и не проверка работоспособности.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_get(url: str, limit: int) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or
            parsed.port not in (None, 443) or parsed.hostname not in
            {'skinsystem.ely.by', 'textures.ely.by', 'ely.by', 'textures.minecraft.net'}):
        raise PatchError('Сервис вернул неподдерживаемый адрес текстуры.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Horizon-Ely-Integration/0.1'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        if response.status != 200:
            raise PatchError('Сервис не вернул текстуру.')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise PatchError('Ответ сервиса превышает допустимый размер.')
    return data


def png(data: bytes, cape: bool) -> None:
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise PatchError('Ответ сервиса не является PNG.')
    size = struct.unpack('>II', data[16:24])
    allowed = {(64, 32), (22, 17)} if cape else {(64, 64), (64, 32)}
    if size not in allowed:
        raise PatchError('Неподдерживаемый размер PNG: ' + str(size))


def fetch_skin(name: str, destination: Path) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_]{3,16}', name):
        raise PatchError('Имя: от 3 до 16 латинских букв, цифр или _.')
    if destination.exists():
        raise PatchError('Для экспорта укажите новый каталог.')
    metadata = json.loads(public_get('https://skinsystem.ely.by/textures/' + name, 256 << 10))
    if not isinstance(metadata, dict):
        raise PatchError('Сервис вернул неподдерживаемый формат метаданных.')
    downloads = {}
    for kind, filename in [('SKIN', 'skin.png'), ('CAPE', 'cape.png')]:
        info = metadata.get(kind)
        if not isinstance(info, dict) or not isinstance(info.get('url'), str):
            continue
        # Upgrade Ely's documented legacy HTTP URLs; never send credentials.
        url = info['url']
        if url.startswith('http://'):
            url = 'https://' + url[len('http://'):]
        body = public_get(url, 2 << 20)
        png(body, kind == 'CAPE')
        downloads[filename] = body
    if not downloads:
        raise PatchError('У сервиса нет доступных текстур для этого имени.')
    destination.mkdir(parents=True)
    for filename, body in downloads.items():
        atomic_write(destination / filename, body)
    skin_info = metadata.get('SKIN')
    details = skin_info.get('metadata') if isinstance(skin_info, dict) else None
    model = details.get('model', 'classic') if isinstance(details, dict) else 'classic'
    result = {'name': name, 'model': 'slim' if model == 'slim' else 'classic',
              'files': sorted(downloads)}
    atomic_write(destination / 'textures.json', json.dumps(result, ensure_ascii=False, indent=2).encode())
    print('Публичные текстуры сохранены:', destination)
    print('Модель:', result['model'])
    print('Это экспорт текстур, а не вход в аккаунт. Его подлинность проверяется через Ely.by при входе.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'apply', 'status', 'rollback', 'bundle', 'skin'])
    parser.add_argument('--source', type=Path, help='Копия исходников Horizon')
    parser.add_argument('--name', help='Имя Ely.by для экспорта публичных текстур')
    parser.add_argument('--out', type=Path, help='Новый каталог для двух готовых бинарных файлов')
    parser.add_argument('--target', help='Rust target triple, если сборка выполнялась с --target')
    args = parser.parse_args()
    try:
        if args.action == 'skin':
            if not args.name or not args.out:
                raise PatchError('Для skin нужны --name и --out.')
            fetch_skin(args.name, args.out.expanduser().absolute())
            return 0
        if not args.source:
            raise PatchError('Требуется --source.')
        root = args.source.expanduser().resolve(strict=True)
        if args.action == 'status':
            status(root)
        elif args.action == 'rollback':
            rollback(root)
        elif args.action == 'bundle':
            if not args.out:
                raise PatchError('Для bundle требуется --out.')
            bundle(root, args.out.expanduser().absolute(), args.target)
        else:
            manifest = load_package()
            if args.action == 'check':
                check(root, manifest)
            else:
                apply(root, manifest)
        return 0
    except (PatchError, OSError, ValueError, KeyError) as error:
        print('Ошибка:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
