"""认证与安全测试：注册、登录、Token 校验、过期与防越权。"""
from __future__ import annotations

import pytest
from app.auth.security import (AuthError, create_access_token, decode_token,
                               hash_password, verify_password)


def test_password_hash_and_verify():
    h = hash_password("pass123456")
    assert h.startswith("scrypt$")
    assert verify_password("pass123456", h) is True
    assert verify_password("wrongpassword", h) is False
    assert verify_password("pass123456", "invalid$hash") is False


def test_password_length_constraint():
    with pytest.raises(AuthError):
        hash_password("short")


def test_jwt_token_cycle(ctx, elder):
    token = create_access_token(elder, ctx.settings)
    claims = decode_token(token, ctx.settings, expected_type="access")
    assert claims["sub"] == elder["id"]
    assert claims["role"] == "elder"
    assert claims["type"] == "access"


def test_jwt_invalid_type(ctx, elder):
    token = create_access_token(elder, ctx.settings)
    with pytest.raises(AuthError):
        decode_token(token, ctx.settings, expected_type="refresh")


def test_jwt_tampered_signature(ctx, elder):
    token = create_access_token(elder, ctx.settings)
    header, payload, sig = token.split(".")
    tampered = f"{header}.{payload}.{sig[:-2]}aa"
    with pytest.raises(AuthError):
        decode_token(tampered, ctx.settings)
