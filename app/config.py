"""
Application Configuration

This module defines all configuration settings for the ServiceScope application.
Settings are loaded from environment variables (.env file or system environment).

Usage:
    from app.config import settings

    database_url = settings.DATABASE_URL
    debug_mode = settings.DEBUG
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden by setting environment variables.
    For example: export DEBUG=True
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # Allow lowercase env vars
        extra="ignore"  # Ignore unknown env vars
    )

    # ===== Application Settings =====
    APP_NAME: str = "ServiceScope"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, staging, production

    # ===== API Settings =====
    API_V1_PREFIX: str = "ServiceScope"
    ALLOWED_HOSTS: str = "2.0.0"
    CORS_ORIGINS: str = "development"

    # ===== Security Settings =====
    SECRET_KEY: str = "your-secret-key-CHANGE-IN-PRODUCTION-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ===== Database - PostgreSQL =====
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "servicescope"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "servicescope"

    @property
    def DATABASE_URL(self) -> str:
        """
        Construct async PostgreSQL connection URL.
        Format: postgresql+asyncpg://user:pass@host:port/db
        """
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """
        Sync PostgreSQL URL for Alembic migrations.
        Format: postgresql://user:pass@host:port/db
        """
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ===== Database - Neo4j =====
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "changeme"

    # ===== Redis =====
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    @property
    def REDIS_URL(self) -> str:
        """
        Construct Redis connection URL.
        Format: redis://[:password@]host:port/db
        """
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ===== Celery Task Queue =====
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 3600  # 1 hour max per task

    # ===== LLM Settings =====
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma2:latest"
    OLLAMA_TIMEOUT: int = 60  # seconds

    # Uncomment if using OpenAI instead of Ollama
    # OPENAI_API_KEY: Optional[str] = None
    # OPENAI_MODEL: str = "gpt-4"

    # ===== Repository Analysis Settings =====
    REPO_CLONE_DIR: str = "/tmp/servicescope/repos"
    MAX_REPO_SIZE_MB: int = 500
    CLONE_TIMEOUT_SECONDS: int = 300  # 5 minutes

    # ===== Rate Limiting =====
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000

    # ===== Logging =====
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    LOG_FORMAT: str = "json"  # json or text

    def get_log_config(self) -> dict:
        """Get logging configuration based on settings"""
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": self.LOG_FORMAT,
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": self.LOG_LEVEL,
                "handlers": ["console"],
            },
        }


# ===== Global Settings Instance =====
# This is imported throughout the application
settings = Settings()


# ===== Helper Functions =====
def is_development() -> bool:
    """Check if running in development mode"""
    return settings.ENVIRONMENT == "development" or settings.DEBUG


def is_production() -> bool:
    """Check if running in production mode"""
    return settings.ENVIRONMENT == "production"


def get_database_url(async_mode: bool = True) -> str:
    """
    Get database URL for different contexts.

    Args:
        async_mode: If True, returns async URL. If False, returns sync URL.

    Returns:
        Database connection URL string
    """
    return settings.DATABASE_URL if async_mode else settings.SYNC_DATABASE_URL