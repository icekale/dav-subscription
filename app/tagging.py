"""纯代码关键词规则打标：不依赖 LLM，零 token 成本。

词表（settings 键 tag_vocabulary）为「标签 + 关键词」对象数组：
    [{"tag": "宏观", "keywords": ["央行", "降息", ...]}, ...]
对新帖的 title+content 做关键词子串匹配——任一关键词命中即给该标签；
多个标签命中都计入，按词表顺序取前 3 个（TAG_PER_POST_MAX）。
无关键词命中 → 无标签（不误标）。纯本地计算，不可能失败。

股票标签（stock_tag_posts）：$股票名(代码)$ 标记精确提取 + 常用股票名表
子串匹配，每条最多 STOCK_PER_POST_MAX 个，叠加在话题标签之后。
"""
from __future__ import annotations

import re

# 每条贴文最多标签数
TAG_PER_POST_MAX = 3
# 词表上限：词表过大既稀释标签区分度，也难维护关键词
TAG_VOCABULARY_MAX = 30
# 每条贴文最多股票标签数（叠加在话题标签之后，总上限 5）
STOCK_PER_POST_MAX = 2

# 雪球 $股票名(代码)$ 标记：名称可有 N/C 等新股前缀，代码为交易所前缀（SH/SZ/BJ）+ 数字。
# 排除组合（ZH）、板块指数（BK）等非个股标记。
_STOCK_MARK_RE = re.compile(r"\$([^$()\n]+)\(([A-Za-z]{2}\d{0,6})\)\$")
# 代码前缀 → 允许的交易所（个股）
_STOCK_EXCHANGE_PREFIXES = ("SH", "SZ", "BJ")
# 新股/特殊前缀（N=上市首日，C=上市次日至第5日），去前缀后才是股票名
_STOCK_NAME_PREFIXES = ("N", "C", "U", "W")


def rule_tag_posts(posts, tag_rules) -> dict[int, list[str]]:
    """给一批贴文打标签，返回「输入列表下标 → 标签列表」（≤3，按词表顺序）。

    tag_rules: [{"tag": str, "keywords": list[str]}]，keywords 为空时该标签不命中。
    对 title+content 做子串匹配，英文关键词大小写不敏感（统一小写比较）。
    """
    rules = []
    for rule in tag_rules or []:
        tag = (rule.get("tag") or "").strip() if isinstance(rule, dict) else str(rule).strip()
        keywords = rule.get("keywords") if isinstance(rule, dict) else []
        if not tag:
            continue
        cleaned = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        if cleaned:
            rules.append((tag, cleaned))

    result: dict[int, list[str]] = {}
    for idx, post in enumerate(posts):
        text = (
            str(getattr(post, "title", "") or "") + " " + str(getattr(post, "content", "") or "")
        ).lower()
        if not text.strip():
            result[idx] = []
            continue
        tags: list[str] = []
        for tag, keywords in rules:
            if any(kw.lower() in text for kw in keywords):
                tags.append(tag)
                if len(tags) >= TAG_PER_POST_MAX:
                    break
        result[idx] = tags
    return result


def stock_tag_posts(posts, stock_names) -> dict[int, list[str]]:
    """给一批贴文打股票标签，返回「输入列表下标 → 股票标签列表」（≤2，按出现顺序）。

    识别来源：
    1. 雪球 $股票名(代码)$ 标记（代码为 SH/SZ/BJ 个股）——零歧义，名称去 N/C 等新股前缀；
    2. 常用股票名表（settings 键 stock_names）子串匹配——纯文字提及也能命中。
    两来源结果去重合并；无命中返回空列表（不误标）。
    """
    names = []
    for n in stock_names or []:
        cleaned = str(n).strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)

    result: dict[int, list[str]] = {}
    for idx, post in enumerate(posts):
        text = (
            str(getattr(post, "title", "") or "") + " " + str(getattr(post, "content", "") or "")
        )
        if not text.strip():
            result[idx] = []
            continue
        tags: list[str] = []
        # 1) $标记$ 精确提取
        for m in _STOCK_MARK_RE.finditer(text):
            name = m.group(1).strip()
            code = m.group(2)
            if not code.startswith(_STOCK_EXCHANGE_PREFIXES):
                continue  # ZH 组合 / BK 板块等非个股
            while name.startswith(_STOCK_NAME_PREFIXES) and len(name) > 1:
                name = name[1:]
            if name and name not in tags:
                tags.append(name)
            if len(tags) >= STOCK_PER_POST_MAX:
                break
        # 2) 常用股票名表子串匹配
        if len(tags) < STOCK_PER_POST_MAX:
            lowered = text.lower()
            for name in names:
                if name in lowered and name not in tags:
                    tags.append(name)
                    if len(tags) >= STOCK_PER_POST_MAX:
                        break
        result[idx] = tags
    return result
