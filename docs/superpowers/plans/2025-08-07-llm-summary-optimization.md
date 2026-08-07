# LLM 摘要生成优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 `app/llm.py` 摘要生成——同批帖文跨用户去重（省钱降延迟）、输入质量（预算自适应 + 原帖优先）、输出 token 缩放、瞬时失败重试。

**Architecture:** `llm.py` 保持无状态纯函数，新增可选 `cache` 参数（成功结果写入、失败不写）；调度器 `flush_digest` 每次冲刷创建一个缓存 dict，跨订阅同一大V的用户复用同一份摘要。输入构造改为按帖数分配正文预算、给原帖/回复打标记并排序；`max_tokens` 随帖数缩放；瞬时错误（超时/429/5xx/空响应）重试一次，4xx 不重试。

**Tech Stack:** Python 3.14、httpx、pytest（MockTransport 注入 client，不触网）

**现状（改动前必须读）：**
- `app/llm.py` — `summarize_posts(posts, llm_config=None, client=None)`：每条帖文经 `digest_body(post, full=False)` 截到 120 字，总量上限 12000 字符，`max_tokens=800` 固定，无重试无缓存。失败返回 None，调用方降级。
- 调用方：`app/scheduler.py::notify_digest_subscribers`（每日精选，每 KOL 每用户一次）、`_send_dnd_summary`（免打扰汇总，每用户一次）。每日精选路径对同一 KOL 的同一批帖文，每个订阅用户各调一次 LLM——这是主要的重复浪费。
- 相关测试：`tests/test_llm.py`（现有 6 个用例，`test_custom_base_url_and_long_content_truncation` 断言 `content_len <= 12000`）、`tests/test_scheduler.py::test_digest_failure_alerts_admin`（flush_digest 模式参考）。

**文件结构：**
- 修改 `app/llm.py` — cache 参数、`_post_lines` 预算/标记、max_tokens 缩放、重试
- 修改 `app/scheduler.py` — `flush_digest` 建缓存 dict，`notify_digest_subscribers` 透传
- 测试 `tests/test_llm.py` — 各行为单测
- 测试 `tests/test_scheduler.py` — 同批帖文只调一次 LLM 的集成测试

---

### Task 1: 摘要结果缓存去重（同批帖文只调一次 LLM）

**Files:**
- Modify: `app/llm.py`（`summarize_posts` 加 `cache` 参数 + 新增 `summary_cache_key`）
- Modify: `app/scheduler.py:791`（`notify_digest_subscribers` 加 `summary_cache` 参数）、`app/scheduler.py:961`（`flush_digest` 建缓存并透传）
- Test: `tests/test_llm.py`、`tests/test_scheduler.py`

- [ ] **Step 1: 写失败测试（llm 层缓存语义）**

追加到 `tests/test_llm.py` 末尾：

```python
def test_cache_reuses_result_within_batch():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "要点"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = {}
    posts = [make_post()]
    assert summarize_posts(posts, make_config(), client=client, cache=cache) == "要点"
    assert summarize_posts(posts, make_config(), client=client, cache=cache) == "要点"
    assert calls["n"] == 1


def test_cache_does_not_store_failure():
    def handler(request):
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = {}
    assert summarize_posts([make_post()], make_config(), client=client, cache=cache) is None
    assert cache == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/kale/Documents/微信小程序大\ v\ 订阅/dav-subscription && .venv/bin/python -m pytest tests/test_llm.py::test_cache_reuses_result_within_batch tests/test_llm.py::test_cache_does_not_store_failure -q`
Expected: FAIL（`TypeError: summarize_posts() got an unexpected keyword argument 'cache'`）

- [ ] **Step 3: 写失败测试（调度器层：两用户同 KOL 只调一次）**

追加到 `tests/test_scheduler.py`（`test_digest_failure_alerts_admin` 之后，复用 `make_db`/`make_post`）：

