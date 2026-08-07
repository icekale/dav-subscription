"""可选 LLM 摘要：把一批动态用 OpenAI 兼容接口生成中文要点。

设计要点：
- 默认关闭：未配置 LLM_API_KEY（或 config.llm.api_key）时不生效，推送管线零变化；
- 失败静默降级：任何异常只记日志并返回 None，调用方回退原列表式汇总；
- 只传帖文标题/大V/平台/摘要，不传用户隐私字段。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "你是信息摘要助手。把下面用户订阅的社交动态整理成简洁的中文要点。"
    "要求：按重要性排序，每条要点一行，以「- 」开头；"
    "先写一句总览（共 N 条，涉及哪些大V/话题），再列要点；"
    "保留关键数字与结论，去掉寒暄与无关细节；不要添加原文没有的信息。"
)


def _post_lines(posts) -> list[str]:
    from .fetchers.base import digest_body

    lines = []
    for post in posts:
        platform = getattr(post, "platform", "")
        kol = getattr(post, "kol_name", "") or ""
        body = digest_body(post, full=False)
        lines.append(f"[{platform}] {kol}：{body[:200]}")
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

    content = "\n".join(_post_lines(posts))
    if not content.strip():
        return None
    key = summary_cache_key(posts, api_base, model) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
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
                "max_tokens": 800,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not text:
            raise RuntimeError("LLM 返回空摘要")
        if key is not None:
            cache[key] = text
        return text
    except Exception as exc:  # noqa: BLE001 - 摘要失败降级为普通汇总，不影响推送
        logger.warning("LLM 摘要失败，降级为普通汇总: %s", exc)
        return None
    finally:
        if owns_client:
            client.close()
