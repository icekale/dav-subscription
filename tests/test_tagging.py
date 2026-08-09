"""纯代码关键词规则打标：零 token，子串匹配，词表顺序取前 3 个。"""
from app.fetchers.base import Post
from app.tagging import (
    TAG_PER_POST_MAX,
    cleanup_stale_tags,
    extract_alias_candidates,
    rule_tag_posts,
    stock_tag_posts,
)


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


def test_stock_mark_extraction():
    """$股票名(代码)$ 标记精确提取，排除 ZH 组合/BK 板块。"""
    post = make_post(content="我关注了 $中船特气(SH688146)$，今天继续涨价。")
    result = stock_tag_posts([post], [])
    assert result[0] == ["中船特气"]


def test_stock_mark_excludes_combination_and_index():
    """ZH 组合、BK 板块指数等非个股标记不打标。"""
    post = make_post(content="关注了 $伯言-A股(ZH3623878)$ 组合，$半导体(BK1036)$ 板块。")
    result = stock_tag_posts([post], [])
    assert result[0] == []


def test_stock_mark_strips_new_prefix():
    """新股前缀（N长鑫）去掉后才是股票名。"""
    post = make_post(content="$N长鑫(SH688825)$ 今日上市。")
    result = stock_tag_posts([post], [])
    assert result[0] == ["长鑫"]


def test_stock_name_substring_match():
    """纯文字提及命中常用股票名表。"""
    post = make_post(content="昨天清仓中际旭创，梭哈了长鑫。")
    result = stock_tag_posts([post], ["中际旭创", "长鑫"])
    assert result[0] == ["中际旭创", "长鑫"]


def test_stock_tags_dedup_and_limit():
    """$标记$ 与股票名表命中同名去重；最多 2 个。"""
    post = make_post(content="$长鑫(SH688825)$ 长鑫大涨，$中船特气(SH688146)$ 也涨，$神火股份(SZ000933)$ 跟进。")
    result = stock_tag_posts([post], ["长鑫"])
    # 长鑫去重后剩 2 个（长鑫、中船特气），第 3 个（神火）被截断
    assert result[0] == ["长鑫", "中船特气"]


def test_stock_no_match_empty():
    post = make_post(content="今天天气不错。")
    result = stock_tag_posts([post], ["长鑫", "宁德时代"])
    assert result[0] == []


def test_stock_multiple_posts():
    posts = [
        make_post(content="$宁德时代(SZ300750)$ 反弹", external_id="a"),
        make_post(content="无聊内容", external_id="b"),
    ]
    result = stock_tag_posts(posts, ["长鑫"])
    assert result[0] == ["宁德时代"]
    assert result[1] == []


def test_alias_hit_uses_official_name():
    """别名命中时打正式名标签。"""
    post = make_post(content="宁王今天又创新高了，市场沸腾。")
    result = stock_tag_posts([post], ["宁德时代"], aliases=[{"alias": "宁王", "stock": "宁德时代"}])
    assert result[0] == ["宁德时代"]


def test_alias_merged_with_stock_names():
    """别名与股票名表、$标记$ 结果去重合并，最多 2 个。"""
    post = make_post(content="$宁德时代(SZ300750)$ 反弹，宁王终于不跌了，长鑫也涨。")
    result = stock_tag_posts([post], ["长鑫"], aliases=[{"alias": "宁王", "stock": "宁德时代"}])
    # $标记$ 宁德时代 与别名宁王→宁德时代 去重；长鑫补上
    assert result[0] == ["宁德时代", "长鑫"]


def test_extract_alias_candidates():
    """候选词提取：高频词、过滤已知名/短词/纯数字/$标记$内正式名。"""
    posts = [
        make_post(content="宁王 宁王 宁王 说宁德好，$宁德时代(SZ300750)$ 值得关注", external_id="a"),
        make_post(content="宁王 又涨了，今天 123 涨 2 个点", external_id="b"),
        make_post(content="随手一写的一句话", external_id="c"),
    ]
    # known 含「宁德时代」（$标记$ 与名表都出现）
    candidates = extract_alias_candidates(posts, known=["宁德时代"])
    assert "宁王" in candidates          # 高频黑话候选
    assert "宁德时代" not in candidates  # 已知名过滤
    assert "涨" not in candidates        # 单字过滤（<2 字）
    assert "123" not in candidates       # 纯数字过滤


def test_cleanup_stale_tags_removes_old():
    """清理过期标签：删除不在有效集合里的（观点/策略），保留有效标签。"""
    import tempfile
    from pathlib import Path

    from app.db import DB

    db = DB(Path(tempfile.mkdtemp()) / "t.db")
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "c1", "t", "c", "u", "")
    db.update_post_tags(pid, ["观点", "宏观", "科技"])
    removed = cleanup_stale_tags(db, valid_tags=["宏观", "科技", "宁德时代"])
    assert removed == 1
    assert db.list_posts(limit=5)[0]["tags"] == ["宏观", "科技"]
    db.close()


def test_cleanup_stale_tags_keeps_valid():
    """全部有效时不清（removed=0）。"""
    import tempfile
    from pathlib import Path

    from app.db import DB

    db = DB(Path(tempfile.mkdtemp()) / "t.db")
    kid = db.add_kol("xueqiu", "A", "1")
    pid = db.insert_post("xueqiu", kid, "c2", "t", "c", "u", "")
    db.update_post_tags(pid, ["宏观", "宁德时代"])
    removed = cleanup_stale_tags(db, valid_tags=["宏观", "科技", "宁德时代"])
    assert removed == 0
    db.close()