```python
def test_digest_llm_summary_computed_once_for_multiple_subscribers(monkeypatch):
    db = make_db()
    kid = db.add_kol("xueqiu", "A", "1")
    uid1 = db.add_user("u1", "h", telegram_chat_id="111")
    uid2 = db.add_user("u2", "h")
    db.add_subscription(uid1, kid)
    db.add_subscription(uid2, kid)
    post = make_post(kid)
    db.insert_post("xueqiu", kid, post.external_id, post.title, post.content, post.url, post.published_at)

    calls = {"n": 0}

    def fake_summarize(posts, cfg, client=None, cache=None):
        calls["n"] += 1
        return "AI 要点"

    monkeypatch.setattr("app.llm.summarize_posts", fake_summarize)
    ncfg = SimpleNamespace(
        telegram=SimpleNamespace(bot_token="t", chat_id=""),
        feishu=SimpleNamespace(),
        wecom=SimpleNamespace(),
    )
    llm_cfg = SimpleNamespace(api_key="sk-test", api_base="https://api.deepseek.com", model="deepseek-chat")
    flush_digest(db, {kid: [post]}, [], ncfg, llm_config=llm_cfg)
    assert calls["n"] == 1
```

- [ ] **Step 4: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_scheduler.py::test_digest_llm_summary_computed_once_for_multiple_subscribers -q`
Expected: FAIL（`assert 2 == 1`）

- [ ] **Step 5: 实现 llm.py 缓存**

`app/llm.py` 改动：

```python
def summary_cache_key(posts, api_base: str, model: str) -> str:
    """摘要缓存键：平台+外部ID 有序拼接，同一批帖文（同配置）复用同一份摘要。"""
    ids = ",".join(f"{p.platform}:{p.external_id}" for p in posts)
    return f"{api_base}|{model}|{ids}"
