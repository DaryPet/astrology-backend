from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Astrology API"
    DATABASE_URL: str = "sqlite+aiosqlite:///./astrology.db"
    OPENAI_API_KEY: Optional[str] = None
    
    # Authentication settings (optional - for future use)
    SECRET_KEY: Optional[str] = None
    ALGORITHM: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: Optional[int] = None
    REFRESH_TOKEN_EXPIRE_DAYS: Optional[int] = None
    BCRYPT_ROUNDS: Optional[int] = None
    
    class Config:
        env_file = ".env"

settings = Settings()
