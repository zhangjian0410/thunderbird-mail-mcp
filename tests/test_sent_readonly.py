from datetime import datetime, timezone
from email.message import EmailMessage
import base64
import mailbox
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mail_reader import MailReader
from mail_store import InvalidInputError
import server


class SentReadonlyTests(unittest.TestCase):
    def make_mailbox(self, path, subject, body, attachment=None):
        message = EmailMessage()
        message['From'] = 'owner@example.test'
        message['To'] = 'recipient@example.test'
        message['Date'] = datetime(2026, 10, 24, tzinfo=timezone.utc)
        message['Message-ID'] = '<' + path.name.lower() + '@example.test>'
        message['Subject'] = subject
        message.set_content(body)
        if attachment is not None:
            message.add_attachment(attachment, maintype='application', subtype='octet-stream', filename='test.bin')
        box = mailbox.mbox(path)
        box.add(message)
        box.close()

    def test_configured_scope_is_inbox_and_sent_only(self):
        self.assertEqual(set(server.READER.paths), {'Inbox', 'Sent'})
        self.assertEqual(server.READER.paths['Inbox'], Path(server.INBOX_PATH))
        self.assertEqual(server.READER.paths['Sent'], Path(server.SENT_PATH))
        self.assertNotIn('Unsent Messages', {p.name for p in server.READER.paths.values()})

    def test_mailbox_environment_overrides_and_sibling_sent_fallback(self):
        with TemporaryDirectory() as directory:
            inbox = Path(directory) / 'inbox account' / 'Inbox'
            inbox.parent.mkdir()
            self.make_mailbox(inbox, 'inbox', 'received')
            alternate_sent = Path(directory) / 'alternate Sent'
            self.make_mailbox(alternate_sent, 'sent', 'saved outgoing copy')
            environment = {**os.environ, 'THUNDERBIRD_INBOX_PATH': str(inbox)}
            environment.pop('THUNDERBIRD_SENT_PATH', None)
            code = '''import os
from pathlib import Path
import server
expected = Path(os.environ.get('THUNDERBIRD_SENT_PATH', str(Path(server.INBOX_PATH).with_name('Sent')))).expanduser()
assert server.READER.paths['Sent'] == expected
assert server.query_email()['total_matches'] == 1
assert server.list_recent_email()[0]['subject'] == 'inbox'
if 'THUNDERBIRD_SENT_PATH' in os.environ:
    result = server.query_email(folders=['Sent'])
    assert result['messages'][0]['subject'] == 'sent'
else:
    assert server.list_mail_folders()['folders'][1]['available'] is False
'''
            for configured in (None, str(alternate_sent)):
                with self.subTest(configured=configured):
                    if configured is not None:
                        environment['THUNDERBIRD_SENT_PATH'] = configured
                    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                            env=environment, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_query_remains_inbox_only_when_sent_unavailable(self):
        with TemporaryDirectory() as directory:
            inbox = Path(directory) / 'Inbox'
            self.make_mailbox(inbox, 'inbox', 'received')
            reader = MailReader({'Inbox': inbox, 'Sent': Path(directory) / 'missing-Sent'})
            with patch.object(server, 'READER', reader):
                result = server.query_email()
                self.assertEqual(result['total_matches'], 1)
                self.assertEqual({m['folder'] for m in result['messages']}, {'Inbox'})
                self.assertEqual(server.list_mail_folders()['folders'][1]['available'], False)
                with self.assertRaises(InvalidInputError):
                    server.query_email(folders=[])

    def test_explicit_sent_query_body_and_attachment_do_not_modify_mailboxes(self):
        with TemporaryDirectory() as directory:
            inbox, sent = [Path(directory) / name for name in ('Inbox', 'Sent')]
            self.make_mailbox(inbox, 'inbox', 'received')
            self.make_mailbox(sent, 'sent', 'saved outgoing copy', b'sent attachment')
            before = {p: p.read_bytes() for p in (inbox, sent)}
            reader = MailReader({'Inbox': inbox, 'Sent': sent})
            with patch.object(server, 'READER', reader), patch.object(server.mail_sender, 'send_email') as send:
                result = server.query_email(folders=['Sent'])
                self.assertEqual(result['total_matches'], 1)
                self.assertEqual(result['messages'][0]['folder'], 'Sent')
                self.assertEqual(result['coverage']['server_sync_status'], 'unknown')
                locator = result['messages'][0]['locator']
                message = server.read_emails([locator])['messages'][0]
                self.assertEqual(message['body'].strip(), 'saved outgoing copy')
                attachment = server.read_attachment(locator, message['attachments'][0]['attachment_id'])
                self.assertEqual(base64.b64decode(attachment['data_base64']), b'sent attachment')
                both = server.query_email(folders=['Inbox', 'Sent'])
                self.assertEqual(both['total_matches'], 2)
                self.assertEqual({m['folder'] for m in both['messages']}, {'Inbox', 'Sent'})
                with self.assertRaises(InvalidInputError):
                    server.query_email(folders=['Outbox'])
                send.assert_not_called()
            self.assertEqual(before, {p: p.read_bytes() for p in (inbox, sent)})
