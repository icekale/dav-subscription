"""REST API：KOL 增删改查、帖子列表、推送记录。"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from .db import ALLOWED_PLATFORMS, DB


class KolIn(BaseModel):
    platform: str
    name: str
    external_id: str
    category_id: int | None = None


class KolUpdate(BaseModel):
    name: str | None = None
    external_id: str | None = None
    enabled: bool | None = None
    category_id: int | None = None


class CategoryIn(BaseModel):
    name: str


def make_auth_dependency(password: str):
    """密码非空时启用 Basic Auth，否则返回空依赖列表。"""
    if not password:
        return []
    basic = HTTPBasic(auto_error=False)

    def check(credentials: HTTPBasicCredentials | None = Depends(basic)):
        if credentials is None or not secrets.compare_digest(credentials.password, password):
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
        return credentials

    return [Depends(check)]


def create_api_router(db: DB, password: str = "") -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=make_auth_dependency(password))

    @router.get("/kols")
    def list_kols(platform: str | None = None, category_id: int | None = None):
        return db.list_kols(platform, category_id)

    @router.post("/kols")
    def add_kol(body: KolIn):
        if body.platform not in ALLOWED_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {body.platform}")
        if not body.name.strip() or not body.external_id.strip():
            raise HTTPException(status_code=400, detail="昵称与外部ID不能为空")
        if body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        kid = db.add_kol(
            body.platform,
            body.name.strip(),
            body.external_id.strip(),
            category_id=body.category_id,
        )
        return db.get_kol(kid)

    @router.put("/kols/{kol_id}")
    def update_kol(kol_id: int, body: KolUpdate):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        if "category_id" in body.model_fields_set and body.category_id is not None:
            if db.get_category(body.category_id) is None:
                raise HTTPException(status_code=400, detail="分类不存在")
        db.update_kol(
            kol_id,
            name=body.name.strip() if body.name is not None else None,
            external_id=body.external_id.strip() if body.external_id is not None else None,
            enabled=body.enabled,
            category_id=body.category_id if "category_id" in body.model_fields_set else None,
        )
        return db.get_kol(kol_id)

    @router.get("/categories")
    def list_categories():
        return db.list_categories()

    @router.post("/categories")
    def add_category(body: CategoryIn):
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            cid = db.add_category(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return db.get_category(cid)

    @router.put("/categories/{category_id}")
    def rename_category(category_id: int, body: CategoryIn):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名不能为空")
        try:
            db.rename_category(category_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return db.get_category(category_id)

    @router.delete("/categories/{category_id}")
    def delete_category(category_id: int):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        db.delete_category(category_id)
        return {"ok": True}

    @router.delete("/kols/{kol_id}")
    def delete_kol(kol_id: int):
        if db.get_kol(kol_id) is None:
            raise HTTPException(status_code=404, detail="KOL 不存在")
        db.delete_kol(kol_id)
        return {"ok": True}

    @router.get("/posts")
    def list_posts(limit: int = 100, platform: str | None = None, kol_id: int | None = None):
        return db.list_posts(limit=min(limit, 500), platform=platform, kol_id=kol_id)

    @router.get("/push-logs")
    def list_push_logs(limit: int = 100):
        return db.list_push_logs(limit=min(limit, 500))

    return router
