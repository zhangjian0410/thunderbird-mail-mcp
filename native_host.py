"""Length-prefixed native messaging host. No command execution or mail sending."""
from __future__ import annotations

import json
import struct
import sys
from mail_sender import SendJournal

MAX_FRAME = 1024 * 1024


def dispatch(message, journal):
    if not isinstance(message, dict):
        raise ValueError('Message must be an object')
    if message.get('op') == 'poll':
        journal.heartbeat(message.get('identities'), message.get('features'), message.get('accounts'))
        return journal.claim(features=message.get('features') or []) if message.get('accept') is True else None
    if message.get('op') == 'complete':
        return journal.complete(message.get('request_id'), message.get('claim_token'), message.get('result'))
    if message.get('op') == 'attachment':
        return journal.attachment_chunk(message.get('request_id'), message.get('claim_token'), message.get('index'), message.get('offset'))
    if message.get('op') == 'diagnostic_poll':
        return journal.claim_forward_diagnostic() if message.get('accept') is True else None
    if message.get('op') == 'diagnostic_complete':
        return journal.complete_forward_diagnostic(message.get('request_id'),message.get('claim_token'),message.get('result'))
    raise ValueError('Unsupported native operation')


def read_exact(stream, size):
    parts = bytearray()
    while len(parts) < size:
        chunk = stream.read(size-len(parts))
        if not chunk:
            raise ValueError('Truncated native message')
        parts.extend(chunk)
    return bytes(parts)


def serve(input_stream, output_stream, journal):
    while True:
        first = input_stream.read(1)
        if not first:
            return
        size = struct.unpack('=I', first + read_exact(input_stream, 3))[0]
        if not 0 < size <= MAX_FRAME:
            raise ValueError('Invalid native message size')
        raw = read_exact(input_stream, size)
        request_id = None
        try:
            message = json.loads(raw)
            request_id = message.get('id') if isinstance(message, dict) else None
            response = {'id': request_id, 'ok': True, 'result': dispatch(message, journal)}
        except (ValueError, TypeError, KeyError) as error:
            response = {'id': request_id, 'ok': False, 'error': str(error)}
        encoded = json.dumps(response, ensure_ascii=False).encode('utf-8')
        if len(encoded) > MAX_FRAME:
            raise ValueError('Native response too large')
        output_stream.write(struct.pack('=I', len(encoded)) + encoded)
        output_stream.flush()


if __name__ == '__main__':
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer, SendJournal())
    except (ValueError, BrokenPipeError):
        sys.exit(1)
