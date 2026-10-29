import unittest
from unittest.mock import patch
import json
from pathlib import Path
import re

from mail_composer import ComposeInputError
import server
from server import compose_email, mcp


class ServerTests(unittest.TestCase):
    def test_documented_version_and_tool_count_match_runtime(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / 'pyproject.toml').read_text()
        version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE).group(1)
        total_tool_count = len(server.create_mcp('direct_send')._tool_manager.list_tools())
        manifest = json.loads((root / 'extension/manifest.json').read_text())
        self.assertEqual(manifest['version'], version)
        self.assertIn(
            f'Current version: **{version}**, with **{total_tool_count} tools** in total.',
            (root / 'README.md').read_text())
        self.assertIn(
            f'当前版本 **{version}**，总计 **{total_tool_count} 个工具**',
            (root / 'README.zh-CN.md').read_text())
        self.assertIn(
            f'## {total_tool_count} 个 MCP 工具（总目录）',
            (root / 'docs/reference.md').read_text())

    def test_html_format_is_exposed_and_reaches_both_queue_actions(self):
        import mail_sender
        from pathlib import Path
        from tempfile import TemporaryDirectory
        direct_mcp = server.create_mcp('direct_send')
        for name in ('send_email', 'create_draft'):
            tool = next(t for t in direct_mcp._tool_manager.list_tools() if t.name == name)
            self.assertEqual(tool.parameters['properties']['body_format']['default'], 'plain')
        with TemporaryDirectory() as directory:
            journal = mail_sender.SendJournal(Path(directory)/'private'/'send.db')
            journal.heartbeat([{'id':'id1','email':'sender@example.com'}], ['html_v1','draft_v1'])
            with patch.object(mail_sender, 'JOURNAL', journal):
                for name in ('send_email','create_draft'):
                    getattr(server,name)(['one@example.com'], 'HTML', '<p>测试</p>', 'sender@example.com', name, body_format='html')
                    job = journal.claim()
                    self.assertEqual(job['payload']['body_format'], 'html')
                    self.assertEqual(job['payload'].get('action','send'), 'draft' if name == 'create_draft' else 'send')

    def test_capability_profiles_register_only_allowed_tools(self) -> None:
        status_tools = {'get_send_status', 'get_send_capabilities', 'get_forward_diagnostic_status'}
        read_tools = {
            'list_mail_folders', 'query_email', 'read_emails', 'read_attachment',
            'search_email', 'read_email', 'list_recent_email', *status_tools,
        }
        review_tools = read_tools | {'compose_email', 'create_draft', 'diagnose_forward_preparation'}
        direct_tools = review_tools | {'send_email', 'reply_email', 'forward_email'}
        expected = {
            'read_only': read_tools,
            'review': review_tools,
            'direct_send': direct_tools,
        }

        for profile, names in expected.items():
            with self.subTest(profile=profile):
                actual = {tool.name for tool in server.create_mcp(profile)._tool_manager.list_tools()}
                self.assertEqual(actual, names)
        self.assertEqual({tool.name for tool in mcp._tool_manager.list_tools()}, review_tools)

    def test_invalid_capability_profile_fails_closed(self) -> None:
        for value in ('', 'send', 'DIRECT_SEND', 'direct-send', 'unknown'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'THUNDERBIRD_MCP_PROFILE'):
                server.normalize_capability_profile(value)

    def test_capabilities_report_active_server_profile(self) -> None:
        import mail_sender
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            journal = mail_sender.SendJournal(Path(directory)/'private'/'send.db')
            journal.heartbeat([{'id':'id1','email':'sender@example.com'}])
            with patch.object(mail_sender, 'JOURNAL', journal), patch.object(server, 'CAPABILITY_PROFILE', 'review'):
                result = server.get_send_capabilities()
        self.assertEqual(result['mcp_profile'], 'review')
        self.assertTrue(result['review_enabled'])
        self.assertFalse(result['direct_send_enabled'])

    def test_new_tools_read_real_fixture_and_attachment(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from mail_reader import MailReader
        from tests.test_mail_store import build_mailbox
        import server
        import base64
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Inbox'
            build_mailbox(path)
            with patch.object(server, 'READER', MailReader({'Inbox': path})):
                result = server.query_email(senders=['weekly.sender@example.test'])
                locator = result['messages'][0]['locator']
                read = server.read_emails([locator])['messages'][0]
                attachment = server.read_attachment(locator, read['attachments'][0]['attachment_id'])
                self.assertEqual(base64.b64decode(attachment['data_base64']), b'123')
                self.assertEqual(server.list_mail_folders()['folders'][0]['folder'], 'Inbox')

    def test_send_tool_returns_pending_then_durable_outcome(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import mail_sender
        import server
        with TemporaryDirectory() as directory:
            journal = mail_sender.SendJournal(Path(directory)/'private'/'send.db')
            journal.heartbeat([{'id':'id1','email':'sender@example.com'}])
            with patch.object(mail_sender, 'JOURNAL', journal):
                result = server.send_email(['one@example.com'], 'test', 'body', 'sender@example.com', 'req-1')
                self.assertEqual(result['status'], 'pending')
                claim = journal.claim()
                journal.complete('req-1', claim['claim_token'], {'status':'sent','message_id':'id@example.com','copy_status':'not_verified'})
                self.assertEqual(server.get_send_status('req-1')['status'], 'sent')
                self.assertTrue(server.get_send_capabilities()['ready'])

    @patch("server.COMPOSER")
    def test_compose_tool_delegates_without_sending(self, composer: object) -> None:
        composer.compose_email.return_value = {"opened": True, "sent": False}

        result = compose_email(
            "one@example.com",
            "主题",
            "正文",
            "copy@example.com",
            None,
        )

        self.assertEqual(result, {"opened": True, "sent": False})
        composer.compose_email.assert_called_once_with(
            to="one@example.com",
            subject="主题",
            body="正文",
            cc="copy@example.com",
            bcc=None,
        )

    @patch("server.COMPOSER")
    def test_compose_tool_translates_input_error(self, composer: object) -> None:
        composer.compose_email.side_effect = ComposeInputError("to 不能为空")

        with self.assertRaisesRegex(ValueError, "to 不能为空"):
            compose_email("", "主题", "正文")
