from __future__ import annotations

import argparse
import secrets

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import ApiClient


def create_client(session: Session, settings: Settings, app_key: str) -> str:
    if not settings.api_secret_key:
        raise ValueError("KIKO_KNOWLEDGE_API_SECRET_KEY 未配置")
    if session.scalar(select(ApiClient.id).where(ApiClient.app_key == app_key)):
        raise ValueError(f"AppKey 已存在: {app_key}")
    secret = secrets.token_urlsafe(32)
    session.add(
        ApiClient(
            app_key=app_key,
            secret_ciphertext=Fernet(settings.api_secret_key.encode())
            .encrypt(secret.encode())
            .decode(),
            allowed_scopes=["knowledge:read"],
        )
    )
    session.commit()
    return secret


def main() -> None:
    parser = argparse.ArgumentParser(description="创建开放接口只读客户端")
    parser.add_argument("app_key")
    args = parser.parse_args()
    settings = Settings()
    factory = sessionmaker(bind=create_database_engine(settings.database_url))
    with factory() as session:
        secret = create_client(session, settings, args.app_key)
    print(f"AppKey={args.app_key}")
    print(f"Secret={secret}")


if __name__ == "__main__":
    main()
