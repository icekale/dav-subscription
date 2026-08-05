from __future__ import annotations

from .base import Fetcher
from .combination import CombinationFetcher
from .rss import RssFetcher
from .weibo import WeiboFetcher
from .xueqiu import XueqiuFetcher


def build_fetchers(config, db) -> dict[str, Fetcher]:
    """根据全局配置构造各平台抓取器。"""
    return {
        "xueqiu": XueqiuFetcher(config.sources.xueqiu, db),
        "combination": CombinationFetcher(config.sources.xueqiu, db),
        "weibo": WeiboFetcher(config.sources.weibo, db),
        "twitter": RssFetcher(config.sources.rss, db),
    }
