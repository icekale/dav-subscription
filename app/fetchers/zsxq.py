"""知识星球抓取器（web API，Cookie 认证）。

对应规格：docs/specs/2026-08-20-zsxq-topic-attachment-design.md
与账号/路由规格（2026-08-19-zsxq-multi-account-design.md）配套：
Fetcher 依赖调用方（调度器）已按 membership 路由好「用哪个账号的 token」，
本类只负责「给定 token，拉一个星球的主题」。

账户 token 来源（优先级）：调度传入 override → db 记录 → 环境变量。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..avatar_cache import cache_avatar, cache_image_file, headers_for
from .base import Fetcher, Post, ThreadLocalClient, format_published_at, strip_html
from .zsxq_inspect import (
    classify_topic,
    collect_comments,
    collect_files,
    collect_images,
    comment_coverage,
    group_profile,
    topics_cursor,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.zsxq.com/v2"
DEFAULT_PAGE_LIMIT = 20
DEFAULT_MAX_PAGES = 3
DEFAULT_DELAY = 1.0
DEFAULT_FILE_DELAY = 1.0
DEFAULT_MAX_COMMENT_PAGES = 3
DEFAULT_COMMENT_BUDGET = 30
# 后台 Cookie 存储键（与雪球/ima 同一套 db settings）
ZSXQ_COOKIE_KEY = "zsxq_cookie"
ZSXQ_COOKIE_TIME_KEY = "zsxq_cookie_updated_at"
TOKEN_KEY = ZSXQ_COOKIE_KEY

# 1059 是随机化反爬过滤（同请求有时过有时拦），重试即可绕过；
# 20601/13607 附件下载量异常/日限，重试无效，交给调度退避
CODE_1059 = 1059
CODE_20601 = 20601
CODE_13607 = 13607
# 1059 重试：随机命中，重发同样请求通过率约 87%，重试几次几乎必过
_RETRY_1059 = 6


def configured_token(db=None, override: str | None = None) -> str:
    """后台设置的 Cookie 优先，其次环境变量。"""
    if override:
        return override.lstrip().split("=")[-1].strip()
    if db is not None:
        stored = db.get_setting(TOKEN_KEY)
        if stored:
            return stored.strip().split("=")[-1].strip()
    raw = os.environ.get("ZSXQ_ACCESS_TOKEN") or os.environ.get("ZSXQ_COOKIE", "")
    return raw.strip().split("=")[-1].strip()


def _delay(db, key: str, default: float) -> float:
    raw = ""
    if db is not None:
        raw = db.get_setting(key) or ""
    raw = raw or os.environ.get(key.upper(), "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _max_pages(db) -> int:
    raw = ""
    if db is not None:
        raw = db.get_setting("zsxq_max_pages") or ""
    raw = raw or os.environ.get("ZSXQ_MAX_PAGES", "")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PAGES


def prefetch_enabled(db) -> bool:
    return bool(db) and (db.get_setting("zsxq_prefetch_files") or "") == "1"


def _comments_enabled(db) -> bool:
    """是否抓取评论（默认开；后台可关）。"""
    if db is None:
        return True
    raw = (db.get_setting("zsxq_fetch_comments") or os.environ.get("ZSXQ_FETCH_COMMENTS", "")).strip()
    return raw != "0"


def _max_comment_pages(db) -> int:
    raw = ""
    if db is not None:
        raw = db.get_setting("zsxq_max_comment_pages") or ""
    raw = raw or os.environ.get("ZSXQ_MAX_COMMENT_PAGES", "")
    try:
        return max(1, min(10, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_COMMENT_PAGES


def _comment_budget(db) -> int:
    """每轮最多发起的评论请求数（保护限流；增量新帖一般十几个内）。"""
    raw = ""
    if db is not None:
        raw = db.get_setting("zsxq_comment_budget") or ""
    raw = raw or os.environ.get("ZSXQ_COMMENT_BUDGET", "")
    try:
        return max(1, min(200, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_COMMENT_BUDGET



def resolve_zsxq_profile(group_id: str, db=None, token: str | None = None, client=None) -> dict:
    """GET /v2/groups/{id} → {name, avatar_url, owner_name}；失败返回空 dict。"""
    token = configured_token(db, override=token)
    group_id = str(group_id or "").strip()
    if not token or not group_id:
        return {}
    owns = client is None
    client = client or httpx.Client(timeout=20)
    try:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://wx.zsxq.com",
            "Referer": "https://wx.zsxq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Cookie": f"zsxq_access_token={token}",
        }
        resp = client.get(f"{API_BASE}/groups/{group_id}", headers=headers)
        data = resp.json()
        if not isinstance(data, dict) or not data.get("succeeded"):
            return {}
        return group_profile((data.get("resp_data") or {}).get("group"))
    except Exception:
        return {}
    finally:
        if owns:
            client.close()


def resolve_zsxq_file_url(file_id: str, db=None, token: str | None = None, client=None) -> str:
    """GET /v2/files/{id}/download_url；失败返回空串。

    13607/20601 这类下载额度/日限错误抛 ZsxqError 便于上层展示真实原因；
    其余（1059 等）返回空串表示暂时取不到。
    """
    token = configured_token(db, override=token)
    file_id = str(file_id or "").strip()
    if not token or not file_id.isdigit():
        return ""
    owns = client is None
    client = client or httpx.Client(timeout=20)
    try:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://wx.zsxq.com",
            "Referer": "https://wx.zsxq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Cookie": f"zsxq_access_token={token}",
        }
        # 1059 是随机过滤：重发同样请求即可；13607/20601 是真额度/日限，直接抛错
        for attempt in range(_RETRY_1059):
            resp = client.get(f"{API_BASE}/files/{file_id}/download_url", headers=headers)
            data = resp.json()
            if isinstance(data, dict) and data.get("succeeded"):
                return str((data.get("resp_data") or {}).get("download_url") or "")
            if not isinstance(data, dict):
                continue
            code = data.get("code")
            if code in (CODE_13607, CODE_20601):
                raise ZsxqError(
                    f"知识星球下载受限 code={code} {data.get('info')}", code=code
                )
            if code != CODE_1059 or attempt == _RETRY_1059 - 1:
                return ""
        return ""
    except ZsxqError:
        raise
    except Exception:
        return ""
    finally:
        if owns:
            client.close()


def _ext_for(name: str, content_type: str) -> str:
    n = (name or "").rsplit(".", 1)[-1].lower()
    if len(n) <= 5 and n.isalnum():
        return n
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    }.get(ct, "bin")


def cache_zsxq_file(db, file_id: str, name: str, url: str, client=None) -> str:
    """把附件下载到 data/zsxq_files/{file_id}.{ext} 并返回本地 URL。

    已存在则直接返回本地 URL，不重复下载。下载失败或内存库返回空串（调用方保留远端 URL）。
    """
    file_id = str(file_id or "").strip()
    db_path = str(getattr(db, "path", "") or "")
    if not file_id or not db_path or db_path == ":memory:":
        return ""
    dest = Path(db_path).parent / "zsxq_files"
    dest.mkdir(parents=True, exist_ok=True)
    existing = sorted(dest.glob(f"{file_id}.*"))
    if existing:
        return f"/zsxq-files/{existing[0].name}"
    if not url:
        return ""
    owns = client is None
    client = client or httpx.Client(timeout=90, follow_redirects=True, headers=headers_for(url))
    try:
        resp = client.get(url, follow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return ""
        ext = _ext_for(name, resp.headers.get("content-type", ""))
        target = dest / f"{file_id}.{ext}"
        target.write_bytes(resp.content)
        return f"/zsxq-files/{target.name}"
    except Exception:
        return ""
    finally:
        if owns:
            client.close()


_FILE_NAME_RE = re.compile(r"^(\d+)\.[A-Za-z0-9]{1,5}$")


def _files_dir(db) -> Path | None:
    db_path = str(getattr(db, "path", "") or "")
    if not db_path or db_path == ":memory:":
        return None
    return Path(db_path).parent / "zsxq_files"


def zsxq_cache_stats(db) -> dict:
    dest = _files_dir(db)
    if dest is None or not dest.is_dir():
        return {"files": 0, "bytes": 0}
    files = [p for p in dest.iterdir() if p.is_file()]
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def purge_unreferenced_zsxq_files(db) -> dict:
    dest = _files_dir(db)
    if dest is None or not dest.is_dir():
        return {"deleted": 0, **zsxq_cache_stats(db)}
    keep: set[str] = set()
    for row in db._rows("SELECT detail FROM posts WHERE platform='zsxq' AND detail LIKE '%file_id%'"):
        raw = row.get("detail") or ""
        try:
            detail = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(detail, dict):
            continue
        for item in detail.get("files") or []:
            if isinstance(item, dict) and item.get("file_id"):
                keep.add(str(item["file_id"]))
    deleted = 0
    for path in list(dest.iterdir()):
        if not path.is_file():
            continue
        matched = _FILE_NAME_RE.match(path.name)
        if not matched or matched.group(1) in keep:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted += 1
    return {"deleted": deleted, **zsxq_cache_stats(db)}


class ZsxqError(RuntimeError):
    """知识星球请求失败；携带服务端错误码（1059/20601 等），供调度退避。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def _topic_text(topic: dict) -> tuple[str, str, str]:
    """从主题各区块提取 (title, content, post_type)。剔除内嵌 <e .../> 标签只留可见文本。"""
    block_keys = [k for k in ("talk", "question", "answer", "task", "solution") if isinstance(topic.get(k), dict)]
    title = str(topic.get("title") or "").strip()
    pieces: list[str] = []
    for key in block_keys:
        blk = topic[key] or {}
        if isinstance(blk.get("text"), str) and blk["text"].strip():
            pieces.append(blk["text"])
        if isinstance(blk.get("article"), dict) and isinstance(blk["article"].get("title"), str):
            if not title:
                title = blk["article"]["title"].strip()
        if key == "question":
            # q&a 正文优先用回答内容
            pass
    content = "\n\n".join(pieces).strip()
    # 清掉 <e .../> 内嵌标签（话题/链接占位），保留可见文本
    content = _strip_embedded_tags(content)
    return title, content, classify_topic(topic)


