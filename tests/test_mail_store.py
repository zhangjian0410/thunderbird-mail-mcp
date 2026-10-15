from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import mailbox
import unittest
from zoneinfo import ZoneInfo

from mail_store import InvalidInputError, MailStore, MessageNotFoundError


SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_message(
    *,
    message_id: str,
    sender: str,
    subject: str,
    date: str,
    body: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = sender
    message["To"] = "recipient@example.test"
    message["Subject"] = subject
    message["Date"] = date
    message.set_content(body)
    return message


def build_mailbox(path: Path) -> None:
    box = mailbox.mbox(path, create=True)
    weekly = make_message(
        message_id="<weekly-1@example.test>",
        sender="Weekly Sender <weekly.sender@example.test>",
        subject="DM周报（8.3~8.9）-示例员工",
        date="Sun, 9 Aug 2026 17:20:14 +0800",
        body="本周完成 SLA 收集。\n\n2026年8月2日 下午10:36，Weekly Sender 写道：\n上一期周报内容。",
    )
    weekly.add_attachment(
        b"123",
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="周报.xlsx",
    )
    box.add(weekly)
    box.add(
        make_message(
            message_id="<other-1@example.test>",
            sender="Other <other@example.test>",
            subject="其他周报",
            date="Sun, 2 Aug 2026 17:20:14 +0800",
            body="不应被日期和发件人组合条件匹配。",
        )
    )
    box.flush()
    box.close()


class MailStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.mailbox_path = Path(self.tempdir.name) / "Inbox"
        build_mailbox(self.mailbox_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_search_matches_keyword_sender_and_days_together(self) -> None:
        store = MailStore(
            self.mailbox_path,
            now=lambda: datetime(2026, 8, 10, 12, tzinfo=SHANGHAI),
        )

        results = store.search_email(keyword="周报", days=7, sender="weekly.sender")

        self.assertEqual(
            results,
            [
                {
                    "message_id": "<weekly-1@example.test>",
                    "date": "2026-08-09T17:20:14+08:00",
                    "from": "Weekly Sender <weekly.sender@example.test>",
                    "to": "recipient@example.test",
                    "subject": "DM周报（8.3~8.9）-示例员工",
                }
            ],
        )

    def test_list_recent_returns_newest_messages_first(self) -> None:
        results = MailStore(self.mailbox_path).list_recent_email(limit=1)

        self.assertEqual(results[0]["message_id"], "<weekly-1@example.test>")

    def test_search_rejects_blank_keyword(self) -> None:
        with self.assertRaises(InvalidInputError):
            MailStore(self.mailbox_path).search_email(keyword="   ")

    def test_read_returns_current_body_and_attachment_metadata(self) -> None:
        result = MailStore(self.mailbox_path).read_email("<weekly-1@example.test>")

        self.assertEqual(result["body"], "本周完成 SLA 收集。")
        self.assertTrue(result["quoted_history_omitted"])
        self.assertEqual(
            result["attachments"],
            [
                {
                    "filename": "周报.xlsx",
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "size_bytes": 3,
                }
            ],
        )

    def test_read_rejects_unknown_message_id(self) -> None:
        with self.assertRaises(MessageNotFoundError):
            MailStore(self.mailbox_path).read_email("<missing@example.test>")

    def test_read_keeps_current_text_when_each_line_has_a_quote_prefix(self) -> None:
        quoted_path = Path(self.tempdir.name) / "QuotedInbox"
        box = mailbox.mbox(quoted_path, create=True)
        box.add(
            make_message(
                message_id="<quoted-current@example.test>",
                sender="Weekly Sender <weekly.sender@example.test>",
                subject="周报",
                date="Sun, 9 Aug 2026 17:20:14 +0800",
                body="> 本周完成 SLA 收集。\n> 2026年8月2日 下午10:36，Weekly Sender 写道：\n> 上一期内容。",
            )
        )
        box.close()

        result = MailStore(quoted_path).read_email("<quoted-current@example.test>")

        self.assertEqual(result["body"], "本周完成 SLA 收集。")
        self.assertTrue(result["quoted_history_omitted"])
