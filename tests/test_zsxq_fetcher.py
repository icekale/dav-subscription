import os

import httpx
import pytest

from app.fetchers.zsxq import ZsxqFetcher, ZsxqError, configured_token, _strip_embedded_tags


def _ok(topics, **extra):
    body = {"succeeded": True, "resp_data": {"topics": topics, **extra}}
    return httpx.Response(200, json=body)


def _topic(tid, text="正文", images=None, files=None, article=None, group=None, owner=None, create_time="2026-08-20T10:00:00.000+0800"):
    talk = {"text": text}
    if article:
        talk["article"] = article
    if images:
        talk["images"] = images
    if files:
        talk["files"] = files
    if owner:
        talk["owner"] = owner
    topic = {
        "topic_id": tid,
        "type": "talk",
        "create_time": create_time,
        "talk": talk,
    }
    if group:
        topic["group"] = group
    return topic


class _Handler:
    def __init__(self, routes, groups=None):
        self.routes = routes
        self.groups = groups or []
        self.calls = []

    def __call__(self, request):
        self.calls.append(str(request.url))
        url = str(request.url)
        for key in sorted(self.routes, key=len, reverse=True):  # 最长/最具体优先
            if key in url:
                val = self.routes[key]
                return val(request) if callable(val) else val
        return httpx.Response(404, json={"succeeded": False, "code": 404, "info": "nf"})


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setenv("ZSXQ_ACCESS_TOKEN", "tok-abc")
    monkeypatch.setenv("ZSXQ_FETCH_DELAY_SECONDS", "0")
    monkeypatch.setenv("ZSXQ_FILE_DELAY_SECONDS", "0")
    monkeypatch.setenv("ZSXQ_MAX_PAGES", "2")


def _make(routes):
    handler = _Handler(routes)
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    return ZsxqFetcher(db=None, client=client), handler


def test_configured_token_handles_bare_or_cookie_header():
    assert configured_token(override="ABC") == "ABC"
    assert configured_token(override="zsxq_access_token=XYZ") == "XYZ"


def test_strip_embedded_tags_unquotes_title():
    assert _strip_embedded_tags(
        'hi <e type="web" href="x" title="https%3A%2F%2Fa.com%2Fb" /> there'
    ) == "hi https://a.com/b there"


def test_fetch_maps_topic_to_post_with_clean_text():
    fetcher, handler = _make(
        {
            "topics": _ok([_topic(1, "第一条正文"), _topic(2, "第二条")]),
        }
    )
    posts = fetcher.fetch({"id": 9, "name": "前沿信息", "external_id": "28888112822211"})
    assert len(posts) == 2
    p = posts[0]
    assert p.platform == "zsxq"
    assert p.external_id == "1"
    assert p.kol_name == "前沿信息"
    assert p.content == "第一条正文"
    assert p.url == "https://wx.zsxq.com/group/28888112822211/1"


def test_fetch_collects_images():
    img = {
        "image_id": 11,
        "original": {"url": "https://img/orig.jpg", "size": 100},
        "large": {"url": "https://img/large.jpg"},
    }
    fetcher, _ = _make({"topics": _ok([_topic(1, images=[img])])})
    posts = fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    assert posts[0].images == ["https://img/orig.jpg"]


def test_fetch_resolves_attachment_urls_and_caches():
    def download(request):
        return httpx.Response(
            200,
            json={"succeeded": True, "resp_data": {"download_url": "https://cdn/x.pdf"}},
        )

    topic = _topic(1, files=[{"file_id": 22, "name": "a.pdf", "size": 100}])
    fetcher, handler = _make(
        {
            "topics": _ok([topic]),
            "files/22/download_url": download,
        }
    )
    posts = fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    files = (posts[0].detail or {}).get("files")
    assert files == [{"file_id": "22", "name": "a.pdf", "size": 100, "url": "https://cdn/x.pdf"}]
    # 再次 fetch 走缓存，不再请求 download_url
    n_before = len([c for c in handler.calls if "/files/" in c])
    fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    n_after = len([c for c in handler.calls if "/files/" in c])
    assert n_after == n_before


