"""可选 LLM 摘要与打标：把一批动态用 OpenAI 兼容接口生成中文要点 / 话题标签。

设计要点：
- 默认关闭：未配置 LLM_API_KEY（或 config.llm.api_key）时不生效，推送管线零变化；
- 失败静默降级：任何异常只记日志并返回 None（摘要）/ {}（标签），调用方回退原逻辑；
- 只传帖文标题/大V/平台/摘要，不传用户隐私字段。
"""
from __future__ import annotations

import json
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


# ---- 贴文话题打标 ----

# 单次请求最多贴文数：超出分块多次调用，控制单条输入长度与超时风险
TAG_CHUNK_SIZE = 25
# 词表上限：词表过大既稀释标签区分度，也会增加模型漏选概率
TAG_VOCABULARY_MAX = 30
# 每条贴文最多标签数
TAG_PER_POST_MAX = 3


TAG_SYSTEM_PROMPT = (
    "你是财经社区内容编辑，负责给社交平台的动态打话题标签。"
    "规则：只从给定的候选标签里选，不要自造标签；"
    "每条最多 3 个，没有合适的就留空数组；只根据内容主题打标，不要臆测。"
    "输出 JSON 对象，键是序号（字符串），值是标签数组，例如 "
    '{"1": ["宏观", "政策"], "2": []}。除 JSON 外不要输出任何其他内容。'
)


def _tag_lines(posts) -> str:
    """把一批贴文转成「序号. [平台] KOL：标题 ｜ 正文」的行，供 LLM 打标。"""
    from .fetchers.base import digest_body

    lines = []
    for idx, post in enumerate(posts, start=1):
        platform = getattr(post, "platform", "") or ""
        kol = getattr(post, "kol_name", "") or ""
        title = (getattr(post, "title", "") or "").strip()
        body = digest_body(post, full=False, max_chars=300)
        text = f"{title} ｜ {body}" if title and title not in body else body
        lines.append(f"{idx}. [{platform}] {kol}：{text}")
    return "\n".join(lines)


def _parse_tag_response(text: str, vocabulary: list[str]) -> dict[str, list[str]]:
    """宽松解析打标 JSON：容忍 markdown fence 与前后缀，丢弃词表外的标签。

    不用 response_format=json_object 是为了兼容 Ollama/vLLM 等任意 OpenAI
    兼容服务（与摘要/翻译一致），因此解析必须足够宽容。
    """
    vocab = set(vocabulary)
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        logger.warning("LLM 打标响应无 JSON 块: %.100s", text)
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, val in data.items():
        if isinstance(val, list):
            picked = []
            for tag in val:
                tag = str(tag).strip()
                if tag in vocab and tag not in picked and len(picked) < TAG_PER_POST_MAX:
                    picked.append(tag)
            result[str(key)] = picked
    return result


def tag_posts(posts, vocabulary: list[str], llm_config=None, client=None) -> dict[int, list[str]]:
    """给一批贴文打话题标签，返回「输入列表下标 → 标签列表」。

    未配置、配置无效或任何失败都返回 {}（调用方按无标签处理），绝不抛异常；
    标签严格限定在 vocabulary 内，保证词表可控、不碎片化。
    """
    api_key = getattr(llm_config, "api_key", "") if llm_config else ""
    if not api_key or not vocabulary:
        return {}
    api_base = (getattr(llm_config, "api_base", "") or "https://api.openai.com/v1").rstrip("/")
    model = getattr(llm_config, "model", "") or "gpt-4o-mini"

    result: dict[int, list[str]] = {}
    try:
        for start in range(0, len(posts), TAG_CHUNK_SIZE):
            chunk = posts[start : start + TAG_CHUNK_SIZE]
            chunk_result = _tag_chunk(
                chunk, vocabulary, api_base, api_key, model, client
            )
            for local_idx, tags in chunk_result.items():
                result[start + local_idx] = tags
    except Exception as exc:  # noqa: BLE001 - 打标失败不影响抓取/推送
        logger.warning("LLM 打标失败，本轮贴文不带标签: %s", exc)
        return {}
    return result


def _tag_chunk(posts, vocabulary, api_base, api_key, model, client=None) -> dict[int, list[str]]:
    """对一批贴文（≤ TAG_CHUNK_SIZE 条）发起一次打标请求，返回下标映射。"""
    import httpx

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
                            {"role": "system", "content": TAG_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"候选标签（只能从中选择）：{json.dumps(vocabulary, ensure_ascii=False)}\n"
                                    f"共 {len(posts)} 条动态，为每条选 0~3 个标签，输出 JSON：\n"
                                    f"{_tag_lines(posts)}"
                                ),
                            },
                        ],
                        "temperature": 0,
                        # 推理模型 max_tokens 含思考预算，托底 2000（与摘要一致）
                        "max_tokens": min(4000, max(2000, 100 + 60 * len(posts))),
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
                usage = (data.get("usage") or {}).get("total_tokens") or 0
                mapping = _parse_tag_response(text, vocabulary)
                if not mapping and text:
                    raise _RetryableError("LLM 打标返回无法解析")
                if not mapping:
                    # 空文本/空 choices：按无结果处理，不产出「全空标签」映射
                    logger.warning("LLM 打标空响应 posts=%d", len(posts))
                    return {}
                logger.info("LLM 打标完成 posts=%d tags=%d tokens=%d", len(posts), len(mapping), usage)
                if owns_client:
                    client.close()
                return {i: mapping.get(str(i + 1), []) for i in range(len(posts))}
            except httpx.HTTPStatusError as exc:
                last_err = exc  # 4xx（鉴权/参数错误）重试无意义
                break
            except (httpx.TransportError, _RetryableError) as exc:
                last_err = exc
            if attempt == 0:
                time.sleep(2)
        logger.warning("LLM 打标失败，本轮贴文不带标签: %s", last_err)
        return {}
    finally:
        if owns_client and client is not None:
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
    "你是财经内容主编，负责把用户今天订阅的社交动态整理成一份精炼的每日综述。"
    "要求："
    "1. 先写一句总览，点明今天共多少条动态、围绕哪些大V/话题；"
    "2. 按重要性排序，把相关帖子按话题归并成要点：重要的展开讲，普通的一笔带过，不要逐条罗列原文；"
    "3. 每条要点一行，以「- 」开头，正文里直接点明是谁（大V名）说的、说了什么；"
    "4. 保留关键数字与结论，去掉寒暄与无关细节；不要添加原文没有的信息，不要臆测。"
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
                        # 推理模型思考预算可能很大，上限放宽到 16000（deepseek-chat 等普通模型用不满）
                        "max_tokens": min(16000, max(2000, 200 + 120 * len(posts))),
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
