#!/usr/bin/env python3
"""Установка готовой Ely-сборки рядом с существующим Horizon. Без компиляции."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import stat
import sys
import tempfile

if os.name == 'nt':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')

BASE = '56f968e11c7627536cb6a83420caddce7e3acb8f'
STATE = 'INSTALL_STATE.json'


def sha(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _sha(f)


def _sha(stream) -> str:
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def binary_target(path: Path) -> tuple[str, str]:
    with path.open('rb') as f:
        head = f.read(64)
        if head[:2] == b'MZ':
            if len(head) != 64:
                raise ValueError('Повреждён PE-заголовок.')
            offset = struct.unpack_from('<I', head, 60)[0]
            if offset > 16 << 20:
                raise ValueError('Недопустимый PE-заголовок.')
            f.seek(offset)
            pe = f.read(6)
            if len(pe) != 6 or pe[:4] != b'PE\0\0':
                raise ValueError('Некорректная подпись PE.')
            arch = {0x8664: 'x86_64', 0xAA64: 'aarch64'}.get(struct.unpack_from('<H', pe, 4)[0])
            system = 'Windows'
        elif head[:5] == b'\x7fELF\x02':
            if len(head) < 20 or head[5] != 1:
                raise ValueError('Поддерживается только little-endian ELF64.')
            arch = {62: 'x86_64', 183: 'aarch64'}.get(struct.unpack_from('<H', head, 18)[0])
            system = 'Linux'
        elif len(head) >= 8 and head[:4] == b'\xcf\xfa\xed\xfe':
            arch = {0x1000007: 'x86_64', 0x100000C: 'aarch64'}.get(struct.unpack_from('<I', head, 4)[0])
            system = 'Darwin'
        else:
            raise ValueError('Неподдерживаемый формат бинарного файла: ' + str(path))
        if not arch:
            raise ValueError('Архитектура бинарного файла не поддерживается.')
        return system, arch


def host_target() -> tuple[str, str]:
    machine = platform.machine().lower()
    return platform.system(), {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)


def find_launcher(explicit: Path | None) -> Path:
    name = 'horizon-launcher.exe' if platform.system() == 'Windows' else 'horizon-launcher'
    if explicit:
        path = explicit.expanduser().absolute()
        if path.is_file():
            return path
        raise ValueError('Указанный лаунчер не найден.')
    candidates = set()
    on_path = shutil.which(name)
    if on_path:
        candidates.add(Path(on_path).resolve())
    home = Path.home()
    folders = [home / 'Downloads', home / 'Documents', home / 'Desktop',
               home / 'Загрузки', home / 'Документы', home / 'Рабочий стол',
               home / '.local/bin', home / 'bin']
    for folder in folders:
        if folder.is_dir():
            for pattern in (name, '*/' + name, '*/*/' + name):
                candidates.update(p.resolve() for p in folder.glob(pattern) if p.is_file())
    for folder in [Path('/Applications'), home / 'Applications']:
        for app in ('Horizon.app', 'Horizon Launcher.app'):
            path = folder / app / 'Contents/MacOS/horizon-launcher'
            if path.is_file():
                candidates.add(path.resolve())
    if len(candidates) != 1:
        raise ValueError('Лаунчер не найден однозначно. Укажите --launcher ПОЛНЫЙ_ПУТЬ.')
    return candidates.pop()


def data_directory(explicit: Path | None) -> Path:
    if explicit:
        return explicit.expanduser().absolute()
    if os.environ.get('HORIZON_LAUNCHER_HOME'):
        return Path(os.environ['HORIZON_LAUNCHER_HOME']).expanduser().absolute()
    system = platform.system()
    if system == 'Windows':
        base = Path(os.environ['APPDATA'])
    elif system == 'Darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    return base / 'horizon-launcher'


def version_name(name: str) -> str:
    if not name or name in ('.', '..') or any(c in name for c in '/\\:'):
        raise ValueError('Недопустимое имя установленной версии.')
    return name


def prepared_version(data: Path, requested: str | None) -> tuple[str, Path]:
    settings_file = data / 'settings.json'
    settings = json.loads(settings_file.read_text('utf-8')) if settings_file.is_file() else {}
    selected = requested or settings.get('selected')
    versions = data / 'versions'
    def ready(name):
        path = versions / version_name(name)
        resources = path / '.local/horizon-client/26.3'
        return path.is_dir() and (path / '.installed').is_file() and resources.is_dir()
    if selected:
        if not ready(selected):
            raise ValueError('Выбранная версия не установлена или не подготовлена для Minecraft 26.3.')
        return selected, versions / selected
    candidates = [p.name for p in versions.iterdir() if p.is_dir() and ready(p.name)] if versions.is_dir() else []
    if len(candidates) != 1:
        raise ValueError('Подготовленная версия не найдена однозначно. Укажите --version ТЕГ.')
    return candidates[0], versions / candidates[0]


def inventory_tree(root: Path) -> tuple[int, int]:
    def regular_node(path):
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('В каталоге версии найдена ссылка: ' + str(path))
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError('Необычный тип файла в каталоге версии: ' + str(path))
    regular_node(root)
    count = size = 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            regular_node(path)
        for name in files:
            count += 1
            size += (Path(folder) / name).stat().st_size
    return count, size


def bundle_info(bundle: Path) -> dict:
    manifest = json.loads((bundle / 'BUNDLE.json').read_text('utf-8'))
    if manifest.get('schema') != 1 or manifest.get('base_commit') != BASE:
        raise ValueError('Формат или исходная ревизия готовой сборки не поддерживаются.')
    system, arch = host_target()
    if (manifest['system'], manifest['architecture']) != (system, arch):
        raise ValueError('Готовая сборка предназначена для другой ОС или архитектуры.')
    suffix = '.exe' if system == 'Windows' else ''
    required = {'horizon-launcher' + suffix, 'horizon-client' + suffix,
                'installed.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'INSTALLED.md'}
    if set(manifest['files']) != required:
        raise ValueError('Неполный или неизвестный состав готовой сборки.')
    for name, expected in manifest['files'].items():
        path = bundle / name
        if not path.is_file() or path.is_symlink() or sha(path) != expected:
            raise ValueError('Повреждён файл готовой сборки: ' + name)
    for name in ('horizon-launcher', 'horizon-client'):
        path = bundle / (name + suffix)
        if binary_target(path) != (system, arch):
            raise ValueError('Бинарный файл не соответствует манифесту.')
        if b'HORIZON_ELY_NATIVE_V1' not in path.read_bytes():
            raise ValueError('В бинарном файле нет маркера интеграции.')
    return manifest


def install(args) -> None:
    launcher = find_launcher(args.launcher)
    if binary_target(launcher) != host_target():
        raise ValueError('Установленный лаунчер не соответствует ОС/архитектуре.')
    data = data_directory(args.data)
    tag, version = prepared_version(data, args.version)
    print('Установленный лаунчер:', launcher)
    print('SHA-256 лаунчера:', sha(launcher))
    print('Версия игры по данным установки:', tag)
    print('Ревизия самого лаунчера по этим данным не подтверждена.')
    count, size = inventory_tree(version)
    print('Копирование подготовленной версии:', count, 'файлов;', size, 'байт.')
    print('Совместимость формата ресурсов с изменённым клиентом остаётся экспериментальной.')
    if args.action == 'inspect':
        print('Диагностика завершена. Программы не запускались, файлы не изменялись.')
        return
    if not args.bundle or not args.target:
        raise ValueError('Для install нужны --bundle и --target.')
    bundle = args.bundle.expanduser().resolve(strict=True)
    manifest = bundle_info(bundle)
    if not args.experimental:
        raise ValueError('Сборка экспериментальная. Для установки нужен явный --experimental.')
    target = args.target.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Каталог назначения уже существует. Выберите новый --target.')
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target.parent).free < size + sum((bundle / n).stat().st_size for n in manifest['files']) + (256 << 20):
        raise ValueError('Недостаточно места для независимой копии версии.')
    temporary = Path(tempfile.mkdtemp(prefix='.horizon-ely-install-', dir=target.parent))
    try:
        tracked = {}
        for name in manifest['files']:
            shutil.copy2(bundle / name, temporary / name)
            tracked[name] = sha(temporary / name)
        shutil.copy2(bundle / 'BUNDLE.json', temporary / 'BUNDLE.json')
        tracked['BUNDLE.json'] = sha(temporary / 'BUNDLE.json')
        private = temporary / 'launcher-data'
        private.mkdir(mode=0o700)
        shutil.copytree(version, private / 'versions' / tag)
        # Reuse installed resources through a separate copy, never a shared junction.
        (private / 'settings.json').write_text(json.dumps({'selected': tag, 'install_new_versions': False}, indent=2), encoding='utf-8')
        (temporary / 'game').mkdir(mode=0o700)
        if manifest['system'] == 'Windows':
            name = 'Start-HorizonEly.cmd'
            text = '@echo off\r\nsetlocal\r\nset "HORIZON_LAUNCHER_HOME=%~dp0launcher-data"\r\nset "HORIZON_HOME=%~dp0game"\r\n"%~dp0horizon-launcher.exe" %*\r\n'
        else:
            name = 'Start-HorizonEly.command' if manifest['system'] == 'Darwin' else 'Start-HorizonEly.sh'
            text = '#!/bin/sh\nset -eu\napp_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport HORIZON_LAUNCHER_HOME="$app_dir/launcher-data"\nexport HORIZON_HOME="$app_dir/game"\nexec "$app_dir/horizon-launcher" "$@"\n'
        (temporary / name).write_bytes(text.encode('utf-8'))
        (temporary / name).chmod(0o755)
        tracked[name] = sha(temporary / name)
        state = {'schema': 1, 'original_launcher': str(launcher), 'original_launcher_sha256': sha(launcher),
                 'original_data': str(data), 'copied_version': tag, 'files': tracked, 'phase': 'installed'}
        (temporary / STATE).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
        if target.exists():
            raise ValueError('Каталог назначения появился во время операции.')
        temporary.rename(target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    print('Отдельная Ely-сборка установлена:', target)
    print('Запуск:', target / name)
    print('Исходный лаунчер, аккаунты и миры не изменены. Новая сборка не запускалась.')


def rollback(target: Path) -> None:
    if target.is_symlink():
        raise ValueError('Каталог назначения является ссылкой.')
    state = json.loads((target / STATE).read_text('utf-8'))
    if state.get('schema') != 1 or state.get('phase') != 'installed':
        raise ValueError('Нет активной установки для отката.')
    allowed = {'horizon-launcher', 'horizon-client', 'horizon-launcher.exe', 'horizon-client.exe',
               'installed.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'INSTALLED.md', 'BUNDLE.json',
               'Start-HorizonEly.cmd', 'Start-HorizonEly.command', 'Start-HorizonEly.sh'}
    if not set(state['files']).issubset(allowed):
        raise ValueError('Журнал содержит неизвестные пути.')
    for name, expected in state['files'].items():
        path = target / name
        if path.is_symlink() or (path.exists() and sha(path) != expected):
            raise ValueError('Файл изменился после установки, откат остановлен: ' + name)
    # Keep the running installer until other files have been removed.
    for name in sorted(state['files'], key=lambda n: n == 'installed.py'):
        (target / name).unlink(missing_ok=True)
    state['phase'] = 'removed'
    (target / STATE).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Добавленные программы удалены. Данные и миры сохранены:', target)
    print('Исходная установка Horizon не изменена.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'install', 'rollback'])
    parser.add_argument('--launcher', type=Path)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--version')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--experimental', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'rollback':
            if not args.target:
                raise ValueError('Укажите --target установленной Ely-сборки.')
            rollback(args.target.expanduser().absolute())
        else:
            install(args)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Ошибка:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
