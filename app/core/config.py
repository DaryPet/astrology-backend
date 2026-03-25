from pydantic_settings import BaseSettings
from typing import Optional
from pydantic import Field

class Settings(BaseSettings):
    # Project settings
    PROJECT_NAME: str = "Astrology API"
    DATABASE_URL: str = "sqlite+aiosqlite:///./astrology.db"
    OPENAI_API_KEY: Optional[str] = None
    
    # Authentication settings
    SECRET_KEY: str = Field(default="your-secret-key-for-jwt-tokens-change-in-production", min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS settings
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # Security settings
    BCRYPT_ROUNDS: int = 12
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
