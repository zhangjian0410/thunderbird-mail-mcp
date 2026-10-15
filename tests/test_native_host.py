import io
import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mail_sender import SendJournal
import native_host


class NativeHostTests(unittest.TestCase):
    def exchange(self, messages, store):
        encoded = b''
        for message in messages:
            body = json.dumps(message).encode()
            encoded += struct.pack('=I', len(body)) + body
        output = io.BytesIO()
        native_host.serve(io.BytesIO(encoded), output, store)
        output.seek(0)
        replies = []
        while header := output.read(4):
            replies.append(json.loads(output.read(struct.unpack('=I', header)[0])))
        return replies

    def test_poll_updates_capability_and_refuses_enqueue_from_extension(self):
        with TemporaryDirectory() as directory:
            store = SendJournal(Path(directory) / 'private' / 'send.db')
            replies = self.exchange([
                {'id': 1, 'op': 'poll', 'identities': [{'id': 'id1', 'email': 'one@example.com'}], 'accept': False},
                {'id': 2, 'op': 'enqueue', 'payload': {'body': 'not allowed'}}
            ], store)
            self.assertEqual(replies[0], {'id': 1, 'ok': True, 'result': None})
            self.assertFalse(replies[1]['ok'])
            self.assertTrue(store.capabilities()['ready'])

    def test_truncated_and_oversized_frames_stop_without_execution(self):
        with TemporaryDirectory() as directory:
            store = SendJournal(Path(directory) / 'private' / 'send.db')
            for data in (b'\x00', struct.pack('=I', 1048577), struct.pack('=I', 20) + b'{}'):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    native_host.serve(io.BytesIO(data), io.BytesIO(), store)

    def test_non_object_message_returns_error_instead_of_killing_host(self):
        with TemporaryDirectory() as directory:
            replies = self.exchange([[], {'id': 2, 'op': 'bad'}], SendJournal(Path(directory)/'private'/'s.db'))
            self.assertEqual(len(replies), 2)
            self.assertFalse(replies[0]['ok'])
