import unittest
from unittest.mock import patch
import json
from pathlib import Path
import re

from mail_composer import ComposeInputError
from server import compose_email, mcp


class ServerTests(unittest.TestCase):
    def test_documented_version_and_tool_count_match_runtime(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / 'pyproject.toml').read_text()
        version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE).group(1)
        tool_count = len(mcp._tool_manager.list_tools())
        manifest = json.loads((root / 'extension/manifest.json').read_text())
        self.assertEqual(manifest['version'], version)
        self.assertIn(
            f'当前版本 **{version}**，提供 **{tool_count} 个工具**',
            (root / 'README.md').read_text())
        self.assertIn(
            f'## {tool_count} 个 MCP 工具',
            (root / 'docs/reference.md').read_text())

    def test_html_format_is_exposed_and_reaches_both_queue_actions(self):
        import server, mail_sender
        from pathlib import Path
        from tempfile import TemporaryDirectory
        for name in ('send_email', 'create_draft'):
            tool = next(t for t in mcp._tool_manager.list_tools() if t.name == name)
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

    def test_server_registers_read_tools_and_native_compose_tool(self) -> None:
        tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}

        self.assertEqual(
            tool_names,
            {"search_email", "read_email", "list_recent_email", "compose_email",
             "list_mail_folders", "query_email", "read_emails", "read_attachment",
             "send_email", "reply_email", "forward_email", "get_send_status", "get_send_capabilities", "create_draft",
             "diagnose_forward_preparation", "get_forward_diagnostic_status"},
        )

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
