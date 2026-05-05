"""
Application settings loaded from environment variables or
AWS Secrets Manager in production.
"""

import json
from typing import cast

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Pydantic settings model for application configuration.
    In production, environment variables are injected from AWS Secrets Manager
    via the ECS task definition. Locally, they are read from a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # -- Application --
    APP_NAME: str = "Bank Transaction System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # -- Database --
    DATABASE_URL: str

    # -- AWS General --
    AWS_REGION: str = "eu-west-1"

    # -- AWS SQS (required in production) --
    SQS_INTERNATIONAL_QUEUE_URL: str | None = None

    # -- Internal Service Auth --
    INTERNAL_SERVICE_API_KEY: str

    # -- CORS --
    # Accepts a JSON array ('["http://..."]') or comma-separated values.
    ALLOWED_ORIGINS_RAW: str = ""

    @property
    def ALLOWED_ORIGINS(self) -> list[str]:
        """Return CORS origins as a list, parsed from ALLOWED_ORIGINS_RAW."""
        raw = self.ALLOWED_ORIGINS_RAW.strip()
        if not raw:
            return []
        if raw.startswith("["):
            return cast(list[str], json.loads(raw))
        return [o.strip() for o in raw.split(",") if o.strip()]

    # -- Rate Limiting --
    RATE_LIMIT_PER_MINUTE: int = 60


settings = Settings()  # type: ignore
