"""Request/response shapes (Pydantic) and the NLU result.

FastAPI uses these to validate incoming JSON and to document the API
automatically at /docs.
"""
from typing import Literal

from pydantic import BaseModel, Field

# Everything the customer might want. The first four touch the bank account,
# so they need identity verification first.
ACCOUNT_INTENTS = ("check_balance", "emi_due", "block_card", "recent_transactions")
INTENTS = ACCOUNT_INTENTS + (
    "talk_to_human",
    "greeting",
    "goodbye",
    "affirm",        # "yes", "haan", "theek hai"
    "deny",          # "no", "nahi", "rehne do"
    "provide_info",  # only gives a detail, e.g. "debit wala" or "1234"
    "unknown",
)

Intent = Literal[INTENTS]
Language = Literal["en", "hi", "hinglish"]


class NLUResult(BaseModel):
    """What we understood from one customer utterance."""
    intent: Intent
    card_type: Literal["debit", "credit"] | None = None
    tpin: str | None = None          # extracted locally by regex, never by the LLM
    language: Language | None = None # None = too short to tell ("yes", "1234")
    source: Literal["llm", "rules", "cache"] = "rules"


class StartCallRequest(BaseModel):
    phone: str = Field(..., examples=["9876543210"], description="Caller ID of the customer")


class TurnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, examples=["mera debit card block karna hai"])


class TurnResponse(BaseModel):
    call_id: str
    transcript: str            # what the customer said (TPIN masked)
    reply: str                 # what the agent says back
    intent: str
    language: str
    nlu_source: str
    action: str | None         # bank action taken this turn, if any
    awaiting: str | None       # what the agent is waiting for next
    verified: bool             # has the TPIN check passed on this call?
    call_ended: bool
    latency_ms: dict[str, float]


class StartCallResponse(BaseModel):
    call_id: str
    customer_name: str
    reply: str
    language: str
