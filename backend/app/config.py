from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Local runs read the repo-root .env; in Docker the variables come from compose.
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    keitaro_api_key: str = ""
    keitaro_url: str = "https://tlgk.host/admin_api/v1"
    database_url: str = "postgresql+asyncpg://kcm:kcm@localhost:5432/kcm"
    # The Keitaro instance is shared: only campaigns with this prefix are ours to touch.
    campaign_prefix: str = "test_kochkurov_"
    # Creator form preselects these by name (the first item when not found).
    default_group: str = "FORTESTS"
    default_traffic_source: str = "FORTESTS"


settings = Settings()
