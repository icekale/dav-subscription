import json
import os

import httpx
import pytest

from app.fetchers.ima import (
    ImaFetcher,
    configured_ima_cookie,
    configured_openapi_creds,
    _decode_text,
)

OPENAPI_LIST_OK = {
    "retcode": 0,
    "data": {
        "knowledge_list": [
            {
                "media_id": "txt_abc",
                "title": "新文档.txt",
                "abstract": "AI摘要: 摘要内容",
                "introduction": "开头片段",
                "create_time": 1787152223403,
                "media_type": 13,
                "file_size": "100",
                "cover_urls": ["https://ima-share-kb.image.myqcloud.com/5/x/c.jpg?sign=1"],
            }
        ],
        "is_end": True,
        "next_cursor": "",
        "current_path": [{"folder_id": "7304333330762611", "name": "库"}],
    },
}

WEB_LIST_OK = {
    "code": 0,
    "msg": "ok",
    "knowledge_list": [
        dict(OPENAPI_LIST_OK["data"]["knowledge_list"][0]),
    ],
    "is_end": True,
    "next_cursor": "",
    "current_path": [{"folder_id": "7304333330762611", "name": "库"}],
}

MEDIA_INFO_WITH_URL = {
    "retcode": 0,
    "data": {"media_type": 13, "url_info": {"url": "https://cdn.example/raw.txt"}},
}

MEDIA_INFO_GATED = {"retcode": 220030, "errmsg": "无权限获取原文"}


class _Handler:
    """按 (url, method) 路由的 mock client 处理器。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, request):
        self.calls.append((str(request.url), request.method, request.content))
        url = str(request.url)
        for key, response in self.routes.items():
            if key in url:
                return response
        return httpx.Response(404, json={"msg": "not found"})


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setenv("IMA_FETCH_DELAY", "0")
    monkeypatch.setenv("IMA_PROBE_DELAY", "0")


def _make(db=None, routes=None, **kw):
    handler = _Handler(routes or {})
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    return ImaFetcher(db=db, client=client, **kw), handler


def test_credential_resolution_env():
    os.environ["IMA_COOKIE"] = "cookie-abc"
    os.environ["IMA_OPENAPI_CLIENTID"] = "cid"
    os.environ["IMA_OPENAPI_APIKEY"] = "key"
    try:
        assert configured_ima_cookie() == "cookie-abc"
        assert configured_openapi_creds() == ("cid", "key")
        # 后台设置优先
        class FakeDB:
            def get_setting(self, key):
                return {"ima_cookie": "db-cookie"}.get(key, "")

        assert configured_ima_cookie(FakeDB()) == "db-cookie"
        class FakeDB2:
            def get_setting(self, key):
                return {"ima_openapi_clientid": "db-cid", "ima_openapi_apikey": "db-key"}.get(key, "")

        assert configured_openapi_creds(FakeDB2()) == ("db-cid", "db-key")
    finally:
        for k in ("IMA_COOKIE", "IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY"):
            os.environ.pop(k, None)


def test_fetch_web_mode_maps_fields_and_skips_folders():
    os.environ["IMA_COOKIE"] = "cookie-abc"
    try:
        routes = {
            "get_knowledge_list": httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "knowledge_list": [
                        WEB_LIST_OK["knowledge_list"][0],
                        {"media_id": "folder_1", "title": "文件夹", "media_type": 99, "create_time": 1},
                    ],
                    "is_end": True,
                    "next_cursor": "",
                },
            )
        }
        fetcher, handler = _make(db=None, routes=routes)
        posts = fetcher.fetch({"id": 7, "name": "Z哥策略", "external_id": "7304333330762611"})
        assert len(posts) == 1
        post = posts[0]
        assert post.title == "新文档.txt"
        assert post.content == "AI摘要: 摘要内容"
        assert post.published_at == "2026-08-19 23:10"
        assert post.images == ["https://ima-share-kb.image.myqcloud.com/5/x/c.jpg?sign=1"]
        assert post.post_type == "txt"
        assert post.url == "https://ima.qq.com/wikis?knowledgeBaseId=7304333330762611"
        # cookie 模式不请求 OpenAPI（无 clientid/apikey）
        assert all("get_media_info" not in str(u) for u, _, _ in handler.calls)
    finally:
        os.environ.pop("IMA_COOKIE", None)


def test_fetch_openapi_mode_full_text_replaces_abstract():
    os.environ["IMA_OPENAPI_CLIENTID"] = "cid"
    os.environ["IMA_OPENAPI_APIKEY"] = "key"
    try:
        routes = {
            "get_knowledge_list": httpx.Response(200, json=OPENAPI_LIST_OK),
            "get_media_info": httpx.Response(200, json=MEDIA_INFO_WITH_URL),
            "cdn.example": httpx.Response(200, content="这是完整正文。".encode("utf-8")),
        }
        db = type("DB", (), {"post_exists": lambda self, p, e: False, "get_setting": lambda self, k: ""})()
        fetcher, handler = _make(db=db, routes=routes)
        posts = fetcher.fetch({"id": 7, "name": "Z哥策略", "external_id": "kb_openapi_1"})
        assert len(posts) == 1
        assert posts[0].content == "这是完整正文。"
        assert posts[0].detail.get("full_text") is True
        assert posts[0].detail.get("media_id") == "txt_abc"
        # 已经入库的帖子不再重复抓全文
        db = type("DB", (), {"post_exists": lambda self, p, e: True, "get_setting": lambda self, k: ""})()
        fetcher2, handler2 = _make(db=db, routes=routes)
        posts2 = fetcher2.fetch({"id": 7, "name": "Z哥策略", "external_id": "kb_openapi_1"})
        assert posts2[0].content == "AI摘要: 摘要内容"
        assert all("get_media_info" not in str(u) for u, _, _ in handler2.calls)
    finally:
        os.environ.pop("IMA_OPENAPI_CLIENTID", None)
        os.environ.pop("IMA_OPENAPI_APIKEY", None)


def test_fetch_openapi_mode_gated_falls_back_to_abstract():
    os.environ["IMA_OPENAPI_CLIENTID"] = "cid"
    os.environ["IMA_OPENAPI_APIKEY"] = "key"
    try:
        routes = {
            "get_knowledge_list": httpx.Response(200, json=OPENAPI_LIST_OK),
            "get_media_info": httpx.Response(200, json=MEDIA_INFO_GATED),
        }
        db = type("DB", (), {"post_exists": lambda self, p, e: False, "get_setting": lambda self, k: ""})()
        fetcher, handler = _make(db=db, routes=routes)
        posts = fetcher.fetch({"id": 7, "name": "Z哥策略", "external_id": "kb_openapi_1"})
        assert len(posts) == 1
        assert posts[0].content == "AI摘要: 摘要内容"  # 订阅库降级：摘要在手
        assert posts[0].detail.get("full_text") is not True
    finally:
        os.environ.pop("IMA_OPENAPI_CLIENTID", None)
        os.environ.pop("IMA_OPENAPI_APIKEY", None)


def test_fetch_binary_content_falls_back():
    assert _decode_text(b"") == ""
    assert _decode_text(b"\x00\x01\x02pdf") == ""  # 二进制
    assert _decode_text("中文正文".encode("utf-8")) == "中文正文"


def test_fetch_without_credentials_raises():
    for k in ("IMA_COOKIE", "IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY"):
        os.environ.pop(k, None)
    fetcher, _ = _make(db=None, routes={})
    with pytest.raises(RuntimeError, match="未配置 ima 凭证"):
        fetcher.fetch({"id": 1, "name": "x", "external_id": "1"})