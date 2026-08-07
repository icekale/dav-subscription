"""可选 LLM 摘要：未配置/失败降级为 None，成功返回文本。"""
import json
from types import SimpleNamespace

import httpx

from app.fetchers.base import Post
from app.llm import summarize_posts


def make_post(content="正文内容") -> Post:
    return Post(
        platform="xueqiu",
        kol_id=1,
        kol_name="张三",
        external_id="p1",
        title="标题",
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
    post = make_post(content="")
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
