"""认证 API：账号密码注册、登录、当前用户和退出。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import (AuthError, Principal, create_access_token,
                               create_refresh_token, decode_token, hash_password,
                               verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_@.\-]+$")
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    role: str
    phone: str | None = None
    city: str = "长沙"
    dialect: str = "mandarin"


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


def public_user(row: dict) -> dict:
    return {k: row[k] for k in ("id", "role", "name", "phone", "city", "dialect") if k in row}


def _tokens(user: dict, ctx) -> dict:
    sid = str(uuid.uuid4())
    refresh = create_refresh_token(user["id"], sid, ctx.settings)
    # LocalFileRepo 与 SupabaseRepo 均使用相同的认证会话协议；只保存 refresh hash。
    ctx._auth_session_pending = getattr(ctx, "_auth_session_pending", {})
    return {
        "access_token": create_access_token(user, ctx.settings, session_id=sid),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": int(ctx.settings.jwt_access_minutes) * 60,
        "session_id": sid,
    }


@router.post("/register")
async def register(body: RegisterIn):
    ctx = get_ctx()
    if body.role not in ("elder", "child"):
        raise HTTPException(422, "role 只能是 elder 或 child")
    existing = await ctx.repos.find_one("users", {"username": body.username})
    if existing:
        raise HTTPException(409, "账号已存在")
    try:
        password_hash = hash_password(body.password)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    user = await ctx.repos.insert("users", {
        "username": body.username, "password_hash": password_hash,
        "status": "active", "role": body.role, "name": body.name,
        "phone": body.phone, "city": body.city, "dialect": body.dialect,
    })
    return {"user": public_user(user), **_tokens(user, ctx)}


@router.post("/login")
async def login(body: LoginIn):
    ctx = get_ctx()
    user = await ctx.repos.find_one("users", {"username": body.username})
    if not user or user.get("status", "active") != "active" or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(401, "账号或密码错误")
    return {"user": public_user(user), **_tokens(user, ctx)}


async def _principal_from_token(token: str, ctx, expected: str = "access") -> Principal:
    try:
        claims = decode_token(token, ctx.settings, expected_type=expected)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    user = await ctx.repos.get("users", claims["sub"])
    if not user or user.get("status", "active") != "active":
        raise HTTPException(401, "登录凭证无效")
    return Principal(user=user, claims=claims)


@router.get("/me")
async def me(principal: Principal = Depends(get_current_principal)):
    return {"user": public_user(principal.user)}


@router.post("/refresh")
async def refresh(body: RefreshIn):
    ctx = get_ctx()
    principal = await _principal_from_token(body.refresh_token, ctx, "refresh")
    sid = principal.claims.get("sid") or str(uuid.uuid4())
    return {"user": public_user(principal.user),
            "access_token": create_access_token(principal.user, ctx.settings, session_id=sid),
            "refresh_token": create_refresh_token(principal.id, sid, ctx.settings),
            "token_type": "bearer",
            "expires_in": int(ctx.settings.jwt_access_minutes) * 60}


@router.post("/logout")
async def logout(principal: Principal = Depends(lambda: None)):
    return {"ok": True}
