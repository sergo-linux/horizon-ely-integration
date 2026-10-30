#!/usr/bin/env python3
"""Создать воспроизводимый ZIP исходников без .research и локальных данных."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / 'dist'
out.mkdir(exist_ok=True)
archive = out / 'horizon-elyby-integration.zip'
roots = ['horizon_ely.py', 'patch.sh', 'patch.ps1', 'bootstrap.py', 'bootstrap.sh',
         'bootstrap.ps1', 'README.md', 'PUBLISHING.md', 'VALIDATION.md',
         'THIRD_PARTY_NOTICES.md', 'LICENSE', 'compatibility.json', 'horizon-ely.patch',
         '.gitignore', '.gitattributes', '.github', 'native', 'payload', 'tests', 'tools']
files = []
for name in roots:
    path = root / name
    if path.is_dir():
        files.extend(p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    else:
        files.append(path)
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError('Ссылки в исходный архив не включаются.')
        relative = 'horizon-elyby-integration/' + path.relative_to(root).as_posix()
        info = zipfile.ZipInfo(relative, date_time=(2026, 10, 30, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (0o100644 << 16)
        z.writestr(info, path.read_bytes())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(out / 'SHA256SUMS').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
print(archive)
print(digest)
