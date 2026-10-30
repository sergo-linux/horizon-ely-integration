"""Изолированные проверки. Не обращаются к настоящему лаунчеру или ключнице."""
import hashlib
import importlib.util
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'horizon_ely.py'
spec = importlib.util.spec_from_file_location('horizon_ely', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'source'
        self.package = Path(self.temp.name).resolve() / 'package'
        self.root.mkdir()
        (self.package / 'payload/src').mkdir(parents=True)
        (self.root / 'src').mkdir()
        (self.root / 'src/account.rs').write_bytes(b'original\r\n')
        (self.package / 'payload/src/account.rs').write_bytes(b'patched\n')
        (self.package / 'payload/src/new.rs').write_bytes(b'new\n')
        sha = lambda b: hashlib.sha256(b).hexdigest()
        self.manifest = {'base_commit': 'a' * 40, 'files': [
            {'path': 'src/account.rs', 'before': sha(b'original\r\n'), 'after': sha(b'patched\n')},
            {'path': 'src/new.rs', 'before': None, 'after': sha(b'new\n')},
        ]}
        (self.package / 'compatibility.json').write_text(json.dumps(self.manifest))
        self.addCleanup(patch.stopall)
        patch.object(module, 'PACKAGE', self.package).start()
        patch.object(module, 'git', return_value='a' * 40).start()

    def test_apply_and_byte_exact_rollback(self):
        module.apply(self.root, module.load_package())
        self.assertEqual((self.root / 'src/account.rs').read_bytes(), b'patched\n')
        module.rollback(self.root)
        self.assertEqual((self.root / 'src/account.rs').read_bytes(), b'original\r\n')
        self.assertFalse((self.root / 'src/new.rs').exists())

    def test_post_patch_user_edit_blocks_whole_rollback(self):
        module.apply(self.root, self.manifest)
        (self.root / 'src/account.rs').write_bytes(b'user edit')
        with self.assertRaises(module.PatchError):
            module.rollback(self.root)
        self.assertEqual((self.root / 'src/new.rs').read_bytes(), b'new\n')

    def test_wrong_revision_and_changed_source_are_rejected(self):
        with patch.object(module, 'git', return_value='b' * 40):
            with self.assertRaises(module.PatchError):
                module.apply(self.root, self.manifest)
        (self.root / 'src/account.rs').write_bytes(b'other source')
        with self.assertRaises(module.PatchError):
            module.apply(self.root, self.manifest)
        self.assertFalse((self.root / module.STATE).exists())

    def test_corrupt_backup_cannot_overwrite_targets(self):
        module.apply(self.root, self.manifest)
        (self.root / module.STATE / 'backup/src/account.rs').write_bytes(b'corrupt')
        with self.assertRaises(module.PatchError):
            module.rollback(self.root)
        self.assertEqual((self.root / 'src/account.rs').read_bytes(), b'patched\n')

    def test_interrupted_apply_can_be_rolled_back(self):
        original = module.atomic_write
        def interrupted(path, data):
            if path == self.root / 'src/new.rs':
                raise OSError('simulated interruption')
            original(path, data)
        with patch.object(module, 'atomic_write', side_effect=interrupted):
            with self.assertRaises(OSError):
                module.apply(self.root, self.manifest)
        module.rollback(self.root)
        self.assertEqual((self.root / 'src/account.rs').read_bytes(), b'original\r\n')

    def test_tampered_payload_is_rejected(self):
        (self.package / 'payload/src/account.rs').write_bytes(b'tampered')
        with self.assertRaises(module.PatchError):
            module.load_package()

    def test_escape_paths_are_rejected(self):
        for name in ['../outside', '/etc/passwd', 'C:/Windows/file', 'src\\file']:
            with self.assertRaises(module.PatchError):
                module.safe_path(self.root, name)

    def test_public_texture_url_rejects_credentials_and_other_origins(self):
        for url in ['http://ely.by/a', 'https://ely.by.evil.test/a',
                    'https://user:password@ely.by/a', 'https://127.0.0.1/a']:
            with self.assertRaises(module.PatchError):
                module.public_get(url, 1024)

    def test_windows_output_supports_russian_in_pipes(self):
        binary = io.BytesIO()
        stream = io.TextIOWrapper(binary, encoding='cp1252')
        with patch.object(module.os, 'name', 'nt'), patch.object(module.sys, 'stdout', stream):
            module.configure_output()
            print('Проверка кодировки')
            stream.flush()
        self.assertEqual(binary.getvalue().decode('utf-8'), 'Проверка кодировки\n')


if __name__ == '__main__':
    unittest.main()
