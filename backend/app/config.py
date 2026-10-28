"""All settings come from environment variables (or a .env file).

Keeping config in one place means the same code runs on a laptop,
in Docker, or on a client's server — only the env changes.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "vaanidesk"
    redis_url: str = "redis://localhost:6379/0"

    # The bank's (mock) core-banking API we integrate with
    bank_api_url: str = "http://localhost:8001"
    bank_api_key: str = "demo-bank-key"
    bank_timeout_seconds: float = 3.0
    bank_max_retries: int = 2

    # LLM + speech-to-text (Groq). Without a key, the app falls back to
    # keyword rules for understanding and voice upload is disabled.
    groq_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-20b"
    stt_model: str = "whisper-large-v3-turbo"
    llm_timeout_seconds: float = 8.0

    # Behaviour
    session_ttl_seconds: int = 30 * 60      # a call's Redis session expires after 30 min idle
    nlu_cache_ttl_seconds: int = 24 * 3600  # cache LLM results for repeated phrases
    stats_cache_ttl_seconds: int = 30
    rate_limit_per_minute: int = 60         # per client IP, on turn/audio endpoints
    max_tpin_attempts: int = 3
    max_audio_bytes: int = 5 * 1024 * 1024

    cors_origins: str = "http://localhost:5173"


settings = Settings()
