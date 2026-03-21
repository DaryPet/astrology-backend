from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Astrology API"
    DATABASE_URL: str = "sqlite+aiosqlite:///./astrology.db"
    OPENAI_API_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"

settings = Settings()
