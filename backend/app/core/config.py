"""Application configuration loaded from environment variables."""
from typing import List, Optional
from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "FreightOps AI"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Server configuration
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # PostgreSQL configuration per Contract 2.2
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_DB: str = "freightops"
    DATABASE_URL: Optional[str] = None
    DB_CONNECT_TIMEOUT_SECONDS: int = 3

    # Session cookie security. Local HTTP development may explicitly disable
    # Secure; every non-development environment forces Secure regardless.
    SESSION_COOKIE_SECURE: bool = False

    # Demo-user seeding (optional). Seeding is skipped unless every role has
    # both an email and a password configured. No password fallback is used.
    DEMO_ADMIN_EMAIL: Optional[str] = None
    DEMO_ADMIN_PASSWORD: Optional[str] = None
    DEMO_BROKER_EMAIL: Optional[str] = None
    DEMO_BROKER_PASSWORD: Optional[str] = None
    DEMO_VIEWER_EMAIL: Optional[str] = None
    DEMO_VIEWER_PASSWORD: Optional[str] = None

    # CORS origins
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_database_credentials(self):
        if self.DATABASE_URL:
            return self
        missing = [
            name
            for name in ("POSTGRES_USER", "POSTGRES_PASSWORD")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                "Database credentials are not configured. Set DATABASE_URL or define "
                + " and ".join(missing)
                + " in the environment."
            )
        return self

    @property
    def COOKIE_SECURE(self) -> bool:
        """Force Secure outside development; allow explicit opt-in in development."""
        if self.ENVIRONMENT.lower() == "development":
            return self.SESSION_COOKIE_SECURE
        return True

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.DATABASE_URL:
            # Normalize postgres:// or postgresql:// to postgresql+psycopg://
            uri = self.DATABASE_URL
            if uri.startswith("postgresql://"):
                return uri.replace("postgresql://", "postgresql+psycopg://", 1)
            elif uri.startswith("postgres://"):
                return uri.replace("postgres://", "postgresql+psycopg://", 1)
            return uri
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
