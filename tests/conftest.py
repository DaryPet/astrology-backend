"""
Shared fixtures for API-level tests (integration/functional/perf).

See plans/testing-plan-minimum.md for the plan these fixtures implement
(Фаза 0). Unit tests under tests/test_*.py that call functions directly
don't need any of this and are unaffected.
"""
import os

import httpx
import pytest

from app.main import app
from app import swephelper
from app.auth import get_current_user
from app.api import endpoints as endpoints_module

FAKE_USER = {"id": "test-user-id", "email": "test@example.com"}


# ---------------------------------------------------------------------------
# Sanity: Swiss Ephemeris data must be present, or chart math silently
# degrades (app/swephelper.py:10-14 only prints a warning, never raises).
# ---------------------------------------------------------------------------
def _ephe_path() -> str:
    return os.path.join(os.path.dirname(swephelper.__file__), "..", "ephe")


if not os.path.isdir(_ephe_path()):
    pytest.exit(
        f"ephe/ not found at {_ephe_path()!r} — astrology math would silently "
        "degrade (see app/swephelper.py). Do not run tests without it."
    )


# ---------------------------------------------------------------------------
# Network lockdown: block any REAL outbound HTTP call (LocationIQ, Supabase
# auth, LLM providers) from any test. httpx.ASGITransport (used by TestClient
# and async_client below to talk to our own app in-process) is a different
# class and is NOT touched by this — only the real network transports are.
# ---------------------------------------------------------------------------
class _NetworkBlocked(RuntimeError):
    pass


def _blocked_sync(self, request):
    raise _NetworkBlocked(f"real network call blocked in tests: {request.method} {request.url}")


async def _blocked_async(self, request):
    raise _NetworkBlocked(f"real network call blocked in tests: {request.method} {request.url}")


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked_async)


# ---------------------------------------------------------------------------
# Module-level in-memory caches leak state between tests if not cleared.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clear_module_caches():
    endpoints_module._geocode_cache.clear()
    endpoints_module._analysis_cache.clear()
    yield
    endpoints_module._geocode_cache.clear()
    endpoints_module._analysis_cache.clear()


# ---------------------------------------------------------------------------
# Rate limiting: off by default so integration/functional tests don't 429
# each other. Tests that specifically exercise rate limiting can flip it
# back on for the duration of the test.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    app.state.limiter.enabled = False
    yield


# ---------------------------------------------------------------------------
# Auth: overridden to a fake user by default (most endpoints require it and
# don't care who it is). Tests that check the 401 path use
# `unauthenticated_client`/`unauthenticated_async_client` instead, which
# clear the override.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _default_auth_override():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def unauthenticated_client():
    app.dependency_overrides.pop(get_current_user, None)
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER


@pytest.fixture
async def async_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def fake_llm_adapter():
    """A minimal LLMAdapter double: fixed reply, call-count tracked."""
    from app.services.llm_adapter import LLMAdapter

    class FakeLLMAdapter(LLMAdapter):
        def __init__(self, reply: str = "Fake LLM analysis text."):
            self.reply = reply
            self.calls = []

        async def generate(self, prompt: str, language: str = "en") -> str:
            self.calls.append(("generate", prompt, language))
            return self.reply

        async def generate_with_messages(self, messages, language: str = "en") -> str:
            self.calls.append(("generate_with_messages", messages, language))
            return self.reply

        async def generate_stream(self, prompt: str, language: str = "en"):
            self.calls.append(("generate_stream", prompt, language))
            yield self.reply

        async def generate_stream_with_messages(self, messages, language: str = "en"):
            self.calls.append(("generate_stream_with_messages", messages, language))
            yield self.reply

    return FakeLLMAdapter()
