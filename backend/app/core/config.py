import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "OminiChannel WhatsApp"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "SUPER_SECRET_JWT_KEY_CHANGE_IN_PRODUCTION_12345"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./omini_channel.db"
    
    # Evolution API (Self-Hosted)
    EVOLUTION_API_URL: str = "http://localhost:8080"
    EVOLUTION_API_KEY: str = "omini_master_key_123"

    # Webhook base URL (used by Evolution API to send events back to this server)
    # In OCI/production, set this to your public domain, e.g. https://ominichannel.duckdns.org
    # In local Docker, use http://host.docker.internal:8000
    WEBHOOK_BASE_URL: str = "http://host.docker.internal:8000"

    # Gemini AI
    GEMINI_API_KEY: str = ""

    # Google Drive Integration
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
