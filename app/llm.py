"""可选 LLM 摘要：把一批动态用 OpenAI 兼容接口生成中文要点 / 每日综述。

设计要点：
- 默认关闭：未配置 LLM_API_KEY（或 config.llm.api_key）时不生效，推送管线零变化；
- 失败静默降级：任何异常只记日志并返回 None，调用方回退原逻辑；
- 只传帖文标题/大V/平台/摘要，不传用户隐私字段。
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

class _RetryableError(Exception):
    """瞬时错误（429/5xx/空响应），可重试一次。"""


SUMMARY_SYSTEM_PROMPT = (
    "你是信息摘要助手。把下面用户订阅的社交动态整理成简洁的中文要点。"
    "要求：按重要性排序，每条要点一行，以「- 」开头；"
    "先写一句总览（共 N 条，涉及哪些大V/话题），再列要点；"
    "保留关键数字与结论，去掉寒暄与无关细节；不要添加原文没有的信息。"
)


def _post_lines(posts) -> list[str]:
    from .fetchers.base import digest_body

    # 帖少给全文（更完整上下文），帖多控制每条预算，总量仍 ≤ 12000
    per_post = 2000 if len(posts) <= 2 else 400
    lines = []
    for post in posts:
        platform = getattr(post, "platform", "")
        kol = getattr(post, "kol_name", "") or ""
        mark = "[原帖]" if (getattr(post, "post_type", "") or "") != "reply" else "[回复]"
        body = digest_body(post, full=False, max_chars=per_post)
        lines.append(f"{mark}[{platform}] {kol}：{body}")
    return lines


def summary_cache_key(posts, api_base: str, model: str) -> str:
    """摘要缓存键：平台+外部ID 有序拼接，同一批帖文（同配置）复用同一份摘要。"""
    ids = ",".join(f"{p.platform}:{p.external_id}" for p in posts)
    return f"{api_base}|{model}|{ids}"


def summarize_posts(posts, llm_config=None, client=None, cache=None) -> str | None:
    """生成摘要文本；未配置或失败返回 None（调用方降级为普通汇总）。

    cache: 可选 dict，以「配置+帖文ID列表」为键缓存摘要，同一批帖文只调一次
    大模型（批量推送时多个订阅用户共享同一份摘要）。
    """
    api_key = getattr(llm_config, "api_key", "") if llm_config else ""
    if not api_key:
        return None
    api_base = (getattr(llm_config, "api_base", "") or "https://api.openai.com/v1").rstrip("/")
    model = getattr(llm_config, "model", "") or "gpt-4o-mini"
    import httpx

    posts = sorted(posts, key=lambda p: (getattr(p, "post_type", "") or "") == "reply")
    content = "\n".join(_post_lines(posts))
    if not content.strip():
        return None
    key = summary_cache_key(posts, api_base, model) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    if not any(
        (getattr(p, "content", "") or "").strip() or (getattr(p, "title", "") or "").strip()
        for p in posts
    ):
        return None
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"共 {len(posts)} 条动态，请整理要点：\n{content[:12000]}"
                                ),
                            },
                        ],
                        "temperature": 0.3,
                        # 推理模型（如 deepseek-v4-flash）的 max_tokens 包含思考预算，
                        # 太低会被思考吃光导致 content 为空；托底 2000、上限 8000
                        "max_tokens": min(8000, max(2000, 200 + 120 * len(posts))),
                    },
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise _RetryableError(f"LLM HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                text = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not text:
                    raise _RetryableError("LLM 返回空摘要")
                usage = (data.get("usage") or {}).get("total_tokens") or 0
                logger.info("LLM 摘要完成 posts=%d tokens=%d", len(posts), usage)
                if key is not None:
                    cache[key] = text
                return text
            except httpx.HTTPStatusError as exc:
                last_err = exc  # 4xx（鉴权/参数错误）重试无意义
                break
            except (httpx.TransportError, _RetryableError) as exc:
                last_err = exc
            if attempt == 0:
                time.sleep(2)
        logger.warning("LLM 摘要失败，降级为普通汇总: %s", last_err)
        return None
    finally:
        if owns_client:
            client.close()


# ---- 每日精选综述 ----

from dataclasses import dataclass, field


@dataclass
class DailyPoint:
    """综述里的一个要点：text 是正文，post_indexes 是依据的帖子在输入列表中的下标。"""

    text: str
    post_indexes: list[int] = field(default_factory=list)


@dataclass
class DailySummary:
    """每日精选综述：总览 + 按重要性/话题组织的要点列表。"""

    overview: str
    points: list[DailyPoint] = field(default_factory=list)


DAILY_SUMMARY_SYSTEM_PROMPT = (
    "你是财经内容主编，负责把用户今天订阅的社交动态综合整理成一份精炼的每日综述。"
    "要求："
    "1. 先写一句总览，点明今天共多少条动态、围绕哪些大V/话题；"
    "2. 把全部内容综合成**最多 3 条**要点（宁可少而全，不要多而碎）；"
    "3. **每条要点控制在 60~80 字左右**，只写核心结论与关键数字，细节、论证过程、背景一律省略；"
    "4. 每条要点以「- 」开头，正文里直接点明是谁（大V名）说的、核心观点是什么；"
    "5. 保留关键数字与结论，去掉寒暄与无关细节；不要添加原文没有的信息，不要臆测。"
    "输出除总览和要点外不要任何解释。"
)


def _daily_lines(posts) -> list[str]:
    """把一批贴文转成「序号. [原帖|回复][平台] KOL：正文摘要」的行，供每日综述。"""
    from .fetchers.base import digest_body

    per_post = 2000 if len(posts) <= 2 else 400
    lines = []
    for idx, post in enumerate(posts, start=1):
        platform = getattr(post, "platform", "") or ""
        kol = getattr(post, "kol_name", "") or ""
        mark = "[原帖]" if (getattr(post, "post_type", "") or "") != "reply" else "[回复]"
        body = digest_body(post, full=False, max_chars=per_post)
        lines.append(f"{idx}. {mark}[{platform}] {kol}：{body}")
    return lines


def _parse_daily_summary(text: str, post_count: int) -> DailySummary | None:
    """宽松解析每日综述：首段（首个要点前的非列表行）为总览，列表行为要点。

    要点行接受「- / • / * / 1.」等常见列表前缀；行尾形如（[1]）或（[1][3]）的
    数字标记解析为帖子下标（容忍后面带句号/逗号等标点，LLM 常顺手加）。序号必须
    落在 1..post_count 内，越界/非数字丢弃；要点无有效序号则保留但不带链接。
    解析失败或没有要点时返回 None（调用方降级为原始列表）。
    """
    if not text:
        return None
    lines = text.strip().splitlines()
    overview_lines: list[str] = []
    points: list[DailyPoint] = []
    for line in lines:
        stripped = line.strip()
        match = re.match(r"^(?:[-•*]\s+|[-•*]|\d+[.、]\s+)(.*)$", stripped, re.DOTALL)
        if match:
            body = match.group(1).strip()
            if not body:
                continue
            # 提取行尾形如（[1]）或（[1][3]）的序号标记，容忍后随句读标点
            indexes: list[int] = []
            tail = body
            while True:
                idx_match = re.search(r"（((?:\[\d+\])+)）[。．.，,；;！!？?]?\s*$", tail)
                if not idx_match:
                    break
                for num_str in re.findall(r"\[(\d+)\]", idx_match.group(1)):
                    num = int(num_str)
                    if 1 <= num <= post_count and num - 1 not in indexes:
                        indexes.append(num - 1)
                tail = tail[: idx_match.start()].rstrip("。．.，,；;！!？? ").rstrip()
            points.append(DailyPoint(text=tail or body, post_indexes=indexes))
        elif stripped:
            overview_lines.append(stripped)
    # 解析层强制上限：模型可能输出超过 3 条，只保留前三条（顺序与引用序号不变）
    points = points[:3]
    if not points:
        logger.warning("LLM 每日综述无要点，降级为原始列表")
        return None
    overview = " ".join(overview_lines).strip()
    return DailySummary(overview=overview, points=points)


def render_daily_summary(summary: DailySummary) -> str:
    """把综述渲染成纯文本：标题 + 总览 + 编号要点，不带原文链接。"""
    lines = ["📊 今日大V精选（LLM 梳理）"]
    if summary.overview:
        lines += ["", summary.overview]
    for idx, point in enumerate(summary.points, start=1):
        lines.append(f"{idx}. {point.text}")
    return "\n".join(lines)


def summarize_daily(posts, llm_config=None, client=None) -> DailySummary | None:
    """生成每日精选综述；未配置或失败返回 None（调用方降级为原始列表）。

    与 summarize_posts 同款降级/重试策略；只传帖文标题/大V/平台/摘要，不传用户隐私字段。
    """
    api_key = getattr(llm_config, "api_key", "") if llm_config else ""
    if not api_key:
        return None
    api_base = (getattr(llm_config, "api_base", "") or "https://api.openai.com/v1").rstrip("/")
    model = getattr(llm_config, "model", "") or "gpt-4o-mini"
    import httpx

    content = "\n".join(_daily_lines(posts))
    if not content.strip():
        return None
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": DAILY_SUMMARY_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"共 {len(posts)} 条动态，请整理成每日综述：\n{content[:12000]}"
                                ),
                            },
                        ],
                        "temperature": 0.3,
                        # 推理模型（deepseek-reasoner）思考预算可达 1 万+ tokens 且与帖数无关，
                        # 用帖数公式（15 帖仅 2000）会被思考吃光致 content 为空；直接给足上限，
                        # 普通模型不会用满。daily 场景帖数 ≤15，单条输入量可控。
                        "max_tokens": 16000,
                    },
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise _RetryableError(f"LLM HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                text = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                summary = _parse_daily_summary(text, len(posts))
                if summary is None:
                    raise _RetryableError("LLM 每日综述无法解析")
                usage = (data.get("usage") or {}).get("total_tokens") or 0
                logger.info("LLM 每日综述完成 posts=%d points=%d tokens=%d", len(posts), len(summary.points), usage)
                return summary
            except httpx.HTTPStatusError as exc:
                last_err = exc  # 4xx（鉴权/参数错误）重试无意义
                break
            except (httpx.TransportError, _RetryableError) as exc:
                last_err = exc
            if attempt == 0:
                time.sleep(2)
        logger.warning("LLM 每日综述失败，降级为原始列表: %s", last_err)
        return None
    finally:
        if owns_client:
            client.close()
