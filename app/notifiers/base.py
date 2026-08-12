"""通知器基类。"""
from __future__ import annotations

from ..fetchers.base import Post


def why_badges(favorite: bool = False, keyword: bool = False) -> str:
    """新帖通知的「为什么推给你」徽标行：特别关注 / 命中关键词。"""
    return " · ".join(
        b
        for b in (("🔔 特别关注" if favorite else ""), ("🔑 命中关键词" if keyword else ""))
        if b
    )


class Notifier:
    channel = ""

    def notify(self, post: Post) -> None:
        raise NotImplementedError

    def send_text(self, text: str, reply_markup: list | None = None) -> None:
        raise NotImplementedError
