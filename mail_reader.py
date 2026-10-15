"""Paged, read-only access to explicitly configured local mbox files.

Coverage refers to local files, never to POP/IMAP synchronization. Locators and
cursors are signed, process-local and invalidated when the mailbox changes.
"""
from __future__ import annotations

import base64
from datetime import datetime
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading

from mail_store import InvalidInputError, MailStore, SHANGHAI


class MailReader:
    def __init__(self, mailboxes: dict[str, str | Path], now=None):
        self.paths = {name: Path(path) for name, path in mailboxes.items()}
        if not self.paths or any(not name or not path.is_absolute() for name, path in self.paths.items()):
            raise InvalidInputError('Configured folders require names and absolute mbox paths')
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self._cache = {}
        self._secret = secrets.token_bytes(32)
        self._lock = threading.RLock()

    @staticmethod
    def _signature(path):
        stat = path.stat()
        if not path.is_file():
            raise InvalidInputError('Configured mailbox is not a regular file')
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]

    def _token(self, value):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        mac = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac + raw).decode()

    def _decode(self, token, kind):
        try:
            if not isinstance(token, str) or len(token) > 16384:
                raise ValueError()
            data = base64.b64decode(token, altchars=b'-_', validate=True)
            mac, raw = data[:32], data[32:]
            if not hmac.compare_digest(mac, hmac.new(self._secret, raw, hashlib.sha256).digest()):
                raise ValueError()
            value = json.loads(raw)
            if value['kind'] != kind:
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidInputError('Invalid or expired cursor/locator; repeat query') from exc

    @staticmethod
    def _timestamp(value):
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
            return parsed
        except (ValueError, AttributeError) as exc:
            raise InvalidInputError('Dates must be timezone-aware ISO timestamps') from exc

    @staticmethod
    def _limit(value, maximum, name, minimum=1):
        if type(value) is not int or not minimum <= value <= maximum:
            raise InvalidInputError(f'{name} must be {minimum}..{maximum}')

    def _folders(self, folders):
        selected = sorted(self.paths) if folders is None else folders
        if (not isinstance(selected, list) or not selected
                or any(not isinstance(f, str) or f not in self.paths for f in selected)
                or len(selected) != len(set(selected))):
            raise InvalidInputError('Unknown, duplicate or empty folder scope')
        return sorted(selected)

    @staticmethod
    def _sender(header):
        addresses = getaddresses([header])
        if len(addresses) != 1 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', addresses[0][1]):
            return None
        return addresses[0][1].casefold()

    def list_mail_folders(self):
        return {'folders': [{'folder': folder, 'available': path.is_file(), 'scope': 'local_mbox'}
                            for folder, path in self.paths.items()],
                'read_only': True, 'server_sync_status': 'unknown'}

    def _index(self, folder):
        with self._lock:
            path = self.paths[folder]
            signature = self._signature(path)
            cached = self._cache.get(folder)
            if cached and cached['signature'] == signature:
                return cached
            rows, gaps = [], []

            def finish(start, end, header):
                if start is None or end <= start:
                    return
                try:
                    if len(header) > 262144:
                        raise ValueError('oversize header')
                    msg = BytesHeaderParser(policy=policy.default).parsebytes(header)
                    # Thunderbird retains moved/deleted records until compaction.
                    status = str(msg.get('X-Mozilla-Status', '0')).strip()
                    if int(status, 16) & 0x0008:
                        return
                    date = parsedate_to_datetime(msg.get('Date', ''))
                    if date is None or date.tzinfo is None:
                        raise ValueError('missing timezone/date')
                    sender = self._sender(str(msg.get('From', '')))
                    if sender is None:
                        raise ValueError('ambiguous sender')
                    rows.append({'folder': folder, 'offset': start, 'length': end - start,
                                 'date': date.isoformat(), 'sender_email': sender,
                                 'from': str(msg.get('From', '')), 'to': str(msg.get('To', '')),
                                 'subject': str(msg.get('Subject', '')),
                                 'rfc_message_id': str(msg.get('Message-ID', '')).strip() or None})
                except (ValueError, TypeError, IndexError, OverflowError) as exc:
                    gaps.append({'folder': folder, 'offset': start, 'reason': f'unindexable_header: {exc}'})

            with path.open('rb') as source:
                start, header, in_header = None, bytearray(), True
                while True:
                    offset = source.tell()
                    line = source.readline()
                    if not line:
                        finish(start, offset, bytes(header))
                        break
                    if line.startswith(b'From '):
                        finish(start, offset, bytes(header))
                        start, header, in_header = source.tell(), bytearray(), True
                    else:
                        if start is None:
                            start = offset
                        if in_header:
                            if len(header) <= 262144:
                                header.extend(line)
                            if line in (b'\n', b'\r\n'):
                                in_header = False
            if self._signature(path) != signature:
                raise InvalidInputError('Mailbox changed during indexing; repeat query')
            indexed = {'signature': signature, 'rows': rows, 'gaps': gaps,
                       'indexed_at': self.now().isoformat()}
            self._cache[folder] = indexed
            return indexed

    def _message(self, folder, record, signature):
        path = self.paths[folder]
        if self._signature(path) != signature:
            raise InvalidInputError('Mailbox changed; repeat query')
        if record['length'] > 64 * 1024 * 1024:
            raise InvalidInputError('Message exceeds 64 MiB read limit')
        with path.open('rb') as source:
            source.seek(record['offset'])
            data = source.read(record['length'])
        if len(data) != record['length'] or self._signature(path) != signature:
            raise InvalidInputError('Mailbox changed during read; repeat query')
        return BytesParser(policy=policy.default).parsebytes(data)

    def _located(self, locator):
        value = self._decode(locator, 'message')
        folder = value['folder']
        if folder not in self.paths or self._signature(self.paths[folder]) != value['signature']:
            raise InvalidInputError('Mailbox changed or folder unavailable; repeat query')
        index = self._index(folder)
        record = next((r for r in index['rows'] if r['offset'] == value['offset']), None)
        if record is None:
            raise InvalidInputError('Message locator no longer exists')
        return record, self._message(folder, record, index['signature'])

    def _summary(self, record, signature):
        return {key: value for key, value in record.items() if key not in ('offset', 'length')} | {
            'locator': self._token({'kind': 'message', 'folder': record['folder'],
                                    'offset': record['offset'], 'signature': signature})}

    def query_email(self, keyword='', senders=None, start=None, end=None,
                    folders=None, page_size=50, cursor=None):
        self._limit(page_size, 200, 'page_size')
        if not isinstance(keyword, str):
            raise InvalidInputError('keyword must be text; empty text enumerates messages')
        selected = self._folders(folders)
        if senders is not None and (not isinstance(senders, list) or not senders
                or any(not isinstance(s, str) or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', s) for s in senders)):
            raise InvalidInputError('senders must contain exact email addresses')
        addresses = sorted(set(s.casefold() for s in senders)) if senders else None
        first, last = self._timestamp(start), self._timestamp(end)
        if first is not None and last is not None and first >= last:
            raise InvalidInputError('start must precede end (half-open interval)')
        criteria = {'keyword': keyword.casefold(), 'senders': addresses, 'start': start,
                    'end': end, 'folders': selected, 'page_size': page_size}
        query_hash = hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()
        indexes = {f: self._index(f) for f in selected}
        signatures = {f: index['signature'] for f, index in indexes.items()}
        position = 0
        if cursor:
            previous = self._decode(cursor, 'page')
            if previous['query'] != query_hash:
                raise InvalidInputError('Cursor belongs to a different query')
            if previous['signatures'] != signatures:
                raise InvalidInputError('Mailbox changed between pages; repeat query')
            position = previous['position']
        matches, gaps = [], [g for index in indexes.values() for g in index['gaps']]
        for folder, index in indexes.items():
            for row in index['rows']:
                date = datetime.fromisoformat(row['date'])
                if addresses is not None and row['sender_email'] not in addresses:
                    continue
                if (first is not None and date < first) or (last is not None and date >= last):
                    continue
                if keyword:
                    try:
                        msg = self._message(folder, row, index['signature'])
                        body, _, _ = self._body(msg)
                        if keyword.casefold() not in (row['subject'] + '\n' + row['from'] + '\n' + body).casefold():
                            continue
                    except (ValueError, OSError) as exc:
                        gaps.append({'folder': folder, 'offset': row['offset'], 'reason': str(exc)})
                        continue
                matches.append(row)
        if any(self._signature(self.paths[f]) != signatures[f] for f in selected):
            raise InvalidInputError('Mailbox changed during query; repeat query')
        matches.sort(key=lambda r: (datetime.fromisoformat(r['date']), r['folder'], r['offset']), reverse=True)
        page = matches[position:position + page_size]
        more = position + len(page) < len(matches)
        next_cursor = self._token({'kind': 'page', 'query': query_hash, 'signatures': signatures,
                                  'position': position + len(page)}) if more else None
        return {'messages': [self._summary(r, signatures[r['folder']]) for r in page],
                'total_matches': len(matches), 'next_cursor': next_cursor, 'has_more': more,
                'coverage': {'local_status': 'partial' if more or gaps else 'complete',
                             'folders': selected, 'requested_start': start, 'requested_end': end,
                             'gaps': gaps, 'enumerated_through': position + len(page),
                             'server_sync_status': 'unknown', 'read_only': True,
                             'mailbox_snapshots': signatures, 'queried_at': self.now().isoformat()}}

    @staticmethod
    def _body(message):
        def decode(part):
            data = part.get_payload(decode=True) or b''
            try:
                return data.decode(part.get_content_charset() or 'utf-8', errors='replace')
            except LookupError:
                return data.decode('utf-8', errors='replace')
        plain, html = [], []
        for _, part in MailReader._visible_parts(message):
            if MailReader._is_attachment(part):
                continue
            if part.get_content_type() == 'text/plain':
                plain.append(decode(part))
            elif part.get_content_type() == 'text/html':
                html.append(decode(part))
        body = '\n'.join(plain).strip() if plain else MailStore._html_to_text('\n'.join(html))
        patterns = [r'(?m)^(?:> ?)?On .+ wrote:\s*$', r'(?m)^(?:> ?)?(?:在 .+|\d{4}年.+)写道：\s*$',
                    r'(?im)^\s*(?:发件人|From)\s*[:：][^\n]+\n(?=[\s\S]{0,600}?(?:发送时间|Sent|Date)\s*[:：])(?=[\s\S]{0,900}?(?:收件人|To|主题|Subject)\s*[:：])']
        positions = [m.start() for p in patterns if (m := re.search(p, body))]
        if positions:
            at = min(positions)
            return body, re.sub(r'(?m)^> ?', '', body[:at]).strip(), body[at:].strip()
        return body, body, ''

    @staticmethod
    def _is_attachment(part):
        return (part.get_content_disposition() == 'attachment' or bool(part.get_filename())
                or part.get_content_type() == 'message/rfc822')

    @staticmethod
    def _visible_parts(message, identifier='0'):
        # walk() descends into attached messages; stop at that boundary instead.
        if MailReader._is_attachment(message) or not message.is_multipart():
            yield identifier, message
        else:
            for i, part in enumerate(message.get_payload()):
                yield from MailReader._visible_parts(part, f'{identifier}.{i}')

    @staticmethod
    def _attachment_parts(message):
        return [(identifier, part) for identifier, part in MailReader._visible_parts(message)
                if MailReader._is_attachment(part)]

    @staticmethod
    def _attachment_data(part):
        if part.get_content_type() == 'message/rfc822' and isinstance(part.get_payload(), list):
            return (b'\n'.join(m.as_bytes(policy=policy.default) for m in part.get_payload()),
                    'serialized_message_rfc822')
        if part.is_multipart():
            return part.as_bytes(policy=policy.default), 'serialized_mime_part'
        return part.get_payload(decode=True) or b'', 'decoded_payload'

    def read_emails(self, locators, include_quoted_history=False, max_body_chars=30000):
        if not isinstance(locators, list) or not 1 <= len(locators) <= 20:
            raise InvalidInputError('locators must contain 1..20 message locators')
        if type(include_quoted_history) is not bool:
            raise InvalidInputError('include_quoted_history must be boolean')
        self._limit(max_body_chars, 100000, 'max_body_chars', minimum=1000)
        results, errors = [], []
        for locator in locators:
            try:
                record, message = self._located(locator)
                full, current, history = self._body(message)
                attachments = []
                for identifier, part in self._attachment_parts(message):
                    data, representation = self._attachment_data(part)
                    attachments.append({'attachment_id': identifier, 'filename': part.get_filename() or '(unnamed)',
                                        'content_type': part.get_content_type(), 'size_bytes': len(data),
                                        'sha256': hashlib.sha256(data).hexdigest(),
                                        'byte_representation': representation})
                signature = self._decode(locator, 'message')['signature']
                if self._signature(self.paths[record['folder']]) != signature:
                    raise InvalidInputError('Mailbox changed during body processing; repeat query')
                results.append({**self._summary(record, signature),
                    'cc': str(message.get('Cc', '')), 'body': current[:max_body_chars],
                    'body_truncated': len(current) > max_body_chars,
                    'body_total_chars': len(current), 'body_sha256': hashlib.sha256(current.encode()).hexdigest(),
                    'full_body_sha256': hashlib.sha256(full.encode()).hexdigest(),
                    'fingerprint_method': 'SHA256 UTF-8 decoded preferred text/plain else HTML-to-text; stripped outer whitespace',
                    'quoted_history': history[:max_body_chars] if include_quoted_history else None,
                    'quoted_history_truncated': len(history) > max_body_chars if include_quoted_history else False,
                    'quoted_history_omitted': bool(history) and not include_quoted_history,
                    'quoted_history_detected': bool(history), 'attachments': attachments,
                    'read_only': True, 'retrieved_at': self.now().isoformat()})
            except (ValueError, OSError) as exc:
                errors.append({'locator': locator, 'error': str(exc)})
        return {'messages': results, 'errors': errors, 'read_only': True}

    def read_attachment(self, locator, attachment_id, offset=0, max_bytes=262144):
        self._limit(offset, 64 * 1024 * 1024, 'offset', minimum=0)
        self._limit(max_bytes, 1048576, 'max_bytes')
        if not isinstance(attachment_id, str):
            raise InvalidInputError('attachment_id must be returned by read_emails')
        record, message = self._located(locator)
        part = next((p for identifier, p in self._attachment_parts(message) if identifier == attachment_id), None)
        if part is None:
            raise InvalidInputError('Attachment not found')
        data, representation = self._attachment_data(part)
        if offset > len(data):
            raise InvalidInputError('offset exceeds attachment length')
        chunk = data[offset:offset + max_bytes]
        if self._signature(self.paths[record['folder']]) != self._decode(locator, 'message')['signature']:
            raise InvalidInputError('Mailbox changed during attachment read; repeat query')
        return {'locator': locator, 'attachment_id': attachment_id,
                'filename': part.get_filename() or '(unnamed)', 'content_type': part.get_content_type(),
                'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'byte_representation': representation,
                'offset': offset, 'bytes_returned': len(chunk),
                'next_offset': offset + len(chunk) if offset + len(chunk) < len(data) else None,
                'data_base64': base64.b64encode(chunk).decode(), 'read_only': True}
