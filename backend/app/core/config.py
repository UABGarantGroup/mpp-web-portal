"""
Application configuration using pydantic-settings.
Supports local SQLite development and Azure PostgreSQL production deployments.
"""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "MS Project Centralized Resource & Template Hub"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite:///./mpp_hub.db"

    # Microsoft Entra ID (Azure AD)
    AZURE_AD_CLIENT_ID: str = ""
    AZURE_AD_TENANT_ID: str = ""
    AZURE_AD_CLIENT_SECRET: str = ""
    INITIAL_ADMIN_EMAIL: str = ""  # Bootstrap admin user from Entra ID
    AUTH_ENABLED: bool = False  # Enabled in production; allows development bypass

    # JVM & MPXJ (for .mpp reading)
    JVM_PATH: str = r"C:\Program Files\Android\Android Studio\jbr\bin\server\jvm.dll"

    # Security & CORS
    CORS_ORIGINS: List[str] = ["*"]
    SECRET_KEY: str = "mpp-hub-super-secret-key-change-in-production-2026"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )


settings = Settings()
