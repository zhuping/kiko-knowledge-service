import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import BusinessError
from app.models.base import utc_now
from app.models.operations import ApiClient, ApiNonce, ApiRateBucket


@dataclass(frozen=True)
class AdminIdentity:
    user_id: str
    display_name: str
    roles: tuple[str, ...]


ROLE_PERMISSIONS = {
    "admin": (
        "knowledge:read",
        "knowledge:write",
        "release:validate",
        "release:publish",
        "admin:manage",
    ),
}

ADMIN_USERNAME = "无问"
ADMIN_PASSWORD = "Kiko123!@#"
ADMIN_SESSION_COOKIE = "kiko_admin_session"
ADMIN_SESSION_MAX_AGE = 8 * 60 * 60


def identity_response(identity: AdminIdentity) -> dict:
    return {
        "userId": identity.user_id,
        "displayName": identity.display_name,
        "roles": list(identity.roles),
        "permissions": [
            "knowledge:read",
            "knowledge:write",
            "mapping:write",
            "relation:write",
            "release:write",
            "audit:read",
        ],
    }


def authenticate_admin(
    request: Request, username: str, password: str
) -> tuple[AdminIdentity, str]:
    settings: Settings = request.app.state.settings
    if not settings.local_admin_enabled:
        raise BusinessError("AUTH_FAILED", "本地管理员登录已关闭", 401)
    if not (
        hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
        and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    ):
        raise BusinessError("AUTH_FAILED", "账号或密码错误", 401)

    now = time.time()
    sessions = request.app.state.admin_sessions
    for token, expires_at in list(sessions.items()):
        if expires_at <= now:
            sessions.pop(token, None)
    token = secrets.token_urlsafe(32)
    sessions[token] = now + ADMIN_SESSION_MAX_AGE
    return (
        AdminIdentity(
            user_id=ADMIN_USERNAME,
            display_name="知识运营管理员",
            roles=("admin",),
        ),
        token,
    )


def revoke_admin_session(request: Request) -> None:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if token:
        request.app.state.admin_sessions.pop(token, None)


def admin_identity(request: Request) -> AdminIdentity:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    expires_at = request.app.state.admin_sessions.get(token) if token else None
    if expires_at is None or expires_at <= time.time():
        if token:
            request.app.state.admin_sessions.pop(token, None)
        raise BusinessError("AUTH_FAILED", "登录已失效，请重新登录", 401)
    return AdminIdentity(
        user_id=ADMIN_USERNAME,
        display_name="知识运营管理员",
        roles=("admin",),
    )


def require_admin(request: Request) -> str:
    identity = admin_identity(request)
    return identity.user_id


def require_roles(*required: str):
    def dependency(request: Request) -> AdminIdentity:
        identity = admin_identity(request)
        if not set(identity.roles).intersection(required):
            raise BusinessError("FORBIDDEN", "当前用户没有执行该操作的权限", 403)
        return identity

    return dependency


def canonical_request(
    request: Request, body: bytes, timestamp: str, nonce: str
) -> bytes:
    query_hash = hashlib.sha256(request.url.query.encode()).hexdigest()
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(
        [request.method, request.url.path, query_hash, body_hash, timestamp, nonce]
    ).encode()


def _decode_secret(ciphertext: str, settings: Settings) -> bytes:
    """Decrypt a client Secret with the deployment-provided Fernet key."""
    if not settings.api_secret_key:
        raise BusinessError("AUTH_FAILED", "服务未配置 API Secret 解密密钥", 401)
    try:
        return Fernet(settings.api_secret_key.encode()).decrypt(ciphertext.encode())
    except (ValueError, InvalidToken) as exc:
        raise BusinessError("AUTH_FAILED", "API Secret 不可用", 401) from exc


async def verify_open_request(
    request: Request, db: Session = Depends(get_db)
) -> ApiClient:
    settings: Settings = request.app.state.settings
    app_key = request.headers.get("X-App-Key")
    timestamp = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    signature = request.headers.get("X-Signature")
    if not all((app_key, timestamp, nonce, signature)):
        raise BusinessError("AUTH_FAILED", "缺少开放接口鉴权请求头", 401)

    try:
        if abs(time.time() - int(timestamp)) > settings.api_hmac_window_seconds:
            raise BusinessError("AUTH_FAILED", "请求已超出时间窗口", 401)
    except ValueError as exc:
        raise BusinessError("AUTH_FAILED", "时间戳无效", 401) from exc

    client = db.scalar(select(ApiClient).where(ApiClient.app_key == app_key))
    if not client or client.status != "active":
        raise BusinessError("AUTH_FAILED", "AppKey 无效", 401)
    if not set(client.allowed_scopes or []).intersection({"read", "knowledge:read"}):
        raise BusinessError("FORBIDDEN", "AppKey 没有知识读取权限", 403)

    db.add(ApiNonce(app_key=app_key, nonce=nonce, created_at=utc_now()))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessError("AUTH_FAILED", "Nonce 重复，拒绝重放请求", 401) from exc

    body = await request.body()
    secret = _decode_secret(client.secret_ciphertext, settings)
    expected = base64.b64encode(
        hmac.new(
            secret, canonical_request(request, body, timestamp, nonce), hashlib.sha256
        ).digest()
    ).decode()
    if not hmac.compare_digest(expected, signature):
        db.rollback()
        raise BusinessError("AUTH_FAILED", "签名校验失败", 401)

    bucket = int(time.time() // 60)
    rate_bucket = db.scalar(
        select(ApiRateBucket).where(
            ApiRateBucket.app_key == app_key, ApiRateBucket.bucket_minute == bucket
        )
    )
    if rate_bucket is None:
        rate_bucket = ApiRateBucket(
            app_key=app_key, bucket_minute=bucket, request_count=0
        )
        db.add(rate_bucket)
    rate_bucket.request_count += 1
    if rate_bucket.request_count > min(
        client.rate_limit_per_minute, settings.api_rate_limit_per_minute
    ):
        db.commit()
        raise BusinessError("RATE_LIMITED", "请求过于频繁，请稍后再试", 429)
    db.commit()
    return client


def open_dependency() -> Callable[..., Awaitable[ApiClient]]:
    return verify_open_request
