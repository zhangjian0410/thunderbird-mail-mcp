from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from scripts.check_secrets import forbidden_path, tracked_snapshot


class SecretScannerTests(unittest.TestCase):
    def test_rejects_local_artifacts_but_keeps_example_configs_and_source(self):
        for name in ('native-host.json', 'nested/rollback.json', '.env', '.env.production',
                     'profiles.ini', 'Inbox', 'data/mail.mbox', 'send.sqlite3',
                     'deployment-backups/run/0', 'extension.xpi', 'send.db-wal', 'send.sqlite3-journal',
                     '.venv/lib/python/site-packages/example.py'):
            with self.subTest(name=name):
                self.assertTrue(forbidden_path(name))
        for name in ('extension/manifest.json', 'uv.lock', '.env.example', '.env.sample',
                     '.gitleaks.toml', '.github/workflows/ci.yml'):
            with self.subTest(name=name):
                self.assertFalse(forbidden_path(name))

    def test_snapshot_cannot_follow_tracked_symlinks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / 'repository'
            repository.mkdir()
            subprocess.run(['git', 'init', '-q', str(repository)], check=True)
            outside = root / 'outside.txt'
            outside.write_text('synthetic local content')
            (repository / 'link.txt').symlink_to(outside)
            subprocess.run(['git', '-C', str(repository), 'add', 'link.txt'], check=True)
            destination = root / 'snapshot'
            destination.mkdir()
            with self.assertRaisesRegex(ValueError, 'symlink'):
                tracked_snapshot(repository, destination)
            self.assertFalse((destination / 'link.txt').exists())
