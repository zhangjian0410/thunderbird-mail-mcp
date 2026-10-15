import base64
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from mail_sender import SendJournal

class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.now=1000
        self.j=SendJournal(self.root/'private'/'s.db', clock=lambda:self.now)
        self.ids=[{'id':'id1','email':'from@example.com'}]
        self.p=dict(to=['to@example.com'],from_email='from@example.com',subject='test',body='body')
        self.file=self.root/'附件.bin'; self.data=b'abc\x00'*200000; self.file.write_bytes(self.data)
        self.a={'path':str(self.file),'sha256':hashlib.sha256(self.data).hexdigest()}
    def ready(self): self.j.heartbeat(self.ids,features=['attachments_v1','draft_v1'])
    def test_snapshot_chunked_and_source_change_cannot_change_queued_bytes(self):
        self.ready(); self.j.enqueue('a',self.p,attachments=[self.a]); self.file.write_bytes(b'new')
        job=self.j.claim(); meta=job['payload']['attachments'][0]
        self.assertEqual(meta['sha256'],self.a['sha256']); self.assertNotIn('path',meta)
        content=b''
        while len(content)<meta['size']:
            r=self.j.attachment_chunk('a',job['claim_token'],0,len(content))
            self.assertLess(len(r['data_base64']),400000)
            content+=base64.b64decode(r['data_base64'])
        self.assertEqual(content,self.data)
        with self.assertRaises(ValueError): self.j.attachment_chunk('a','wrong',0,0)
        self.assertEqual(self.j.enqueue('a',self.p,attachments=[self.a]),self.j.status('a'))
        with self.assertRaises(ValueError): self.j.enqueue('new-request',self.p,attachments=[self.a])
    def test_stale_extension_rejects_attachment_and_draft(self):
        self.j.heartbeat(self.ids)
        for opts in [dict(attachments=[self.a]),dict(action='draft')]:
            with self.assertRaisesRegex(ValueError,'support'): self.j.enqueue('a',self.p,**opts)
        self.assertEqual(self.j.status('a')['status'],'not_found')
    def test_hash_mismatch_and_nonfile_are_rejected_before_enqueue(self):
        self.ready()
        for a in [{**self.a,'sha256':'0'*64},{'path':str(self.root),'sha256':'0'*64},{'path':'relative','sha256':'0'*64}]:
            with self.assertRaises(ValueError): self.j.enqueue('a',self.p,attachments=[a])
        self.assertEqual(self.j.status('a')['status'],'not_found')
    def test_draft_cannot_report_sent_and_completion_releases_blob(self):
        self.ready(); self.j.enqueue('a',self.p,attachments=[self.a],action='draft'); job=self.j.claim()
        with self.assertRaises(ValueError): self.j.complete('a',job['claim_token'],{'status':'sent','message_id':'x','copy_status':'verified'})
        self.j.complete('a',job['claim_token'],{'status':'drafted','drafts':[{'id':42}]})
        self.assertFalse(self.j.status('a')['sent'])
        self.assertEqual(self.j.status('a')['attachments'][0]['sha256'],self.a['sha256'])
        with self.assertRaises(ValueError): self.j.attachment_chunk('a',job['claim_token'],0,0)
    def test_expiry_removes_snapshots(self):
        self.ready(); self.j.enqueue('a',self.p,attachments=[self.a]); self.now+=61
        self.assertEqual(self.j.status('a')['status'],'expired')
        with self.j.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM attachments').fetchone()[0],0)

    def test_claimant_features_are_not_taken_from_other_connection(self):
        self.ready(); self.j.enqueue('a',self.p,attachments=[self.a],action='draft')
        self.assertIsNone(self.j.claim(features=[]))
        self.assertEqual(self.j.status('a')['status'],'pending')
        self.assertIsNotNone(self.j.claim(features=['attachments_v1','draft_v1']))

    def test_limits_and_empty_files(self):
        from mail_sender import snapshot_attachments
        self.file.write_bytes(b'')
        empty={**self.a,'sha256':hashlib.sha256(b'').hexdigest()}
        metadata,blobs=snapshot_attachments([empty]*10)
        self.assertEqual(len(metadata),10); self.assertEqual(blobs,[b'']*10)
        with self.assertRaises(ValueError): snapshot_attachments([empty]*11)
        data=b'x'*(20*1024*1024); self.file.write_bytes(data)
        full={**self.a,'sha256':hashlib.sha256(data).hexdigest()}
        self.assertEqual(snapshot_attachments([full])[0][0]['size'],len(data))
        with self.assertRaises(ValueError): snapshot_attachments([full,self.a])
        self.file.write_bytes(data+b'x')
        with self.assertRaises(ValueError): snapshot_attachments([full])

    def test_draft_retry_preserves_unsent_status_and_manifest(self):
        self.ready(); initial=self.j.enqueue('a',self.p,attachments=[self.a],action='draft')
        self.assertEqual(initial['action'],'draft')
        self.assertEqual(initial['attachments'][0]['sha256'],self.a['sha256'])
        self.j.claim(); self.now+=301
        retry=self.j.enqueue('a',self.p,attachments=[self.a],action='draft')
        self.assertEqual(retry,self.j.status('a'))
        self.assertIs(retry['sent'],False)
