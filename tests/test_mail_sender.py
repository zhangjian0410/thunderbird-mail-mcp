import concurrent.futures
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import mail_sender


class SendJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.path = Path(self.tmp.name) / 'private' / 'send.sqlite3'
        self.store = mail_sender.SendJournal(self.path, clock=lambda: self.now)
        self.payload = dict(to=['one@example.com'], cc=[], bcc=[], from_email='sender@example.com',
                            subject='中文主题', body='正文\n第二行')
        self.identities = [{'id': 'id1', 'email': 'sender@example.com'}]

    def ready(self):
        self.store.heartbeat(self.identities)

    def test_feature_available(self):
        self.assertTrue(hasattr(mail_sender, 'SendJournal'))

    def test_offline_bridge_does_not_leave_a_queued_send(self):
        with self.assertRaisesRegex(ValueError, 'bridge'):
            self.store.enqueue('req-1', self.payload)
        self.assertEqual(self.store.status('req-1')['status'], 'not_found')

    def test_duplicate_key_has_one_claim_and_rejects_changed_message(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        self.store.enqueue('req-1', self.payload)
        self.assertEqual(self.store.claim()['request_id'], 'req-1')
        self.assertIsNone(self.store.claim())
        with self.assertRaisesRegex(ValueError, 'different'):
            self.store.enqueue('req-1', {**self.payload, 'body': 'changed'})

    def test_concurrent_workers_can_claim_only_once(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: self.store.claim(), range(2)))
        self.assertEqual(sum(x is not None for x in claims), 1)

    def test_expired_pending_mail_is_not_sent_after_restart(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        self.now += 61
        self.ready()
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.status('req-1')['status'], 'expired')

    def test_claimed_mail_is_never_retried_even_after_restart_or_timeout(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        self.store.claim()
        self.now += 301
        restarted = mail_sender.SendJournal(self.path, clock=lambda: self.now)
        self.assertEqual(restarted.status('req-1')['status'], 'unknown')
        self.assertIsNone(restarted.claim())
        self.assertFalse(restarted.enqueue('req-1', self.payload)['safe_to_retry'])

    def test_sent_and_copy_are_separate_and_do_not_regress(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        claim = self.store.claim()
        result = {'status': 'sent', 'message_id': 'abc@example.com', 'copy_status': 'not_verified', 'copies': []}
        self.store.complete('req-1', claim['claim_token'], result)
        self.assertEqual(self.store.status('req-1')['status'], 'sent')
        self.assertEqual(self.store.status('req-1')['copy_status'], 'not_verified')
        with self.assertRaises(ValueError):
            self.store.complete('req-1', claim['claim_token'], {**result, 'status': 'unknown'})
        self.assertIsNone(self.store.claim())

    def test_result_requires_claim_token_and_real_message_id(self):
        self.ready()
        self.store.enqueue('req-1', self.payload)
        claim = self.store.claim()
        with self.assertRaises(ValueError):
            self.store.complete('req-1', 'wrong-token', {'status': 'unknown'})
        with self.assertRaises(ValueError):
            self.store.complete('req-1', claim['claim_token'], {'status': 'sent', 'copy_status': 'not_verified'})

    def test_sender_and_header_validation_prevent_wrong_or_injected_recipient(self):
        self.ready()
        for changes in ({'from_email': 'other@example.com'}, {'to': ['one@example.com\nBcc: bad@example.com']},
                        {'to': []}, {'subject': 'bad\r\nX: 1'}, {'body': '\x00'}, {'to': ['not-an-email']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.enqueue('req-1', {**self.payload, **changes})
        self.assertEqual(self.store.status('req-1')['status'], 'not_found')

    def test_journal_permissions_are_private(self):
        self.ready()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
