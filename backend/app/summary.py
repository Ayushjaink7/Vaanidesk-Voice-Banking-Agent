"""Post-call summary: what happened, how the customer felt, any follow-up.

Runs in the background worker after a call ends, so the live call never
waits for it. The outcome (disposition) is computed from facts in code;
the LLM only writes the summary text and judges sentiment.
"""
import json
import logging
from datetime import datetime, timezone

from .config import settings
from .prompts import SUMMARY_JSON_SCHEMA, SUMMARY_SYSTEM_PROMPT

log = logging.getLogger("vaanidesk.summary")

NEGATIVE_WORDS = ["angry", "worst", "frustrat", "useless", "bad service", "complain", "fraud",
                  "pareshan", "gussa", "bakwas", "bekar", "परेशान", "गुस्सा", "बेकार"]
POSITIVE_WORDS = ["thank", "great", "helpful", "dhanyavad", "shukriya", "badhiya", "धन्यवाद", "शुक्रिया"]

READABLE = {"check_balance": "balance enquiry", "emi_due": "EMI enquiry", "block_card": "card block",
            "recent_transactions": "recent transactions", "talk_to_human": "human agent"}


def disposition(call: dict) -> str:
    if call.get("transferred"):
        return "transferred"
    return "resolved" if call.get("resolved") else "unresolved"


def rule_based_summary(call: dict) -> dict:
    customer_text = " ".join(t["text"].lower() for t in call["turns"] if t["role"] == "customer")
    if any(w in customer_text for w in NEGATIVE_WORDS):
        sentiment = "negative"
    elif any(w in customer_text for w in POSITIVE_WORDS):
        sentiment = "positive"
    else:
        sentiment = "neutral"
    asked = ", ".join(READABLE.get(i, i) for i in call.get("intents", [])) or "no clear request"
    outcome = disposition(call)
    return {
        "summary": f"Customer asked about: {asked}. Outcome: {outcome}.",
        "sentiment": sentiment,
        "follow_up": "Call back the customer" if outcome != "resolved" else "none",
    }


async def llm_summary(llm, call: dict) -> dict:
    transcript = "\n".join(f"{t['role']}: {t['text']}" for t in call["turns"])
    resp = await llm.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                  {"role": "user", "content": f"Outcome: {disposition(call)}\n\nTranscript:\n{transcript}"}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "call_summary", "strict": True, "schema": SUMMARY_JSON_SCHEMA}},
        temperature=0,
        reasoning_effort="low",
        include_reasoning=False,
        timeout=settings.llm_timeout_seconds,
    )
    data = json.loads(resp.choices[0].message.content)
    if data.get("sentiment") not in ("positive", "neutral", "negative") or not data.get("summary"):
        raise ValueError(f"bad summary JSON: {data}")
    return {"summary": data["summary"], "sentiment": data["sentiment"],
            "follow_up": data.get("follow_up") or "none"}


async def summarize_call(db, llm, call_id: str) -> dict | None:
    call = await db.calls.find_one({"_id": call_id})
    if not call or call.get("summary"):        # missing, or already done (job ran twice)
        return None

    result, source = None, "rules"
    if llm is not None:
        try:
            result, source = await llm_summary(llm, call), "llm"
        except Exception as e:
            log.warning("LLM summary failed for %s, using rules: %s", call_id, e)
    if result is None:
        result = rule_based_summary(call)

    result.update(disposition=disposition(call), source=source)
    await db.calls.update_one({"_id": call_id},
                              {"$set": {"summary": result, "summarized_at": datetime.now(timezone.utc)}})
    return result
