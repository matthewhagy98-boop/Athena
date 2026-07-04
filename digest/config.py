from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DigestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    email_sender: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str = "digest@example.com"


@lru_cache
def get_digest_settings() -> DigestSettings:
    return DigestSettings()
