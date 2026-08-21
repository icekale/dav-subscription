"""纯代码关键词规则打标：不依赖 LLM，零 token 成本。

词表（settings 键 tag_vocabulary）为「标签 + 关键词」对象数组：
    [{"tag": "宏观", "keywords": ["央行", "降息", ...]}, ...]
对新帖的 title+content 做关键词子串匹配——任一关键词命中即给该标签；
多个标签命中都计入，按词表顺序取前 3 个（TAG_PER_POST_MAX）。
无关键词命中 → 无标签（不误标）。纯本地计算，不可能失败。

股票标签（stock_tag_posts）：$股票名(代码)$ 标记精确提取 + 常用股票名表
子串匹配，每条最多 STOCK_PER_POST_MAX 个，叠加在话题标签之后。

LLM 标签维护（run_tag_maintenance）：识别黑话别名、从 $标记$ 扩充名表、
清理过期标签。调度器每日一次，管理端也可立即执行。
"""
from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger(__name__)

# 每条贴文最多标签数
TAG_PER_POST_MAX = 3
# 词表上限：词表过大既稀释标签区分度，也难维护关键词
TAG_VOCABULARY_MAX = 30
# 每条贴文最多股票标签数（叠加在话题标签之后，总上限 5）
STOCK_PER_POST_MAX = 2
# 股票名表 / 别名表上限，防膨胀
STOCK_TABLE_MAX = 200
# 黑话候选只扫最近 N 帖（控 token）；$标记$ 全库扫描（纯本地、便宜）
ALIAS_CANDIDATE_SCAN = 500
MARK_RESOLVE_BATCH = 80

# 雪球 $股票名(代码)$ 标记：名称可有 N/C 等新股前缀，代码为交易所前缀（SH/SZ/BJ）+ 数字。
# 排除组合（ZH）、板块指数（BK）以及上证/深证指数代码。
_STOCK_MARK_RE = re.compile(r"\$([^$()\n]+)\(([A-Za-z]{2}\d{0,6})\)\$")
# 代码前缀 → 允许的交易所（个股）
_STOCK_EXCHANGE_PREFIXES = ("SH", "SZ", "BJ")
# 新股/特殊前缀（N=上市首日，C=上市次日至第5日），去前缀后才是股票名
_STOCK_NAME_PREFIXES = ("N", "C", "U", "W")
# 名称含这些词不当个股（上证指数/沪深300ETF 等）
_NON_EQUITY_NAME_MARKERS = ("指数", "ETF", "etf", "基金", "板块")
_maintain_lock = threading.Lock()

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


def is_equity_code(code: str) -> bool:
    """是否为沪深京个股代码。排除 ZH 组合、BK 板块、上证指数（SH000）、深证指数（SZ399）。"""
    raw = str(code or "").strip().upper()
    if len(raw) < 4:
        return False
    exch, digits = raw[:2], raw[2:]
    if exch not in _STOCK_EXCHANGE_PREFIXES:
        return False
    if exch == "SH" and digits.startswith("000"):
        return False
    if exch == "SZ" and digits.startswith("399"):
        return False
    return True


def is_equity_name(name: str) -> bool:
    """正式名是否像个股。指数/ETF/基金/板块不当股票名写入名表。"""
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    return not any(marker in cleaned for marker in _NON_EQUITY_NAME_MARKERS)


def _contains_term(text_casefolded: str, term: str) -> bool:
    """匹配单个关键词：纯 ASCII 词用英文单词边界，其他（中文/混合）子串匹配。

    英文短词（如 AI、NVDA）做子串匹配会误命中 said/train 等含子串的单词，
    因此对纯 ASCII 字母数字词要求前后不能是字母数字。text 需已 casefold。
    """
    cleaned = str(term).strip()
    if not cleaned:
        return False
    folded = cleaned.casefold()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+#-]*", cleaned):
        return re.search(
            rf"(?<![A-Za-z0-9]){re.escape(folded)}(?![A-Za-z0-9])",
            text_casefolded,
        ) is not None
    return folded in text_casefolded


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
        ).casefold()
        if not text.strip():
            result[idx] = []
            continue
        tags: list[str] = []
        for tag, keywords in rules:
            if any(_contains_term(text, kw) for kw in keywords):
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
            if not is_equity_code(code):
                continue  # ZH 组合 / BK 板块 / 指数等非个股
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
            folded = text.casefold()
            for name in names:
                if _contains_term(folded, name) and name not in tags:
                    tags.append(name)
                    if len(tags) >= STOCK_PER_POST_MAX:
                        break
        # 3) 黑话别名 → 正式名
        if len(tags) < STOCK_PER_POST_MAX:
            folded = text.casefold()
            for alias, stock in alias_map:
                if _contains_term(folded, alias) and stock not in tags:
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
            if not is_equity_code(code):
                continue  # ZH 组合 / BK 板块 / 指数等非个股
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


