"""Reply request boundary tests. All identities and journals are synthetic."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mail_sender
import native_host
import server


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.j = mail_sender.SendJournal(Path(self.tmp.name)/'private'/'send.db', clock=lambda:self.now)
        self.identities = [{'id':'id1','email':'sender@example.com','account_id':'account1'}]
        self.accounts = [{'id':'account1','type':'pop3','name':'Synthetic account'}, {'id':'local1','type':'none','name':'Local folders'}]
        self.context = dict(message_id='original@example.test', account_id='local1', identity_id='id1', mode='reply_all')
        self.payload = dict(to=['one@example.com'],cc=['copy@example.com'],bcc=[],
                            subject='Re: approved',body='Approved text\nSignature',from_email='sender@example.com',reply=self.context)

    def ready(self, features=None):
        native_host.dispatch(dict(op='poll',identities=self.identities,accounts=self.accounts,
                                  features=features if features is not None else ['reply_v1'],accept=False), self.j)

    def test_native_capabilities_expose_account_ids_without_guessing(self):
        self.ready()
        caps = self.j.capabilities()
        self.assertEqual(caps['accounts'],self.accounts)
        self.assertEqual(caps['identities'],self.identities)
        self.assertIn('reply_v1',caps['features'])

    def test_reply_requires_new_extension_and_current_source_identity(self):
        for features,changes in [([],{}),(['reply_v1'],{'identity_id':'wrong'}),
                                 (['reply_v1'],{'account_id':'missing'})]:
            with self.subTest(features=features,changes=changes):
                self.ready(features)
                with self.assertRaises(ValueError):
                    self.j.enqueue('reply', {**self.payload,'reply':{**self.context,**changes}})
                self.assertEqual(self.j.status('reply')['status'],'not_found')

    def test_context_reaches_claim_and_is_immutable_across_retries(self):
        self.ready()
        first = self.j.enqueue('reply', self.payload)
        self.assertEqual(first['status'],'pending')
        claim = self.j.claim()
        self.assertEqual(claim['payload']['reply'], self.context)
        self.assertEqual(claim['payload']['identity_account_id'],'account1')
        self.assertIsNone(self.j.claim())
        # Angle brackets represent the same RFC Message-ID, but no other context may change.
        self.assertEqual(self.j.enqueue('reply',{**self.payload,'reply':{**self.context,'message_id':'<original@example.test>'}})['status'],'sending')
        for changes in ({'message_id':'other@example.test'},{'mode':'reply_sender'},
                        {'account_id':'account1'},{'identity_id':'id2'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError,'different'):
                self.j.enqueue('reply',{**self.payload,'reply':{**self.context,**changes}})
        for changes in ({'to':['other@example.com']},{'cc':[]},{'bcc':['hidden@example.com']},
                        {'body':'changed'},{'body_format':'html'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError,'different'):
                self.j.enqueue('reply',{**self.payload,**changes})
        self.now += 301
        self.assertEqual(self.j.enqueue('reply',self.payload)['status'],'unknown')
        self.assertIsNone(self.j.claim())

    def test_downgraded_extension_cannot_claim_reply(self):
        self.ready()
        self.j.enqueue('reply', self.payload)
        self.assertIsNone(self.j.claim(features=[]))
        self.assertEqual(self.j.status('reply')['status'],'pending')
        self.assertIsNotNone(self.j.claim(features=['reply_v1']))

    def test_completed_failed_or_unknown_reply_is_never_requeued(self):
        for status in ('failed','unknown'):
            self.ready()
            self.j.enqueue(status,self.payload)
            claim = self.j.claim()
            self.j.complete(status,claim['claim_token'],{'status':status,'error':'synthetic outcome'})
            self.assertEqual(self.j.enqueue(status,self.payload)['status'],status)
            self.assertIsNone(self.j.claim())

    def test_invalid_source_ids_modes_and_draft_reply_fail_before_queue(self):
        for changes in ({'message_id':''},{'message_id':'locator-1'}, {'message_id':'id@example.test\r\nBcc: other@example.com'},
                        {'message_id':'<broken@example.test'}, {'account_id':''}, {'identity_id':'bad\n'},
                        {'mode':'new'}, {'extra':'unexpected'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.j.enqueue('invalid',{**self.payload,'reply':{**self.context,**changes}})
        with self.assertRaisesRegex(ValueError,'send only'):
            self.j.enqueue('invalid',self.payload,action='draft')
        self.assertFalse(self.j.path.exists())

    def test_message_id_rejects_every_c0_and_del_character(self):
        for code in (*range(32),127):
            for value in (f'original{chr(code)}@example.test',f'original@example{chr(code)}.test'):
                with self.subTest(code=code,value=repr(value)), self.assertRaises(ValueError):
                    self.j.enqueue('invalid',{**self.payload,'reply':{**self.context,'message_id':value}})
        for value in ('original@example.test','<original@example.test>','part+tag.123@example.test'):
            with self.subTest(value=value):
                actual = mail_sender.validate_reply({**self.context,'message_id':value})
                self.assertEqual(actual['message_id'],value.strip('<>'))
        self.assertFalse(self.j.path.exists())

    def test_mcp_tool_exposes_and_enqueues_explicit_context(self):
        self.ready()
        tool = next(t for t in server.create_mcp('direct_send')._tool_manager.list_tools() if t.name == 'reply_email')
        self.assertTrue({'source_message_id','source_account_id','identity_id','idempotency_key'} <= set(tool.parameters['required']))
        with patch.object(mail_sender,'JOURNAL',self.j):
            server.reply_email(to=self.payload['to'],cc=self.payload['cc'],subject=self.payload['subject'],
                               body=self.payload['body'],from_email=self.payload['from_email'],idempotency_key='mcp-reply',
                               source_message_id='<original@example.test>',source_account_id='local1',identity_id='id1')
        self.assertEqual(self.j.claim()['payload']['reply'],self.context)

    def test_legacy_digest_and_heartbeat_remain_compatible(self):
        legacy = {key:value for key,value in self.payload.items() if key != 'reply'}
        self.j.heartbeat([{'id':'id1','email':'sender@example.com'}])
        self.j.enqueue('legacy',legacy)
        with self.j.db() as db:
            stored = db.execute('SELECT digest FROM sends WHERE id=?',('legacy',)).fetchone()[0]
        self.assertEqual(stored,mail_sender.SendJournal._digest(legacy))
        self.assertEqual(self.j.enqueue('legacy',legacy)['status'],'pending')
        self.assertEqual(self.j.capabilities()['accounts'],[])


if __name__ == '__main__':
    unittest.main()
