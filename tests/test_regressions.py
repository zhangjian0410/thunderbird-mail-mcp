"""Regression cases use synthetic mail, temporary journals and temporary deployments."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings

from mail_sender import SendJournal
from mail_store import MailStore
from scripts import deploy_send, package_send
from tests.test_mail_store import build_mailbox


ROOT = Path(__file__).resolve().parents[1]


class DeploymentRegressionTests(unittest.TestCase):
    def prepare_target(self, root):
        target = root / 'installation with spaces'
        (target / '.venv/bin').mkdir(parents=True)
        (target / '.venv/bin/python').symlink_to(sys.executable)
        return target

    def test_full_deployment_launcher_handles_spaces_and_native_framing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.prepare_target(root)
            output = root / 'package'
            package_send.build(ROOT, output, target)
            changes = deploy_send.prepare(target, output, root / 'native')
            deploy_send.install(changes, root / 'backup')
            request = json.dumps({'id': 1, 'op': 'poll', 'identities': [], 'accept': False}).encode()
            result = subprocess.run(
                [str(target / 'native-send-launcher')], cwd=root,
                input=struct.pack('=I', len(request)) + request,
                env={**os.environ, 'HOME': directory}, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            size = struct.unpack('=I', result.stdout[:4])[0]
            self.assertEqual(len(result.stdout), size + 4)
            self.assertEqual(json.loads(result.stdout[4:]), {'id': 1, 'ok': True, 'result': None})
            self.assertTrue((root / 'Library/Application Support/ThunderbirdMailMCP/send.sqlite3').is_file())
            self.assertEqual(json.loads((root / 'native/com.thunderbird_mail_mcp.native_send.json').read_text())['path'],
                             str(target / 'native-send-launcher'))

    def test_check_rejects_manifest_pointing_to_another_installation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.prepare_target(root)
            output = root / 'package'
            package_send.build(ROOT, output, root / 'wrong installation')
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/deploy_send.py'),
                 '--target', str(target), '--output', str(output),
                 '--native-dir', str(root / 'native'), '--check'],
                capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Native host', result.stderr)
            self.assertFalse((root / 'native').exists())
            self.assertFalse((target / 'server.py').exists())

    def test_manifest_name_type_and_allowlist_are_validated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.prepare_target(root)
            output = root / 'package'
            package_send.build(ROOT, output, target)
            path = output / 'native-host.json'
            original = json.loads(path.read_text())
            for change in ({'name': 'wrong.host'}, {'type': 'network'},
                           {'allowed_extensions': ['other@example.test']},
                           {'allowed_extensions': original['allowed_extensions'] + ['other@example.test']},
                           {'path': 'relative/native-send-launcher'}):
                with self.subTest(change=change):
                    path.write_text(json.dumps({**original, **change}))
                    with self.assertRaisesRegex(ValueError, 'Native host'):
                        deploy_send.prepare(target, output, root / 'native')


class AttachmentRetryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1000
        self.journal = SendJournal(self.root / 'private/send.sqlite3', clock=lambda: self.now)
        self.journal.heartbeat([{'id': 'id1', 'email': 'sender@example.com'}],
                               ['attachments_v1', 'draft_v1'])
        self.payload = dict(to=['recipient@example.com'], from_email='sender@example.com',
                            subject='Synthetic subject', body='Synthetic body')
        self.files = [self.root / 'first.txt', self.root / 'second.txt']
        self.attachments = []
        for index, path in enumerate(self.files):
            path.write_bytes(f'synthetic attachment {index}'.encode())
            self.attachments.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    def test_missing_source_retries_preserve_each_durable_state(self):
        for state in ('pending', 'sending', 'sent', 'drafted', 'expired', 'unknown'):
            with self.subTest(state=state):
                self.files[0].write_bytes(b'synthetic attachment 0')
                action = 'draft' if state == 'drafted' else 'send'
                self.journal.enqueue(state, self.payload, attachments=self.attachments[:1], action=action)
                if state in ('sending', 'sent', 'drafted', 'unknown'):
                    job = self.journal.claim()
                    self.assertEqual(job['request_id'], state)
                    if state == 'sent':
                        self.journal.complete(state, job['claim_token'],
                            {'status': 'sent', 'message_id': 'synthetic@example.test', 'copy_status': 'not_verified'})
                    elif state == 'drafted':
                        self.journal.complete(state, job['claim_token'], {'status': 'drafted', 'drafts': [{'id': 1}]})
                self.now += 301 if state == 'unknown' else (61 if state == 'expired' else 16)
                expected = self.journal.status(state)
                self.files[0].unlink()
                with patch('mail_sender.snapshot_attachments', side_effect=AssertionError('Retry must use persisted metadata')):
                    actual = self.journal.enqueue(state, self.payload, attachments=self.attachments[:1], action=action)
                self.assertEqual(actual, expected)
                self.assertEqual(actual['status'], state)
                # Remove pending fixture from the claim queue before the next state case.
                if state == 'pending':
                    self.now += 61
                    self.journal.status(state)
                self.journal.heartbeat([{'id': 'id1', 'email': 'sender@example.com'}],
                                       ['attachments_v1', 'draft_v1'])
        with self.journal.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sends').fetchone()[0], 6)

    def test_missing_files_do_not_disable_payload_or_attachment_conflicts(self):
        self.journal.enqueue('original', self.payload, attachments=self.attachments)
        for path in self.files:
            path.unlink()
        cases = [
            ({**self.payload, 'body': 'different'}, self.attachments, 'send'),
            (self.payload, self.attachments, 'draft'),
            (self.payload, [{**self.attachments[0], 'sha256': '0' * 64}, self.attachments[1]], 'send'),
            (self.payload, [{**self.attachments[0], 'path': str(self.root / 'renamed.txt')}, self.attachments[1]], 'send'),
            (self.payload, list(reversed(self.attachments)), 'send'),
            (self.payload, self.attachments[:1], 'send'),
            (self.payload, None, 'send'),
        ]
        for payload, attachments, action in cases:
            with self.subTest(payload=payload, attachments=attachments, action=action):
                with self.assertRaisesRegex(ValueError, 'different message'):
                    self.journal.enqueue('original', payload, attachments=attachments, action=action)
        self.assertEqual(self.journal.status('original')['status'], 'pending')
        self.assertIsNotNone(self.journal.claim())
        self.assertIsNone(self.journal.claim())

    def test_concurrent_attachment_enqueue_still_creates_one_request(self):
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.journal.enqueue('same', self.payload, attachments=self.attachments), range(2)))
        self.assertEqual(results[0], results[1])
        job = self.journal.claim()
        self.assertEqual(job['request_id'], 'same')
        self.assertIsNone(self.journal.claim())
        with self.journal.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0], 2)


class LegacyDateRegressionTests(unittest.TestCase):
    def test_bad_dates_are_isolated_with_warning_and_valid_results_preserved(self):
        with TemporaryDirectory() as directory:
            inbox = Path(directory) / 'Inbox'
            build_mailbox(inbox)
            malformed = b''
            for date in (b'', b'Date: not-a-date\n'):
                malformed += (b'From synthetic@example.test Thu Jan  1 00:00:00 2026\n'
                              b'From: synthetic@example.test\nSubject: private synthetic marker\n' + date + b'\nbody\n')
            inbox.write_bytes(malformed + inbox.read_bytes())
            store = MailStore(inbox)
            for operation in (store.list_recent_email, lambda: store.search_email('周报'),
                              lambda: store.read_email('<other-1@example.test>')):
                with self.subTest(operation=operation):
                    with warnings.catch_warnings(record=True) as captured:
                        warnings.simplefilter('always')
                        result = operation()
                    if isinstance(result, list):
                        self.assertEqual(len(result), 2)
                        self.assertEqual(result[0]['message_id'], '<weekly-1@example.test>')
                    else:
                        self.assertEqual(result['message_id'], '<other-1@example.test>')
                    self.assertTrue(captured)
                    for item in captured:
                        self.assertIn('query_email', str(item.message))
                        self.assertNotIn('private synthetic marker', str(item.message))
                        self.assertNotIn(directory, str(item.message))


class IgnoreRulesRegressionTests(unittest.TestCase):
    def test_local_manifests_rollback_and_packaged_artifacts_are_ignored(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            shutil.copy2(ROOT / '.gitignore', root / '.gitignore')
            for name in ('native-host.json', 'nested/native-host.json',
                         'com.thunderbird_mail_mcp.native_send.json', 'nested/rollback.json',
                         'thunderbird-native-send.xpi', 'deployment-backups/example/0'):
                with self.subTest(path=name):
                    result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', name], cwd=root)
                    self.assertEqual(result.returncode, 0, name)
            for name in ('README.md', 'extension/manifest.json', 'scripts/package_send.py', 'tests/test_regressions.py'):
                with self.subTest(source=name):
                    result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', name], cwd=root)
                    self.assertEqual(result.returncode, 1, name)