def _rows_to_posts(rows):
    from .fetchers.base import Post

    return [
        Post(
            platform=r["platform"],
            kol_id=r["kol_id"],
            kol_name=r.get("kol_name") or "",
            external_id=r["external_id"],
            title=r["title"],
            content=r["content"],
            url=r["url"],
            published_at=r["published_at"],
            category=r.get("category_name") or "",
            post_type=r.get("post_type") or "",
            images=r.get("images") or [],
        )
        for r in rows
    ]


def iter_post_row_batches(db, *, limit: int = 500, untagged_only: bool = False):
    """按 id 倒序分页遍历贴文，避免一次装入全库。"""
    below_id: int | None = None
    while True:
        rows = db.list_posts(limit=limit, untagged_only=untagged_only, below_id=below_id)
        if not rows:
            break
        yield rows
        below_id = min(r["id"] for r in rows)


def backfill_post_tags(db, mode: str = "pending") -> dict:
    """按当前词表 + 股票名 + 别名回填贴文标签。

    mode=pending 只处理未打标（''/NULL）；mode=all 全量重算。
    """
    if mode not in ("pending", "all"):
        raise ValueError(f"unknown backfill mode: {mode}")
    tag_rules = db.get_tag_vocabulary()
    stock_names = db.get_stock_names()
    stock_aliases = db.get_stock_aliases()
    processed = 0
    tagged_count = 0
    for batch in iter_post_row_batches(db, untagged_only=mode == "pending"):
        posts = _rows_to_posts(batch)
        tagged = rule_tag_posts(posts, tag_rules)
        stock_tagged = stock_tag_posts(posts, stock_names, aliases=stock_aliases)
        for i, _post in enumerate(posts):
            merged = list((tagged.get(i) or [])[:TAG_PER_POST_MAX]) + list(
                (stock_tagged.get(i) or [])[:STOCK_PER_POST_MAX]
            )
            db.update_post_tags(batch[i]["id"], merged)
            if merged:
                tagged_count += 1
        processed += len(batch)
    return {"processed": processed, "tagged": tagged_count}


def _append_alias(aliases: list[dict], existing: set[str], alias: str, stock: str) -> bool:
    """写入一条别名；与股票名/已有别名冲突时跳过。满员返回 False。"""
    if not alias or not stock or alias == stock:
        return False
    if alias in existing or alias in {a["stock"] for a in aliases}:
        return False
    if len(aliases) >= STOCK_TABLE_MAX:
        return False
    aliases.append({"alias": alias, "stock": stock})
    existing.add(alias)
    return True


def _append_stock_name(stock_names: list[str], existing: set[str], name: str) -> bool:
    if not name or name in existing or not is_equity_name(name):
        return False
    if len(stock_names) >= STOCK_TABLE_MAX:
        return False
    stock_names.append(name)
    existing.add(name)
    return True


