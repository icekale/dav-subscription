"""微信小程序登录：code2session 换取 openid。"""
from __future__ import annotations

import httpx


def code2session(code: str, app_id: str, app_secret: str, client: httpx.Client | None = None) -> dict:
    """用 wx.login 的 code 换取 openid/session_key。"""
    client = client or httpx.Client(timeout=15)
    resp = client.get(
        "https://api.weixin.qq.com/sns/jscode2session",
        params={
            "appid": app_id,
            "secret": app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode"):
        raise RuntimeError(f"微信登录失败: {data.get('errmsg', data)}")
    if not data.get("openid"):
        raise RuntimeError("微信登录失败: 未返回 openid")
    return data
