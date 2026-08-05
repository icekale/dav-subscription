"""通知器基类。"""
from __future__ import annotations

from ..fetchers.base import Post


class Notifier:
    channel = ""

    def notify(self, post: Post) -> None:
        raise NotImplementedError

    def send_text(self, text: str) -> None:
        raise NotImplementedError
