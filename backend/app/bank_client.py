"""Async client for the bank's API.

This is the "integration" part of a forward-deployed engineer's job:
talk to the client's system safely. Every call has
  - an API key header,
  - a timeout (a slow bank must not freeze a live call),
  - retries with backoff for temporary failures (timeouts, 5xx),
  - no retries for real answers like 404 "no loan".
"""
import asyncio

import httpx

from .config import settings


class BankUnavailable(Exception):
    """The bank didn't answer after all retries."""


class BankNotFound(Exception):
    """The bank answered 404 (e.g. no loan, no such card)."""


class BankConflict(Exception):
    """The bank answered 409 (e.g. card already blocked)."""


class BankClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        # `transport` lets tests plug the bank app in directly, without a network.
        self.http = httpx.AsyncClient(
            base_url=base_url or settings.bank_api_url,
            headers={"X-API-Key": settings.bank_api_key},
            timeout=settings.bank_timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        last_error = None
        for attempt in range(settings.bank_max_retries + 1):
            try:
                resp = await self.http.request(method, path, **kwargs)
            except httpx.TransportError as e:          # timeout, connection refused...
                last_error = e
            else:
                if resp.status_code == 404:
                    raise BankNotFound(resp.json().get("detail", "not found"))
                if resp.status_code == 409:
                    raise BankConflict(resp.json().get("detail", "conflict"))
                if resp.status_code < 500:
                    resp.raise_for_status()           # 401 etc. is our bug: fail loudly
                    return resp.json()
                last_error = RuntimeError(f"bank returned {resp.status_code}")
            if attempt < settings.bank_max_retries:
                await asyncio.sleep(0.2 * 2 ** attempt)  # 0.2s, 0.4s, ...
        raise BankUnavailable(str(last_error))

    async def list_customers(self) -> list:
        return await self._request("GET", "/customers")

    async def find_customer(self, phone: str) -> dict:
        return await self._request("GET", f"/customers/by-phone/{phone}")

    async def verify_tpin(self, customer_id: str, tpin: str) -> bool:
        data = await self._request("POST", f"/customers/{customer_id}/verify-tpin", json={"tpin": tpin})
        return bool(data["verified"])

    async def get_balance(self, customer_id: str) -> dict:
        return await self._request("GET", f"/customers/{customer_id}/balance")

    async def get_emi(self, customer_id: str) -> dict:
        return await self._request("GET", f"/customers/{customer_id}/emi")

    async def get_transactions(self, customer_id: str, limit: int = 3) -> list:
        return await self._request("GET", f"/customers/{customer_id}/transactions", params={"limit": limit})

    async def get_cards(self, customer_id: str) -> dict:
        return await self._request("GET", f"/customers/{customer_id}/cards")

    async def block_card(self, customer_id: str, card_type: str) -> dict:
        return await self._request("POST", f"/customers/{customer_id}/cards/block", json={"card_type": card_type})
