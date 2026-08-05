import logging

from app import logging_setup


def test_ring_buffer_keeps_recent_logs():
    logging_setup.setup_logging("DEBUG")
    logging.getLogger("app.test_debug").info("hello ring buffer %d", 42)
    lines = logging_setup.recent_logs(limit=500)
    assert any("hello ring buffer 42" in line for line in lines)


def test_ring_buffer_limits():
    logging_setup.setup_logging("DEBUG")
    logger = logging.getLogger("app.test_debug")
    for i in range(50):
        logger.info("line %d", i)
    lines = logging_setup.recent_logs(limit=10)
    assert len(lines) <= 10
    assert any("line 49" in line for line in lines)


def test_recent_logs_filter_by_level_and_keyword():
    logging_setup.setup_logging("DEBUG")
    logger = logging.getLogger("app.test_filter")
    logger.info("抓取正常 kol=超级鹿鼎公")
    logger.error("推送失败 user=kale channel=telegram err=timeout")
    lines = logging_setup.recent_logs(limit=500, level="ERROR")
    assert all(" ERROR " in line for line in lines)
    assert any("推送失败" in line for line in lines)
    assert not any("抓取正常" in line for line in lines)
    lines_q = logging_setup.recent_logs(limit=500, q="kale")
    assert any("推送失败" in line for line in lines_q)
    assert not any("抓取正常" in line for line in lines_q)
