from datetime import datetime, timezone
from email.message import EmailMessage
import base64
import hashlib
import mailbox
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mail_reader import MailReader
from mail_store import InvalidInputError


class MailReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'Inbox'
        self.add('a@example.test', '2026-09-09T09:00:00+08:00', '<same@test>', '第一封')
        self.add('a@example.test', '2026-09-10T09:00:00+08:00', '<same@test>', '第二封')
        self.add('"a@example.test" <evil@example.test>', '2026-09-10T10:00:00+08:00', None, '第三封')
        self.reader = MailReader({'Inbox': self.path}, now=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc))

    def add(self, sender, dt, mid, body, attachment=None):
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = 'owner@example.test'
        msg['Date'] = datetime.fromisoformat(dt)
        if mid is not None:
            msg['Message-ID'] = mid
        msg['Subject'] = '业务申请'
        msg.set_content(body)
        if attachment is not None:
            msg.add_attachment(attachment, maintype='application', subtype='octet-stream', filename='名单.xlsx')
        box = mailbox.mbox(self.path)
        box.add(msg)
        box.close()

    def test_exact_sender_blank_keyword_and_half_open_dates(self):
        result = self.reader.query_email(senders=['a@example.test'],
            start='2026-09-09T09:00:00+08:00', end='2026-09-10T09:00:00+08:00')
        self.assertEqual(result['total_matches'], 1)
        self.assertEqual(result['messages'][0]['sender_email'], 'a@example.test')
        self.assertEqual(result['coverage']['local_status'], 'complete')
        self.assertEqual(result['coverage']['server_sync_status'], 'unknown')

    def test_invalid_ranges_folders_senders_and_limits_fail(self):
        for kwargs in [{'start': '2026-09-01'}, {'start': '2026-09-11T00:00:00Z', 'end': '2026-09-01T00:00:00Z'},
                       {'folders': ['../Inbox']}, {'senders': ['a']}, {'page_size': True}, {'page_size': 201}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidInputError):
                self.reader.query_email(**kwargs)

    def test_pagination_has_no_duplicates_and_cursor_is_bound_to_query(self):
        first = self.reader.query_email(page_size=1)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['coverage']['local_status'], 'partial')
        second = self.reader.query_email(page_size=1, cursor=first['next_cursor'])
        third = self.reader.query_email(page_size=1, cursor=second['next_cursor'])
        locators = [p['messages'][0]['locator'] for p in [first, second, third]]
        self.assertEqual(len(set(locators)), 3)
        self.assertIsNone(third['next_cursor'])
        self.assertEqual(third['coverage']['local_status'], 'complete')
        with self.assertRaises(InvalidInputError):
            self.reader.query_email(senders=['a@example.test'], page_size=1, cursor=first['next_cursor'])
        with self.assertRaises(InvalidInputError):
            self.reader.query_email(cursor=first['next_cursor'] + 'tampered')

    def test_changed_mailbox_invalidates_cursor_and_locator(self):
        first = self.reader.query_email(page_size=1)
        locator = first['messages'][0]['locator']
        self.add('a@example.test', '2026-09-11T00:00:00+08:00', '<new@test>', '追加')
        with self.assertRaisesRegex(InvalidInputError, 'changed|变化'):
            self.reader.query_email(page_size=1, cursor=first['next_cursor'])
        result = self.reader.read_emails([locator])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['messages'], [])

    def test_duplicate_or_missing_rfc_id_does_not_break_locator_reads(self):
        result = self.reader.query_email()
        self.assertEqual(len({m['locator'] for m in result['messages']}), 3)
        self.assertEqual(sum(m['rfc_message_id'] is None for m in result['messages']), 1)
        read = self.reader.read_emails([m['locator'] for m in result['messages']])
        self.assertEqual(len(read['messages']), 3)
        self.assertEqual(read['errors'], [])
        self.assertEqual({m['body'].strip() for m in read['messages']}, {'第一封', '第二封', '第三封'})

    def test_attachment_chunks_and_body_history_are_read_only(self):
        body = '本次39人\n发件人： manager@example.test\n发送时间： 2026-09-09 17:30\n收件人： a@example.test\n主题： 回复\n历史39人'
        self.add('a@example.test', '2026-09-10T23:00:00+08:00', '<attach@test>', body, b'abcdef')
        before = self.path.read_bytes()
        locator = self.reader.query_email(page_size=1)['messages'][0]['locator']
        message = self.reader.read_emails([locator], include_quoted_history=True)['messages'][0]
        self.assertEqual(message['body'], '本次39人')
        self.assertIn('历史39人', message['quoted_history'])
        self.assertFalse(message['body_truncated'])
        attachment = message['attachments'][0]
        part1 = self.reader.read_attachment(locator, attachment['attachment_id'], max_bytes=3)
        part2 = self.reader.read_attachment(locator, attachment['attachment_id'], offset=part1['next_offset'], max_bytes=3)
        self.assertEqual(base64.b64decode(part1['data_base64']) + base64.b64decode(part2['data_base64']), b'abcdef')
        self.assertEqual(part2['sha256'], hashlib.sha256(b'abcdef').hexdigest())
        self.assertIsNone(part2['next_offset'])
        self.assertEqual(before, self.path.read_bytes())

    def test_body_truncation_is_explicit_and_quote_like_business_text_is_retained(self):
        self.add('a@example.test', '2026-09-10T23:00:00+08:00', '<body@test>', '发件人：这只是业务字段\n' + 'a' * 2000)
        loc = self.reader.query_email(page_size=1)['messages'][0]['locator']
        message = self.reader.read_emails([loc], max_body_chars=1000)['messages'][0]
        self.assertTrue(message['body_truncated'])
        self.assertFalse(message['quoted_history_omitted'])
        self.assertEqual(len(message['body']), 1000)

    def test_unreadable_date_reports_gap_instead_of_crashing_or_claiming_complete(self):
        with self.path.open('ab') as out:
            out.write(b'From - Thu Sep 10 00:00:00 2026\nFrom: a@example.test\nDate: nonsense\nSubject: bad\n\nbody\n')
        result = self.reader.query_email(senders=['a@example.test'])
        self.assertEqual(result['total_matches'], 2)
        self.assertEqual(result['coverage']['local_status'], 'partial')
        self.assertTrue(result['coverage']['gaps'])

    def test_batch_keeps_successes_when_one_locator_is_invalid(self):
        loc = self.reader.query_email()['messages'][0]['locator']
        result = self.reader.read_emails([loc, 'invalid'])
        self.assertEqual(len(result['messages']), 1)
        self.assertEqual(len(result['errors']), 1)

    def test_multiple_configured_folders_have_separate_scope(self):
        other = Path(self.tmp.name) / 'Archive'
        other.write_bytes(self.path.read_bytes())
        reader = MailReader({'Inbox': self.path, 'Archive': other})
        self.assertEqual(reader.query_email(folders=['Archive'])['total_matches'], 3)
        self.assertEqual(reader.query_email()['total_matches'], 6)
        self.assertEqual({f['folder'] for f in reader.list_mail_folders()['folders']}, {'Inbox', 'Archive'})

    def test_mailbox_change_during_body_processing_is_not_returned_as_current(self):
        locator = self.reader.query_email()['messages'][0]['locator']
        original = self.reader._body
        def changed(message):
            result = original(message)
            self.add('a@example.test', '2026-09-11T00:00:00+08:00', '<change@test>', '追加')
            return result
        with patch.object(self.reader, '_body', changed):
            result = self.reader.read_emails([locator])
        self.assertEqual(result['messages'], [])
        self.assertEqual(len(result['errors']), 1)

    def test_attached_email_stays_out_of_body_and_remains_readable(self):
        outer = EmailMessage()
        outer['From'] = 'a@example.test'
        outer['Date'] = 'Thu, 10 Sep 2026 23:00:00 +0800'
        outer['Subject'] = 'new'
        outer.set_content('Current report: 45 people')
        inner = EmailMessage()
        inner['Subject'] = 'old'
        inner.set_content('Old attached report: 10 people')
        outer.add_attachment(inner, filename='old.eml')
        box = mailbox.mbox(self.path); box.add(outer); box.close()
        loc = self.reader.query_email(page_size=1)['messages'][0]['locator']
        read = self.reader.read_emails([loc])['messages'][0]
        self.assertEqual(read['body'], 'Current report: 45 people')
        self.assertEqual(len(read['attachments']), 1)
        data = self.reader.read_attachment(loc, read['attachments'][0]['attachment_id'])
        self.assertIn(b'Old attached report: 10 people', base64.b64decode(data['data_base64']))
        self.assertEqual(data['byte_representation'], 'serialized_message_rfc822')

    def test_same_length_change_with_restored_mtime_invalidates_snapshot(self):
        first = self.reader.query_email(page_size=1)
        before = self.path.stat()
        content = self.path.read_bytes()
        self.path.write_bytes(content.replace(b'owner@example.test', b'other@example.test'))
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(InvalidInputError, 'changed|变化'):
            self.reader.query_email(page_size=1, cursor=first['next_cursor'])


if __name__ == '__main__':
    unittest.main()
