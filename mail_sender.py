"""Private durable handoff journal; only Thunderbird performs mail delivery."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import base64
import mimetypes
import stat
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

STATE_PATH = Path.home() / 'Library/Application Support/ThunderbirdMailMCP/send.sqlite3'
KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}\Z")


def validate_payload(payload):
    def address(value):
        if not isinstance(value, str) or not ADDRESS.fullmatch(value):
            raise ValueError('Use plain email addresses, without display names or control characters')
        return value
    result = {'from_email': address(payload.get('from_email'))}
    for field in ('to', 'cc', 'bcc'):
        values = payload.get(field) or []
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('Recipient fields must be lists of up to 100 addresses')
        result[field] = list(dict.fromkeys(address(v) for v in values))
    if not result['to'] or sum(len(result[f]) for f in ('to', 'cc', 'bcc')) > 100:
        raise ValueError('Supply 1 to 100 recipients, including at least one to recipient')
    for field, limit in (('subject', 998), ('body', 100000)):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > limit:
            raise ValueError(f'{field} is empty or too large')
        if '\x00' in value or (field == 'subject' and any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f'{field} contains control characters')
        result[field] = value
    body_format = payload.get('body_format', 'plain')
    if body_format not in ('plain', 'html'):
        raise ValueError('body_format must be plain or html')
    # Omit the default so existing idempotency digests remain valid.
    if body_format == 'html':
        result['body_format'] = 'html'
    return result


def snapshot_attachments(items):
    if items is None:
        return [], []
    if not isinstance(items, list) or len(items) > 10:
        raise ValueError('Use at most 10 attachments')
    metadata, blobs, total = [], [], 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('Attachment requires an absolute path and sha256')
        path = Path(item['path'])
        expected = item.get('sha256')
        if not path.is_absolute() or not isinstance(expected, str) or not re.fullmatch('[0-9a-fA-F]{64}', expected):
            raise ValueError('Attachment requires an absolute path and expected sha256')
        if any(ord(c) < 32 or ord(c) == 127 for c in path.name):
            raise ValueError('Invalid attachment filename')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('Attachment must be a regular file')
                data = stream.read(20 * 1024 * 1024 - total + 1)
        except OSError as error:
            raise ValueError('Cannot read attachment as a regular file') from error
        total += len(data)
        if total > 20 * 1024 * 1024:
            raise ValueError('Attachments exceed 20 MiB total')
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected.lower():
            raise ValueError('Attachment sha256 changed; review the actual file before sending')
        metadata.append({'index':len(metadata), 'name':path.name, 'size':len(data),
                         'sha256':digest, 'type':mimetypes.guess_type(path.name)[0] or 'application/octet-stream'})
        blobs.append(data)
    return metadata, blobs


class SendJournal:
    def __init__(self, path=STATE_PATH, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    @contextmanager
    def db(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('Send journal must not be a symlink')
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA synchronous=FULL')
            conn.execute('CREATE TABLE IF NOT EXISTS bridge (id INTEGER PRIMARY KEY, seen REAL, identities TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS bridge_features (id INTEGER PRIMARY KEY, features TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS attachments (request_id TEXT, ordinal INTEGER, data BLOB, PRIMARY KEY(request_id, ordinal))')
            conn.execute('CREATE TABLE IF NOT EXISTS request_meta (id TEXT PRIMARY KEY, action TEXT, attachments TEXT)')
            conn.execute('''CREATE TABLE IF NOT EXISTS sends (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT, created REAL,
                claimed REAL, token TEXT, state TEXT NOT NULL, result TEXT)''')
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def validate_key(key):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError('idempotency_key must be 1-128 ASCII letters, numbers, . _ : or -')

    def heartbeat(self, identities, features=None):
        if features is None:
            features = []
        if not isinstance(features, list) or len(features) > 20 or not all(isinstance(f, str) and len(f) <= 64 for f in features):
            raise ValueError('Invalid bridge features')
        if not isinstance(identities, list) or len(identities) > 100:
            raise ValueError('Invalid identities')
        clean = []
        for identity in identities:
            if not isinstance(identity, dict) or not isinstance(identity.get('id'), str) or not isinstance(identity.get('email'), str):
                raise ValueError('Invalid identity')
            clean.append({'id': identity['id'], 'email': identity['email']})
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO bridge VALUES (1, ?, ?)', (self.clock(), json.dumps(clean)))
            db.execute('INSERT OR REPLACE INTO bridge_features VALUES (1, ?)', (json.dumps(features),))

    def capabilities(self):
        with self.db() as db:
            row = db.execute('SELECT * FROM bridge WHERE id=1').fetchone()
            features = db.execute('SELECT features FROM bridge_features WHERE id=1').fetchone()
        age = self.clock() - row['seen'] if row else None
        ready = age is not None and 0 <= age <= 15
        return {'ready': ready, 'identities': json.loads(row['identities']) if ready else [],
                'features': json.loads(features[0]) if ready and features else [],
                'attachment_limits': {'max_count':10, 'total_bytes':20*1024*1024},
                'bridge_age_seconds': age, 'requires': 'Thunderbird 153+ with Native Send extension running',
                'copy_policy': 'Use account FCC; report copy verification separately'}

    def enqueue(self, key, payload, attachments=None, action='send'):
        self.validate_key(key)
        if action not in ('send', 'draft'):
            raise ValueError('Unsupported action')
        payload = validate_payload(payload)
        metadata, blobs = snapshot_attachments(attachments)
        # Preserve legacy attachment-free send digests across upgrades.
        if metadata:
            payload['attachments'] = metadata
        if action == 'draft':
            payload['action'] = action
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.db() as db:
            old = db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('idempotency_key is already bound to a different message')
                return self._public(old, db.execute('SELECT * FROM request_meta WHERE id=?', (key,)).fetchone())
            bridge = db.execute('SELECT * FROM bridge WHERE id=1').fetchone()
            if not bridge or not 0 <= self.clock() - bridge['seen'] <= 15:
                raise ValueError('Thunderbird send bridge offline; no message queued')
            feature_row = db.execute('SELECT features FROM bridge_features WHERE id=1').fetchone()
            features = json.loads(feature_row[0]) if feature_row else []
            if (metadata and 'attachments_v1' not in features) or (action == 'draft' and 'draft_v1' not in features) or (payload.get('body_format') == 'html' and 'html_v1' not in features):
                raise ValueError('Running Thunderbird extension does not support this request; update it first')
            matches = [i for i in json.loads(bridge['identities']) if i['email'].lower() == payload['from_email'].lower()]
            if len(matches) != 1:
                raise ValueError('from_email must match exactly one available Thunderbird identity')
            payload['identity_id'] = matches[0]['id']
            db.execute('INSERT INTO sends (id,digest,payload,created,state) VALUES (?,?,?,?,?)',
                       (key, digest, json.dumps(payload, ensure_ascii=False), self.clock(), 'pending'))
            db.execute('INSERT INTO request_meta VALUES (?,?,?)', (key, action, json.dumps(metadata, ensure_ascii=False)))
            db.executemany('INSERT INTO attachments VALUES (?,?,?)', [(key,i,data) for i,data in enumerate(blobs)])
            return self._public(db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone(),
                                db.execute('SELECT * FROM request_meta WHERE id=?', (key,)).fetchone())

    def _expire(self, db):
        db.execute("UPDATE sends SET state='expired', payload=NULL WHERE state='pending' AND created<?", (self.clock()-60,))
        db.execute("DELETE FROM attachments WHERE request_id IN (SELECT id FROM sends WHERE state='expired')")

    def attachment_chunk(self, key, token, index, offset):
        self.validate_key(key)
        if type(index) is not int or type(offset) is not int or index < 0 or offset < 0:
            raise ValueError('Invalid attachment index or offset')
        with self.db() as db:
            row = db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone()
            if not row or row['state'] != 'sending' or not isinstance(token, str) or not secrets.compare_digest(row['token'] or '', token):
                raise ValueError('Invalid attachment claim')
            blob = db.execute('SELECT length(data), substr(data,?,?) FROM attachments WHERE request_id=? AND ordinal=?',
                              (offset+1, 262144, key, index)).fetchone()
            if blob is None or offset > blob[0]:
                raise ValueError('Invalid attachment offset')
            return {'data_base64':base64.b64encode(blob[1]).decode('ascii'),
                    'next_offset':offset+len(blob[1]) if offset+len(blob[1]) < blob[0] else None}

    def claim(self, features=None):
        with self.db() as db:
            self._expire(db)
            row = db.execute("SELECT * FROM sends WHERE state='pending' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            payload = json.loads(row['payload'])
            feature_row = db.execute('SELECT features FROM bridge_features WHERE id=1').fetchone()
            if features is None:
                features = json.loads(feature_row[0]) if feature_row else []
            if (payload.get('attachments') and 'attachments_v1' not in features) or (payload.get('action') == 'draft' and 'draft_v1' not in features) or (payload.get('body_format') == 'html' and 'html_v1' not in features):
                return None
            token = secrets.token_hex(32)
            db.execute("UPDATE sends SET state='sending', claimed=?, token=? WHERE id=?", (self.clock(), token, row['id']))
            return {'request_id': row['id'], 'claim_token': token, 'payload': json.loads(row['payload'])}

    def complete(self, key, token, result):
        self.validate_key(key)
        if not isinstance(result, dict) or result.get('status') not in ('sent', 'drafted', 'failed', 'unknown'):
            raise ValueError('Invalid send outcome')
        if result['status'] == 'sent' and (not result.get('message_id') or result.get('copy_status') not in ('verified', 'not_verified')):
            raise ValueError('A sent outcome requires a Message-ID and copy_status')
        if result['status'] == 'drafted' and not result.get('drafts'):
            raise ValueError('A draft outcome requires saved draft IDs')
        clean = {k: result[k] for k in ('status', 'message_id', 'copy_status', 'copies', 'drafts', 'error') if k in result}
        serialized = json.dumps(clean, ensure_ascii=False)
        if len(serialized.encode()) > 100000:
            raise ValueError('Outcome too large')
        with self.db() as db:
            row = db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone()
            if not row or not row['token'] or not isinstance(token, str) or not secrets.compare_digest(row['token'], token):
                raise ValueError('Invalid claim token')
            meta = db.execute('SELECT action FROM request_meta WHERE id=?', (key,)).fetchone()
            action = meta[0] if meta else 'send'
            if (action == 'draft' and result['status'] == 'sent') or (action == 'send' and result['status'] == 'drafted'):
                raise ValueError('Outcome does not match request action')
            if row['result']:
                if row['result'] != serialized:
                    raise ValueError('Cannot overwrite an existing send outcome')
            else:
                db.execute('UPDATE sends SET state=?, result=?, payload=NULL WHERE id=?', (clean['status'], serialized, key))
                db.execute('DELETE FROM attachments WHERE request_id=?', (key,))
        return self.status(key)

    def _public(self, row, meta=None):
        state = row['state']
        if state == 'pending' and self.clock() - row['created'] > 60:
            state = 'expired'
        if state == 'sending' and self.clock() - row['claimed'] > 300:
            state = 'unknown'
        result = json.loads(row['result']) if row['result'] else {}
        public = {'request_id': row['id'], 'status': state, 'sent': True if state == 'sent' else (None if state in ('sending', 'unknown') else False),
                'safe_to_retry': False, 'created_at': row['created'], **result}
        if meta:
            public.update(action=meta['action'], attachments=json.loads(meta['attachments']))
            if meta['action'] == 'draft':
                public['sent'] = False
        return public

    def status(self, key):
        self.validate_key(key)
        with self.db() as db:
            self._expire(db)
            row = db.execute('SELECT * FROM sends WHERE id=?', (key,)).fetchone()
            meta = db.execute('SELECT * FROM request_meta WHERE id=?', (key,)).fetchone()
            return self._public(row, meta) if row else {'request_id': key, 'status': 'not_found', 'sent': False}


JOURNAL = SendJournal()


def send_email(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format='plain'):
    return JOURNAL.enqueue(idempotency_key, dict(to=to, subject=subject, body=body, from_email=from_email, cc=cc, bcc=bcc, body_format=body_format), attachments=attachments)