def run_tag_maintenance(db, llm_config=None) -> dict:
    """跑一轮标签维护：去非个股名、LLM 识别别名/$标记$、清理误标。

    未配置 LLM 时跳过识别，清理仍执行。别名与 $标记$ 两路结果合并后再写库，
    避免后一步覆盖前一步。返回供管理端展示的结果摘要。
    """
    tag_rules = db.get_tag_vocabulary()
    topic_tags = {r["tag"] for r in tag_rules}
    stock_names = [n for n in db.get_stock_names() if str(n).strip()]
    aliases = list(db.get_stock_aliases())

    removed_stock_names = [n for n in stock_names if not is_equity_name(n)]
    if removed_stock_names:
        stock_names = [n for n in stock_names if is_equity_name(n)]
        db.set_stock_names(stock_names)

    added_aliases: list[dict] = []
    added_stock_names: list[str] = []
    llm_used = False
    error = None
    candidates_n = 0
    marks_n = 0

    llm_ok = bool(llm_config and getattr(llm_config, "api_key", ""))
    if llm_ok:
        try:
            from .llm import resolve_stock_marks, suggest_stock_aliases

            llm_used = True
            recent = db.list_posts(limit=ALIAS_CANDIDATE_SCAN)
            known = list(topic_tags) + stock_names
            known += [a["stock"] for a in aliases]
            known += [a["alias"] for a in aliases]
            candidates = extract_alias_candidates(_rows_to_posts(recent), known)
            candidates_n = len(candidates)
            existing_aliases = {a["alias"] for a in aliases}
            existing_stocks = set(stock_names)

            if candidates:
                suggestions = suggest_stock_aliases(candidates, stock_names, llm_config)
                for item in suggestions or []:
                    if item.get("confidence") != "high":
                        continue
                    alias = str(item.get("alias") or "").strip()
                    stock = str(item.get("stock") or "").strip()
                    if alias in topic_tags or alias in existing_stocks:
                        continue
                    if stock not in existing_stocks:
                        continue
                    if _append_alias(aliases, existing_aliases, alias, stock):
                        added_aliases.append({"alias": alias, "stock": stock})

            all_marks: list[tuple[str, str]] = []
            seen_marks: set[tuple[str, str]] = set()
            for batch in iter_post_row_batches(db):
                for mark in extract_stock_marks(_rows_to_posts(batch)):
                    if mark not in seen_marks:
                        seen_marks.add(mark)
                        all_marks.append(mark)
            marks_n = len(all_marks)
            known_names = set(existing_stocks)
            known_names.update(existing_aliases)
            known_names.update(a["stock"] for a in aliases)
            known_names.update(topic_tags)
            new_marks = [(n, c) for n, c in all_marks if n not in known_names]

            resolved: list[dict] = []
            for i in range(0, len(new_marks), MARK_RESOLVE_BATCH):
                resolved.extend(
                    resolve_stock_marks(new_marks[i : i + MARK_RESOLVE_BATCH], llm_config)
                    or []
                )
            for item in resolved:
                official = str(item.get("official") or "").strip()
                name = str(item.get("name") or "").strip()
                if official in topic_tags or not is_equity_name(official):
                    continue
                if _append_stock_name(stock_names, existing_stocks, official):
                    added_stock_names.append(official)
                if item.get("is_alias") and name and name != official:
                    if name in topic_tags or name in existing_stocks:
                        continue
                    if _append_alias(aliases, existing_aliases, name, official):
                        added_aliases.append({"alias": name, "stock": official})

            if added_stock_names or removed_stock_names:
                db.set_stock_names(stock_names)
            if added_aliases:
                db.set_stock_aliases(aliases)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.warning("标签维护识别异常: %s", exc)

    valid_tags = [r["tag"] for r in tag_rules] + stock_names
    valid_tags += [a["stock"] for a in aliases]
    cleaned = 0
    try:
        cleaned = cleanup_stale_tags(db, valid_tags)
    except Exception as exc:  # noqa: BLE001
        logger.warning("贴文标签清理失败: %s", exc)
        if error is None:
            error = str(exc)

    return {
        "cleaned": cleaned,
        "added_aliases": added_aliases,
        "added_stock_names": added_stock_names,
        "removed_stock_names": removed_stock_names,
        "candidates": candidates_n,
        "marks": marks_n,
        "llm_used": llm_used,
        "error": error,
    }


def try_run_tag_maintenance(db, llm_config=None) -> dict | None:
    """尝试执行维护；已有任务在跑时返回 None，避免并发双写词表。"""
    if not _maintain_lock.acquire(blocking=False):
        return None
    try:
        return run_tag_maintenance(db, llm_config)
    finally:
        _maintain_lock.release()
