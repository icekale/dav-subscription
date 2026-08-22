from app.fetchers.base import Post, format_published_at, strip_html, truncate_text
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


def test_strip_html_decodes_entities():
    # 数字实体（&#34; 引号）与常见命名实体都应还原
    assert strip_html('苹果&#34;A20 Pro&#34;处理器') == '苹果"A20 Pro"处理器'
    assert strip_html("<b>大涨</b><br/>继续") == "大涨\n继续"
    assert strip_html("&lt;b&gt;字面&lt;/b&gt;") == "<b>字面</b>"
    assert strip_html("&amp;lt;") == "&lt;"
    assert strip_html("a&nbsp;b") == "a b"


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
    button = card["card"]["body"]["elements"][-1]
    assert button["behaviors"][0]["default_url"] == "https://xueqiu.com/1"


def test_telegram_text_escapes_html():
    text = build_telegram_text(make_post())
    # 头部为加粗的大V名，帖子标题作为正文兜底
    assert "<b>📌 张三 · 雪球</b>" in text
    assert "&lt;b&gt;大涨&lt;/b&gt;" in text
    assert "🕐 2026-08-04" in text
    # 正文不再重复出现「📌 张三 · 雪球」这一行
    assert text.count("📌 张三 · 雪球") == 1
    assert "查看原文" not in text
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
    assert "年化 27.1% · 净值 1.271" in text
    assert "🗑 清仓　永杉锂业（SH603399）" in text
    assert "🆕 新建　天华新能（SZ300390）" in text
    assert "21.1% → 0.0%" in text
    assert "💵 现金 80.0% · 🕐 2026-08-04" in text
    assert "查看原文" not in text
    # 每个操作独立成块，避免挤在一行
    assert text.count("→") == 2


def test_combination_feishu_card():
    card = build_feishu_combination_card(make_combination_post())
    assert card["card"]["header"]["title"]["content"] == "📌 伯言-A股 · 雪球组合 · 调仓"
    contents = [
        e["text"]["content"]
        for e in card["card"]["body"]["elements"]
        if e.get("tag") == "div" and e.get("text")
    ]
    assert any("**年化** 27.1%" in c for c in contents)
    assert any("🗑 **清仓** 永杉锂业（SH603399）" in c for c in contents)
    assert any("💵 现金 **80.0%**" in c for c in contents)


def test_format_published_at_rfc2822():
    # X：UTC +0000 转北京时间
    assert format_published_at("Fri Aug 06 10:00:00 +0000 2026") == "2026-08-06 18:00"
    # 微博：已带 +0800
    assert format_published_at("Wed Aug 05 21:00:00 +0800 2026") == "2026-08-05 21:00"
    # 已是可读格式的不动
    assert format_published_at("2026-08-04 21:00") == "2026-08-04 21:00"
    # 纯数字毫秒时间戳继续转换
    assert format_published_at("1720000000000") == "2024-07-03 17:46"
