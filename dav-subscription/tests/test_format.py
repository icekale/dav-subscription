from app.fetchers.base import Post
from app.notifiers.feishu import build_feishu_card
from app.notifiers.telegram import build_telegram_text


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="1",
        title="看多",
        content="今天 <b>大涨</b>",
        url="https://xueqiu.com/1",
        published_at="2026-08-04",
    )


def test_feishu_card_contains_author_and_url():
    card = build_feishu_card(make_post())
    assert card["msg_type"] == "interactive"
    assert "📌 张三 · 雪球" in card["card"]["header"]["title"]["content"]
    button = card["card"]["elements"][-1]["actions"][0]
    assert button["url"] == "https://xueqiu.com/1"


def test_telegram_text_escapes_html():
    text = build_telegram_text(make_post())
    # 头部为加粗的大V名，帖子标题作为正文兜底
    assert "<b>📌 张三 · 雪球</b>" in text
    assert "&lt;b&gt;大涨&lt;/b&gt;" in text
    # 正文不再重复出现「📌 张三 · 雪球」这一行
    assert text.count("📌 张三 · 雪球") == 1
    assert 'href="https://xueqiu.com/1"' in text
    # 正文为空时用帖子标题兜底
    empty = make_post()
    empty.content = ""
    assert "看多" in build_telegram_text(empty)
