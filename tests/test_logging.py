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
