import asyncio
from typing import TypeVar, Any

T = TypeVar('T')

async def run_sync_in_thread(func: Any, *args, **kwargs) -> T:
    """
    Выполняет синхронную функцию в отдельном потоке.
    Использует asyncio.to_thread (Python 3.10+).
    Позволяет не блокировать event loop на время I/O операций.
    """
    return await asyncio.to_thread(func, *args, **kwargs)