def test_fetch_detail_backfill_for_article():
    list_topic = {
        "topic_id": 7,
        "type": "talk",
        "create_time": "2026-08-20T10:00:00.000+0800",
        "talk": {
            "text": "",  # 列表里正文为空
            "article": {"article_id": 70, "title": "长文标题"},
        },
    }
    detail = {
        "succeeded": True,
        "resp_data": {
            "topic": {
                "topic_id": 7,
                "type": "talk",
                "create_time": "2026-08-20T10:00:00.000+0800",
                "talk": {"text": "长文完整正文"},  # 详情里有全文
            }
        },
    }
    fetcher, _ = _make({"topics": _ok([list_topic]), "topics/7": httpx.Response(200, json=detail)})
    posts = fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    assert posts[0].content == "长文完整正文"


def test_1059_raises_ZsxqError_with_code():
    err = httpx.Response(200, json={"succeeded": False, "code": 1059, "info": "签名失败"})
    fetcher, _ = _make({"topics": err})
    with pytest.raises(ZsxqError) as ei:
        fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    assert ei.value.code == 1059


def test_fetch_missing_token_raises():
    fetcher, _ = _make({})
    os.environ.pop("ZSXQ_ACCESS_TOKEN", None)
    try:
        with pytest.raises(RuntimeError):
            fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    finally:
        os.environ["ZSXQ_ACCESS_TOKEN"] = "tok-abc"


def test_fetch_keeps_files_when_download_url_fails():
    topic = _topic(1, text="#note#", files=[{"file_id": 22, "name": "a.pdf", "size": 10}])
    fetcher, _ = _make(
        {
            "topics": _ok([topic]),
            "files/22/download_url": httpx.Response(
                200, json={"succeeded": False, "code": 20601, "info": "limit"}
            ),
        }
    )
    posts = fetcher.fetch({"id": 1, "name": "g", "external_id": "123"})
    files = (posts[0].detail or {}).get("files")
    assert files == [{"file_id": "22", "name": "a.pdf", "size": 10, "url": ""}]


def test_fetch_syncs_group_name_and_owner_avatar(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.kol = {"id": 4, "name": "zsxq_288", "avatar_url": "", "avatar_source": ""}

        def get_setting(self, key):
            return None

        def get_kol(self, kid):
            return dict(self.kol)

        def update_kol(self, kid, name=None, **_kw):
            if name:
                self.kol["name"] = name

        def update_kol_avatar(self, kid, url):
            self.kol["avatar_url"] = url

    db = FakeDB()
    monkeypatch.setattr("app.fetchers.zsxq.cache_avatar", lambda _db, _kid, url: url)
    topic = _topic(
        1,
        group={
            "group_id": 288,
            "name": "Frontier",
            "background_url": "https://img/cover.jpg",
            "owner": {"name": "August", "avatar_url": "https://img/august.jpg"},
        },
    )
    handler = _Handler({"topics": _ok([topic])})
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=db, client=client)
    fetcher.fetch({"id": 4, "name": "zsxq_288", "external_id": "288"})
    assert db.kol["name"] == "Frontier"
    assert db.kol["avatar_url"] == "https://img/august.jpg"


def test_resolve_zsxq_profile_reads_group_owner():
    from app.fetchers.zsxq import resolve_zsxq_profile

    body = {
        "succeeded": True,
        "resp_data": {
            "group": {
                "name": "Frontier",
                "background_url": "https://img/cover.jpg",
                "owner": {"name": "August", "avatar_url": "https://img/august.jpg"},
            }
        },
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
        timeout=10,
    )
    profile = resolve_zsxq_profile("288", token="tok", client=client)
    assert profile == {
        "name": "Frontier",
        "avatar_url": "https://img/august.jpg",
        "owner_name": "August",
    }


