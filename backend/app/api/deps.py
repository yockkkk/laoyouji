"""FastAPI 依赖：全局 AppContext 与 Bearer JWT 认证注入。"""
from __future__ import annotations

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
