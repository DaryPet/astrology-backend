from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Astrology API"
    DATABASE_URL: str = "sqlite+aiosqlite:///./astrology.db"
    OPENAI_API_KEY: Optional[str] = None

    # Supabase settings
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    
    # LLM Provider settings (swappable - change via .env)
    LLM_PROVIDER: str = "openai"  # openai, claude, ollama, gemini
    ANTHROPIC_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    GEMINI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "anthropic/claude-sonnet-4.5"  # дефолт если фронт не прислал model

    # Geocoding (LocationIQ)
    LOCATIONIQ_ACCESS_TOKEN: Optional[str] = None

    # Authentication settings (optional - for future use)
    SECRET_KEY: Optional[str] = None
    ALGORITHM: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: Optional[int] = None
    REFRESH_TOKEN_EXPIRE_DAYS: Optional[int] = None
    BCRYPT_ROUNDS: Optional[int] = None
    
    class Config:
        env_file = ".env"
        extra = "ignore" 

settings = Settings()
