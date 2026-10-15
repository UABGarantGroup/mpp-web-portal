"""
Application configuration using pydantic-settings.
Supports local SQLite development and Azure PostgreSQL production deployments.
"""

import logging
import secrets
from typing import List
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

DEFAULT_INSECURE_SECRET = "mpp-hub-super-secret-key-change-in-production-2026"


class Settings(BaseSettings):
    PROJECT_NAME: str = "MS Project Centralized Resource & Template Hub"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite:///./mpp_hub.db"

    # Microsoft SQL Server Configuration (Optional: auto-builds DATABASE_URL if MSSQL_HOST is set)
    MSSQL_HOST: str = ""       # e.g., "192.168.1.100", "sqlserver.corp.local", or "SRV-SQL01\SQLEXPRESS"
    MSSQL_PORT: int = 1433
    MSSQL_DATABASE: str = "mpp_hub"
    MSSQL_USER: str = ""       # e.g., "sa" or "mpp_user"
    MSSQL_PASSWORD: str = ""
    MSSQL_TRUSTED_CONNECTION: bool = False  # Set True for Windows Authentication
    MSSQL_DRIVER: str = "ODBC Driver 18 for SQL Server"

    # Microsoft Entra ID (Azure AD)
    AZURE_AD_CLIENT_ID: str = ""
    AZURE_AD_TENANT_ID: str = ""
    AZURE_AD_CLIENT_SECRET: str = ""
    INITIAL_ADMIN_EMAIL: str = ""  # Bootstrap admin user from Entra ID
    EMERGENCY_ADMIN_USERNAME: str = "emergency_admin"
    EMERGENCY_ADMIN_PASSWORD: str = ""
    AUTH_ENABLED: bool = False  # Enforced True automatically when ENVIRONMENT=="production"

    # JVM & MPXJ (for .mpp reading)
    JVM_PATH: str = ""

    # Security, Upload Limits & CORS
    CORS_ORIGINS: List[str] = [
        "https://192.168.28.229",
        "http://192.168.28.229",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    SECRET_KEY: str = DEFAULT_INSECURE_SECRET
    MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB max upload size

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )

    @model_validator(mode="after")
    def process_settings(self) -> "Settings":
        # Auto-construct MSSQL DATABASE_URL if MSSQL_HOST is specified and not already an explicit MSSQL URL
        if self.MSSQL_HOST and not self.DATABASE_URL.startswith("mssql"):
            import urllib.parse
            if self.MSSQL_TRUSTED_CONNECTION:
                driver_clean = self.MSSQL_DRIVER.replace(" ", "+")
                self.DATABASE_URL = (
                    f"mssql+pyodbc://@{self.MSSQL_HOST}:{self.MSSQL_PORT}/{self.MSSQL_DATABASE}"
                    f"?driver={driver_clean}&trusted_connection=yes&TrustServerCertificate=yes"
                )
            else:
                user_enc = urllib.parse.quote_plus(self.MSSQL_USER)
                pwd_enc = urllib.parse.quote_plus(self.MSSQL_PASSWORD)
                self.DATABASE_URL = (
                    f"mssql+pymssql://{user_enc}:{pwd_enc}@{self.MSSQL_HOST}:{self.MSSQL_PORT}/{self.MSSQL_DATABASE}"
                )

        if self.ENVIRONMENT.strip().lower() == "production":
            # Never allow unauthenticated dev bypass in production
            self.AUTH_ENABLED = True
            # Never allow the hardcoded default SECRET_KEY in production
            if not self.SECRET_KEY or self.SECRET_KEY == DEFAULT_INSECURE_SECRET or len(self.SECRET_KEY) < 32:
                logger.warning(
                    "SECURITY: Default or weak SECRET_KEY detected in production! "
                    "Generating a strong ephemeral 256-bit secret key. Set a strong SECRET_KEY in .env."
                )
                self.SECRET_KEY = secrets.token_hex(32)
            # Disallow wildcard CORS in production when credentials are enabled
            if "*" in self.CORS_ORIGINS:
                self.CORS_ORIGINS = [o for o in self.CORS_ORIGINS if o != "*"] or ["https://192.168.28.229"]
        return self


settings = Settings()

