"""Exercise the public stdio interface without a harness or real mailbox."""
import base64
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

from tests.test_mail_store import build_mailbox


ROOT = Path(__file__).resolve().parents[1]


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_stdio_clients_discover_and_read_without_a_harness(self):
        example = json.loads((ROOT / 'examples/mcp-stdio.json').read_text())
        config = example['mcpServers']['thunderbird_mail']
        self.assertEqual(config['type'], 'stdio')
        with TemporaryDirectory(prefix='mail-mcp protocol ') as directory:
            temporary = Path(directory)
            mailbox = temporary / 'FixtureInbox'
            build_mailbox(mailbox)
            sent = temporary / 'Sent'
            build_mailbox(sent)
            original = mailbox.read_bytes()
            original_sent = sent.read_bytes()
            replacements = {
                config['command']: sys.executable,
                config['args'][0]: str(ROOT / 'server.py'),
                config['env']['THUNDERBIRD_INBOX_PATH']: str(mailbox),
            }
            parameters = StdioServerParameters(
                command=replacements[config['command']],
                args=[replacements[arg] for arg in config['args']],
                env={name: replacements[value] for name, value in config['env'].items()},
                cwd=temporary,
            )
            for name in ('neutral-client-alpha', 'neutral-client-beta'):
                with self.subTest(client=name), anyio.fail_after(30):
                    with (temporary / f'{name}.stderr').open('w') as diagnostics:
                        async with stdio_client(parameters, errlog=diagnostics) as (reader, writer):
                            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15),
                                                     client_info=Implementation(name=name, version='1.0')) as session:
                                initialized = await session.initialize()
                                self.assertEqual(initialized.serverInfo.name, 'Thunderbird Mail')
                                tools = (await session.list_tools()).tools
                                self.assertEqual(len(tools), 12)
                                self.assertTrue({'query_email', 'read_emails', 'read_attachment',
                                                 'create_draft', 'send_email'} <= {tool.name for tool in tools})

                                async def call(tool, arguments=None):
                                    result = await session.call_tool(tool, arguments or {})
                                    self.assertFalse(result.isError, result.content)
                                    return result.structuredContent or json.loads(result.content[0].text)

                                folders = await call('list_mail_folders')
                                self.assertEqual(folders['folders'][0]['folder'], 'Inbox')
                                query = await call('query_email', {'senders': ['weekly.sender@example.test']})
                                self.assertEqual(query['total_matches'], 1)
                                locator = query['messages'][0]['locator']
                                read = await call('read_emails', {'locators': [locator]})
                                message = read['messages'][0]
                                self.assertIn('SLA', message['body'])
                                attachment = await call('read_attachment', {
                                    'locator': locator, 'attachment_id': message['attachments'][0]['attachment_id']})
                                self.assertEqual(base64.b64decode(attachment['data_base64']), b'123')
                                self.assertEqual(attachment['sha256'], hashlib.sha256(b'123').hexdigest())
                                sent_query = await call('query_email', {
                                    'senders': ['weekly.sender@example.test'], 'folders': ['Sent']})
                                self.assertEqual(sent_query['total_matches'], 1)
                                self.assertEqual(sent_query['messages'][0]['folder'], 'Sent')
                                sent_locator = sent_query['messages'][0]['locator']
                                sent_read = await call('read_emails', {'locators': [sent_locator]})
                                self.assertIn('SLA', sent_read['messages'][0]['body'])
                                sent_attachment = await call('read_attachment', {
                                    'locator': sent_locator,
                                    'attachment_id': sent_read['messages'][0]['attachments'][0]['attachment_id']})
                                self.assertEqual(base64.b64decode(sent_attachment['data_base64']), b'123')
                                both = await call('query_email', {
                                    'senders': ['weekly.sender@example.test'], 'folders': ['Inbox', 'Sent']})
                                self.assertEqual(both['total_matches'], 2)
                                self.assertEqual({item['folder'] for item in both['messages']}, {'Inbox', 'Sent'})
                self.assertEqual(mailbox.read_bytes(), original)
                self.assertEqual(sent.read_bytes(), original_sent)
