"""FastAPI 依赖：全局 AppContext 与 Bearer JWT 认证注入。"""
from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Callable

from fastapi import Depends, Header, HTTPException

from app.auth.security import AuthError, Principal, decode_token
from app.bootstrap import build_context
from app.core.context import AppContext


@lru_cache(maxsize=1)
def get_app_context() -> AppContext:
    return build_context()


def get_ctx() -> AppContext:
    return get_app_context()


async def get_current_principal(
    authorization: str | None = Header(None, alias="Authorization"),
    ctx: AppContext = Depends(get_ctx),
) -> Principal:
    if not authorization:
        raise HTTPException(401, "缺少登录认证 Header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "无效的认证凭证格式")
    token = authorization[7:].strip()
    try:
        claims = decode_token(token, ctx.settings, expected_type="access")
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    user = await ctx.repos.get("users", claims["sub"])
    if not user or user.get("status", "active") != "active":
        raise HTTPException(401, "用户不存在或已被禁用")
    return Principal(user=user, claims=claims)


def require_role(role: str) -> Callable:
    async def _checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.user.get("role") != role:
            raise HTTPException(403, f"该操作仅限 {role} 角色访问")
        return principal
    return _checker


def valid_session_id(session_id: str | None) -> str:
    """会话 id 必须是合法 uuid，否则当作"会话不存在"。

    ``session_id: str`` 挡不住空串和 ``abc`` 这类值，它们会被原样拼进
    ``sessions?id=eq.`` 交给 Postgres，uuid 列直接抛 22P02，接口 500。
    前端 storage 里存的 id 是可能被清成空串的，这不是服务器错误，
    是"这个会话找不到" —— 所以在进库前就拦掉，给 404。

    放在 deps 里是因为凡是接收 session_id 的路由都得过这一关（/chat/history、
    /sessions/{id}、/sessions/{id}/events），一处漏掉就又是一个 500。
    """
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(404, "会话不存在")
    try:
        uuid.UUID(sid)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, "会话不存在") from None
    return sid


async def get_optional_principal(
    authorization: str | None = Header(None, alias="Authorization"),
    ctx: AppContext = Depends(get_ctx),
) -> Principal | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        claims = decode_token(authorization[7:].strip(), ctx.settings, expected_type="access")
        user = await ctx.repos.get("users", claims["sub"])
        if user and user.get("status", "active") == "active":
            return Principal(user=user, claims=claims)
    except Exception:
        return None
    return None
