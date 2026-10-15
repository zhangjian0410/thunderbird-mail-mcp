import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.test_mail_store import build_mailbox


ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_mailbox_environment_routes_legacy_and_paged_queries(self):
        with TemporaryDirectory() as directory:
            inbox = Path(directory) / 'Inbox'
            build_mailbox(inbox)
            code = '''import server
assert server.list_recent_email()[0]['message_id'] == '<weekly-1@example.test>'
result = server.query_email(senders=['weekly.sender@example.test'])
assert len(result['messages']) == 1
assert server.list_mail_folders()['folders'][0]['available'] is True
'''
            for configured in (str(inbox), '~/Inbox'):
                with self.subTest(configured=configured):
                    result = subprocess.run(
                        [sys.executable, '-c', code], cwd=ROOT,
                        env={**os.environ, 'HOME': directory, 'THUNDERBIRD_INBOX_PATH': configured},
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_launcher_runs_from_installation_with_spaces(self):
        with TemporaryDirectory() as directory:
            install = Path(directory) / 'installation with spaces'
            (install / '.venv/bin').mkdir(parents=True)
            (install / '.venv/bin/python').symlink_to(sys.executable)
            for name in ('native-send-launcher', 'native_host.py', 'mail_sender.py'):
                shutil.copy2(ROOT / name, install / name)
            message = json.dumps({'id': 1, 'op': 'poll', 'identities': [], 'accept': False}).encode()
            result = subprocess.run(
                [str(install / 'native-send-launcher')], cwd=directory,
                env={**os.environ, 'HOME': directory},
                input=struct.pack('=I', len(message)) + message,
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            size = struct.unpack('=I', result.stdout[:4])[0]
            self.assertEqual(len(result.stdout), size + 4)
            self.assertEqual(json.loads(result.stdout[4:]), {'id': 1, 'ok': True, 'result': None})
            self.assertTrue((Path(directory) / 'Library/Application Support/ThunderbirdMailMCP/send.sqlite3').is_file())
