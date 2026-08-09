"""纯代码关键词规则打标：零 token，子串匹配，词表顺序取前 3 个。"""
from app.fetchers.base import Post
from app.tagging import TAG_PER_POST_MAX, rule_tag_posts


def make_post(content="正文内容", title="标题", external_id="p1") -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id=external_id,
        title=title,
        content=content,
        url="https://xueqiu.com/1/2",
        published_at="",
    )


RULES = [
    {"tag": "宏观", "keywords": ["央行", "降息", "GDP", "美联储"]},
    {"tag": "科技", "keywords": ["AI", "芯片", "大模型"]},
    {"tag": "政策", "keywords": ["证监会", "监管", "政策"]},
    {"tag": "资讯", "keywords": ["消息", "据悉"]},
]


def test_keyword_hit_assigns_tag():
    post = make_post(content="央行宣布降息，市场反应积极")
    result = rule_tag_posts([post], RULES)
    assert result[0] == ["宏观"]


def test_multiple_keywords_multiple_tags():
    post = make_post(content="美联储降息，AI 芯片板块大涨")
    result = rule_tag_posts([post], RULES)
    # 宏观（美联储/降息）、科技（AI/芯片）都命中
    assert "宏观" in result[0] and "科技" in result[0]


def test_max_three_tags_in_vocab_order():
    post = make_post(content="央行降息 AI 芯片 证监会监管 消息面复杂")
    result = rule_tag_posts([post], RULES)
    # 4 个标签都命中，只保留前 3 个（按词表顺序）
    assert len(result[0]) == TAG_PER_POST_MAX
    assert result[0] == ["宏观", "科技", "政策"]


def test_no_keyword_hit_returns_empty():
    post = make_post(content="今天天气不错，出去走走")
    result = rule_tag_posts([post], RULES)
    assert result[0] == []


def test_english_keyword_case_insensitive():
    post = make_post(content="NVIDIA 发布新一代 gpu，ai 应用加速")
    result = rule_tag_posts([post], RULES)
    assert result[0] == ["科技"]


def test_empty_rules_or_text_no_error():
    assert rule_tag_posts([make_post(content="任何内容")], []) == {0: []}
    assert rule_tag_posts([make_post(content="", title="")], RULES) == {0: []}


def test_rule_without_keywords_never_hits():
    post = make_post(content="宏观 这个词出现也没用")
    result = rule_tag_posts([post], [{"tag": "宏观", "keywords": []}])
    assert result[0] == []


def test_multiple_posts_mapping():
    posts = [make_post(content="央行降息", external_id="a"), make_post(content="无聊内容", external_id="b")]
    result = rule_tag_posts(posts, RULES)
    assert result[0] == ["宏观"]
    assert result[1] == []
