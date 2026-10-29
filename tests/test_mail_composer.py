from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from mail_composer import ComposeInputError, MailComposer, ThunderbirdLaunchError


class MailComposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.executable = Path(self.tempdir.name) / "thunderbird"
        self.executable.touch()
        self.calls: list[tuple[list[str], dict[str, object]]] = []

        def launch(args: list[str], **options: object) -> object:
            self.calls.append((args, options))
            return object()

        self.composer = MailComposer(self.executable, launcher=launch)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_compose_launches_thunderbird_with_prefilled_fields(self) -> None:
        result = self.composer.compose_email(
            to="one@example.com,two@example.com",
            cc="copy@example.com",
            bcc="audit@example.com",
            subject="中文周报",
            body="第一行\n第二行",
        )

        self.assertEqual(
            self.calls,
            [
                (
                    [
                        str(self.executable),
                        "-compose",
                        "to='one@example.com,two@example.com',cc='copy@example.com',bcc='audit@example.com',subject='中文周报',body='第一行\n第二行'",
                    ],
                    {
                        "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                        "start_new_session": True,
                    },
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "opened": True,
                "sent": False,
                "message": "Thunderbird compose process launched; window readiness is unverified; this tool did not send mail.",
            },
        )

    def test_compose_escapes_backslashes_and_single_quotes(self) -> None:
        self.composer.compose_email(
            to="one@example.com",
            subject="项目 'A'",
            body="路径 C:\\Temp 和 '引用'",
        )

        compose_argument = self.calls[0][0][2]
        self.assertIn("subject='项目 \\'A\\''", compose_argument)
        self.assertIn("body='路径 C:\\\\Temp 和 \\'引用\\''", compose_argument)

    def test_compose_rejects_blank_required_fields(self) -> None:
        for field in ("to", "subject", "body"):
            arguments = {
                "to": "one@example.com",
                "subject": "主题",
                "body": "正文",
            }
            arguments[field] = "   "
            with self.subTest(field=field), self.assertRaises(ComposeInputError):
                self.composer.compose_email(**arguments)

    def test_compose_rejects_header_injection_and_body_nul(self) -> None:
        invalid_arguments = [
            {
                "to": "one@example.com\nBcc: hidden@example.com",
                "subject": "主题",
                "body": "正文",
            },
            {
                "to": "one@example.com",
                "subject": "主题\r\nBcc: hidden@example.com",
                "body": "正文",
            },
            {
                "to": "one@example.com",
                "subject": "主题",
                "body": "正文\x00尾部",
            },
        ]
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments), self.assertRaises(ComposeInputError):
                self.composer.compose_email(**arguments)

    def test_compose_reports_missing_thunderbird(self) -> None:
        missing = MailComposer(
            Path(self.tempdir.name) / "missing",
            launcher=lambda *args, **kwargs: object(),
        )

        with self.assertRaisesRegex(ThunderbirdLaunchError, "未找到 Thunderbird"):
            missing.compose_email("one@example.com", "主题", "正文")

    def test_compose_wraps_process_launch_failure(self) -> None:
        def fail_launch(*args: object, **kwargs: object) -> object:
            raise OSError("launch failed")

        composer = MailComposer(self.executable, launcher=fail_launch)

        with self.assertRaisesRegex(ThunderbirdLaunchError, "无法启动 Thunderbird"):
            composer.compose_email("one@example.com", "主题", "正文")
