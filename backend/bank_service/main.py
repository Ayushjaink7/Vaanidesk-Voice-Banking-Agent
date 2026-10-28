"""Mock core-banking API — stands in for a real bank's backend.

In a real deployment, the bank gives us an API like this and VaaniDesk
integrates with it. It runs as a separate service (port 8001) so the
agent has to talk to it over HTTP, with an API key, timeouts and retries,
exactly as it would with a client's system.

All data here is fake demo data.
"""
import asyncio
import os
import random
import uuid
from copy import deepcopy

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

API_KEY = os.getenv("BANK_API_KEY", "demo-bank-key")
# Set e.g. BANK_FAILURE_RATE=0.3 to see the agent's retries in action.
FAILURE_RATE = float(os.getenv("BANK_FAILURE_RATE", "0"))

SEED_CUSTOMERS = {
    "C1001": {
        "name": "Rahul Sharma", "phone": "9876543210", "tpin": "1234",
        "account_last4": "3021", "balance": 45230.50,
        "cards": {"debit": {"last4": "4821", "status": "active"},
                  "credit": {"last4": "7710", "status": "active"}},
        "loan": {"type": "Home loan", "emi": 18500.00, "due_date": "2026-11-05"},
        "transactions": [
            {"date": "2026-10-15", "desc": "UPI - Swiggy", "amount": -412.00},
            {"date": "2026-10-14", "desc": "Salary credit", "amount": 68000.00},
            {"date": "2026-10-12", "desc": "ATM withdrawal", "amount": -5000.00},
        ],
    },
    "C1002": {
        "name": "Priya Nair", "phone": "9123456780", "tpin": "4321",
        "account_last4": "7745", "balance": 128940.00,
        "cards": {"debit": {"last4": "3390", "status": "active"}},
        "loan": None,
        "transactions": [
            {"date": "2026-10-16", "desc": "NEFT - Rent", "amount": -22000.00},
            {"date": "2026-10-10", "desc": "UPI - Amazon", "amount": -1899.00},
        ],
    },
    "C1003": {
        "name": "Amit Verma", "phone": "9988776655", "tpin": "2580",
        "account_last4": "5509", "balance": 3215.75,
        "cards": {"debit": {"last4": "1187", "status": "active"},
                  "credit": {"last4": "6642", "status": "active"}},
        "loan": {"type": "Personal loan", "emi": 7250.00, "due_date": "2026-10-28"},
        "transactions": [
            {"date": "2026-10-16", "desc": "UPI - Electricity bill", "amount": -1340.00},
            {"date": "2026-10-11", "desc": "IMPS from Ravi", "amount": 2000.00},
        ],
    },
    "C1004": {
        "name": "Sunita Devi", "phone": "9000012345", "tpin": "7890",
        "account_last4": "8812", "balance": 12480.00,
        "cards": {"debit": {"last4": "5520", "status": "active"}},
        "loan": {"type": "Two-wheeler loan", "emi": 2150.00, "due_date": "2026-11-10"},
        "transactions": [
            {"date": "2026-10-13", "desc": "PM-KISAN credit", "amount": 2000.00},
            {"date": "2026-10-09", "desc": "UPI - Kirana store", "amount": -640.00},
        ],
    },
}

app = FastAPI(title="Mock Core Banking API", version="1.0")
CUSTOMERS = deepcopy(SEED_CUSTOMERS)


class TpinRequest(BaseModel):
    tpin: str


class BlockRequest(BaseModel):
    card_type: str


async def check_api_key_and_simulate(x_api_key: str | None = Header(default=None)):
    """Every endpoint: require the API key, add realistic latency, maybe fail."""
    if x_api_key != API_KEY:
        raise HTTPException(401, "invalid API key")
    await asyncio.sleep(random.uniform(0.03, 0.12))
    if random.random() < FAILURE_RATE:
        raise HTTPException(503, "core banking temporarily unavailable")


def get_customer(customer_id: str) -> dict:
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        raise HTTPException(404, "customer not found")
    return customer


router_deps = [Depends(check_api_key_and_simulate)]


@app.get("/customers", dependencies=router_deps)
async def list_demo_customers():
    """Demo-only helper so the UI can show which phone numbers to call from."""
    return [{"customer_id": cid, "name": c["name"], "phone": c["phone"]} for cid, c in CUSTOMERS.items()]


@app.get("/customers/by-phone/{phone}", dependencies=router_deps)
async def find_by_phone(phone: str):
    for cid, c in CUSTOMERS.items():
        if c["phone"] == phone:
            return {"customer_id": cid, "name": c["name"]}
    raise HTTPException(404, "no customer with this phone")


@app.post("/customers/{customer_id}/verify-tpin", dependencies=router_deps)
async def verify_tpin(customer_id: str, body: TpinRequest):
    return {"verified": get_customer(customer_id)["tpin"] == body.tpin}


@app.get("/customers/{customer_id}/balance", dependencies=router_deps)
async def balance(customer_id: str):
    c = get_customer(customer_id)
    return {"account_last4": c["account_last4"], "balance": c["balance"], "currency": "INR"}


@app.get("/customers/{customer_id}/emi", dependencies=router_deps)
async def emi(customer_id: str):
    loan = get_customer(customer_id)["loan"]
    if not loan:
        raise HTTPException(404, "no active loan")
    return {"loan_type": loan["type"], "emi_amount": loan["emi"], "due_date": loan["due_date"]}


@app.get("/customers/{customer_id}/transactions", dependencies=router_deps)
async def transactions(customer_id: str, limit: int = 3):
    return get_customer(customer_id)["transactions"][:limit]


@app.post("/customers/{customer_id}/cards/block", dependencies=router_deps)
async def block_card(customer_id: str, body: BlockRequest):
    card = get_customer(customer_id)["cards"].get(body.card_type)
    if not card:
        raise HTTPException(404, f"customer has no {body.card_type} card")
    if card["status"] == "blocked":
        raise HTTPException(409, "card already blocked")
    card["status"] = "blocked"
    return {"card_last4": card["last4"], "status": "blocked",
            "reference_id": "BLK" + uuid.uuid4().hex[:8].upper()}


@app.get("/customers/{customer_id}/cards", dependencies=router_deps)
async def cards(customer_id: str):
    return get_customer(customer_id)["cards"]


@app.post("/_reset")
async def reset():
    """Demo/test helper: restore the seed data (unblocks cards)."""
    CUSTOMERS.clear()
    CUSTOMERS.update(deepcopy(SEED_CUSTOMERS))
    return {"ok": True}
