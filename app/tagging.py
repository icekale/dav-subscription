"""纯代码关键词规则打标：不依赖 LLM，零 token 成本。

词表（settings 键 tag_vocabulary）为「标签 + 关键词」对象数组：
    [{"tag": "宏观", "keywords": ["央行", "降息", ...]}, ...]
对新帖的 title+content 做关键词子串匹配——任一关键词命中即给该标签；
多个标签命中都计入，按词表顺序取前 3 个（TAG_PER_POST_MAX）。
无关键词命中 → 无标签（不误标）。纯本地计算，不可能失败。
"""
from __future__ import annotations

# 每条贴文最多标签数
TAG_PER_POST_MAX = 3
# 词表上限：词表过大既稀释标签区分度，也难维护关键词
TAG_VOCABULARY_MAX = 30


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
