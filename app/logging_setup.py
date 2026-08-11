"""统一日志配置：级别可控、内存环形缓冲（网页查看）、可选文件轮转。"""
from __future__ import annotations

import logging
import logging.handlers
import os
import threading
from collections import deque
from pathlib import Path

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s [%(threadName)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
RING_SIZE = 2000

_ring: deque[str] = deque(maxlen=RING_SIZE)
_ring_lock = threading.Lock()
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


LEVEL_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

# WARNING+ 持久化 sink（由 create_app 注入 DB 写入函数；未注入时丢弃）
_error_sink = None


def register_error_sink(sink) -> None:
    """注册错误日志持久化回调（logging 模块不直接依赖 DB）。"""
    global _error_sink
    _error_sink = sink


class ErrorDbHandler(logging.Handler):
    """把 WARNING+ 日志写入 DB，跨重启可查（管理后台错误记录面板）。"""

    def emit(self, record: logging.LogRecord) -> None:
        sink = _error_sink
        if sink is None:
            return
        try:
            sink(record)
        except Exception:  # noqa: BLE001, S110 - 错误日志落库失败不影响业务
            pass


def recent_logs(limit: int = 200, level: str | None = None, q: str | None = None) -> list[str]:
    """返回内存环形缓冲里的最近日志行，可按级别（含更高级别）与关键词过滤。

    DEBUG 为精确匹配（只显示 DEBUG 行）；其余级别为「及以上」（ERROR+ 含 ERROR/CRITICAL）。
    """
    with _ring_lock:
        lines = list(_ring)
    if level:
        want = level.upper()
        exact = want == "DEBUG"  # DEBUG 行最稀缺且不会混入上级日志，选它时只显示 DEBUG
        min_rank = LEVEL_RANK.get(want, 0)
        lines = [
            line for line in lines
            if (r := _line_rank(line)) is not None
            and (r == LEVEL_RANK["DEBUG"] if exact else r >= min_rank)
        ]
    if q:
        needle = q.lower()
        lines = [line for line in lines if needle in line.lower()]
    return lines[-limit:]


def _line_rank(line: str) -> int | None:
    # 日志格式：2026-08-05 22:14:58.091 LEVEL app.name [thread] message
    try:
        return LEVEL_RANK.get(line.split()[2].upper())
    except (IndexError, AttributeError):
        return None


def setup_logging(level: str | None = None, log_file: str | None = None) -> None:
    """配置根日志器（幂等）：stdout + 可选滚动文件 + 环形缓冲。"""
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
                Path(log_file).parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                root.addHandler(file_handler)
    # httpx 访问日志会打印完整 URL（含 bot token），默认降到 WARNING 防泄露
    logging.getLogger("httpx").setLevel(
        logging.DEBUG if (level or "").upper() == "DEBUG" else logging.WARNING
    )
