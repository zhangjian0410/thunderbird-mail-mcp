from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess


THUNDERBIRD_PATH = Path("/Applications/Thunderbird.app/Contents/MacOS/thunderbird")


class ComposeInputError(ValueError):
    pass


class ThunderbirdLaunchError(RuntimeError):
    pass


class MailComposer:
    def __init__(
        self,
        executable: str | Path = THUNDERBIRD_PATH,
        launcher: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self._executable = Path(executable)
        self._launcher = launcher

    def compose_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, object]:
        fields = [
            ("to", self._require_header(to, "to")),
            ("cc", self._optional_header(cc, "cc")),
            ("bcc", self._optional_header(bcc, "bcc")),
            ("subject", self._require_header(subject, "subject")),
            ("body", self._require_body(body)),
        ]
        if not self._executable.is_file():
            raise ThunderbirdLaunchError(f"未找到 Thunderbird：{self._executable}")
        compose_argument = ",".join(
            f"{name}='{self._escape(value)}'"
            for name, value in fields
            if value is not None
        )
        try:
            self._launcher(
                [str(self._executable), "-compose", compose_argument],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            raise ThunderbirdLaunchError(f"无法启动 Thunderbird：{error}") from error
        return {
            "opened": True,
            "sent": False,
            "message": "Thunderbird 写信窗口已打开；邮件尚未发送。",
        }

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _require_header(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ComposeInputError(f"{field_name} 不能为空")
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ComposeInputError(f"{field_name} 不能包含控制字符")
        return value.strip()

    @classmethod
    def _optional_header(cls, value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        return cls._require_header(value, field_name)

    @staticmethod
    def _require_body(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ComposeInputError("body 不能为空")
        if "\x00" in value:
            raise ComposeInputError("body 不能包含 NUL")
        return value