def test_resolve_zsxq_file_url():
    from app.fetchers.zsxq import resolve_zsxq_file_url
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"succeeded": True, "resp_data": {"download_url": "https://files.zsxq.com/a.pdf"}},
            )
        ),
        timeout=10,
    )
    assert resolve_zsxq_file_url("22", token="tok", client=client) == "https://files.zsxq.com/a.pdf"
    assert resolve_zsxq_file_url("nope", token="tok", client=client) == ""


def test_fetch_prefers_group_api_owner_avatar(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.kol = {"id": 4, "name": "zsxq_288", "avatar_url": ""}
            self.path = ":memory:"
        def get_setting(self, key):
            return None
        def get_kol(self, kid):
            return dict(self.kol)
        def update_kol(self, kid, name=None, **_kw):
            if name:
                self.kol["name"] = name
        def update_kol_avatar(self, kid, url):
            self.kol["avatar_url"] = url

    db = FakeDB()
    monkeypatch.setattr("app.fetchers.zsxq.cache_avatar", lambda _db, _kid, url: url)
    topic = _topic(1, group={"group_id": 288, "name": "CoverOnly", "background_url": "https://img/cover.jpg"})
    group_body = {
        "succeeded": True,
        "resp_data": {
            "group": {
                "name": "Frontier",
                "background_url": "https://img/cover.jpg",
                "owner": {"name": "August", "avatar_url": "https://img/august.jpg"},
            }
        },
    }

    def handler(request):
        path = request.url.path
        if path.endswith("/topics"):
            return _ok([topic])
        if path.endswith("/groups/288"):
            return httpx.Response(200, json=group_body)
        return httpx.Response(404, json={"succeeded": False})

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=db, client=client)
    fetcher.fetch({"id": 4, "name": "zsxq_288", "external_id": "288"})
    assert db.kol["name"] == "Frontier"
    assert db.kol["avatar_url"] == "https://img/august.jpg"


def test_get_retries_1059_random_filter(monkeypatch):
    """1059 是随机化反爬：_get 应重发同样请求直到随机放行，而不是直接抛错。"""
    calls = {"n": 0}

    class FakeResp:
        status_code = 200
        def json(self):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"succeeded": False, "code": 1059, "info": "blocked"}
            return {"succeeded": True, "resp_data": {"topics": [{"topic_id": "1"}]}}

    class FakeClient:
        def get(self, url, headers=None):
            return FakeResp()

    db = ":memory:"
    fetcher = ZsxqFetcher(db=None)
    monkeypatch.setattr(fetcher, "_pause", lambda *a, **k: None)
    fetcher.client = FakeClient()
    out = fetcher._get("tok", "/groups/1/topics")
    assert out == {"topics": [{"topic_id": "1"}]}
    assert calls["n"] == 3


def test_get_raises_after_retries_exhausted(monkeypatch):
    """1059 一直命中时，重试耗尽后抛 ZsxqError(code=1059)。"""
    class FakeResp:
        status_code = 200
        def json(self):
            return {"succeeded": False, "code": 1059, "info": "blocked"}

    class FakeClient:
        def get(self, url, headers=None):
            return FakeResp()

    fetcher = ZsxqFetcher(db=None)
    monkeypatch.setattr(fetcher, "_pause", lambda *a, **k: None)
    fetcher.client = FakeClient()
    with pytest.raises(ZsxqError) as ei:
        fetcher._get("tok", "/groups/1/topics")
    assert ei.value.code == 1059


def test_resolve_zsxq_file_url_raises_on_quota(monkeypatch):
    """13607 下载量异常/日限是真实额度错误：抛 ZsxqError(code=13607)，不静默返回空串。"""
    from app.fetchers.zsxq import resolve_zsxq_file_url

    class FakeResp:
        def json(self):
            return {"succeeded": False, "code": 13607, "info": "检测到你的下载量异常"}

    class FakeClient:
        def get(self, url, headers=None):
            return FakeResp()

    with pytest.raises(ZsxqError) as ei:
        resolve_zsxq_file_url("22", db=":memory:", token="tok", client=FakeClient())
    assert ei.value.code == 13607


