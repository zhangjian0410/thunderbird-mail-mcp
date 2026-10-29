import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_build_contains_runnable_extension_and_allowlisted_native_manifest(self):
        spec = importlib.util.spec_from_file_location('package_send', ROOT/'scripts/package_send.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as directory:
            output = Path(directory)
            module.build(ROOT, output, Path('/example/mail-mcp-server'))
            expected_manifest = json.loads((ROOT / 'extension/manifest.json').read_text())
            with zipfile.ZipFile(output/'thunderbird-native-send.xpi') as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['version'], expected_manifest['version'])
                self.assertIn('compose.send', manifest['permissions'])
                self.assertIn(b'forward_v1', archive.read('background.js'))
                self.assertIn(b'forward_diagnostic_v1', archive.read('background.js'))
                self.assertIn(b'beginForward', archive.read('sender.js'))
                for script in manifest['background']['scripts']:
                    self.assertTrue(archive.read(script))
                native = json.loads((output/'native-host.json').read_text())
                self.assertEqual(native['allowed_extensions'], [manifest['browser_specific_settings']['gecko']['id']])
                self.assertEqual(native['path'], '/example/mail-mcp-server/native-send-launcher')
            original = (output/'thunderbird-native-send.xpi').read_bytes()
            module.build(ROOT, output, Path('/example/mail-mcp-server'))
            self.assertEqual(original, (output/'thunderbird-native-send.xpi').read_bytes())
