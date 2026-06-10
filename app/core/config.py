"""
Application configuration using Pydantic Settings.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Conflux API"
    app_version: str = "0.1.0"
    debug: bool = False
    demo_mode: bool = Field(default=False, alias="CONFLUX_DEMO")
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )

    # Database
    database_url: str = Field(default="sqlite:///data/conflux.db", alias="DATABASE_URL")

    # External APIs
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    groq_api_url: str = Field(default="https://api.groq.com/openai/v1/chat/completions", alias="GROQ_API_URL")

    # Overpass
    overpass_enabled: bool = Field(default=False, alias="OVERPASS_ENABLED")
    overpass_url: str = Field(default="https://overpass-api.de/api/interpreter", alias="OVERPASS_URL")

    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    data_dir: Path = base_dir / "data"
    policy_dir: Path = base_dir / "policy_docs"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def local_clusters_file(self) -> Path:
        return self.data_dir / "local_clusters.json"

    @property
    def local_threads_file(self) -> Path:
        return self.data_dir / "local_threads_geojson.json"

    @property
    def local_threads_source_file(self) -> Path:
        return self.data_dir / "local_threads.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()