"""统一日志配置：级别可控、内存环形缓冲（网页查看）、可选文件轮转。"""
from __future__ import annotations

import logging
import logging.handlers
import os
import threading
from collections import deque

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s [%(threadName)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
RING_SIZE = 2000

_ring: deque[str] = deque(maxlen=RING_SIZE)
_ring_lock = threading.Lock()
_configured = False
_configured_lock = threading.Lock()


class RingBufferHandler(logging.Handler):
    """把格式化后的日志行保留在内存环形缓冲，供管理后台查看。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            with _ring_lock:
                _ring.append(line)
        except Exception:  # noqa: BLE001, S110 - 日志记录失败不影响业务
            pass


def recent_logs(limit: int = 200) -> list[str]:
    with _ring_lock:
        return list(_ring)[-limit:]


def setup_logging(level: str | None = None, log_file: str | None = None) -> None:
    """配置根日志器（幂等）：stdout + 可选滚动文件 + 环形缓冲。"""
    global _configured
    level = level or os.environ.get("LOG_LEVEL", "INFO")
    log_file = log_file if log_file is not None else os.environ.get("LOG_FILE", "")
    with _configured_lock:
        root = logging.getLogger()
        root.setLevel(level.upper())
        # 幂等：避免 create_app 多次调用时重复挂 handler
        if not any(isinstance(h, RingBufferHandler) for h in root.handlers):
            formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            root.addHandler(console)
            ring = RingBufferHandler(level=logging.DEBUG)
            ring.setFormatter(formatter)
            root.addHandler(ring)
            if log_file:
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                root.addHandler(file_handler)
        _configured = True
    # httpx 访问日志会打印完整 URL（含 bot token），默认降到 WARNING 防泄露
    logging.getLogger("httpx").setLevel(
        logging.DEBUG if (level or "").upper() == "DEBUG" else logging.WARNING
    )