def test_cache_zsxq_file_downloads_to_disk_and_reuses(tmp_path, monkeypatch):
    """附件落盘缓存：下载一次到 zsxq_files/{id}.pdf，重复调用直接命中不重复下载。"""
    from app.db import DB
    from app.fetchers.zsxq import cache_zsxq_file

    db = DB(tmp_path / "t.db")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if request.url.path.endswith("/a.pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 data")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    u1 = cache_zsxq_file(db, "22", "红书.pdf", "https://files.zsxq.com/a.pdf", client=client)
    assert u1 == "/zsxq-files/22.pdf"
    assert (tmp_path / "zsxq_files" / "22.pdf").read_bytes() == b"%PDF-1.7 data"
    # second call → cache hit, no download
    calls["n"] = 0
    u2 = cache_zsxq_file(db, "22", "红书.pdf", "https://files.zsxq.com/a.pdf", client=client)
    assert u2 == u1
    assert calls["n"] == 0


def test_cache_zsxq_file_skips_empty_url_and_memory(tmp_path):
    from app.fetchers.zsxq import cache_zsxq_file
    assert cache_zsxq_file(":memory:", "1", "a.pdf", "https://x/a.pdf") == ""
    assert cache_zsxq_file(tmp_path / "t2.db", "1", "a.pdf", "") == ""


