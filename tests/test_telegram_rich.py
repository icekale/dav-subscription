from app.fetchers.base import Post
from app.notifiers.telegram_rich import build_telegram_rich_html


def make_post() -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="1",
        title="看多",
        content="今天 <b>大涨</b>\n第二段",
        url="https://xueqiu.com/1",
        published_at="2026-08-04",
        category="实盘",
        tags=["宏观", "白酒"],
    )


def test_single_post_rich_has_heading_paragraphs_tags():
    html = build_telegram_rich_html(make_post())
    assert "<h2>" in html and "张三" in html and "雪球" in html
    assert "&lt;b&gt;大涨&lt;/b&gt;" in html
    assert "<p>第二段</p>" in html
    assert "<hr>" in html
    assert "宏观" in html and "白酒" in html
    assert "实盘" in html
    assert 'href="https://xueqiu.com/1"' in html
    assert "<script>" not in html


def test_single_post_rich_marks_badges_and_reply_quote():
    post = make_post()
    post.post_type = "reply"
    html = build_telegram_rich_html(post, favorite=True, keyword=True)
    assert "特别关注" in html
    assert "命中关键词" in html
    assert "回复" in html
    assert "<blockquote>" in html


def test_zsxq_rich_omits_original_link():
    post = make_post()
    post.platform = "zsxq"
    post.url = "https://wx.zsxq.com/1"
    html = build_telegram_rich_html(post)
    assert "查看原文" not in html
    assert "href=" not in html
