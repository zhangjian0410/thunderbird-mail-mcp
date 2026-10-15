from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts import deploy_send

class DeploymentTests(unittest.TestCase):
    def test_installed_checkout_can_check_without_private_baseline(self):
        with TemporaryDirectory() as d:
            root=Path(d); (root/'server.py').write_text('content')
            (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').write_text('runtime')
            (root/'native-host.json').write_text('{}')
            with patch.object(deploy_send,'SOURCE',root),patch.object(deploy_send,'FILES',['server.py']):
                self.assertEqual(deploy_send.prepare(root,root,root/'native')[root/'server.py'][0],b'content')
                other=root/'other'; other.mkdir(); (other/'server.py').write_text('unrelated')
                with self.assertRaisesRegex(ValueError,'Concurrent change'): deploy_send.prepare(other,root,root/'native')
    def test_partial_install_failure_restores_original_bytes_and_mode(self):
        with TemporaryDirectory() as d:
            root=Path(d); first=root/'first'; first.write_bytes(b'old'); first.chmod(0o600)
            second=root/'second'; second.symlink_to(first)
            with self.assertRaises(ValueError):
                deploy_send.install({first:(b'new',0o644),second:(b'unwanted',0o644)},root/'rollback')
            self.assertEqual(first.read_bytes(),b'old');self.assertEqual(first.stat().st_mode&0o777,0o600)
            self.assertTrue(second.is_symlink())
