from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KIKO_KNOWLEDGE_", env_file=".env", extra="ignore"
    )

    environment: str = "development"
    database_url: str = "sqlite:///./kiko_knowledge.db"
    local_admin_enabled: bool = True
    api_hmac_window_seconds: int = 300
    api_rate_limit_per_minute: int = 1000
    api_secret_key: str = ""
