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

# 候选词过滤停用词：滑窗提取会产生大量口语高频词（回复/一个/今天…），
# 会挤占真正黑话昵称的候选名额，喂给 LLM 前先剔除
_ALIAS_STOPWORDS = {
    "回复", "一个", "今天", "昨天", "明天", "不是", "这个", "那个", "什么", "怎么",
    "就是", "还是", "现在", "没有", "可以", "自己", "可能", "一下", "但是", "因为",
    "所以", "如果", "我们", "你们", "他们", "以及", "或者", "已经", "之后", "之前",
    "进行", "获得", "认为", "表示", "指出", "相关", "对于", "通过", "主要", "目前",
    "最近", "国内", "国外", "行业", "问题", "情况", "方面", "部分", "一定", "这么",
    "那么", "如何", "为何", "真的", "感觉", "觉得", "知道", "看到", "听到", "想到",
    "说到", "开始", "结束", "继续", "希望", "需要", "想要", "能够", "应该", "必须",
    "而且", "并且", "不过", "然而", "既然", "即使", "虽然", "于是", "然后", "接着",
    "同时", "另外", "总之", "最后", "首先", "其次", "再次", "还有", "比如", "例如",
    "等等", "之类", "大家", "有点", "一点", "不少",
    "看看", "说说", "想想", "问问", "聊聊", "记得", "忘记", "明白", "了解",
    "东西", "时候", "地方", "事情", "办法", "方式", "水平", "程度", "空间", "时间",
    # 财经通用词：不是股票黑话，LLM 判断也只会给 none，提前剔除省 token
    "指数", "市场", "数据", "公司", "投资", "现金", "反弹", "美股", "交易", "美国",
    "股市", "影响", "调仓", "预期", "板块", "个股", "大盘", "业绩", "财报", "估值",
    "资金", "仓位", "持仓", "净值", "收益", "涨幅", "跌幅", "市值", "利润", "营收",
    "分红", "回购", "风险", "机会", "趋势", "周期", "泡沫", "回调", "突破", "支撑",
    "压力", "成本", "价格", "订单", "产能", "需求", "供给", "竞争", "格局", "龙头",
    "龙头股", "逻辑", "核心", "方向", "观点", "结论", "底部", "顶部",
    "进场", "出场", "建仓", "减仓", "加仓", "清仓", "满仓", "空仓", "短线", "长线",
    "价值", "成长", "红利", "权重", "题材", "热点", "风口", "赛道", "结构", "节奏",
}


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


def stock_tag_posts(posts, stock_names, aliases=None) -> dict[int, list[str]]:
    """给一批贴文打股票标签，返回「输入列表下标 → 股票标签列表」（≤2，按出现顺序）。

    识别来源：
    1. 雪球 $股票名(代码)$ 标记（代码为 SH/SZ/BJ 个股）——零歧义，名称去 N/C 等新股前缀；
    2. 常用股票名表（settings 键 stock_names）子串匹配——纯文字提及也能命中；
    3. 黑话别名表（settings 键 stock_aliases，LLM 每日自动识别）——命中别名打对应正式名。
    各来源结果去重合并；无命中返回空列表（不误标）。
    """
    names = []
    for n in stock_names or []:
        cleaned = str(n).strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)
    # 别名表：{"alias": "宁王", "stock": "宁德时代"}；打标时输出正式名
    alias_map = []
    for a in aliases or []:
        if isinstance(a, dict):
            alias = str(a.get("alias") or "").strip()
            stock = str(a.get("stock") or "").strip()
        else:
            alias, stock = "", ""
        if alias and stock and alias not in names:
            alias_map.append((alias, stock))

    result: dict[int, list[str]] = {}
    for idx, post in enumerate(posts):
        text = (
            str(getattr(post, "title", "") or "") + " " + str(getattr(post, "content", "") or "")
        )
        if not text.strip():
            result[idx] = []
            continue
        tags: list[str] = []
        # 1) $标记$ 精确提取（戏称如「贵州茅坑」已在别名表时，直接打正式名）
        alias_by_name = {alias: stock for alias, stock in alias_map}
        for m in _STOCK_MARK_RE.finditer(text):
            name = m.group(1).strip()
            code = m.group(2)
            if not code.startswith(_STOCK_EXCHANGE_PREFIXES):
                continue  # ZH 组合 / BK 板块等非个股
            while name.startswith(_STOCK_NAME_PREFIXES) and len(name) > 1:
                name = name[1:]
            # 戏称标记 → 用正式名打标（如 贵州茅坑 → 贵州茅台），避免戏称当标签
            if name in alias_by_name:
                name = alias_by_name[name]
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
        # 3) 黑话别名 → 正式名
        if len(tags) < STOCK_PER_POST_MAX:
            lowered = text.lower()
            for alias, stock in alias_map:
                if alias in lowered and stock not in tags:
                    tags.append(stock)
                    if len(tags) >= STOCK_PER_POST_MAX:
                        break
        result[idx] = tags
    return result


