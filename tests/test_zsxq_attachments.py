from app.fetchers.base import Post, attachment_lines, show_original


def _post(files=None):
    return Post(
        platform="zsxq",
        kol_id=1,
        kol_name="前沿信息",
        external_id="9",
        title="t",
        content="正文",
        url="https://wx.zsxq.com/group/28888112822211/9",
        published_at="2026-08-20 10:00",
        detail={"files": files} if files is not None else {},
    )


def test_attachment_lines_empty_because_no_files():
    assert attachment_lines(_post(files=[])) == []
    assert attachment_lines(_post(files=None)) == []


def test_attachment_lines_renders_name_and_url():
    lines = attachment_lines(
        _post(files=[{"file_id": "22", "name": "a.pdf", "size": 100, "url": "https://cdn/x.pdf"}])
    )
    assert len(lines) == 1
    assert "a.pdf" in lines[0]
    assert "https://cdn/x.pdf" in lines[0]
    assert "链接可能过期" in lines[0]


def test_show_original_skips_zsxq():
    assert show_original("xueqiu", "https://xueqiu.com/1")
    assert not show_original("zsxq", "https://wx.zsxq.com/topic/1")
    assert not show_original("zsxq", "")


def test_attachment_lines_marks_url_missing():
    lines = attachment_lines(_post(files=[{"file_id": "22", "name": "b.pdf", "url": ""}]))
    assert lines == []


def test_attachment_lines_skips_relative_local_urls():
    """本地 /zsxq-files 路径不能进推送，对端打不开。"""
    lines = attachment_lines(
        _post(files=[{"file_id": "22", "name": "a.pdf", "url": "/zsxq-files/22.pdf"}])
    )
    assert lines == []


def test_insert_batch_refreshes_zsxq_files():
    """已入库星球帖下次抓到附件时要回写 detail/images，不能 INSERT OR IGNORE 丢掉。"""
    from app.db import DB
    from app.fetchers.base import Post

    db = DB(":memory:")
    kid = db.add_kol("zsxq", "g", "288")
    first = Post(
        platform="zsxq",
        kol_id=kid,
        kol_name="g",
        external_id="t1",
        title="#note#",
        content="#note#",
        url="https://wx.zsxq.com/group/288/t1",
        published_at="2026-08-20 10:00",
        images=[],
        detail={"files": []},
    )
    assert db.insert_posts_batch([first])[0]
    refreshed = Post(
        platform="zsxq",
        kol_id=kid,
        kol_name="g",
        external_id="t1",
        title="#note#",
        content="#note#",
        url="https://wx.zsxq.com/group/288/t1",
        published_at="2026-08-20 10:00",
        images=["https://img/a.jpg"],
        detail={"files": [{"file_id": "22", "name": "a.pdf", "url": "https://cdn/a.pdf"}]},
    )
    ids = db.insert_posts_batch([refreshed])
    assert ids == [None]
    row = db.list_posts(platform="zsxq", limit=5)[0]
    import json
    detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else row["detail"]
    assert detail["files"][0]["name"] == "a.pdf"
    images = json.loads(row["images"]) if isinstance(row["images"], str) else row["images"]
    assert images == ["https://img/a.jpg"]
