from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "RoomieSplit API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = "development"

    # Required in .env. Generate with: openssl rand -hex 32
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # PostgreSQL Database
    POSTGRES_USER: str = "parat"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_DB: str = "roomie_db"
    
    # Full connection string (can be overridden in .env)
    DATABASE_URL: Optional[str] = None

    # Server Host & Port
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # Password reset
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    FRONTEND_RESET_PASSWORD_URL: str = "http://localhost:3000/#/reset-password"

    # Admin emails that can always reset password directly (token returned in response)
    ADMIN_EMAILS: str = "dk1747056@gmail.com,dheerajparat@gmail.com"

    # Optional SMTP configuration for password reset emails
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_SECONDS: int = 10

    # Brevo (formerly Sendinblue) — RECOMMENDED for cloud deployments
    # Free: 300 emails/day. No custom domain needed — just verify your sender email.
    # Sign up: https://app.brevo.com  →  Settings → Senders & IP → Add a sender email
    # API key: https://app.brevo.com/settings/keys/api
    BREVO_API_KEY: Optional[str] = None
    BREVO_FROM_EMAIL: Optional[str] = None   # e.g. "dk1747056@gmail.com" (must be verified sender)
    BREVO_SENDER_EMAIL: Optional[str] = None  # alias for BREVO_FROM_EMAIL

    # Resend — requires verified custom domain to send to arbitrary recipients
    # Get a free API key at https://resend.com
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None  # e.g. "RoomieSplit <noreply@yourdomain.com>"


    model_config = SettingsConfigDict(
        env_file=[
            str(BASE_DIR / ".env"),
            str(ROOT_DIR / ".env"),
        ],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def model_post_init(self, __context):
        if not self.DATABASE_URL:
            auth = f"{self.POSTGRES_USER}"
            if self.POSTGRES_PASSWORD:
                auth += f":{self.POSTGRES_PASSWORD}"
            self.DATABASE_URL = (
                f"postgresql://{auth}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]


settings = Settings()
