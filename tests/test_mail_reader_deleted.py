import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from mail_reader import MailReader

class DeletedMailTests(unittest.TestCase):
    def test_expunged_messages_are_excluded_before_filtering(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'Inbox'
            path.write_bytes(b''.join(
                f'From - Tue Sep 15 10:00:00 2026\nX-Mozilla-Status: {status}\nFrom: one@example.com\nDate: Tue, 15 Sep 2026 10:00:00 +0800\nSubject: {status}\n\nbody\n'.encode()
                for status in ['0009','0001','0008','0000']))
            result=MailReader({'Inbox':path}).query_email()
            self.assertEqual(result['total_matches'],2)
            self.assertEqual({m['subject'] for m in result['messages']},{'0000','0001'})
            self.assertEqual(result['coverage']['local_status'],'complete')
            from mail_store import MailStore
            self.assertEqual({m['subject'] for m in MailStore(path).list_recent_email()},{'0000','0001'})
