from app.fetchers.ima_inspect import (
    addable_ids,
    classify_item,
    first_url,
    inventory_items,
    knowledge_bases,
    knowledge_items,
    list_cursor,
    public_numeric_id,
    summarize_media,
    summarize_public_item,
)


def test_classify_item_uses_folder_fields_and_media_prefix():
    assert classify_item({"folder_id": "folder_1", "name": "目录", "file_number": 2}) == "folder"
    assert classify_item({"media_id": "folder_abc", "title": "子目录"}) == "folder"
    assert classify_item({"media_id": "note_abc", "title": "笔记"}) == "note"
    assert classify_item({"media_id": "weburl_1", "title": "网页"}) == "web"
    assert classify_item({"media_id": "x", "media_type": 6, "title": "公号"}) == "wechat"


def test_knowledge_bases_reads_list_or_map():
    listed = knowledge_bases(
        {"info_list": [{"kb_id": "kb1", "kb_name": "频道", "role_type": 2}]}
    )
    assert listed[0]["id"] == "kb1"
    assert listed[0]["name"] == "频道"
    mapped = knowledge_bases({"infos": {"kb1": {"name": "频道"}}})
    assert mapped == [{"name": "频道", "kb_id": "kb1", "id": "kb1"}]


def test_list_cursor_and_inventory_flag_time_fields():
    payload = {
        "knowledge_list": [
            {"media_id": "file_1", "title": "a", "create_time": 1},
            {"folder_id": "folder_1", "name": "d", "file_number": 0},
        ],
        "is_end": False,
        "next_cursor": "c2",
    }
    assert list_cursor(payload) == {"is_end": False, "next_cursor": "c2", "count": 2}
    summary = inventory_items(knowledge_items(payload))
    assert summary["kinds"] == {"file": 1, "folder": 1}
    assert summary["has_time"] is True
    assert "create_time" in summary["field_names"]


def test_addable_ids_and_media_summary_hide_full_url():
    ids = addable_ids({"addable_knowledge_base_list": [{"id": "kb1"}, {"name": "无id"}]})
    assert ids == {"kb1"}
    url = "https://cos.ap-guangzhou.myqcloud.com/x.pdf?q-sign=1"
    summary = summarize_media({"download_url": url, "media_type": 1})
    assert summary["has_url"] is True
    assert summary["host"] == "cos.ap-guangzhou.myqcloud.com"
    assert summary["signed"] is True
    assert first_url({"nested": {"url": url}}) == url


def test_public_numeric_id_and_public_item_summary():
    assert (
        public_numeric_id({"current_path": [{"folder_id": "7419792097", "name": "库"}]})
        == "7419792097"
    )
    summary = summarize_public_item(
        {
            "media_id": "txt_1",
            "media_type": 13,
            "title": "标题",
            "introduction": "x" * 20,
            "create_time": "1",
            "raw_file_url": "https://mp.weixin.qq.com/s/abc",
        }
    )
    assert summary["has_time"] is True
    assert summary["intro_len"] == 20
    assert summary["content_len"] == 0
    assert summary["has_jump_url"] is False
    assert summary["raw_host"] == "mp.weixin.qq.com"


def test_item_helpers_for_posts_and_fulltext():
    from app.fetchers.ima_inspect import (
        item_cover,
        item_detail,
        item_text,
        item_time_ms,
        media_info_target,
    )

    item = {
        "media_id": "txt_abc",
        "title": "笔记.txt",
        "abstract": "AI摘要: 要点",
        "introduction": "开头",
        "create_time": 1787152223403,
        "update_time": 1787152223404,
        "media_type": 13,
        "file_size": "123",
        "md5_sum": "md5",
        "raw_file_url": "5/x/file_manager/a",
        "cover_urls": ["https://ima-share-kb.image.myqcloud.com/5/x/c.jpg?sign=1"],
        "empty_field": "",
    }
    assert item_time_ms(item) == 1787152223403
    assert item_text(item) == "AI摘要: 要点"
    assert item_text({**item, "abstract": ""}) == "开头"
    assert item_text({}) == ""
    assert item_cover(item) == "https://ima-share-kb.image.myqcloud.com/5/x/c.jpg?sign=1"
    assert item_cover({}) == ""
    detail = item_detail(item)
    assert detail["media_id"] == "txt_abc"
    assert detail["file_size"] == "123"
    assert "empty_field" not in detail
    assert "introduction" not in detail  # 正文不进 detail，避免重复存储

    assert media_info_target({"data": {"url_info": {"url": "https://x/raw", "headers": {"Authorization": "B"}}}}) == ("https://x/raw", {"Authorization": "B"})
    assert media_info_target({"data": {"url_info": {"headers": {}}}}) == ("", {})
    assert media_info_target({"data": {}}) == ("", {})
