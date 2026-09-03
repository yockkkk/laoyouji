"""认证工具：密码哈希与短期 Bearer JWT。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass


class AuthError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthError("密码至少需要 8 位")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (_b64(salt), _b64(digest))


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        scheme, n, r, p, salt_text, digest_text = (encoded or "").split("$", 5)
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt_text),
                                n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest, _unb64(digest_text))
    except (ValueError, TypeError):
        return False


def _secret(config) -> bytes:
    secret = getattr(config, "jwt_secret", "") or "laoyouji-dev-insecure-secret-key-for-local-demo"
    return secret.encode("utf-8")


def create_access_token(user: dict, config, *, session_id: str | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": user["id"],
        "role": user.get("role"),
        "type": "access",
        "iat": now,
        "exp": now + int(getattr(config, "jwt_access_minutes", 30)) * 60,
    }
    if session_id:
        payload["sid"] = session_id
    return _encode(payload, _secret(config))


def create_refresh_token(user_id: str, session_id: str, config) -> str:
    now = int(time.time())
    return _encode({
        "sub": user_id, "sid": session_id, "type": "refresh", "iat": now,
        "exp": now + int(getattr(config, "jwt_refresh_days", 30)) * 86400,
    }, _secret(config))


def decode_token(token: str, config, *, expected_type: str = "access") -> dict:
    try:
        header_text, payload_text, signature = token.split(".", 2)
        signing = f"{header_text}.{payload_text}".encode("ascii")
        expected = _b64(hmac.new(_secret(config), signing, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise AuthError("无效的登录凭证")
        header = json.loads(_unb64(header_text))
        payload = json.loads(_unb64(payload_text))
        if header.get("alg") != "HS256" or payload.get("type") != expected_type:
            raise AuthError("无效的登录凭证")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise AuthError("登录凭证已过期")
        if not payload.get("sub"):
            raise AuthError("无效的登录凭证")
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthError("无效的登录凭证") from exc


def _encode(payload: dict, secret: bytes) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"},
                             separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


@dataclass(frozen=True)
class Principal:
    user: dict
    claims: dict

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def role(self) -> str:
        return self.user.get("role", "")
