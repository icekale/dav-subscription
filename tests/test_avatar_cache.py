import httpx

from app.avatar_cache import cache_avatar
from app.db import DB


def make_db(tmp_path) -> DB:
    return DB(tmp_path / "t.db")


def test_cache_avatar_downloads_once(tmp_path):
    db = make_db(tmp_path)
    kid = db.add_kol("weibo", "A", "1")
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"\xff\xd8\xff" * 20,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    url1 = cache_avatar(db, kid, "https://img.example/a.jpg", client=client)
    assert url1 == f"/avatars/{kid}.jpg"
    assert (tmp_path / "avatars" / f"{kid}.jpg").exists()
    assert db.get_kol(kid)["avatar_url"] == url1
    assert db.get_kol(kid)["avatar_source"] == "https://img.example/a.jpg"

    # 同一来源再次调用：命中本地缓存，不再下载
    url2 = cache_avatar(db, kid, "https://img.example/a.jpg", client=client)
    assert url2 == url1
    assert hits["n"] == 1


def test_cache_avatar_rejects_non_image_and_failure(tmp_path):
    db = make_db(tmp_path)
    kid = db.add_kol("twitter", "B", "2")

    def handler(request):
        if request.url.path == "/bad":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")
        if request.url.path == "/fail":
            return httpx.Response(403)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG" * 10)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert cache_avatar(db, kid, "https://img.example/bad", client=client) == "https://img.example/bad"
    assert cache_avatar(db, kid, "https://img.example/fail", client=client) == "https://img.example/fail"
    assert (tmp_path / "avatars").exists() is False or not list((tmp_path / "avatars").glob(f"{kid}.*"))


def test_cache_avatar_keeps_local_url(tmp_path):
    db = make_db(tmp_path)
    kid = db.add_kol("weibo", "C", "3")
    db.update_kol_avatar(kid, "/avatars/3.jpg")
    assert cache_avatar(db, kid, "/avatars/3.jpg") == "/avatars/3.jpg"
