from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
import re
import warnings
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


class InvalidInputError(ValueError):
    pass


class MessageNotFoundError(LookupError):
    pass


class MailStore:
    def __init__(
        self,
        mailbox_path: str | Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._mailbox_path = Path(mailbox_path)
        self._now = now or (lambda: datetime.now(SHANGHAI))

    def search_email(
        self,
        keyword: str,
        days: int | None = None,
        sender: str | None = None,
    ) -> list[dict[str, str]]:
        needle = self._require_text(keyword, "keyword").casefold()
        if days is not None and (not isinstance(days, int) or isinstance(days, bool) or days <= 0):
            raise InvalidInputError("days 必须是正整数")
        sender_needle = (sender or "").casefold()
        earliest = self._now().astimezone(SHANGHAI) - timedelta(days=days or 0)
        results: list[tuple[datetime, dict[str, str]]] = []

        for message, date in self._dated_messages():
            haystack = "\n".join(
                [
                    message.get("Subject", ""),
                    message.get("From", ""),
                    self._body_text(message),
                ]
            ).casefold()
            if needle not in haystack or sender_needle not in message.get("From", "").casefold():
                continue
            if days is not None and date < earliest:
                continue
            results.append((date, self._to_summary(message, date)))

        return [summary for _, summary in sorted(results, key=lambda item: item[0], reverse=True)]

    def list_recent_email(self, limit: int = 20) -> list[dict[str, str]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise InvalidInputError("limit 必须是 1 到 100 的整数")
        results = [
            (date, self._to_summary(message, date))
            for message, date in self._dated_messages()
        ]
        return [summary for _, summary in sorted(results, key=lambda item: item[0], reverse=True)[:limit]]

    def read_email(self, message_id: str) -> dict[str, object]:
        target = self._require_text(message_id, "message_id")
        for message, date in self._dated_messages():
            if message.get("Message-ID", "").strip() != target:
                continue
            body, quoted_history_omitted = self._current_body(message)
            return {
                **self._to_summary(message, date),
                "cc": message.get("Cc", ""),
                "body": body,
                "quoted_history_omitted": quoted_history_omitted,
                "attachments": self._attachments(message),
            }
        raise MessageNotFoundError("未找到指定 Message-ID 的邮件")

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidInputError(f"{field_name} 不能为空")
        return value.strip()

    def _dated_messages(self) -> Iterator[tuple[Message, datetime]]:
        for message in self._iter_messages():
            try:
                date = self._parse_date(message)
            except (ValueError, TypeError, IndexError, OverflowError):
                warnings.warn('Skipped a message with a missing or invalid Date header; '
                              'use query_email for explicit coverage gaps.', RuntimeWarning, stacklevel=2)
                continue
            yield message, date

    def _iter_messages(self) -> Iterator[Message]:
        with self._mailbox_path.open("rb") as source:
            message_lines: list[bytes] = []
            for line in source:
                if line.startswith(b"From "):
                    if message_lines:
                        message = BytesParser(policy=policy.default).parsebytes(b"".join(message_lines))
                        if not int(str(message.get('X-Mozilla-Status', '0')).strip(), 16) & 0x0008:
                            yield message
                        message_lines = []
                    continue
                message_lines.append(line)
            if message_lines:
                message = BytesParser(policy=policy.default).parsebytes(b"".join(message_lines))
                if not int(str(message.get('X-Mozilla-Status', '0')).strip(), 16) & 0x0008:
                    yield message

    @staticmethod
    def _body_text(message: Message) -> str:
        if message.is_multipart():
            return "\n".join(
                MailStore._body_text(part)
                for part in message.walk()
                if not part.is_multipart() and part.get_content_disposition() != "attachment"
            )
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
        return ""

    def _current_body(self, message: Message) -> tuple[str, bool]:
        plain_parts = [
            self._body_text(part)
            for part in message.walk()
            if not part.is_multipart()
            and part.get_content_type() == "text/plain"
            and part.get_content_disposition() != "attachment"
        ]
        body = "\n".join(part.strip() for part in plain_parts if part.strip())
        if not body:
            html_parts = [
                self._body_text(part)
                for part in message.walk()
                if not part.is_multipart()
                and part.get_content_type() == "text/html"
                and part.get_content_disposition() != "attachment"
            ]
            body = self._html_to_text("\n".join(html_parts))
        return self._strip_quoted_history(body)

    @staticmethod
    def _strip_quoted_history(body: str) -> tuple[str, bool]:
        markers = [
            r"(?m)^(?:> ?)?On .+ wrote:\s*$",
            r"(?m)^(?:> ?)?在 .+ 写道：\s*$",
            r"(?m)^(?:> ?)?\d{4}年.+写道：\s*$",
        ]
        positions = [match.start() for pattern in markers if (match := re.search(pattern, body))]
        if not positions:
            return body.strip(), False
        current = body[: min(positions)]
        return re.sub(r"(?m)^> ?", "", current).strip(), True

    @staticmethod
    def _html_to_text(html: str) -> str:
        without_blocks = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
        with_breaks = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", without_blocks)
        return re.sub(r"\n{3,}", "\n\n", unescape(re.sub(r"(?s)<[^>]+>", "", with_breaks))).strip()

    @staticmethod
    def _attachments(message: Message) -> list[dict[str, object]]:
        attachments: list[dict[str, object]] = []
        for part in message.walk():
            if part.is_multipart() or (part.get_content_disposition() != "attachment" and not part.get_filename()):
                continue
            attachments.append(
                {
                    "filename": part.get_filename() or "(unnamed)",
                    "content_type": part.get_content_type(),
                    "size_bytes": len(part.get_payload(decode=True) or b""),
                }
            )
        return attachments

    @staticmethod
    def _parse_date(message: Message) -> datetime:
        parsed = parsedate_to_datetime(message.get("Date", ""))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.astimezone(SHANGHAI)

    @staticmethod
    def _to_summary(message: Message, date: datetime) -> dict[str, str]:
        return {
            "message_id": message.get("Message-ID", ""),
            "date": date.isoformat(),
            "from": message.get("From", ""),
            "to": message.get("To", ""),
            "subject": message.get("Subject", ""),
        }
