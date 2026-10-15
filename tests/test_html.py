import unittest
from test_mail_sender import SendJournalTests


class HtmlTests(SendJournalTests):
    def test_html_requires_capability_and_survives_claim(self):
        p = {**self.payload, 'body_format': 'html', 'body': '<table><tr><td>预算</td></tr></table>'}
        self.ready()
        with self.assertRaises(ValueError):
            self.store.enqueue('html', p)
        self.store.heartbeat(self.identities, ['html_v1', 'draft_v1'])
        self.store.enqueue('html', p, action='draft')
        self.assertIsNone(self.store.claim(features=['draft_v1']))
        job = self.store.claim(features=['html_v1', 'draft_v1'])
        self.assertEqual(job['payload']['body_format'], 'html')
        self.assertEqual(job['payload']['body'], p['body'])

    def test_plain_default_preserves_existing_digest(self):
        self.ready()
        self.store.enqueue('legacy', self.payload)
        self.store.enqueue('legacy', {**self.payload, 'body_format': 'plain'})
        with self.assertRaisesRegex(ValueError, 'different'):
            self.store.enqueue('legacy', {**self.payload, 'body_format': 'html'})

    def test_unknown_format_rejected(self):
        self.ready()
        with self.assertRaises(ValueError):
            self.store.enqueue('bad', {**self.payload, 'body_format': 'markdown'})

    def test_html_send_wrapper(self):
        from unittest.mock import patch
        import mail_sender
        self.store.heartbeat(self.identities, ['html_v1'])
        with patch.object(mail_sender, 'JOURNAL', self.store):
            mail_sender.send_email(to=self.payload['to'], subject='HTML', body='<p>好</p>',
                from_email=self.payload['from_email'], idempotency_key='wrapped', body_format='html')
        self.assertEqual(self.store.claim()['payload']['body_format'], 'html')
