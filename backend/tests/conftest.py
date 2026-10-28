"""Test fixtures: everything runs in memory, no MongoDB/Redis/Groq needed.

- MongoDB  -> mongomock-motor (in-memory fake with the same async API)
- Redis    -> fakeredis
- Bank API -> the real mock bank app, called through httpx's ASGI transport
- LLM      -> a small fake object that returns the JSON we choose
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from fakeredis import aioredis
from mongomock_motor import AsyncMongoMockClient

import bank_service.main as bank_app
from app.bank_client import BankClient
from app.main import app, build_services


@pytest.fixture
def redis():
    return aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def db():
    return AsyncMongoMockClient()["vaanidesk_test"]


@pytest.fixture
async def bank():
    await bank_app.reset()
    bank_app.FAILURE_RATE = 0.0
    client = BankClient(base_url="http://bank", transport=httpx.ASGITransport(app=bank_app.app))
    yield client
    bank_app.FAILURE_RATE = 0.0
    await client.close()


class FakeLLM:
    """Mimics groq.AsyncGroq: client.chat.completions.create(...) and client.audio.transcriptions.create(...)."""

    def __init__(self, nlu_reply=None, error=None, transcript="mera balance batao"):
        self.nlu_reply, self.error, self.transcript = nlu_reply, error, transcript
        self.calls = []  # every chat request we received
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcribe))

    async def _chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = self.nlu_reply if isinstance(self.nlu_reply, str) else json.dumps(self.nlu_reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    async def _transcribe(self, **kwargs):
        return SimpleNamespace(text=self.transcript)


@pytest.fixture
def fake_llm_factory():
    return FakeLLM


@pytest.fixture
async def api(db, redis, bank):
    """HTTP client for the VaaniDesk API, wired to the in-memory services (rules-only NLU)."""
    app.state.services = build_services(db, redis, bank, llm_client=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
