from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.errors import ApiError
from app.core.media import validate_media_urls
from app.core.security import (
    AdminContext,
    digest_secret,
    issue_api_key,
    key_expired,
    require_role,
)
from app.core.time import utcnow
from app.models import Base, ClientApp, Objective, PackageVersion


def test_api_key_generation_and_digest():
    key_id, secret, token = issue_api_key()
    assert token == f"kh_live_{key_id}.{secret}"
    assert len(digest_secret(secret)) == 64
    assert digest_secret(secret) == digest_secret(secret)
    assert key_expired(utcnow() - timedelta(seconds=1))
    assert not key_expired(None)


def test_admin_role_can_be_global_or_package_scoped():
    global_actor = AdminContext("a", frozenset({("editor", None)}))
    require_role(global_actor, "editor", package_id="pkg")
    scoped = AdminContext("b", frozenset({("reviewer", "pkg")}))
    require_role(scoped, "reviewer", package_id="pkg")
    with pytest.raises(ApiError) as exc:
        require_role(scoped, "publisher", package_id="pkg")
    assert exc.value.code == "ACCESS_DENIED"


def test_media_urls_require_https_allowlist_and_public_host():
    client = ClientApp(
        code="test",
        name="test",
        key_id="key",
        secret_digest="x" * 64,
        allowed_media_hosts_json=["media.example.com"],
    )
    validate_media_urls(["https://media.example.com/question.png"], client)
    for url in [
        "http://media.example.com/a",
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://evil.example.com/a",
        "https://user:pass@media.example.com/a",
        "https://media.example.com:444/a",
    ]:
        with pytest.raises(ApiError) as exc:
            validate_media_urls([url], client)
        assert exc.value.code == "MEDIA_NOT_ALLOWED"


def test_production_settings_reject_unsafe_defaults():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url="sqlite:///unsafe.db",
            local_admin_enabled=False,
        )
    settings = Settings(
        environment="production",
        database_url="mysql+pymysql://user:pass@db/knowledge",
        local_admin_enabled=False,
        api_key_pepper="x" * 32,
        classifier_api_key="secret",
        classifier_model="model",
    )
    assert settings.environment == "production"


def test_development_settings_require_mysql():
    with pytest.raises(ValidationError):
        Settings(environment="development", database_url="sqlite:///unsafe.db")


def test_schema_compiles_for_mysql():
    statements = [
        str(CreateTable(table).compile(dialect=mysql.dialect()))
        for table in Base.metadata.sorted_tables
    ]
    assert statements
    assert all("VARCHAR(26)" in statement for statement in statements)


def test_published_content_and_metadata_are_immutable(seeded):
    with SessionLocal() as db:
        version = db.get(PackageVersion, seeded["version"]["id"])
        version.release_notes = "attempted overwrite"
        with pytest.raises(ApiError) as exc:
            db.commit()
        assert exc.value.code == "PACKAGE_VERSION_IMMUTABLE"
        db.rollback()

        objective = db.get(Objective, seeded["objectives"][0]["id"])
        objective.name = "attempted overwrite"
        with pytest.raises(ApiError):
            db.commit()
