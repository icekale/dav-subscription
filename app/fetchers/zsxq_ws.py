"""知识星球 App 原生 WebSocket 协议层（对应逆向 network/okhttp/ws/d.java+e.java+WSResp.java，G5）。

已确认（都由 @SerializedName 钉死）：
- 握手头仅 3 个：User-Agent / X-Request-Id / X-Version（鉴权在 wsAddress URL 本身，不带 Cookie）
- 发送请求：{"req_data":{"dynamics":{"begin_time":T},"groups":[{"group_id":G,"begin_time":T}],
  "in_app_notifications":{"begin_time":T}}}
- 响应信封 WSResp：{succeeded, code, info, resp_data:{resp_id, dynamics, in_app_notifications,
  groups[{group_id, joined/updated/exited}], command:{text,action}, im_messages}}
- UTCTime 线上表示：ISO 串 "2026-08-20T22:12:03.000+0800"（无冒号的 +0800）
- command.action == "logout" 即服务端登出

connect() 需真实 wsAddress（登录后 Session.getWsAddress()）。首次对真实服务前，用
`utc_str` 输出比对捕获确认 T 格式；如报 "无效的begin_time" 再调。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# App 头部（读通道与 WS 握手共用，与 fetcher._api_headers 的 app 分支一致）
APP_VERSION = "5.27.3"
APP_API_VERSION = "2.81.0"
APP_UA = f"xiaomiquan/{APP_VERSION} Android/Phone/16 OnePlus_PJD110"
_CN = timezone(timedelta(hours=8))


def utc_str(ts_ms: int) -> str:
    """毫秒时间戳 → ISO 串(东八) "2026-08-20T22:12:03.000+0800"。"""
    return datetime.fromtimestamp(ts_ms / 1000.0, _CN).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0800"


def _ts(obj) -> str | None:
    try:
        t = obj["occur_time"]
    except (TypeError, KeyError):
        return None
    return t if isinstance(t, str) else None


def build_request(begin_time_ms: int, groups: list[tuple[int, int]], in_app_time_ms: int) -> dict:
    """构造发送信封。groups=[(group_id:int, begin_ms:int)]。"""
    return {
        "req_data": {
            "dynamics": {"begin_time": utc_str(begin_time_ms)},
            "groups": [
                {"group_id": gid, "begin_time": utc_str(bt)}
                for gid, bt in groups
            ],
            "in_app_notifications": {"begin_time": utc_str(in_app_time_ms)},
        }
    }


def parse_resp(raw: str) -> dict:
    """解析 WSResp 为一组归一化事件。保证顺序稳定、可测。

    返回 {succeeded, code, info, resp_id, events:[(kind, detail), ...]}
    kind ∈ dynamics / in_app / group / logout / im。
    """
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {"succeeded": False, "events": []}
    events: list[tuple[str, dict]] = []
    rd = data.get("resp_data") or {}
    if data.get("succeeded") and isinstance(rd, dict):
        if rd.get("resp_id"):
            events.append(("resp_id", rd["resp_id"]))
        dyn = rd.get("dynamics") or {}
        if _ts(dyn.get("updated")):
            events.append(("dynamics", {"occur_time": _ts(dyn["updated"])}))
        inapp = rd.get("in_app_notifications") or {}
        if _ts(inapp.get("updated")):
            events.append(("in_app", {"occur_time": _ts(inapp["updated"])}))
        for g in rd.get("groups") or []:
            gid = g.get("group_id")
            if g.get("joined") and _ts(g["joined"]):
                events.append(("group", {"group_id": gid, "action": "joined", "occur_time": _ts(g["joined"])}))
            elif g.get("updated"):
                events.append(("group", {"group_id": gid, "action": "updated"}))
            elif g.get("exited"):
                exit_d = g["exited"]
                events.append(("group", {
                    "group_id": gid, "action": "exited",
                    "removed": bool(exit_d.get("removed")),
                    "occur_time": _ts(exit_d),
                }))
        cmd = rd.get("command") or {}
        if cmd.get("action") == "logout":
            events.append(("logout", {"text": cmd.get("text") or ""}))
        if rd.get("im_messages"):
            events.append(("im", {"messages": rd["im_messages"]}))
    return {
        "succeeded": bool(data.get("succeeded")),
        "code": data.get("code"),
        "info": data.get("info"),
        "events": events,
    }


def ws_handshake_headers() -> dict[str, str]:
    return {
        "User-Agent": APP_UA,
        "X-Request-Id": str(uuid.uuid4()),
        "X-Version": APP_API_VERSION,
    }


class WsClient:
    """App 原生 WS 长连接：握手→发信→接收→去重分发。默认不自动重连。

    用法（需真实 wsAddress，loginId 从 Session 取）：
        async with WsClient(ws_url, group_ids=[...], on_event=print) as c:
            await c.run()
    """

    def __init__(self, ws_url: str, group_ids: list[int], on_event=None, heartbeat_s: int = 30):
        self.ws_url = ws_url
        self.group_ids = group_ids
        self.on_event = on_event or (lambda *_: None)
        self.heartbeat_s = heartbeat_s
        self._seen: set[str] = set()

    async def __aenter__(self):
        import websockets
        self._ws = await websockets.connect(self.ws_url, additional_headers=ws_handshake_headers())
        return self

    async def __aexit__(self, *exc):
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as e:  # noqa: BLE001 - 关连接失败无需上抛
                logger.debug("ws close error: %s", e)

    async def send_request(self, now_ms: int | None = None) -> None:
        now_ms = now_ms or int(__import__("time").time() * 1000)
        groups = [(g, now_ms) for g in self.group_ids]
        await self._ws.send(json.dumps(build_request(now_ms, groups, now_ms), ensure_ascii=False))

    async def run(self, since_ms: int | None = None) -> None:
        """连接成功即发首请求，随后循环收帧 + 心跳 ping。"""
        import asyncio

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(self.heartbeat_s)
                try:
                    await self._ws.ping()
                except Exception:
                    return

        hb = asyncio.create_task(_heartbeat())
        try:
            await self.send_request(since_ms)
            async for raw in self._ws:
                parsed = parse_resp(raw)
                events = parsed["events"]
                dup = False
                for kind, detail in events:
                    if kind == "resp_id":
                        if detail in self._seen:
                            dup = True
                        else:
                            self._seen.add(detail)
                if not dup:
                    self.on_event(parsed)
        finally:
            hb.cancel()


if __name__ == "__main__":
    import argparse
    import asyncio

    p = argparse.ArgumentParser(description="知识星球 App 原生 WS 长连客户端（G5）")
    p.add_argument("--url", required=True, help="wsAddress（登录后 Session.getWsAddress() 的值，如 wss://...）")
    p.add_argument("--group", type=int, action="append", default=[], help="监听星球 group_id（可多次）")
    p.add_argument("--timeout", type=int, default=30, help="运行秒数后退出（默认 30）")
    args = p.parse_args()

    async def _main() -> None:
        import time

        groups = args.group or [0]
        async with WsClient(args.url, groups, on_event=lambda ev: logger.info("ws event: %s", ev)) as c:
            await c.send_request(int(time.time() * 1000))
            print("connected, waiting for events...", flush=True)
            try:
                await asyncio.wait_for(c.run(), timeout=args.timeout)
            except TimeoutError:
                print("timeout reached", flush=True)

    asyncio.run(_main())


def _self_test() -> None:
    now = int(__import__("time").time() * 1000)
    req = build_request(now, [(28888112822211, now)], now)
    assert set(req["req_data"]) == {"dynamics", "groups", "in_app_notifications"}
    assert req["req_data"]["groups"][0]["group_id"] == 28888112822211
    assert "+0800" in req["req_data"]["dynamics"]["begin_time"]
    # 解析样例（覆盖全部事件类型）
    sample = json.dumps({
        "succeeded": True, "code": 0, "info": "", "resp_data": {
            "resp_id": "abc",
            "dynamics": {"updated": {"occur_time": "2026-08-20T22:12:03.000+0800"}},
            "in_app_notifications": {"updated": {"occur_time": "2026-08-20T22:12:04.000+0800"}},
            "groups": [
                {"group_id": 1, "joined": {"occur_time": "2026-08-20T22:12:05.000+0800"}},
                {"group_id": 2, "updated": {"need_submit_recordations": True,
                                            "occur_time": "2026-08-20T22:12:06.000+0800"}},
                {"group_id": 3, "exited": {"removed": True, "occur_time": "2026-08-20T22:12:07.000+0800"}},
            ],
            "command": {"text": "bye", "action": "logout"},
            "im_messages": [{"conversation_id": 9, "updated_time": "x"}],
        }
    })
    r = parse_resp(sample)
    assert r["succeeded"] and r["events"][0] == ("resp_id", "abc")
    kinds = [k for k, _ in r["events"]]
    assert "dynamics" in kinds and "in_app" in kinds and "logout" in kinds and "im" in kinds
    assert sum(1 for k, d in r["events"] if k == "group") == 3
    assert utc_str(1764252723000) == "2025-11-27T22:12:03.000+0800"
    print("zsxq_ws self-test OK")


if __name__ == "__main__":
    _self_test()
