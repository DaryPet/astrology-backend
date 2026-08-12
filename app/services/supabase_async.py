import asyncio
from typing import TypeVar, Any

T = TypeVar('T')

async def run_sync_in_thread(func: Any, *args, **kwargs) -> T:
    """
    Runs a synchronous function in a separate thread.
    Uses asyncio.to_thread (Python 3.10+).
    Keeps the event loop from blocking during I/O operations.
    """
    return await asyncio.to_thread(func, *args, **kwargs)