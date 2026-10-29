"""Native forward request boundary tests; no real Thunderbird or SMTP use."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mail_sender
import native_host
import server


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.journal = mail_sender.SendJournal(Path(self.tmp.name) / 'private' / 'send.db', clock=lambda: self.now)
        self.identities = [{'id': 'id1', 'email': 'sender@example.com', 'account_id': 'account1'}]
        self.accounts = [{'id': 'account1', 'type': 'pop3'}, {'id': 'source1', 'type': 'none'}]
        self.context = dict(message_id='original@example.test', account_id='source1',
                            identity_id='id1', mode='forward_attachment')
        self.payload = dict(to=['one@example.com'], cc=['copy@example.com'], bcc=[],
                            subject='Fwd: approved', body='Approved commentary',
                            from_email='sender@example.com', forward=self.context)

    def ready(self, features=None):
        native_host.dispatch(dict(op='poll', identities=self.identities, accounts=self.accounts,
                                  features=features if features is not None else ['forward_v1', 'forward_diagnostic_v1'], accept=False),
                             self.journal)

    def test_forward_capability_is_required_at_enqueue_and_claim(self):
        self.ready([])
        with self.assertRaisesRegex(ValueError, 'update it first'):
            self.journal.enqueue('forward', self.payload)
        self.ready()
        self.assertEqual(self.journal.enqueue('forward', self.payload)['status'], 'pending')
        self.assertIsNone(self.journal.claim(features=[]))
        self.assertIsNotNone(self.journal.claim(features=['forward_v1']))

    def test_forward_context_and_final_message_are_idempotent(self):
        self.ready()
        self.journal.enqueue('forward', self.payload)
        for changes in ({'message_id': 'other@example.test'}, {'account_id': 'account1'},
                        {'identity_id': 'id2'}, {'mode': 'forward_inline'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.journal.enqueue('forward', {**self.payload, 'forward': {**self.context, **changes}})
        for changes in ({'to': ['other@example.com']}, {'cc': []}, {'bcc': ['hidden@example.com']},
                        {'subject': 'changed'}, {'body': 'changed'}, {'body_format': 'html'}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'different'):
                self.journal.enqueue('forward', {**self.payload, **changes})

    def test_failed_forward_key_is_never_requeued_after_upgrade(self):
        self.ready()
        key = 'synthetic-failed-forward-before-upgrade'
        self.journal.enqueue(key, self.payload)
        claim = self.journal.claim(features=['forward_v1'])
        self.journal.complete(key, claim['claim_token'],
                              {'status': 'failed', 'error': 'Cannot prepare message; send was not attempted',
                               'failure_code': 'forward_raw_mismatch'})
        status = self.journal.enqueue(key, self.payload)
        self.assertEqual(status['status'], 'failed')
        self.assertEqual(status['failure_code'], 'forward_raw_mismatch')
        self.assertIsNone(self.journal.claim(features=['forward_v1']))

    def test_failure_codes_are_bounded_before_persistence(self):
        self.ready()
        self.journal.enqueue('diagnostic', self.payload)
        claim = self.journal.claim(features=['forward_v1'])
        with self.assertRaisesRegex(ValueError, 'failure code'):
            self.journal.complete('diagnostic', claim['claim_token'],
                                  {'status': 'failed', 'error': 'safe', 'failure_code': '/private/message.eml'})

    def test_prepare_diagnostic_uses_separate_non_send_domain(self):
        self.ready()
        context = dict(message_id='original@example.test', account_id='source1',
                       identity_id='id1', mode='forward_attachment')
        queued = self.journal.enqueue_forward_diagnostic('prepare-only', context, 'sender@example.com')
        self.assertEqual(queued['status'], 'pending')
        self.assertIsNone(self.journal.claim(features=['forward_v1']))
        job = self.journal.claim_forward_diagnostic()
        result = {'status':'prepared','source_size':123,'source_sha256':'a'*64,
                  'inherited':{'count':1,'items':[{'extension':'.eml','type_class':'message_rfc822'}]},
                  'reread':{'count':1,'size':123,'sha256':'a'*64,'equal':True,
                            'items':[{'extension':'.eml','type_class':'message_rfc822'}]},'close_confirmed':True}
        done = self.journal.complete_forward_diagnostic('prepare-only',job['claim_token'],result)
        self.assertEqual(done['status'],'prepared')
        self.assertIsNone(self.journal.claim(features=['forward_v1']))

    def test_prepare_diagnostic_requires_its_own_extension_capability(self):
        self.ready(['forward_v1'])
        with self.assertRaisesRegex(ValueError, 'update it first'):
            self.journal.enqueue_forward_diagnostic(
                'old-extension', self.context, 'sender@example.com')
        self.ready(['forward_v1', 'forward_diagnostic_v1'])
        self.assertEqual(
            self.journal.enqueue_forward_diagnostic(
                'current-extension', self.context, 'sender@example.com')['status'],
            'pending')

    def test_diagnostic_idempotency_tokens_completion_and_interrupted_recovery(self):
        self.ready();ctx=dict(message_id='original@example.test',account_id='source1',identity_id='id1',mode='forward_attachment')
        first=self.journal.enqueue_forward_diagnostic('same',ctx,'sender@example.com')
        self.assertEqual(self.journal.enqueue_forward_diagnostic('same',ctx,'sender@example.com'),first)
        with self.assertRaisesRegex(ValueError,'already bound'):
            self.journal.enqueue_forward_diagnostic('same',{**ctx,'account_id':'account1'},'sender@example.com')
        job=self.journal.claim_forward_diagnostic();result={'status':'failed','failure_stage':'forward_raw_read','close_confirmed':False}
        for token in ('','stale'):
            with self.assertRaisesRegex(ValueError,'token'):self.journal.complete_forward_diagnostic('same',token,result)
        self.journal.complete_forward_diagnostic('same',job['claim_token'],result)
        with self.assertRaisesRegex(ValueError,'token'):self.journal.complete_forward_diagnostic('same',job['claim_token'],result)
        self.journal.enqueue_forward_diagnostic('interrupted',ctx,'sender@example.com');self.journal.claim_forward_diagnostic();self.now+=16
        self.assertIsNone(self.journal.claim_forward_diagnostic())
        self.assertEqual(self.journal.forward_diagnostic_status('interrupted')['failure_stage'],'interrupted')

    def test_diagnostic_rejects_sensitive_mime_value(self):
        self.ready();ctx=dict(message_id='original@example.test',account_id='source1',identity_id='id1',mode='forward_attachment')
        self.journal.enqueue_forward_diagnostic('mime',ctx,'sender@example.com');job=self.journal.claim_forward_diagnostic()
        bad={'status':'failed','failure_stage':'forward_native_attachment','close_confirmed':True,
             'inherited':{'count':1,'items':[{'extension':'.eml','type_class':'private/customer-name'}]}}
        with self.assertRaisesRegex(ValueError,'attachment class'):
            self.journal.complete_forward_diagnostic('mime',job['claim_token'],bad)

    def test_diagnostic_attachment_summary_is_bounded_and_shape_checked(self):
        self.ready();items=[{'extension':'.eml','type_class':'message_rfc822'}]*16
        accepted={'status':'failed','failure_stage':'forward_native_attachment','close_confirmed':True,
                  'inherited':{'count':2500,'truncated':True,'items':items}}
        self.journal.enqueue_forward_diagnostic('bounded',self.context,'sender@example.com')
        job=self.journal.claim_forward_diagnostic()
        self.assertEqual(
            self.journal.complete_forward_diagnostic('bounded',job['claim_token'],accepted)
                ['inherited']['count'],
            2500)
        for index,section in enumerate((
                {'count':2500,'truncated':False,'items':items},
                {'count':17,'truncated':True,'items':items+[items[0]]},
                {'count':1,'items':{'extension':'.eml'}})):
            key=f'invalid-summary-{index}'
            self.journal.enqueue_forward_diagnostic(key,self.context,'sender@example.com')
            claim=self.journal.claim_forward_diagnostic()
            with self.assertRaisesRegex(ValueError,'attachment result'):
                self.journal.complete_forward_diagnostic(key,claim['claim_token'],
                    {'status':'failed','failure_stage':'forward_native_attachment',
                     'close_confirmed':True,'inherited':section})

    def test_diagnostic_accepts_only_fixed_reread_stages_with_safe_partial_metadata(self):
        for index,stage in enumerate(('reread_list','reread_get_file','reread_array_buffer','reread_hash','reread_compare')):
            self.ready();ctx=dict(message_id='original@example.test',account_id='source1',identity_id='id1',mode='forward_attachment')
            key=f'stage-{index}';self.journal.enqueue_forward_diagnostic(key,ctx,'sender@example.com');job=self.journal.claim_forward_diagnostic()
            result={'status':'failed','failure_stage':stage,'close_confirmed':True,
                    'reread':{'count':1,'size':None,'sha256':None,'equal':False,
                              'items':[{'extension':'.eml','type_class':'message_rfc822','metadata_size':123}]}}
            self.assertEqual(self.journal.complete_forward_diagnostic(key,job['claim_token'],result)['failure_stage'],stage)

    def test_invalid_context_and_forward_draft_fail_before_queue(self):
        for changes in ({'message_id': 'locator-1'}, {'account_id': ''}, {'identity_id': 'bad\n'},
                        {'mode': 'forward_inline'}, {'extra': 'unexpected'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.journal.enqueue('invalid', {**self.payload, 'forward': {**self.context, **changes}})
        self.ready(['forward_v1', 'draft_v1'])
        with self.assertRaisesRegex(ValueError, 'immediate send only'):
            self.journal.enqueue('draft-forward', self.payload, action='draft')

    def test_mcp_tool_exposes_and_enqueues_native_context(self):
        self.ready()
        tool = next(tool for tool in server.create_mcp('direct_send')._tool_manager.list_tools() if tool.name == 'forward_email')
        self.assertTrue({'source_message_id', 'source_account_id', 'identity_id', 'idempotency_key'}
                        <= set(tool.parameters['required']))
        self.assertEqual(tool.parameters['properties']['forward_mode']['default'], 'forward_attachment')
        with patch.object(mail_sender, 'JOURNAL', self.journal):
            result = server.forward_email(to=self.payload['to'], cc=self.payload['cc'], bcc=[],
                subject=self.payload['subject'], body=self.payload['body'], from_email=self.payload['from_email'],
                idempotency_key='mcp-forward', source_message_id='<original@example.test>',
                source_account_id='source1', identity_id='id1')
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(self.journal.claim()['payload']['forward'], self.context)


if __name__ == '__main__':
    unittest.main()
