from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

REGIONS = ("eu", "us")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    blizzard_client_id: str = ""
    blizzard_client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str = "dev-secret-change-me"
    token_encryption_key: str = ""
    database_url: str = "sqlite:///./wow_alt_tracker.db"
    default_region: str = "eu"
    sync_interval_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