```

`summarize_posts` 签名与关键点（其余请求代码不动）：

```python
def summarize_posts(posts, llm_config=None, client=None, cache=None) -> str | None:
    """生成摘要文本；未配置或失败返回 None（调用方降级为普通汇总）。

    cache：可选 dict，同一批帖文（同配置）只调一次 LLM；成功结果写入，失败不写。
    典型场景：合并摘要一次性推给多个订阅同一大V的用户。
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
```

- [ ] **Step 6: 实现 scheduler.py 透传**

`app/scheduler.py::notify_digest_subscribers` 签名加 `summary_cache: dict | None = None`（`llm_config` 之后），摘要调用处改为：

```python
                    summary = summarize_posts(matched, llm_cfg, cache=summary_cache)
```

`app/scheduler.py::flush_digest` 签名加 `llm_config=None` 之后保持；函数体内创建缓存并透传：

```python
    summary_cache: dict = {}
    for kol_id, posts in items:
        kol = db.get_kol(kol_id)
        if kol is None or not posts:
            continue
        notify_digest_subscribers(
            db, posts, kol, notifiers_config, notifiers, retry_queue, dnd_buffer, llm_config, summary_cache
        )
```

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm.py tests/test_scheduler.py -q`
Expected: 全 PASS（含新增 3 个用例；现有 172 个相关用例不回归）

- [ ] **Step 8: 提交**

```bash
git add app/llm.py app/scheduler.py tests/test_llm.py tests/test_scheduler.py
git commit -m "feat(llm): 同批帖文摘要跨用户去重，只调一次大模型"
```

---

### Task 2: 输入质量——正文预算自适应 + 原帖/回复标记与排序

**Files:**
- Modify: `app/llm.py`（`_post_lines` 预算与标记；`summarize_posts` 内排序）
- Test: `tests/test_llm.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_llm.py`：

```python
def test_summary_input_originals_first_with_markers():
    captured = {}

    def handler(request):
        captured["content"] = json.loads(request.read())["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reply = make_post(content="回复内容", external_id="r1")
    reply.post_type = "reply"
    original = make_post(content="原创内容", external_id="o1")
    summarize_posts([reply, original], make_config(), client=client)
    body = captured["content"]
    assert body.index("[原帖]") < body.index("[回复]")
    assert "原创内容" in body


def test_many_posts_per_line_budget_capped():
    captured = {}

    def handler(request):
        captured["content"] = json.loads(request.read())["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posts = [make_post(content="长" * 500, external_id=f"p{i}") for i in range(10)]
    summarize_posts(posts, make_config(), client=client)
    assert len(captured["content"]) <= 12000
    for line in captured["content"].splitlines():
        assert len(line) <= 400 + 64  # 每行正文 ≤ 400 + 标记/来源前缀
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm.py::test_summary_input_originals_first_with_markers tests/test_llm.py::test_many_posts_per_line_budget_capped -q`
Expected: FAIL（目前 120 字截断无标记、无排序）

- [ ] **Step 3: 实现**

`app/llm.py::_post_lines` 改为：

```python
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
```

`summarize_posts` 在 `content = ...` 之前加排序（原帖在前，回复沉底；稳定排序保持同类型内原顺序）：

```python
    posts = sorted(posts, key=lambda p: (getattr(p, "post_type", "") or "") == "reply")
    content = "\n".join(_post_lines(posts))
```

注意：排序在缓存键 `summary_cache_key` 之前发生，同一输入列表排序结果稳定，键不受影响。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm.py tests/test_scheduler.py -q`
Expected: 全 PASS（`test_custom_base_url_and_long_content_truncation` 仍满足 `<= 12000`）

- [ ] **Step 5: 提交**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat(llm): 摘要输入按帖数分配预算，原帖优先并标记原帖/回复"
```

---

### Task 3: 输出 max_tokens 随帖数缩放

**Files:**
- Modify: `app/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_llm.py`：

```python
def test_max_tokens_scales_with_post_count():
    captured = {}

    def handler(request):
        captured["max_tokens"] = json.loads(request.read())["max_tokens"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "摘要"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posts = [make_post(external_id=f"p{i}") for i in range(10)]
    summarize_posts(posts, make_config(), client=client)
    assert captured["max_tokens"] == 1400  # 200 + 120*10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm.py::test_max_tokens_scales_with_post_count -q`
Expected: FAIL（`assert 800 == 1400`）

- [ ] **Step 3: 实现**

`app/llm.py` 请求体里：

```python
                "temperature": 0.3,
                "max_tokens": min(2000, max(400, 200 + 120 * len(posts))),
```

（2 帖 → 440，10 帖 → 1400，≥15 帖封顶 2000。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm.py tests/test_scheduler.py -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat(llm): max_tokens 随帖数缩放，避免多帖摘要被截断"
```

---

### Task 4: 瞬时失败重试一次（超时/429/5xx/空响应），4xx 不重试

**Files:**
- Modify: `app/llm.py`（顶部加 `import time`；重写请求 try 块）
- Test: `tests/test_llm.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_llm.py`：

```python
def test_retry_transient_then_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": "要点"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) == "要点"
    assert calls["n"] == 2


def test_no_retry_on_auth_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid key"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert summarize_posts([make_post()], make_config(), client=client) is None
    assert calls["n"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm.py::test_retry_transient_then_success tests/test_llm.py::test_no_retry_on_auth_error -q`
Expected: FAIL（`assert 1 == 2` / `assert 2 == 1`）

- [ ] **Step 3: 实现**

`app/llm.py` 顶部 import 加 `import time`（放在 `import logging` 之后）。模块级新增：

```python
class _RetryableError(Exception):
    """瞬时错误（429/5xx/空响应），可重试一次。"""
```

`summarize_posts` 的 `try/except/finally` 整块替换为（重试循环放在外层 `try` 内部，`finally` 保证关连接）：

```python
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
                        "max_tokens": min(2000, max(400, 200 + 120 * len(posts))),
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
```

（外层 `try/finally` 包住重试循环，`finally` 只负责关连接；内层 `try/except` 处理每次尝试。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm.py tests/test_scheduler.py -q`
Expected: 全 PASS。注意 `test_http_error_returns_none`（500 响应）现在重试一次（2 次调用 + 2s sleep），断言仍成立；`test_cache_does_not_store_failure` 同理。

- [ ] **Step 5: 跑全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全 PASS（当前基线 333 个 + 新增用例）

- [ ] **Step 6: 提交**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat(llm): 瞬时错误重试一次并记录 token 用量，4xx 不重试"
```

---

## 明确不做（YAGNI）

- **跨批次持久化缓存**：缓冲里的帖文每次都是新帖，跨轮次命中率低；`flush_digest` 内一次性缓存已覆盖主要浪费。需要时再加 TTL 缓存。
- **按用户关键词个性化摘要**：会破坏同批复用（缓存键需含关键词）、增加成本与延迟。需要时单独设计。
- **流式 / JSON 结构化输出**：推送路径同步、单条文本直发聊天工具，收益低。
- **并发并行生成**：有缓存后每批帖文只有第一个用户付钱，串行足够。

## 风险与回滚

- 每步独立提交，`git revert <sha>` 即可回退单步。
- 缓存只在 `flush_digest` 作用域内，进程内无跨轮次状态，出错最多浪费一次调用，不会发陈旧摘要。
- 重试仅针对瞬时错误；4xx 立即降级，避免每次推送都打一次无效请求。
