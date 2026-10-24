from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mail_composer import ComposeInputError, MailComposer, ThunderbirdLaunchError
from mail_store import InvalidInputError, MailStore, MessageNotFoundError
from mail_reader import MailReader
import mail_sender


INBOX_PATH = str(Path(os.environ.get("THUNDERBIRD_INBOX_PATH", "~/Library/Thunderbird/Inbox")).expanduser())
SENT_PATH = str(Path(os.environ.get("THUNDERBIRD_SENT_PATH", str(Path(INBOX_PATH).with_name("Sent")))).expanduser())
STORE = MailStore(INBOX_PATH)
READER = MailReader({"Inbox": INBOX_PATH, "Sent": SENT_PATH})
COMPOSER = MailComposer()
mcp = FastMCP("Thunderbird Mail")


@mcp.tool()
def list_mail_folders() -> dict[str, object]:
    """List configured local Inbox/Sent mbox files; server sync is unknown.

    Sent contains saved sent copies. Pending Outbox is not configured.
    """
    return READER.list_mail_folders()


@mcp.tool()
def query_email(
    keyword: str = "",
    senders: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    folders: list[str] | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, object]:
    """Read-only local enumeration. Empty keyword allowed; senders match exact addresses.

    start/end are timezone-aware ISO timestamps in a half-open interval. Reuse
    all parameters with next_cursor until exhausted. Omitted folders reads Inbox
    only; pass ["Sent"] for saved sent copies, or ["Inbox", "Sent"] for both.
    Pending Outbox is not configured. Cursors/locators expire on
    mailbox changes or server restart. Coverage is LOCAL only, not server sync.
    """
    selected_folders = ["Inbox"] if folders is None else folders
    return READER.query_email(keyword, senders, start, end, selected_folders, page_size, cursor)


@mcp.tool()
def read_emails(
    locators: list[str],
    include_quoted_history: bool = False,
    max_body_chars: int = 30000,
) -> dict[str, object]:
    """Read 1..20 query_email locators without marking read. Returns per-message
    errors, explicit truncation, separate current/quoted bodies, RFC IDs, and
    attachment IDs/hashes. Quoted-history splitting is heuristic, not deletion.
    """
    return READER.read_emails(locators, include_quoted_history, max_body_chars)


@mcp.tool()
def read_attachment(
    locator: str,
    attachment_id: str,
    offset: int = 0,
    max_bytes: int = 262144,
) -> dict[str, object]:
    """Read attachment bytes as base64 without saving files or opening programs.
    Use attachment_id from read_emails; follow next_offset until null. Verify
    combined size and SHA256. At most 1 MiB per chunk, 64 MiB message read limit.
    """
    return READER.read_attachment(locator, attachment_id, offset, max_bytes)


@mcp.tool()
def search_email(
    keyword: str,
    days: int | None = None,
    sender: str | None = None,
) -> list[dict[str, str]]:
    try:
        return STORE.search_email(keyword=keyword, days=days, sender=sender)
    except InvalidInputError as error:
        raise ValueError(str(error)) from error


@mcp.tool()
def read_email(message_id: str) -> dict[str, object]:
    try:
        return STORE.read_email(message_id)
    except (InvalidInputError, MessageNotFoundError) as error:
        raise ValueError(str(error)) from error


@mcp.tool()
def list_recent_email(limit: int = 20) -> list[dict[str, str]]:
    try:
        return STORE.list_recent_email(limit=limit)
    except InvalidInputError as error:
        raise ValueError(str(error)) from error


@mcp.tool()
def compose_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict[str, object]:
    try:
        return COMPOSER.compose_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )
    except (ComposeInputError, ThunderbirdLaunchError) as error:
        raise ValueError(str(error)) from error


@mcp.tool()
def send_email(
    to: list[str], subject: str, body: str, from_email: str,
    idempotency_key: str, cc: list[str] | None = None, bcc: list[str] | None = None,
    attachments: list[dict[str, str]] | None = None,
    body_format: str = 'plain',
) -> dict[str, object]:
    """Actually send a user-authorized email via the running Thunderbird extension.

    Requires explicit user authorization for the recipients and purpose. body_format
    is plain (default) or html. HTML requires html_v1 capability; supply actual HTML,
    not Markdown. Preview a native draft before approving formatted mail; HTML sends
    with a Thunderbird-generated plain-text alternative. Recipient lists contain
    bare email addresses. Choose a unique key
    for this logical send, and reuse it on retries. A returned pending/sending
    status is NOT sent: call get_send_status. Unknown outcomes must not be retried
    under a new key. Retrying the same key never enqueues a second send. Thunderbird
    uses its configured account/FCC; delivery and saved-copy status are separate.
    Each attachment must include an absolute path and the expected sha256 of its
    reviewed bytes. Up to 10 files, 20 MiB total. Snapshots are immutable once queued.
    Authorization may be per-message or a task-specific bounded delegation; a
    general agreement about automation is not authorization to send this message.
    """
    return mail_sender.send_email(to, subject, body, from_email, idempotency_key, cc, bcc, attachments, body_format)


@mcp.tool()
def create_draft(
    to: list[str], subject: str, body: str, from_email: str,
    idempotency_key: str, cc: list[str] | None = None, bcc: list[str] | None = None,
    attachments: list[dict[str, str]] | None = None,
    body_format: str = 'plain',
) -> dict[str, object]:
    """Save a native Thunderbird draft; NEVER send. Poll get_send_status until
    drafted/failed/unknown. Attachments require absolute path and expected sha256,
    at most 10 files and 20 MiB total. Reuse the key for retries. Creation alone is
    not sending authorization. Draft save follows the account's Drafts settings.
    body_format is plain (default) or html; HTML requires html_v1. Supply actual
    HTML, not Markdown, and inspect the saved draft before requesting send approval.
    """
    return mail_sender.JOURNAL.enqueue(idempotency_key,
        dict(to=to,subject=subject,body=body,from_email=from_email,cc=cc,bcc=bcc,body_format=body_format),
        attachments=attachments, action='draft')


@mcp.tool()
def get_send_status(idempotency_key: str) -> dict[str, object]:
    """Read durable status without sending. sent confirms outgoing submission, not
    recipient delivery. copy_status=verified means Thunderbird could read a saved
    copy with the same Message-ID. Unknown requires investigation, never resending.
    """
    return mail_sender.JOURNAL.status(idempotency_key)


@mcp.tool()
def get_send_capabilities() -> dict[str, object]:
    """Read extension heartbeat and available sender identities; does not send mail."""
    return mail_sender.JOURNAL.capabilities()


if __name__ == "__main__":
    mcp.run(transport="stdio")
