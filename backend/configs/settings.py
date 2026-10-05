from pydantic_settings import BaseSettings, NoDecode
from pydantic import field_validator, ValidationInfo
from typing import Annotated, Optional, List

class Settings(BaseSettings):
    # Project Info
    PROJECT_NAME: str = "NeoTrade"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    SERVER_PORT: int = 8001  # Port the server runs on

    # Database
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "stock_investor_db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # OmniRoute (self-hosted OpenAI-compatible gateway) -- the only LLM
    # provider this app uses. OMNIROUTE_API_KEY(S) holds the gateway key
    # issued from the OmniRoute dashboard's Endpoints page, not a Google key.
    OMNIROUTE_API_KEY: Optional[str] = None
    OMNIROUTE_API_KEYS: List[str] = []
    OMNIROUTE_BASE_URL: str = "http://omniroute:20128/v1"
    OMNIROUTE_MODEL: str = "agy/gemini-3-flash"  # unversioned: agy rotates versioned ids within hours

    FINNHUB_API_KEY: Optional[str] = None

    # Deep-tier LLM calls the ingest worker may spend scoring news per IST
    # day (backend/datalayer/news.py, one call per 5-minute pass at most);
    # past it the backlog waits in Mongo.
    NEWS_LLM_CALLS_PER_DAY: int = 200

    # Broker API credentials are per-user and encrypted in Mongo
    # (backend/auth/broker_credentials.py) -- there is deliberately no
    # deployment-wide KITE_API_KEY/KITE_API_SECRET any more. One shared pair
    # meant every signed-in user traded the same broker account, and the
    # settings API let any of them overwrite it.
    #
    # Fernet key: generate with
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Losing it means every stored credential must be re-entered; rotating it
    # requires re-encrypting them.
    CREDENTIAL_ENCRYPTION_KEY: Optional[str] = None

    # Guardrail alerts (backend/guardrails/telegram.py). One bot for the whole
    # deployment, created with @BotFather; unset means in-app alerts only.
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # Emails allowed to change deployment-wide settings. Role is re-derived
    # from this list on every login.
    ADMIN_EMAILS: Annotated[List[str], NoDecode] = []

    # Google Sign-In (ID-token verification only -- no client secret, no
    # redirect URI needed for this flow).
    GOOGLE_CLIENT_ID: Optional[str] = None

    # Session JWT (bearer token, not a cookie -- see auth design spec).
    # Short-lived on purpose: a stolen access token (XSS, a logged request,
    # a compromised extension) is only useful for this long. Silent renewal
    # is REFRESH_TOKEN's job, not a long access-token lifetime's.
    JWT_SECRET: str = "change-me-in-production"
    SESSION_MAX_AGE_SECONDS: int = 1800  # 30 minutes

    # Long-lived refresh token (httpOnly cookie, never touches JS). Opaque
    # and DB-backed (backend/auth/refresh_store.py) rather than a second
    # JWT, specifically so it can be revoked before it naturally expires.
    REFRESH_TOKEN_MAX_AGE_SECONDS: int = 60 * 24 * 3600  # 60 days
    REFRESH_COOKIE_NAME: str = "neotrade_refresh"

    # Explicit CORS allowlist -- replaces allow_origins=["*"], which is an
    # invalid combination with allow_credentials=True for real credentialed
    # cross-origin requests.
    # NoDecode: pydantic-settings otherwise tries to JSON-decode any env var
    # feeding a List[str] field before any validator runs, which crashes on
    # a plain comma-separated string like "http://a,http://b" (not valid
    # JSON) -- NoDecode passes the raw string through to our validator.
    CORS_ALLOWED_ORIGINS: Annotated[List[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def split_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("ADMIN_EMAILS", mode="before")
    @classmethod
    def split_admin_emails(cls, v):
        if isinstance(v, str):
            return [email.strip() for email in v.split(",") if email.strip()]
        return v

    @field_validator("OMNIROUTE_API_KEYS", mode="before")
    @classmethod
    def assemble_omniroute_keys(cls, v: Optional[List[str]], info: ValidationInfo) -> List[str]:
        if isinstance(v, list) and v:
            return v
        # Fallback to splitting the single key if it contains commas, or just using it
        values = info.data.get("OMNIROUTE_API_KEY")
        if values:
            return [k.strip() for k in values.split(",") if k.strip()]
        return []

    # System Settings
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()