def _strip_embedded_tags(text: str) -> str:
    """移除 <e type="..." ... />（话题、web 链接占位）但保留括号里可能有的可见锚文本。"""
    import re

    def repl(m):
        inner = m.group(1)
        # 尽量保留 title 属性里的可见文字
        tm = re.search(r'title="([^"]*)"', inner)
        if tm:
            from urllib.parse import unquote
            return unquote(tm.group(1))
        return ""
    return re.sub(r"<e\b([^>]*?)/?>", repl, text)


class ZsxqFetcher(Fetcher):
    platform = "zsxq"

    def __init__(self, source_config=None, db=None, client=None):
        super().__init__(source_config)
        self.db = db
        # ThreadLocalClient 适配调度器的代理/客户端注入管线
        def _make_client():
            from ..proxy import acquire_client_proxy, attach_proxy

            proxy, pid = acquire_client_proxy(self.db, "zsxq")
            c = httpx.Client(timeout=30, proxy=proxy)
            attach_proxy(c, pid)
            return c

        self._http = ThreadLocalClient(_make_client, injected=client)
        # file_id → download_url 的会话内缓存，避免重复请求
        self._file_cache: dict[str, str] = {}

    @property
    def client(self):
        return self._http.get()

    @client.setter
    def client(self, value):
        self._http.set(value)

    # ---- 请求 ----

    def _pause(self, key: str = "zsxq_fetch_delay_seconds", default: float = DEFAULT_DELAY) -> None:
        time.sleep(_delay(self.db, key, default))

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://wx.zsxq.com",
            "Referer": "https://wx.zsxq.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Cookie": f"zsxq_access_token={token}",
        }

    def _get(self, token: str, path: str, params: dict | None = None,
             delay_key: str = "zsxq_fetch_delay_seconds") -> dict:
        self._pause(delay_key)
        url = f"{API_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        last = None
        for attempt in range(_RETRY_1059):
            try:
                resp = self.client.get(url, headers=self._headers(token))
            except httpx.TransportError as exc:
                raise RuntimeError(f"知识星球网络错误 {path}: {exc}") from exc
            try:
                data = resp.json()
            except ValueError:
                raise RuntimeError(f"知识星球非 JSON HTTP {resp.status_code} path={path}") from None
            if not isinstance(data, dict):
                raise RuntimeError("知识星球响应不是对象")
            if data.get("succeeded"):
                return data.get("resp_data") or {}
            code = data.get("code")
            # 1059 是随机过滤：重发同样请求即可；其余（20601 等）直接抛错由调度退避
            if code != CODE_1059 or attempt == _RETRY_1059 - 1:
                raise ZsxqError(
                    f"知识星球失败 code={code} {data.get('info') or data.get('error')} path={path}",
                    code=code,
                )
            last = code
            logger.info("知识星球 1059 随机过滤，重试 %s/%s path=%s", attempt + 1, _RETRY_1059, path)
            self._pause(delay_key)
        raise ZsxqError("知识星球 1059 重试耗尽", code=1059)

    def _download_url(self, token: str, file_id: str) -> str:
        if file_id in self._file_cache:
            return self._file_cache[file_id]
        payload = self._get(token, f"/files/{file_id}/download_url", delay_key="zsxq_file_delay_seconds")
        url = str((payload or {}).get("download_url") or "")
        self._file_cache[file_id] = url
        return url

    def _fetch_comments(self, token: str, topic_id: str, comments_count: int) -> list[dict]:
        """分页拉某主题全部已存评论（有界，默认最多 3 页）。"""
        comments: list[dict] = []
        end_time = None
        max_pages = _max_comment_pages(self.db)
        want = min(int(comments_count or 0), 500)
        pages = 0
        while pages < max_pages and len(comments) < want:
            params = {"count": DEFAULT_PAGE_LIMIT}
            if end_time:
                params["end_time"] = end_time
            payload = self._get(
                token, f"/topics/{topic_id}/comments", params, delay_key="zsxq_fetch_delay_seconds"
            )
            comments.extend(collect_comments(payload))
            cov = comment_coverage(comments_count, payload)
            if not cov["has_more"] or not cov["next_end_time"]:
                break
            end_time = cov["next_end_time"]
            pages += 1
        # 按 comment_id 去重
        seen: set[str] = set()
        uniq: list[dict] = []
        for c in comments:
            if c["comment_id"] and c["comment_id"] not in seen:
                seen.add(c["comment_id"])
                uniq.append(c)
        return uniq

    def _comments_for(self, topic_id: str, topic: dict, token: str) -> list[dict] | None:
        """返回该主题应入库的评论列表；None 表示不抓取、detail 不写 comments。

        已存过评论的（含旧帖升级后）直接沿用，刷新签名 URL 时不丢；
        新主题按 comments_count 决定是否抓取，并受单轮预算保护。
        """
        if self.db is None:
            return None
        get_detail = getattr(self.db, "get_post_detail", None)
        stored = get_detail("zsxq", topic_id).get("comments") if get_detail else None
        if stored is not None:
            return stored
        count = int(topic.get("comments_count") or 0)
        if not _comments_enabled(self.db) or count <= 0:
            return None
        if getattr(self, "_comments_budget", 0) <= 0:
            return None
        self._comments_budget -= 1
        try:
            return self._fetch_comments(token, topic_id, count)
        except (RuntimeError, ZsxqError) as exc:
            logger.info("知识星球评论抓取失败 topic=%s err=%s", topic_id, exc)
            return None


    # ---- 主流程 ----

    def fetch(self, kol: dict, token: str | None = None) -> list[Post]:
        token = configured_token(self.db, override=token)
        if not token:
            raise RuntimeError("未配置知识星球登录态：请在后台填入 zsxq Cookie")
        group_id = str(kol.get("external_id") or "").strip()
        if not group_id:
            raise RuntimeError(f"知识星球缺少 external_id kol={kol['name']}")
        self._comments_budget = _comment_budget(self.db)
        topics: list[dict] = []
        end_time = None
        max_pages = _max_pages(self.db)
        for _ in range(max_pages):
            params = {"scope": "all", "count": DEFAULT_PAGE_LIMIT}
            if end_time:
                params["end_time"] = end_time
            page = self._get(token, f"/groups/{group_id}/topics", params)
            batch = page.get("topics") or []
            topics.extend(batch)
            cursor = topics_cursor(page)
            if not cursor["has_more"] or not cursor["next_end_time"]:
                break
            end_time = cursor["next_end_time"]
        group_url = f"https://wx.zsxq.com/group/{group_id}"
        posts = [self._build_post(kol, group_url, t, token) for t in topics]
        self._sync_group_profile(kol, topics, token)
        return posts

    def _build_post(self, kol: dict, group_url: str, topic: dict, token: str) -> Post:
        topic_id = str(topic.get("topic_id") or "")
        title, content, kind = _topic_text(topic)
        # 长文（article）或正文缺失时补详情
        article = (topic.get("talk") or {}).get("article")
        if (not content) or article:
            try:
                detail = self._get(token, f"/topics/{topic_id}")
                raw = detail.get("topic") or detail
                d_title, d_content, d_kind = _topic_text(raw)
                title = title or d_title
                if d_content:
                    content = d_content
                kind = d_kind
                topic = raw
            except (RuntimeError, ZsxqError) as exc:
                logger.info("知识星球详情补全失败 topic=%s err=%s", topic_id, exc)
        images = [
            cache_image_file(self.db, i["url"], "zsxq_images", "/zsxq-images")
            if self.db is not None else i["url"]
            for i in collect_images(topic)
        ]
        files_meta = collect_files(topic)
        files = []
        prefetch = prefetch_enabled(self.db)
        for fm in files_meta:
            local = cache_zsxq_file(self.db, fm["file_id"], fm["name"], "")
            if local:
                files.append({**fm, "url": local})
                continue
            try:
                url = self._download_url(token, fm["file_id"])
            except (RuntimeError, ZsxqError) as exc:
                logger.info("知识星球附件 URL 解析失败 file=%s err=%s", fm["file_id"], exc)
                url = ""
            if url and prefetch:
                cache_zsxq_file(
                    self.db, fm["file_id"], fm["name"], url, client=self.client
                )
            files.append({**fm, "url": url})
        # 过滤空 content（列表里一些无声主题）
        if not content and not images and not files:
            content = title or "（无声主题）"
        detail = {"files": files, "raw": topic}
        comments = self._comments_for(topic_id, topic, token)
        if comments is not None:
            detail["comments"] = comments
            detail["comments_count"] = len(comments)
        return Post(
            platform=self.platform,
            kol_id=kol["id"],
            kol_name=kol["name"],
            external_id=topic_id,
            title=title or "（无标题）",
            content=content,
            url=f"{group_url}/{topic_id}",
            published_at=format_published_at(str(topic.get("create_time") or "")),
            post_type=kind,
            category="星球",
            images=images,
            detail=detail,
        )

    def _sync_group_profile(self, kol: dict, topics: list[dict], token: str) -> None:
        if self.db is None or not kol.get("id"):
            return
        profile = resolve_zsxq_profile(
            str(kol.get("external_id") or ""), db=self.db, token=token, client=self.client
        )
        if not profile.get("name") and not profile.get("avatar_url"):
            group = next((t.get("group") for t in topics if isinstance(t.get("group"), dict)), None)
            profile = group_profile(group)
        name = profile.get("name") or ""
        if name and name != kol.get("name"):
            self.db.update_kol(kol["id"], name=name)
            kol["name"] = name
        avatar = profile.get("avatar_url") or ""
        if avatar and avatar != (self.db.get_kol(kol["id"]) or {}).get("avatar_url"):
            self.db.update_kol_avatar(kol["id"], cache_avatar(self.db, kol["id"], avatar))

