"""Installation fixtures contain inert headers, never runnable applications."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('installed', Path(__file__).resolve().parents[1] / 'installed.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fake_binary(system, arch):
    if system == 'Windows':
        header = bytearray(64)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 60, 64)
        return bytes(header) + b'PE\0\0' + struct.pack('<H', 0x8664 if arch == 'x86_64' else 0xAA64) + b'HORIZON_ELY_NATIVE_V1'
    if system == 'Linux':
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', header, 18, 62 if arch == 'x86_64' else 183)
        return bytes(header) + b'HORIZON_ELY_NATIVE_V1'
    return b'\xcf\xfa\xed\xfe' + struct.pack('<I', 0x1000007 if arch == 'x86_64' else 0x100000C) + bytes(56) + b'HORIZON_ELY_NATIVE_V1'


class InstalledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.data = root / 'original-data'
        self.version = self.data / 'versions/test-tag'
        resources = self.version / '.local/horizon-client/26.3'
        resources.mkdir(parents=True)
        (resources / 'fixture.bin').write_bytes(b'inert resources')
        (self.version / '.installed').write_text('')
        (self.data / 'accounts.json').write_text('{"original":true}')
        (self.data / 'settings.json').write_text('{"selected":"test-tag"}')
        self.bundle = root / 'bundle'
        self.bundle.mkdir()
        system, arch = module.host_target()
        suffix = '.exe' if system == 'Windows' else ''
        names = ['horizon-launcher' + suffix, 'horizon-client' + suffix]
        for name in names:
            (self.bundle / name).write_bytes(fake_binary(system, arch))
        for name in ['installed.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'INSTALLED.md']:
            (self.bundle / name).write_bytes(b'inert fixture')
            names.append(name)
        self.manifest = {'schema': 1, 'base_commit': module.BASE, 'system': system,
                         'architecture': arch, 'files': {n: module.sha(self.bundle / n) for n in names}}
        (self.bundle / 'BUNDLE.json').write_text(json.dumps(self.manifest))
        self.launcher = root / ('original-launcher' + suffix)
        self.launcher.write_bytes(fake_binary(system, arch))
        self.target = root / 'HorizonEly'
        self.args = argparse.Namespace(action='install', launcher=self.launcher, data=self.data,
                                       version=None, bundle=self.bundle, target=self.target, experimental=True)

    def test_install_and_rollback_preserve_original_files_and_new_worlds(self):
        before = module.sha(self.launcher)
        module.install(self.args)
        self.assertEqual(module.sha(self.launcher), before)
        self.assertEqual((self.data / 'accounts.json').read_text(), '{"original":true}')
        self.assertFalse((self.target / 'launcher-data/accounts.json').exists())
        copied = self.target / 'launcher-data/versions/test-tag/.local/horizon-client/26.3/fixture.bin'
        self.assertEqual(copied.read_bytes(), b'inert resources')
        world = self.target / 'game/keep-this-world.txt'
        world.write_text('keep')
        module.rollback(self.target)
        self.assertEqual(world.read_text(), 'keep')
        self.assertEqual(module.sha(self.launcher), before)

    def test_corrupt_bundle_never_creates_target(self):
        (self.bundle / 'LICENSE').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            module.install(self.args)
        self.assertFalse(self.target.exists())

    def test_missing_prepared_resources_is_rejected(self):
        (self.version / '.installed').unlink()
        with self.assertRaises(ValueError):
            module.install(self.args)
        self.assertFalse(self.target.exists())

    def test_rollback_refuses_modified_program(self):
        module.install(self.args)
        (self.target / 'LICENSE').write_text('changed')
        with self.assertRaises(ValueError):
            module.rollback(self.target)
        self.assertTrue((self.target / 'installed.py').exists())

    def test_inspect_is_read_only(self):
        self.args.action = 'inspect'
        module.install(self.args)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
