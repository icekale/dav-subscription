"""可选 LLM 摘要：未配置/失败降级为 None，成功返回文本。"""
import json
from types import SimpleNamespace

import httpx

from app.fetchers.base import Post
from app.llm import summarize_posts


def make_post(content="正文内容", external_id="p1", title="标题", url="https://xueqiu.com/1/2") -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id=external_id,
        title=title,
        content=content,
        url=url,
        published_at="",
    )


def make_config(api_key="sk-test", api_base="https://api.openai.com/v1", model="gpt-4o-mini"):
    return SimpleNamespace(api_key=api_key, api_base=api_base, model=model)


def test_no_config_returns_none():
    assert summarize_posts([make_post()], None) is None
    assert summarize_posts([make_post()], SimpleNamespace(api_key="")) is None


def test_success_returns_text():
    def handler(request):
        payload = request.read() and json.loads(request.read())
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "- 要点一\n- 要点二"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = summarize_posts([make_post()], make_config(), client=client)
    assert result == "- 要点一\n- 要点二"


def test_empty_choices_returns_none():
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) is None


def test_http_error_returns_none():
    def handler(request):
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) is None


def test_empty_content_returns_none():
    # 空正文/标题时直接返回 None，不发请求
    def handler(request):
        raise AssertionError("不应发起请求")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    post = make_post(content="", title="")
    assert summarize_posts([post], make_config(), client=client) is None


def test_custom_base_url_and_long_content_truncation():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        payload = json.loads(request.read())
        captured["content_len"] = len(payload["messages"][1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = make_config(api_base="https://llm.example.com/v1")
    summarize_posts([make_post(content="长" * 50000)], config, client=client)
    assert "llm.example.com/v1/chat/completions" in captured["url"]
    # 内容截断到 12000 字符以内
    assert captured["content_len"] <= 12000


def test_rejects_unsafe_api_base_before_request():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("不应访问内网 LLM"))
        )
    )
    unsafe = make_config(api_base="http://127.0.0.1:8000/v1")
    unsafe.user_supplied = True
    assert summarize_posts([make_post()], unsafe, client=client) is None
    metadata = make_config(api_base="http://169.254.169.254/latest")
    metadata.user_supplied = True
    assert summarize_posts([make_post()], metadata, client=client) is None


def test_cache_reuses_result_within_batch():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "要点"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = {}
    posts = [make_post()]
    assert summarize_posts(posts, make_config(), client=client, cache=cache) == "要点"
    assert summarize_posts(posts, make_config(), client=client, cache=cache) == "要点"
    assert calls["n"] == 1


def test_cache_does_not_store_failure():
    def handler(request):
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = {}
    assert summarize_posts([make_post()], make_config(), client=client, cache=cache) is None
    assert cache == {}


