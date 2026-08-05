from app.fetchers.base import Post, truncate_text
from app.notifiers.feishu import (
    build_feishu_card,
    build_feishu_combination_card,
    build_feishu_daily_card,
)
from app.notifiers.telegram import (
    build_combination_text,
    build_telegram_daily,
    build_telegram_text,
)


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


def test_truncate_text_short_keeps_all():
    assert truncate_text("短文本", 100) == "短文本"
    assert truncate_text("", 100) == ""


def test_truncate_text_cuts_with_ellipsis():
    long_text = "第一句。" + "中" * 300 + "。结尾句"
    t = truncate_text(long_text, 200)
    assert t.endswith("…")
    assert len(t) <= 201
    assert "第一句。" in t


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


def test_daily_builders():
    posts = [make_post(), make_post()]
    text = build_telegram_daily(posts)
    assert "今日大V精选" in text and "张三" in text
    card = build_feishu_daily_card(posts)
    assert "今日大V精选" in card["header"]["title"]["content"]


def make_combination_post() -> Post:
    return Post(
        platform="combination",
        kol_id=2,
        kol_name="伯言-A股",
        external_id="1",
        title="伯言-A股 调仓",
        content="年化 27.1% · 净值 1.271\n🗑 永杉锂业 清仓 21.1%",
        url="https://xueqiu.com/P/ZH3623878",
        published_at="2026-08-04",
        detail={
            "stats": [("年化", "27.1%"), ("净值", "1.271")],
            "actions": [
                {"type": "清仓", "stock": "永杉锂业", "symbol": "SH603399", "prev": "21.1%", "target": "0.0%"},
                {"type": "新建", "stock": "天华新能", "symbol": "SZ300390", "prev": "0.0%", "target": "20.0%"},
            ],
            "cash": "80.0%",
        },
    )


def test_combination_text_layout():
    text = build_combination_text(make_combination_post())
    assert "<b>📌 伯言-A股 · 雪球组合 · 调仓</b>" in text
    assert "<b>年化</b> 27.1%　<b>净值</b> 1.271" in text
    assert "🗑 <b>清仓</b>　永杉锂业（SH603399）" in text
    assert "　　21.1% → 0.0%" in text
    assert "💵 现金 <b>80.0%</b>" in text
    # 每个操作独立成块，避免挤在一行
    assert text.count("→") == 2


def test_combination_feishu_card():
    card = build_feishu_combination_card(make_combination_post())
    assert card["card"]["header"]["title"]["content"] == "📌 伯言-A股 · 雪球组合 · 调仓"
    contents = [
        e["text"]["content"]
        for e in card["card"]["elements"]
        if e.get("tag") == "div" and e.get("text")
    ]
    assert any("**年化** 27.1%" in c for c in contents)
    assert any("🗑 **清仓** 永杉锂业（SH603399）" in c for c in contents)
    assert any("💵 现金 **80.0%**" in c for c in contents)
