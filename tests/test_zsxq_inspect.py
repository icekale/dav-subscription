from app.fetchers.zsxq_inspect import (
    access_token_from_cookie,
    classify_topic,
    collect_files,
    collect_images,
    comment_coverage,
    inventory_topics,
    topics_cursor,
)


def test_access_token_from_cookie_accepts_bare_or_header():
    assert access_token_from_cookie("ABC-123") == "ABC-123"
    assert (
        access_token_from_cookie("foo=1; zsxq_access_token=ABC-123; bar=2") == "ABC-123"
    )
    assert access_token_from_cookie("zsxq_access_token=ABC-123") == "ABC-123"


def test_classify_topic_distinguishes_article_forward_and_qa():
    assert classify_topic({"type": "talk", "talk": {"text": "hi"}}) == "talk"
    assert classify_topic(
        {"type": "talk", "talk": {"article": {"article_id": 1, "title": "长文"}}}
    ) == "article"
    assert classify_topic(
        {
            "type": "talk",
            "talk": {"text": "转发"},
            "referenced_topic": {"topic_id": 9, "type": "talk"},
        }
    ) == "forward"
    assert classify_topic(
        {
            "type": "q&a",
            "question": {"text": "问"},
            "answer": {"text": "答", "files": [{"file_id": 2, "name": "a.pdf"}]},
        }
    ) == "q&a"


def test_collect_media_prefers_original_and_keeps_answer_files():
    topic = {
        "type": "q&a",
        "question": {
            "images": [
                {
                    "image_id": 11,
                    "large": {"url": "https://img/large.jpg", "size": 10},
                    "original": {"url": "https://img/orig.jpg", "size": 99},
                }
            ]
        },
        "answer": {
            "files": [{"file_id": 22, "name": "讲义.pdf", "size": 2048}],
        },
    }
    images = collect_images(topic)
    assert images == [
        {"image_id": "11", "url": "https://img/orig.jpg", "size": 99}
    ]
    files = collect_files(topic)
    assert files == [{"file_id": "22", "name": "讲义.pdf", "size": 2048}]


def test_comment_coverage_flags_truncated_first_page():
    status = comment_coverage(
        comments_count=45,
        payload={"comments": [{"comment_id": i} for i in range(30)]},
    )
    assert status["returned"] == 30
    assert status["incomplete"] is True
    assert status["next_index"] == 30


def test_topics_cursor_reads_official_page_fields():
    cursor = topics_cursor(
        {
            "topics": [{"topic_id": 1, "create_time": "2026-08-01T00:00:00.000+0800"}],
            "next_end_time": "2026-08-01T00:00:00.000+0800",
            "has_more": True,
        }
    )
    assert cursor == {
        "count": 1,
        "has_more": True,
        "next_end_time": "2026-08-01T00:00:00.000+0800",
    }


def test_inventory_topics_counts_kinds_and_file_bytes():
    summary = inventory_topics(
        [
            {
                "topic_id": 1,
                "type": "talk",
                "talk": {
                    "article": {"article_id": 8, "title": "长文"},
                    "files": [{"file_id": 3, "name": "a.zip", "size": 1000}],
                },
            },
            {
                "topic_id": 2,
                "type": "talk",
                "talk": {"text": "转发"},
                "referenced_topic": {"topic_id": 1},
            },
            {
                "topic_id": 3,
                "type": "q&a",
                "comments_count": 40,
                "question": {"text": "问"},
            },
        ]
    )
    assert summary["kinds"] == {"article": 1, "forward": 1, "q&a": 1}
    assert summary["file_bytes"] == 1000
    assert summary["need_comment_pages"] == 1
    assert summary["topic_count"] == 3


def test_collect_comments_normalizes_fields_and_skips_bad():
    from app.fetchers.zsxq_inspect import collect_comments

    payload = {
        "comments": [
            {
                "comment_id": 11,
                "create_time": "2026-08-20T11:00:00.000+0800",
                "owner": {"name": "甲"},
                "text": "好文",
                "likes_count": 3,
            },
            {"comment_id": 12, "create_time": "2026-08-20T11:01:00.000+0800", "owner": {"name": "乙"}, "text": "顶", "likes_count": 0},
            "not-a-dict",
            None,
        ]
    }
    out = collect_comments(payload)
    assert out == [
        {"comment_id": "11", "create_time": "2026-08-20T11:00:00.000+0800", "owner": "甲", "text": "好文", "likes_count": 3},
        {"comment_id": "12", "create_time": "2026-08-20T11:01:00.000+0800", "owner": "乙", "text": "顶", "likes_count": 0},
    ]
    assert collect_comments({}) == []
    assert collect_comments(None) == []
