from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = (
        "mysql+pymysql://kiko:kiko-development@127.0.0.1:3306/"
        "kiko_knowledge?charset=utf8mb4"
    )
    celery_broker_url: str = "redis://127.0.0.1:6379/2"
    celery_result_backend: str = "redis://127.0.0.1:6379/3"
    celery_task_always_eager: bool = False
    classification_timeout_seconds: int = Field(default=180, ge=30, le=3600)
    classification_dispatch_wait_seconds: int = Field(default=30, ge=5, le=600)
    classification_max_retries: int = Field(default=2, ge=0, le=10)
    classifier_base_url: str = "https://api.deepseek.com"
    classifier_api_key: str = ""
    classifier_model: str = "deepseek-v4-flash"
    classifier_version: str = "classifier-v1"
    classifier_prompt_version: str = "classification-prompt-v1"
    classifier_timeout_seconds: int = Field(default=30, ge=1, le=120)
    api_key_pepper: str = "development-only-change-me"
    local_admin_enabled: bool = True
    media_allowed_hosts: str = ""
    max_question_chars: int = Field(default=20_000, ge=100, le=100_000)

    @property
    def configured_media_hosts(self) -> set[str]:
        return {
            item.strip().lower() for item in self.media_allowed_hosts.split(",") if item
        }

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment == "test":
            return self
        if not self.database_url.startswith("mysql"):
            raise ValueError("运行环境必须使用 MySQL")
        if self.environment == "development":
            return self
        if len(self.api_key_pepper) < 32:
            raise ValueError("非开发环境 API Key pepper 至少 32 位")
        if self.local_admin_enabled:
            raise ValueError("非开发环境必须关闭本地管理身份")
        if not self.classifier_api_key or not self.classifier_model:
            raise ValueError("非开发环境必须配置判断模型")
        return self

    model_config = SettingsConfigDict(
        env_prefix="KIKO_KNOWLEDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
