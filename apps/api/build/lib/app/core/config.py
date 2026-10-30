"""Typed, validated application configuration.

All configuration comes from environment variables (optionally a local .env file in
development). Feature flags use the strict convention ``1`` = enabled, ``0`` = disabled.

Precedence for email verification:
  ``EMAIL_VERIFICATION_ENABLED`` is canonical. ``REQUIRE_EMAIL_VERIFICATION`` is a
  documented compatibility alias that is only consulted when the canonical flag is not
  set at all. When both are set and disagree, the canonical flag wins and a warning is
  recorded in ``Settings.config_warnings``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when configuration is invalid; startup must abort."""


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return value.strip() == "1"
    raise ValueError("feature flags must be 1 (enabled) or 0 (disabled)")


def _opt_flag(value: object) -> bool | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return _flag(value)


Flag = Annotated[bool, BeforeValidator(_flag)]
OptFlag = Annotated[bool | None, BeforeValidator(_opt_flag)]

AIProviderName = Literal["gemini", "openai", "anthropic", "openai_compatible", "demo"]
SearchProviderName = Literal["firecrawl", "tavily", "brave", "demo"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        # A variable that exists but is blank (e.g. an optional prompt left empty in a hosting
        # dashboard) means "use the default", never "set to empty string".
        env_ignore_empty=True,
    )

    # --- Application -----------------------------------------------------------------
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    APP_NAME: str = "Deep Research"
    FRONTEND_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    CORS_ALLOWED_ORIGINS: str = ""  # comma separated, FRONTEND_URL always included
    TRUSTED_PROXY_HOPS: int = 1  # number of reverse proxies whose X-Forwarded-For we trust

    # --- Storage ----------------------------------------------------------------------
    MONGODB_URI: str = ""
    MONGODB_DATABASE: str = "deep_research"
    REDIS_URL: str = ""
    UPLOAD_DIR: str = "/var/lib/deep-research/uploads"

    # --- Auth -------------------------------------------------------------------------
    AUTH_SECRET: str = ""
    ACCESS_TOKEN_TTL_MINUTES: int = Field(15, ge=1, le=120)
    REFRESH_TOKEN_TTL_DAYS: int = Field(30, ge=1, le=365)
    COOKIE_DOMAIN: str = ""
    ADMIN_BOOTSTRAP_EMAILS: str = ""  # comma separated; verified accounts with these emails become ADMIN

    GOOGLE_AUTH_ENABLED: Flag = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    EMAIL_VERIFICATION_ENABLED: OptFlag = None
    REQUIRE_EMAIL_VERIFICATION: OptFlag = None
    PASSWORD_RESET_ENABLED: Flag = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: Flag = True
    EMAIL_FROM: str = ""

    # --- AI providers -----------------------------------------------------------------
    AI_PROVIDER: AIProviderName = "gemini"
    AI_MODEL: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_COMPATIBLE_BASE_URL: str = ""
    OPENAI_COMPATIBLE_API_KEY: str = ""
    AI_FALLBACK_ENABLED: Flag = True
    AI_REQUEST_TIMEOUT_SECONDS: int = Field(120, ge=5, le=900)

    # --- Search -----------------------------------------------------------------------
    SEARCH_PROVIDER: SearchProviderName = "firecrawl"
    FIRECRAWL_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    SEARCH_FALLBACK_ENABLED: Flag = True
    SEARCH_CACHE_TTL_SECONDS: int = 6 * 3600
    SCHOLARLY_SEARCH_ENABLED: Flag = True  # OpenAlex (keyless public API)
    OPENALEX_MAILTO: str = ""
    FETCH_TIMEOUT_SECONDS: float = 15.0
    FETCH_MAX_BYTES: int = 5 * 1024 * 1024
    FETCH_ALLOWED_PORTS: str = "80,443"

    # --- Billing ----------------------------------------------------------------------
    BILLING_ENABLED: Flag = False
    BILLING_PROVIDER: Literal["paddle"] = "paddle"
    PADDLE_API_KEY: str = ""
    PADDLE_WEBHOOK_SECRET: str = ""
    PADDLE_ENVIRONMENT: Literal["sandbox", "production"] = "sandbox"
    PADDLE_PRICE_IDS: str = ""  # "pro:pri_123,team:pri_456"
    BILLING_GRACE_DAYS: int = 7
    BILLING_GRACE_ALLOWS_NEW_JOBS: Flag = True

    # --- Product flags ----------------------------------------------------------------
    PUBLIC_SIGNUP_ENABLED: Flag = True
    ALLOW_USER_MODEL_SELECTION: Flag = True
    ALLOW_USER_API_KEYS: Flag = False
    DEMO_MODE: Flag = False
    DEMO_STEP_DELAY_MS: int = Field(0, ge=0, le=10_000)  # pacing for demo provider calls (0 = instant)
    RATE_LIMIT_ENABLED: Flag = True
    AUDIT_LOG_ENABLED: Flag = True
    CONTENT_SAFETY_ENABLED: Flag = True
    FILE_UPLOADS_ENABLED: Flag = True
    CHARTS_ENABLED: Flag = True
    PUBLIC_REPORT_SHARING_ENABLED: Flag = False
    EMBEDDED_WORKER: Flag = False  # dev only: run the worker loop inside the API process

    # --- Limits -----------------------------------------------------------------------
    MAX_CONCURRENT_RESEARCH_JOBS_PER_USER: int = Field(2, ge=1, le=50)
    MAX_RESEARCH_DURATION_SECONDS: int = Field(1800, ge=60, le=6 * 3600)
    MAX_SEARCH_CALLS_PER_JOB: int = Field(25, ge=1, le=500)
    MAX_SOURCES_PER_JOB: int = Field(30, ge=1, le=300)
    MAX_TOOL_CALLS_PER_JOB: int = Field(60, ge=1, le=1000)
    MAX_OUTPUT_TOKENS_PER_JOB: int = Field(20000, ge=1000, le=2_000_000)
    MAX_JOB_ATTEMPTS: int = Field(5, ge=1, le=20)
    DAILY_RESEARCH_JOBS_PER_USER: int = Field(30, ge=1)
    MONTHLY_COST_LIMIT_USD_PER_USER: float = Field(25.0, ge=0)
    MAX_FILE_SIZE_MB: int = Field(20, ge=1, le=200)
    MAX_RESEARCH_UPLOADS_PER_JOB: int = Field(10, ge=0, le=100)
    UPLOAD_RETENTION_DAYS: int = 30

    # --- Secrets for at-rest encryption -----------------------------------------------
    # Comma-separated urlsafe-base64 32-byte keys. The first key encrypts; all decrypt
    # (supports rotation). Generate with: python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    ENCRYPTION_KEYS: str = ""

    # --- Worker -----------------------------------------------------------------------
    WORKER_CONCURRENCY: int = Field(2, ge=1, le=32)
    WORKER_LEASE_SECONDS: int = Field(60, ge=10, le=600)
    WORKER_HEARTBEAT_SECONDS: int = Field(15, ge=2, le=120)
    WORKER_POLL_SECONDS: float = 5.0
    # Touched by the worker's maintenance loop; container health checks read its mtime.
    WORKER_HEALTH_FILE: str = "/tmp/deep-research-worker.alive"  # noqa: S108

    # --- Observability ------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: OptFlag = None
    ERROR_TRACKING_DSN: str = ""  # hook for Sentry-compatible trackers

    config_warnings: list[str] = Field(default_factory=list, exclude=True)

    # ------------------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.APP_ENV in ("production", "staging")

    @property
    def email_verification_required(self) -> bool:
        if self.EMAIL_VERIFICATION_ENABLED is not None:
            return self.EMAIL_VERIFICATION_ENABLED
        if self.REQUIRE_EMAIL_VERIFICATION is not None:
            return self.REQUIRE_EMAIL_VERIFICATION
        return False

    @property
    def cors_origins(self) -> list[str]:
        extra = [o.strip().rstrip("/") for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        return sorted({self.FRONTEND_URL.rstrip("/"), *extra})

    @property
    def admin_bootstrap_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_BOOTSTRAP_EMAILS.split(",") if e.strip()}

    @property
    def fetch_allowed_ports(self) -> set[int]:
        return {int(p) for p in self.FETCH_ALLOWED_PORTS.split(",") if p.strip()}

    @property
    def paddle_price_ids(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in self.PADDLE_PRICE_IDS.split(","):
            if ":" in item:
                plan, pid = item.split(":", 1)
                out[plan.strip()] = pid.strip()
        return out

    @property
    def uses_memory_db(self) -> bool:
        return self.MONGODB_URI.startswith("mongomock://")

    @property
    def log_json(self) -> bool:
        return self.LOG_JSON if self.LOG_JSON is not None else self.is_production

    @property
    def secure_cookies(self) -> bool:
        return self.FRONTEND_URL.startswith("https://")

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAIL_FROM)

    # ------------------------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate(self) -> Settings:
        warnings: list[str] = []
        errors: list[str] = []

        if (
            self.EMAIL_VERIFICATION_ENABLED is not None
            and self.REQUIRE_EMAIL_VERIFICATION is not None
            and self.EMAIL_VERIFICATION_ENABLED != self.REQUIRE_EMAIL_VERIFICATION
        ):
            warnings.append(
                "EMAIL_VERIFICATION_ENABLED and REQUIRE_EMAIL_VERIFICATION disagree; "
                "EMAIL_VERIFICATION_ENABLED (canonical) wins."
            )

        if self.GOOGLE_AUTH_ENABLED and not (self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET):
            (errors if self.is_production else warnings).append(
                "GOOGLE_AUTH_ENABLED=1 but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are missing; "
                "Google login will be reported as misconfigured."
            )

        if self.is_production:
            if len(self.AUTH_SECRET) < 32:
                errors.append("AUTH_SECRET must be at least 32 characters in production.")
            if not self.MONGODB_URI or self.uses_memory_db:
                errors.append("MONGODB_URI must point to MongoDB (Atlas) in production.")
            if not self.REDIS_URL:
                errors.append("REDIS_URL is required in production.")
            if not self.FRONTEND_URL.startswith("https://"):
                errors.append("FRONTEND_URL must use https in production.")
            if self.DEMO_MODE:
                errors.append("DEMO_MODE=1 is not allowed in production.")
            if self.EMBEDDED_WORKER:
                errors.append("EMBEDDED_WORKER=1 is not allowed in production; run apps/worker.")
            if (self.email_verification_required or self.PASSWORD_RESET_ENABLED) and not self.smtp_configured:
                errors.append("SMTP_HOST and EMAIL_FROM are required when email verification or password reset is enabled.")
            if not self.ENCRYPTION_KEYS:
                errors.append("ENCRYPTION_KEYS is required in production (encrypts stored provider credentials).")
            if self.BILLING_ENABLED and not (self.PADDLE_API_KEY and self.PADDLE_WEBHOOK_SECRET):
                errors.append("BILLING_ENABLED=1 requires PADDLE_API_KEY and PADDLE_WEBHOOK_SECRET.")
        else:
            if not self.AUTH_SECRET:
                warnings.append("AUTH_SECRET is empty; using an ephemeral development secret (sessions reset on restart).")
            if self.ALLOW_USER_API_KEYS and not self.ENCRYPTION_KEYS:
                warnings.append("ALLOW_USER_API_KEYS=1 without ENCRYPTION_KEYS; using an ephemeral development key.")

        if self.ALLOW_USER_API_KEYS and self.is_production and not self.ENCRYPTION_KEYS:
            errors.append("ALLOW_USER_API_KEYS=1 requires ENCRYPTION_KEYS.")

        if errors:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))
        self.config_warnings = warnings
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