def test_summary_input_originals_first_with_markers():
    captured = {}

    def handler(request):
        captured["content"] = json.loads(request.read())["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reply = make_post(content="回复内容", external_id="r1")
    reply.post_type = "reply"
    original = make_post(content="原创内容", external_id="o1")
    summarize_posts([reply, original], make_config(), client=client)
    body = captured["content"]
    assert body.index("[原帖]") < body.index("[回复]")
    assert "原创内容" in body


def test_many_posts_per_line_budget_capped():
    captured = {}

    def handler(request):
        captured["content"] = json.loads(request.read())["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posts = [make_post(content="长" * 500, external_id=f"p{i}") for i in range(10)]
    summarize_posts(posts, make_config(), client=client)
    assert len(captured["content"]) <= 12000
    for line in captured["content"].splitlines():
        assert len(line) <= 400 + 64  # 每行正文 ≤ 400 + 标记/来源前缀


def test_retry_transient_then_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": "要点"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) == "要点"
    assert calls["n"] == 2


def test_no_retry_on_auth_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) is None
    assert calls["n"] == 1


def test_max_tokens_scales_with_post_count():
    captured = {}

    def handler(request):
        captured["max_tokens"] = json.loads(request.read())["max_tokens"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # 10 帖被 2000 托底（推理模型需思考预算）；30 帖随帖数增长
    summarize_posts([make_post(external_id=f"p{i}") for i in range(10)], make_config(), client=client)
    assert captured["max_tokens"] == 2000
    summarize_posts([make_post(external_id=f"p{i}") for i in range(30)], make_config(), client=client)
    assert captured["max_tokens"] == 3800  # 200 + 120*30


# ---- 每日精选综述 ----

from app.llm import DailyPoint, DailySummary, render_daily_summary, summarize_daily


def _daily_handler(content):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


def test_summarize_daily_success_parses():
    client = httpx.Client(transport=httpx.MockTransport(_daily_handler(
        "今日共 2 条动态，围绕 AI 与宏观。\n"
        "- 美联储释放降息信号，科技股受益（[1]）\n"
        "- 市场整体波动不大（[2]）"
    )))
    posts = [make_post(external_id=f"p{i}") for i in range(2)]
    summary = summarize_daily(posts, make_config(), client=client)
    assert summary is not None
    assert "AI" in summary.overview
    assert len(summary.points) == 2
    assert summary.points[0].text.startswith("美联储")
    assert summary.points[0].post_indexes == [0]
    assert summary.points[1].post_indexes == [1]


def test_summarize_daily_prompt_includes_rules():
    captured = {}

    def handler(request):
        payload = json.loads(request.read())
        captured["system"] = payload["messages"][0]["content"]
        captured["user"] = payload["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "- 要点（[1]）"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarize_daily([make_post()], make_config(), client=client)
    # system 指令要求综合成最多 8 条、每条限定字数、要点点名大V并标注依据序号
    assert "最多 8 条" in captured["system"]
    assert "100~150 字" in captured["system"]
    assert "大V" in captured["system"]
    assert "（[N]）" in captured["system"]
    # 输入行带序号，模型可引用
    assert "1. [原帖][xueqiu] 张三：" in captured["user"]


def test_summarize_daily_no_points_returns_none():
    client = httpx.Client(transport=httpx.MockTransport(_daily_handler("今日无事。")))
    assert summarize_daily([make_post()], make_config(), client=client) is None


def test_summarize_daily_http_error_returns_none():
    def handler(request):
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_daily([make_post()], make_config(), client=client) is None


def test_summarize_daily_no_config_returns_none():
    assert summarize_daily([make_post()], None) is None
    assert summarize_daily([make_post()], SimpleNamespace(api_key="")) is None


def test_render_daily_summary_plain_text_no_links():
    """综述渲染为纯文本：标题 + 总览 + 编号要点，不带任何原文链接。"""
    summary = DailySummary(
        overview="今日共 2 条动态。",
        points=[
            DailyPoint(text="要点甲", post_indexes=[0]),
            DailyPoint(text="要点乙", post_indexes=[0, 1]),
            DailyPoint(text="无来源要点", post_indexes=[]),
        ],
    )
    text = render_daily_summary(summary)
    assert "今日大V精选" in text
    assert "今日共 2 条动态。" in text
    assert "1. 要点甲" in text
    assert "2. 要点乙" in text
    assert "3. 无来源要点" in text
    # 不出现任何链接/原文标记
    assert "http" not in text and "原文" not in text


def test_render_daily_summary_empty_points():
    summary = DailySummary(overview="")
    text = render_daily_summary(summary)
    assert "今日大V精选" in text


def test_summarize_daily_parses_trailing_punctuation_and_multiple_indexes():
    """LLM 常在（[N]）后带句号、多个序号连写——都应正确解析出链接依据。"""
    client = httpx.Client(transport=httpx.MockTransport(_daily_handler(
        "今日共 3 条动态。\n"
        "- 要点一（[1]）。\n"
        "- 要点二（[2][3]）\n"
        "- 要点三"
    )))
    posts = [make_post(external_id=f"p{i}") for i in range(3)]
    summary = summarize_daily(posts, make_config(), client=client)
    assert summary is not None
    assert summary.points[0].post_indexes == [0]
    assert summary.points[1].post_indexes == [1, 2]
    assert summary.points[2].post_indexes == []


def test_summarize_daily_accepts_other_list_prefixes():
    """LLM 偶发用 • / 1. 等列表前缀，不应导致整体降级。"""
    client = httpx.Client(transport=httpx.MockTransport(_daily_handler(
        "今日共 2 条动态。\n"
        "1. 数字列表要点（[1]）\n"
        "• 圆点要点（[2]）"
    )))
    posts = [make_post(external_id=f"p{i}") for i in range(2)]
    summary = summarize_daily(posts, make_config(), client=client)
    assert summary is not None
    assert len(summary.points) == 2
    assert summary.points[0].post_indexes == [0]
    assert summary.points[1].post_indexes == [1]


def test_summarize_daily_max_tokens():
    captured = {}

    def handler(request):
        captured["max_tokens"] = json.loads(request.read())["max_tokens"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "- 要点（[1]）"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarize_daily([make_post(external_id=f"p{i}") for i in range(30)], make_config(), client=client)
    # 固定给足上限，兼容推理模型思考预算（普通模型不会用满）
    assert captured["max_tokens"] == 16000


def test_summarize_daily_enforces_max_eight_points():
    """模型输出 10 条要点时，解析层只保留前八条（顺序与引用序号不变）。"""
    client = httpx.Client(transport=httpx.MockTransport(_daily_handler(
        "今日共 10 条动态。\n"
        + "\n".join(f"- 要点{i}（[{i}]）" for i in range(1, 11))
    )))
    posts = [make_post(external_id=f"p{i}") for i in range(10)]
    summary = summarize_daily(posts, make_config(), client=client)
    assert summary is not None
    assert len(summary.points) == 8
    assert [p.text for p in summary.points] == [f"要点{i}" for i in range(1, 9)]
    assert [p.post_indexes for p in summary.points] == [[i - 1] for i in range(1, 9)]


def test_render_daily_summary_with_posts_appends_links():
    """传入 posts 后，要点末尾附依据帖子的原文链接。"""
    summary = DailySummary(
        overview="今日共 2 条动态。",
        points=[
            DailyPoint(text="要点甲", post_indexes=[1]),
            DailyPoint(text="无来源要点", post_indexes=[]),
        ],
    )
    posts = [make_post(external_id="p0"), make_post(external_id="p1", url="https://example.com/1")]
    text = render_daily_summary(summary, posts)
    assert "🔗 https://example.com/1" in text
    assert "无来源要点" in text and "http" not in text.split("无来源要点")[1]


def test_render_daily_summary_skips_link_when_posts_have_no_url():
    summary = DailySummary(overview="", points=[DailyPoint(text="要点", post_indexes=[0])])
    text = render_daily_summary(summary, [make_post(external_id="p0", url="")])
    assert "http" not in text


# ---- 股票黑话别名识别 ----

from app.llm import suggest_stock_aliases


def _alias_handler(content):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


def test_suggest_aliases_parses_and_filters_confidence():
    client = httpx.Client(transport=httpx.MockTransport(_alias_handler(
        '[{"alias": "宁王", "stock": "宁德时代", "confidence": "high"},'
        '{"alias": "药茅", "stock": "恒瑞医药", "confidence": "medium"},'
        '{"alias": "废话", "stock": "宁德时代", "confidence": "none"},'
        '{"alias": "乱写", "stock": "不存在的股票", "confidence": "high"}]'
    )))
    result = suggest_stock_aliases(["宁王", "药茅", "废话", "乱写"], ["宁德时代", "恒瑞医药"], make_config(), client=client)
    # high/medium 保留；none 丢弃；stock 不在已知列表的丢弃
    assert {r["alias"] for r in result} == {"宁王", "药茅"}
    assert all(r["stock"] in ("宁德时代", "恒瑞医药") for r in result)


def test_suggest_aliases_empty_and_failure():
    # 无候选词 / 未配置 → []
    assert suggest_stock_aliases([], ["宁德时代"], make_config()) == []
    assert suggest_stock_aliases(["宁王"], ["宁德时代"], None) == []
    # 非 JSON 响应 → []
    client = httpx.Client(transport=httpx.MockTransport(_alias_handler("抱歉，我不知道")))
    assert suggest_stock_aliases(["宁王"], ["宁德时代"], make_config(), client=client) == []
    # 5xx → []
    def err(request):
        return httpx.Response(500, json={})
    client2 = httpx.Client(transport=httpx.MockTransport(err))
    assert suggest_stock_aliases(["宁王"], ["宁德时代"], make_config(), client=client2) == []


# ---- 股票标记解析（$标记$ → 官方名/戏称） ----

from app.llm import resolve_stock_marks


def _mark_handler(content):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


def test_resolve_stock_marks_official_and_alias():
    client = httpx.Client(transport=httpx.MockTransport(_mark_handler(
        '[{"name": "盐湖股份", "code": "SZ000792", "official": "盐湖股份", "is_alias": false},'
        '{"name": "涂改液", "code": "SZ000858", "official": "五粮液", "is_alias": true},'
        '{"name": "洋河大蛆", "code": "SZ002304", "official": "洋河股份", "is_alias": true}]'
    )))
    marks = [("盐湖股份", "SZ000792"), ("涂改液", "SZ000858"), ("洋河大蛆", "SZ002304")]
    result = resolve_stock_marks(marks, make_config(), client=client)
    assert len(result) == 3
    official = [r for r in result if not r["is_alias"]]
    alias = [r for r in result if r["is_alias"]]
    assert official[0]["official"] == "盐湖股份"
    assert {a["name"] for a in alias} == {"涂改液", "洋河大蛆"}
    assert alias[0]["official"] == "五粮液"


def test_resolve_stock_marks_failure_and_invalid():
    # 非 SH/SZ/BJ 代码丢弃
    client = httpx.Client(transport=httpx.MockTransport(_mark_handler(
        '[{"name": "组合", "code": "ZH123", "official": "组合", "is_alias": false}]'
    )))
    assert resolve_stock_marks([("组合", "ZH123")], make_config(), client=client) == []
    # 非 JSON → []
    client2 = httpx.Client(transport=httpx.MockTransport(_mark_handler("无法解析")))
    assert resolve_stock_marks([("涂改液", "SZ000858")], make_config(), client=client2) == []
    # 未配置 / 空输入 → []
    assert resolve_stock_marks([], make_config()) == []
    assert resolve_stock_marks([("涂改液", "SZ000858")], None) == []
