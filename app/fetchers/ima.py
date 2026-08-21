"""腾讯 ima 知识库抓取器。

两种凭证与自动模式选择：
- 网页 Cookie（IMA_COOKIE）：网页列表接口（get_knowledge_list），标题/时间/摘要/封面齐全。
  订阅知识库的原文被服务端拦截，只能到此为止；自有库网页列表会被拒（code≠0）。
- OpenAPI 凭证（IMA_OPENAPI_CLIENTID + IMA_OPENAPI_APIKEY）：官方通道。
  对「自己创建的知识库」get_media_info 返回原文下载链接（url_info.url），可直接拿全文；
  对「订阅的知识库」原文被静默拦截（data 为空），自动降级用摘要（abstract/introduction）。
- 两者都有：先试网页列表（订阅库元数据最全），失败再回退 OpenAPI 列表。
  kol.external_id 用知识库 ID（OpenAPI 列表的 kb_id）或网页 wiki 的 knowledgeBaseId。

凭证读取顺序：后台设置（管理员填）→ 环境变量。后台设置键：
ima_cookie / ima_openapi_clientid / ima_openapi_apikey。
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from .base import Fetcher, Post, format_published_at
from .ima_inspect import (
    TEXT_LIKE_TYPES,
    classify_item,
    item_cover,
    item_detail,
    item_text,
    item_time_ms,
    knowledge_items,
    list_cursor,
    media_info_target,
    public_numeric_id,
)

logger = logging.getLogger(__name__)

IMA_COOKIE_KEY = "ima_cookie"
IMA_COOKIE_TIME_KEY = "ima_cookie_updated_at"
IMA_CLIENT_ID_KEY = "ima_openapi_clientid"
IMA_API_KEY_KEY = "ima_openapi_apikey"
IMA_DELAY_KEY = "ima_fetch_delay"

OPENAPI_BASE = "https://ima.qq.com/openapi/wiki/v1"
WEB_LIST = "https://ima.qq.com/cgi-bin/knowledge_tab_reader_nl/get_knowledge_list"
DEFAULT_PAGE_LIMIT = 20
DEFAULT_MAX_PAGES = 3
DEFAULT_DELAY = 0.8
FULL_TEXT_TYPES = TEXT_LIKE_TYPES  # 只对文本类媒体尝试下载原文，二进制文件跳过


def configured_ima_cookie(db=None, override: str | None = None) -> str:
    """后台写入的 Cookie 优先，否则回退环境变量。"""
    if override:
        return override
    if db is not None:
        stored = db.get_setting(IMA_COOKIE_KEY)
        if stored:
            return stored
    return os.environ.get("IMA_COOKIE", "")


def configured_openapi_creds(db=None) -> tuple[str, str]:
    client_id = os.environ.get("IMA_OPENAPI_CLIENTID") or os.environ.get("IMA_CLIENT_ID", "")
    api_key = os.environ.get("IMA_OPENAPI_APIKEY") or os.environ.get("IMA_API_KEY", "")
    if db is not None:
        stored_id = db.get_setting(IMA_CLIENT_ID_KEY)
        if stored_id:
            client_id = stored_id
        stored_key = db.get_setting(IMA_API_KEY_KEY)
        if stored_key:
            api_key = stored_key
    return (client_id or "").strip(), (api_key or "").strip()


def _delay(db=None) -> float:
    raw = ""
    if db is not None:
        raw = db.get_setting(IMA_DELAY_KEY) or ""
    raw = raw or os.environ.get("IMA_PROBE_DELAY") or os.environ.get("IMA_FETCH_DELAY") or ""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_DELAY


def _decode_text(content: bytes) -> str:
    """字节解成文本；二进制内容（PDF/Office）回退空串，避免把乱码当正文。"""
    if not content:
        return ""
    if b"\x00" in content[:512]:
        return ""
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""



class ImaFetcher(Fetcher):
    platform = "ima"

    def __init__(self, source_config=None, db=None, client=None):
        super().__init__(source_config)
        self.db = db
        # httpx.Client 线程安全，多线程轮询直接共享一个
        self._http = client or httpx.Client(timeout=30)

    # ---- 凭证与请求 ----

    def _openapi_headers(self) -> dict[str, str] | None:
        client_id, api_key = configured_openapi_creds(self.db)
        if not client_id or not api_key:
            return None
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ima-openapi-clientid": client_id,
            "ima-openapi-apikey": api_key,
        }

    def _web_headers(self, cookie: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://ima.qq.com",
            "Referer": "https://ima.qq.com/",
            "x-ima-cookie": cookie,
            "from_browser_ima": "1",
        }
        bkn = os.environ.get("IMA_X_IMA_BKN", "")
        if bkn:
            headers["x-ima-bkn"] = bkn
        return headers

    def _pause(self) -> None:
        time.sleep(_delay(self.db))

    def _openapi_post(self, method: str, body: dict) -> dict:
        headers = self._openapi_headers()
        if headers is None:
            raise RuntimeError("未配置 ima OpenAPI 凭证（IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY）")
        self._pause()
        try:
            resp = self._http.post(f"{OPENAPI_BASE}/{method}", headers=headers, json=body)
        except httpx.TransportError as exc:
            raise RuntimeError(f"ima OpenAPI 网络错误 {method}: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"ima OpenAPI {method} 非 JSON HTTP {resp.status_code}") from None
        if not isinstance(data, dict):
            raise RuntimeError(f"ima OpenAPI {method} 响应不是对象")
        retcode = data.get("retcode", data.get("code"))
        if retcode not in (0, None):
            raise RuntimeError(f"ima OpenAPI {method} 失败 retcode={retcode} {data.get('errmsg') or data.get('msg')}")
        payload = data.get("data")
        if payload is None:
            payload = {k: v for k, v in data.items() if k not in ("retcode", "errmsg")}
        if not isinstance(payload, dict):
            raise RuntimeError(f"ima OpenAPI {method} data 不是对象")
        return payload

    def _web_list(self, kb_numeric_id: str, cookie: str, cursor: str) -> dict:
        """网页列表接口（Cookie 模式）。返回 payload（code 字段在里层或顶层）。"""
        self._pause()
        try:
            resp = self._http.post(
                WEB_LIST,
                headers=self._web_headers(cookie),
                json={
                    "knowledge_base_id": kb_numeric_id,
                    "folder_id": "",
                    "cursor": cursor,
                    "limit": DEFAULT_PAGE_LIMIT,
                    "need_default_cover": True,
                    "sort_type": 9,
                },
            )
        except httpx.TransportError as exc:
            raise RuntimeError(f"ima 网页列表网络错误: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"ima 网页列表非 JSON HTTP {resp.status_code}") from None
        if not isinstance(data, dict):
            raise RuntimeError("ima 网页列表响应不是对象")
        code = data.get("code", data.get("retcode"))
        if code not in (0, None):
            raise RuntimeError(f"ima 网页列表失败 code={code} {data.get('msg') or data.get('errmsg')}")
        return data.get("data") if isinstance(data.get("data"), dict) else data

    def _list_openapi(self, kb_id: str) -> tuple[list[dict], str]:
        items: list[dict] = []
        cursor = ""
        numeric = ""
        for _ in range(DEFAULT_MAX_PAGES):
            payload = self._openapi_post(
                "get_knowledge_list",
                {"knowledge_base_id": kb_id, "cursor": cursor, "limit": DEFAULT_PAGE_LIMIT},
            )
            if not numeric:
                numeric = public_numeric_id(payload)
            batch = knowledge_items(payload)
            items.extend(batch)
            page = list_cursor(payload)
            if page["is_end"] or not page["next_cursor"]:
                break
            cursor = page["next_cursor"]
        return items, numeric

    def _list_web(self, kb_numeric_id: str, cookie: str) -> list[dict]:
        items: list[dict] = []
        cursor = ""
        for _ in range(DEFAULT_MAX_PAGES):
            payload = self._web_list(kb_numeric_id, cookie, cursor)
            batch = knowledge_items(payload)
            items.extend(batch)
            page = list_cursor(payload)
            if page["is_end"] or not page["next_cursor"]:
                break
            cursor = page["next_cursor"]
        return items

    def _full_text(self, media_id: str) -> str:
        """尝试经 get_media_info 拿原文；拿不到/失败返回空串，由调用方降级。"""
        try:
            payload = self._openapi_post("get_media_info", {"media_id": media_id})
        except RuntimeError as exc:
            # 订阅库原文被拦截（220030 等）：对抓取器不是致命错误，本轮降级为摘要
            logger.info("ima get_media_info 不可用 media=%s err=%s", media_id[:30], exc)
            return ""
        url, headers = media_info_target(payload)
        if not url:
            return ""
        try:
            resp = self._http.get(url, headers=headers, timeout=30)
        except httpx.TransportError as exc:
            logger.info("ima 原文下载网络错误 media=%s err=%s", media_id[:30], exc)
            return ""
        if resp.status_code != 200:
            return ""
        return _decode_text(resp.content)

    # ---- 主流程 ----

    def fetch(self, kol: dict) -> list[Post]:
        cookie = configured_ima_cookie(self.db)
        openapi = self._openapi_headers() is not None
        if not cookie and not openapi:
            raise RuntimeError("未配置 ima 凭证：请在后台填入 ima Cookie 或 OpenAPI 凭证")
        kb_ref = str(kol.get("external_id") or "").strip()
        if not kb_ref:
            raise RuntimeError(f"ima 知识库缺少 external_id kol={kol['name']}")
        items: list[dict] = []
        kb_numeric = ""
        if cookie:
            # 网页列表优先：订阅库元数据最全（时间/摘要/封面）；自有库可能被拒（code≠0）
            try:
                items = self._list_web(kb_ref, cookie)
                kb_numeric = kb_ref
            except RuntimeError as exc:
                logger.info("ima 网页列表不可用，回退 OpenAPI 列: %s", exc)
                items = []
        if not items and openapi:
            items, kb_numeric = self._list_openapi(kb_ref)
        if not items:
            raise RuntimeError(f"ima 知识库无可见条目 platform=ima kol={kol['name']} external_id={kb_ref[:20]}")
        items.sort(key=lambda it: item_time_ms(it) or 0, reverse=True)
        kb_url = f"https://ima.qq.com/wikis?knowledgeBaseId={kb_numeric or kb_ref}"
        posts = [
            self._build_post(kol, item, kb_url, openapi)
            for item in items
            if classify_item(item) != "folder"
        ]
        return posts

    def _build_post(self, kol: dict, item: dict, kb_url: str, can_full_text: bool) -> Post:
        media_id = str(item.get("media_id") or "")
        title = str(item.get("title") or "").strip() or "（无标题）"
        content = item_text(item)
        detail = item_detail(item)
        if (
            media_id
            and self.db is not None
            and can_full_text
            and int(item.get("media_type") or 0) in FULL_TEXT_TYPES
        ):
            try:
                known = self.db.post_exists(self.platform, media_id)
            except Exception:  # noqa: BLE001 - 查询失败不阻塞本轮抓取
                known = True
            if not known:
                full = self._full_text(media_id)
                if full:
                    content = full
                    detail["full_text"] = True
        return Post(
            platform=self.platform,
            kol_id=kol["id"],
            kol_name=kol["name"],
            external_id=media_id,
            title=title,
            content=content,
            url=kb_url,
            published_at=format_published_at(str(item_time_ms(item) or "")),
            post_type=classify_item(item),
            images=[item_cover(item)] if item_cover(item) else [],
            detail=detail,
        )