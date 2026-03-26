# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
# from sqlalchemy.orm import declarative_base
# from app.core.config import settings

# engine = create_async_engine(settings.DATABASE_URL, echo=True)
# async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Base = declarative_base()

# async def get_db():
#     async with async_session_maker() as session:
#         yield session

# async def init_db():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Заменяем postgresql:// на postgresql+asyncpg://
ASYNC_DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(ASYNC_DATABASE_URL, echo=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with async_session_maker() as session:
        yield session