def extract_alias_candidates(posts, known) -> list[str]:
    """从一批帖子正文提取可能的股票黑话别名候选词。

    中文昵称（宁王/药茅等）多为 2~4 字，正文无天然词边界——用滑窗统计
    高频子串；英文保持单词级提取。过滤纯数字、已在 known（股票名表/
    别名表/话题词表）中的词、$标记$ 内的正式名。返回按频次降序的候选
    列表（供 LLM 判断是否为股票别名）。
    """
    from collections import Counter

    known_lower = {str(k).lower() for k in known if str(k).strip()}
    counts: Counter = Counter()
    for post in posts:
        text = (
            str(getattr(post, "title", "") or "") + " " + str(getattr(post, "content", "") or "")
        )
        # 去掉 $标记$ 内的正式名（已有精确识别，不重复当候选）
        text = _STOCK_MARK_RE.sub("", text)
        # 中文无词边界：按连续中文段枚举全部 2~4 字子串（黑话昵称多为 2~4 字），
        # 高频出现的子串才是候选；英文保持单词级提取
        for seg in re.findall(r"[\u4e00-\u9fff]+", text):
            length = len(seg)
            for start in range(length - 1):
                for size in (2, 3, 4):
                    if start + size <= length:
                        counts[seg[start : start + size]] += 1
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9.-]{1,19}", text):
            counts[m.group(0)] += 1
    # 出现≥2次、非已知词、非停用词，按频次降序
    candidates = []
    for word, n in counts.most_common():
        if n < 2:
            continue
        if word.lower() in known_lower:
            continue
        if word in _ALIAS_STOPWORDS:
            continue
        candidates.append(word)
    return candidates[:400]


def extract_stock_marks(posts) -> list[tuple[str, str]]:
    """从一批帖子提取 $股票名(代码)$ 标记，去新股前缀、去重，返回 [(name, code), ...]。

    只保留 SH/SZ/BJ 个股（排除 ZH 组合/BK 板块）；供 LLM 解析为官方名/戏称，
    用于扩充股票名表与别名表。
    """
    seen = set()
    marks = []
    for post in posts:
        text = (
            str(getattr(post, "title", "") or "") + " " + str(getattr(post, "content", "") or "")
        )
        for m in _STOCK_MARK_RE.finditer(text):
            name = m.group(1).strip()
            code = m.group(2)
            if not code.startswith(_STOCK_EXCHANGE_PREFIXES):
                continue  # ZH 组合 / BK 板块等非个股
            while name.startswith(_STOCK_NAME_PREFIXES) and len(name) > 1:
                name = name[1:]
            key = (name, code)
            if name and key not in seen:
                seen.add(key)
                marks.append(key)
    return marks


def cleanup_stale_tags(db, valid_tags) -> int:
    """清理贴文里的过期标签（旧词表残留等），返回清理条数。

    valid_tags: 当前有效标签集合（话题词表 + 股票名表 + 别名正式名）。
    用 id 游标分页遍历全部有标签的帖子，删除不在集合内的标签；
    无变化不写库（避免无谓 UPDATE）。纯本地规则，零成本。
    """
    valid = {str(t).strip() for t in valid_tags if str(t).strip()}
    removed = 0
    below_id: int | None = None
    while True:
        rows = db.list_posts(limit=500, below_id=below_id)
        if not rows:
            break
        for row in rows:
            tags = row.get("tags") or []
            stale = [t for t in tags if t not in valid]
            if stale:
                kept = [t for t in tags if t in valid]
                db.update_post_tags(row["id"], kept)
                removed += 1
        below_id = min(r["id"] for r in rows)
    return removed
