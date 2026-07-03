from __future__ import annotations

from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False

    if algorithm != PASSWORD_ALGORITHM:
        return False

    expected = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return compare_digest(expected.hex(), digest_hex)


def create_access_token(payload: dict[str, Any]) -> str:
    serializer = URLSafeTimedSerializer(settings.auth_secret_key, salt="client-auth")
    return serializer.dumps(payload)


def read_access_token(token: str, max_age: int | None = None) -> dict[str, Any]:
    serializer = URLSafeTimedSerializer(settings.auth_secret_key, salt="client-auth")
    try:
        data = serializer.loads(token, max_age=max_age or settings.access_token_expire_seconds)
    except BadSignature as exc:
        raise ValueError("登录状态无效或已过期") from exc

    if not isinstance(data, dict):
        raise ValueError("登录状态内容无效")
    return data