def test_fetch_prefetches_files_when_enabled(tmp_path):
    """打开预缓存后附件落到磁盘，但 files[].url 仍是签名 URL，避免推送相对路径。"""
    from app.db import DB

    db = DB(tmp_path / "t.db")
    db.set_setting("zsxq_prefetch_files", "1")
    kid = db.add_kol("zsxq", "g", "123")
    topic = _topic(1, files=[{"file_id": 22, "name": "a.pdf", "size": 100}])
    handler = _Handler(
        {
            "topics": _ok([topic]),
            "files/22/download_url": httpx.Response(
                200, json={"succeeded": True, "resp_data": {"download_url": "https://cdn/x.pdf"}}
            ),
            "x.pdf": httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 data"
            ),
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": kid, "name": "g", "external_id": "123"})
    files = (posts[0].detail or {}).get("files")
    assert files == [{"file_id": "22", "name": "a.pdf", "size": 100, "url": "https://cdn/x.pdf"}]
    assert (tmp_path / "zsxq_files" / "22.pdf").read_bytes() == b"%PDF-1.7 data"


def test_prefetch_skips_download_url_when_file_cached(tmp_path):
    """预缓存开启且本地已有文件时，不再请求 download_url（不烧日限）。"""
    from app.db import DB

    db = DB(tmp_path / "t.db")
    db.set_setting("zsxq_prefetch_files", "1")
    kid = db.add_kol("zsxq", "g", "123")
    dest = tmp_path / "zsxq_files"
    dest.mkdir()
    (dest / "22.pdf").write_bytes(b"%PDF-1.7 data")
    topic = _topic(1, files=[{"file_id": 22, "name": "a.pdf", "size": 100}])
    handler = _Handler({"topics": _ok([topic])})
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": kid, "name": "g", "external_id": "123"})
    assert (posts[0].detail or {}).get("files")[0]["url"] == "/zsxq-files/22.pdf"
    assert not any("/files/" in c for c in handler.calls)


def test_fetch_prefers_disk_cache_without_prefetch(tmp_path):
    """未开预缓存但本地已有文件时，同样走本地 URL，不请求 download_url。"""
    from app.db import DB

    db = DB(tmp_path / "t.db")
    kid = db.add_kol("zsxq", "g", "123")
    dest = tmp_path / "zsxq_files"
    dest.mkdir()
    (dest / "22.pdf").write_bytes(b"%PDF-1.7 data")
    topic = _topic(1, files=[{"file_id": 22, "name": "a.pdf", "size": 100}])
    handler = _Handler({"topics": _ok([topic])})
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": kid, "name": "g", "external_id": "123"})
    assert (posts[0].detail or {}).get("files")[0]["url"] == "/zsxq-files/22.pdf"
    assert not any("/files/" in c for c in handler.calls)


def test_purge_unreferenced_zsxq_files(tmp_path):
    """清理只删当前帖子不再引用的附件，引用中的留下。"""
    from app.db import DB
    from app.fetchers.zsxq import purge_unreferenced_zsxq_files, zsxq_cache_stats

    db = DB(tmp_path / "t.db")
    dest = tmp_path / "zsxq_files"
    dest.mkdir()
    (dest / "22.pdf").write_bytes(b"keep")
    (dest / "99.pdf").write_bytes(b"gone-data")
    kid = db.add_kol("zsxq", "g", "123")
    db.insert_post(
        "zsxq",
        kid,
        "t1",
        "t",
        "c",
        "u",
        "2026-08-20",
        detail={"files": [{"file_id": "22", "name": "a.pdf", "url": "/zsxq-files/22.pdf"}]},
    )
    before = zsxq_cache_stats(db)
    assert before == {"files": 2, "bytes": len(b"keep") + len(b"gone-data")}
    result = purge_unreferenced_zsxq_files(db)
    assert result["deleted"] == 1
    assert result["files"] == 1
    assert result["bytes"] == len(b"keep")
    assert (dest / "22.pdf").exists()
    assert not (dest / "99.pdf").exists()


def _comments_ok(topic_id, comments, **extra):
    body = {"succeeded": True, "resp_data": {"comments": comments, **extra}}
    return httpx.Response(200, json=body)


def _comment(cid, name, text, likes=0):
    return {
        "comment_id": cid,
        "create_time": "2026-08-21T08:00:00.000+0800",
        "owner": {"name": name},
        "text": text,
        "likes_count": likes,
    }


class _CommentsDB:
    """带 get_post_detail 的最小 FakeDB；settings 可注入。"""

    def __init__(self, stored=None, **settings):
        self._stored = stored or {}
        self._settings = settings or {}

    def get_setting(self, key):
        return self._settings.get(key)

    def get_post_detail(self, platform, external_id):
        return dict(self._stored.get(external_id, {}))


def test_fetch_collects_comments_for_new_topic():
    """新主题有评论时抓取并写入 detail；请求打到 /topics/{id}/comments。"""
    topic = _topic(1, "正文")
    topic["comments_count"] = 2
    db = _CommentsDB()
    handler = _Handler(
        {
            "topics": _ok([topic]),
            "topics/1/comments": _comments_ok(1, [_comment(11, "甲", "好文", 3), _comment(12, "乙", "顶")]),
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": 9, "name": "g", "external_id": "123"})
    detail = posts[0].detail or {}
    assert detail["comments"] == [
        {"comment_id": "11", "create_time": "2026-08-21T08:00:00.000+0800", "owner": "甲", "text": "好文", "likes_count": 3},
        {"comment_id": "12", "create_time": "2026-08-21T08:00:00.000+0800", "owner": "乙", "text": "顶", "likes_count": 0},
    ]
    assert detail["comments_count"] == 2
    assert any("/topics/1/comments" in c for c in handler.calls)


def test_fetch_preserves_stored_comments_for_existing_topic():
    """已存过评论的主题刷新签名 URL 时沿用本地评论，不再请求评论接口。"""
    topic = _topic(1, "正文")
    topic["comments_count"] = 5
    stored_comments = [{"comment_id": "11", "create_time": "t", "owner": "甲", "text": "旧评论", "likes_count": 1}]
    db = _CommentsDB(stored={"1": {"comments": stored_comments}})
    handler = _Handler({"topics": _ok([topic])})  # 无 /comments 路由 → 若误请求会 404
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": 9, "name": "g", "external_id": "123"})
    detail = posts[0].detail or {}
    assert detail["comments"] == stored_comments
    assert not any("/comments" in c for c in handler.calls)


def test_fetch_skips_comments_when_disabled():
    """zsxq_fetch_comments=0 时不抓评论，detail 不写 comments。"""
    topic = _topic(1, "正文")
    topic["comments_count"] = 3
    db = _CommentsDB(zsxq_fetch_comments="0")
    handler = _Handler({"topics": _ok([topic])})
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": 9, "name": "g", "external_id": "123"})
    detail = posts[0].detail or {}
    assert "comments" not in detail


def test_fetch_respects_comment_budget_per_round():
    """单轮评论请求预算耗尽后不再发起新的评论请求。"""
    t1 = _topic(1, "一"); t1["comments_count"] = 1
    t2 = _topic(2, "二"); t2["comments_count"] = 1
    db = _CommentsDB(zsxq_comment_budget="1")
    handler = _Handler(
        {
            "topics": _ok([t1, t2]),
            "topics/1/comments": _comments_ok(1, [_comment(11, "甲", "c1")]),
            "topics/2/comments": _comments_ok(2, [_comment(21, "乙", "c2")]),
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    posts = ZsxqFetcher(db=db, client=client).fetch({"id": 9, "name": "g", "external_id": "123"})
    comment_requests = [c for c in handler.calls if "/comments" in c]
    assert len(comment_requests) == 1  # 预算只有 1 次
    assert (posts[0].detail or {}).get("comments_count") == 1
    assert "comments" not in (posts[1].detail or {})


def test_default_headers_are_web_flavor():
    """默认（未开 App 通道）发浏览器 UA + Origin/Referer，不带 X-Version。"""
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return _ok([_topic(1, "正文")])

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=None, client=client)
    fetcher.fetch({"id": 9, "name": "g", "external_id": "123"})
    h = seen["headers"]
    assert "Mozilla/5.0" in h.get("user-agent", "")
    assert h.get("origin") == "https://wx.zsxq.com"
    assert "x-version" not in h


def test_app_channel_headers_when_enabled():
    """开 App 通道：xiaomiquan UA + X-Request-Id + X-Version，去掉 Origin/Referer。"""
    seen = {}

    class _DB:
        def get_setting(self, key):
            return {"zsxq_app_channel": "1"}.get(key)

        def get_post_detail(self, platform, external_id):
            return {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return _ok([_topic(1, "正文")])

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=_DB(), client=client)
    fetcher.fetch({"id": 9, "name": "g", "external_id": "123"})
    h = seen["headers"]
    assert h.get("user-agent", "").startswith("xiaomiquan/5.27.3 Android/Phone/")
    assert h["x-version"] == "2.81.0"
    assert len(h.get("x-request-id", "")) == 36  # uuid4
    assert "origin" not in h and "referer" not in h


def test_app_channel_custom_device():
    """自定义设备串压制空格并用于 UA。"""
    seen = {}

    class _DB:
        def get_setting(self, key):
            return {"zsxq_app_channel": "1", "zsxq_app_device": "14 Xiaomi M2007J3SG"}.get(key)

        def get_post_detail(self, platform, external_id):
            return {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return _ok([_topic(1, "正文")])

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=_DB(), client=client)
    fetcher.fetch({"id": 9, "name": "g", "external_id": "123"})
    assert seen["headers"]["user-agent"] == "xiaomiquan/5.27.3 Android/Phone/14_Xiaomi_M2007J3SG"


def test_app_channel_off_by_default_even_with_device_set():
    """只配设备串不开开关，仍用 web 头。"""
    seen = {}

    class _DB:
        def get_setting(self, key):
            return {"zsxq_app_device": "14 Xiaomi"}.get(key)

        def get_post_detail(self, platform, external_id):
            return {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return _ok([_topic(1, "正文")])

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10)
    fetcher = ZsxqFetcher(db=_DB(), client=client)
    fetcher.fetch({"id": 9, "name": "g", "external_id": "123"})
    assert "xiaomiquan" not in seen["headers"].get("user-agent", "")
