"""可选 LLM 摘要与打标：未配置/失败降级，成功返回文本/标签映射。"""
import json
from types import SimpleNamespace

import httpx

from app.fetchers.base import Post
from app.llm import TAG_CHUNK_SIZE, summarize_posts, tag_posts


def make_post(content="正文内容", external_id="p1", title="标题") -> Post:
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


# ---- 贴文打标 ----

VOCAB = ["宏观", "大盘", "科技", "政策", "生活"]


def tag_posts_config(api_key="sk-test", api_base="https://api.openai.com/v1", model="gpt-4o-mini"):
    return SimpleNamespace(api_key=api_key, api_base=api_base, model=model)


def _tag_handler(content):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


def test_tag_posts_no_config_returns_empty():
    assert tag_posts([make_post()], VOCAB, None) == {}
    assert tag_posts([make_post()], VOCAB, SimpleNamespace(api_key="")) == {}
    assert tag_posts([make_post()], [], tag_posts_config()) == {}


def test_tag_posts_success_mapping():
    def handler(request):
        payload = json.loads(request.read())
        assert payload["model"] == "gpt-4o-mini"
        assert payload["temperature"] == 0
        # 提示词包含完整词表
        assert "宏观" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"1": ["宏观", "政策"], "2": [], "3": ["科技"]}'}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posts = [make_post(external_id=f"p{i}") for i in range(3)]
    result = tag_posts(posts, VOCAB, tag_posts_config(), client=client)
    assert result[0] == ["宏观", "政策"]
    assert result[1] == []
    assert result[2] == ["科技"]


def test_tag_posts_discards_unknown_and_dedupes():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"1": ["宏观", "不存在的标签", "宏观", "政策", "生活"]}'}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = tag_posts([make_post()], VOCAB, tag_posts_config(), client=client)
    # 未知标签被丢弃、重复去重、最多 3 个
    assert result[0] == ["宏观", "政策", "生活"]


def test_tag_posts_tolerates_markdown_fence():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '```json\n{"1": ["大盘"]}\n```'}}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = tag_posts([make_post()], VOCAB, tag_posts_config(), client=client)
    assert result[0] == ["大盘"]


def test_tag_posts_unparsable_returns_empty():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "抱歉，我无法处理"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert tag_posts([make_post()], VOCAB, tag_posts_config(), client=client) == {}


def test_tag_posts_empty_choices_returns_empty():
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert tag_posts([make_post()], VOCAB, tag_posts_config(), client=client) == {}


def test_tag_posts_http_error_returns_empty():
    def handler(request):
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert tag_posts([make_post()], VOCAB, tag_posts_config(), client=client) == {}


def test_tag_posts_retry_transient_then_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"1": ["科技"]}'}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = tag_posts([make_post()], VOCAB, tag_posts_config(), client=client)
    assert result[0] == ["科技"]
    assert calls["n"] == 2


def test_tag_posts_no_retry_on_auth_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert tag_posts([make_post()], VOCAB, tag_posts_config(), client=client) == {}
    assert calls["n"] == 1


def test_tag_posts_chunks_over_limit():
    captured = []

    def handler(request):
        payload = json.loads(request.read())
        # 帖子行以「序号. 」开头，候选标签/提示行不是；按帖子行数推断本块帖子数
        lines = payload["messages"][1]["content"].splitlines()
        captured.append(len([l for l in lines if l[0].isdigit()]))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"1": ["科技"]}'}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posts = [make_post(external_id=f"p{i}") for i in range(TAG_CHUNK_SIZE + 5)]
    result = tag_posts(posts, VOCAB, tag_posts_config(), client=client)
    assert len(captured) == 2
    assert captured[0] == TAG_CHUNK_SIZE
    assert captured[1] == 5
    # 两块请求各自映射回原下标
    assert result[0] == ["科技"]
    assert result[TAG_CHUNK_SIZE] == ["科技"]


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
    # system 指令要求按重要性排序、标注帖子序号
    assert "重要性" in captured["system"] and "序号" in captured["system"]
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


def test_render_daily_summary_links():
    posts = [make_post(external_id="p1"), make_post(external_id="p2")]
    posts[0].url = "https://xueqiu.com/1"
    posts[1].url = "https://xueqiu.com/2"
    summary = DailySummary(
        overview="今日共 2 条动态。",
        points=[
            DailyPoint(text="要点甲", post_indexes=[0]),
            DailyPoint(text="要点乙", post_indexes=[0, 1]),
            DailyPoint(text="无来源要点", post_indexes=[]),
        ],
    )
    text = render_daily_summary(summary, posts)
    assert "今日大V精选" in text
    assert "今日共 2 条动态。" in text
    # 单来源直接列 URL
    assert "1. 要点甲（https://xueqiu.com/1）" in text
    # 多来源用编号链接串
    assert "2. 要点乙（[原文1](https://xueqiu.com/1) · [原文2](https://xueqiu.com/2)）" in text
    # 无来源不带链接
    assert "3. 无来源要点" in text and "原文" not in text.split("3. ")[1]


def test_render_daily_summary_ignores_bad_indexes():
    posts = [make_post(external_id="p1")]
    posts[0].url = "https://xueqiu.com/1"
    summary = DailySummary(
        overview="",
        points=[
            DailyPoint(text="越界", post_indexes=[99]),
            DailyPoint(text="正常", post_indexes=[0]),
        ],
    )
    text = render_daily_summary(summary, posts)
    assert "1. 越界" in text and "原文" not in text.split("1. ")[1]
    assert "2. 正常（https://xueqiu.com/1）" in text


def test_summarize_daily_max_tokens():
    captured = {}

    def handler(request):
        captured["max_tokens"] = json.loads(request.read())["max_tokens"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "- 要点（[1]）"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarize_daily([make_post(external_id=f"p{i}") for i in range(30)], make_config(), client=client)
    assert captured["max_tokens"] == 3800  # 200 + 120*30
