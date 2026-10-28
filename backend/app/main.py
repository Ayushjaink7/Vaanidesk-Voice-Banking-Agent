"""VaaniDesk API — a multilingual voice support agent for banking.

Endpoints (interactive docs at http://localhost:8000/docs):
  POST /calls                  start a call from the customer's phone number
  POST /calls/{id}/turns       customer says something (text)
  POST /calls/{id}/audio       customer says something (voice note -> Whisper)
  POST /calls/{id}/end         hang up; queues the post-call summary
  GET  /calls, /calls/{id}     call history with transcripts and summaries
  GET  /stats                  dashboard numbers (cached in Redis)
  GET  /customers/demo         demo phone numbers to call from
  GET  /health                 are MongoDB and Redis reachable?
"""
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from time import perf_counter

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .agent import Agent, new_session
from .bank_client import BankClient, BankNotFound, BankUnavailable
from .config import settings
from .nlu import NLU, mask_digits
from .replies import render
from .schemas import ACCOUNT_INTENTS, StartCallRequest, StartCallResponse, TurnRequest, TurnResponse
from .storage import (STATS_KEY, SUMMARY_QUEUE, allow_request, connect_mongo, connect_redis,
                      delete_session, ensure_indexes, load_session, save_session)
from .stt import SpeechToText

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # don't log every bank/LLM request
log = logging.getLogger("vaanidesk.api")


@dataclass
class Services:
    """Everything a request needs. Built once at startup; tests build their own."""
    db: object
    redis: object
    bank: BankClient
    nlu: NLU
    agent: Agent
    stt: SpeechToText | None


def build_services(db, redis, bank: BankClient, llm_client=None) -> Services:
    return Services(db=db, redis=redis, bank=bank, nlu=NLU(redis, llm_client), agent=Agent(bank),
                    stt=SpeechToText(llm_client) if llm_client else None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm = None
    if settings.groq_api_key:
        from groq import AsyncGroq
        llm = AsyncGroq(api_key=settings.groq_api_key)
    svc = build_services(connect_mongo(), connect_redis(), BankClient(), llm)
    await ensure_indexes(svc.db)
    app.state.services = svc
    log.info("VaaniDesk started (LLM: %s)", settings.llm_model if llm else "off, keyword rules only")
    yield
    await svc.bank.close()
    await svc.redis.aclose()


app = FastAPI(title="VaaniDesk API", version="1.0", lifespan=lifespan,
              description="Multilingual (English/Hindi/Hinglish) voice support agent for banking")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_methods=["*"], allow_headers=["*"])


def services(request: Request) -> Services:
    return request.app.state.services


async def rate_limited(request: Request) -> None:
    svc = services(request)
    client_id = request.client.host if request.client else "unknown"
    if not await allow_request(svc.redis, client_id, settings.rate_limit_per_minute):
        raise HTTPException(429, "Too many requests. Please slow down.")


def now() -> datetime:
    return datetime.now(timezone.utc)


def ms_since(start: float) -> float:
    return round((perf_counter() - start) * 1000, 1)


# ------------------------------------------------------------------ calls

@app.post("/calls", response_model=StartCallResponse, status_code=201)
async def start_call(body: StartCallRequest, svc: Services = Depends(services)):
    try:
        customer = await svc.bank.find_customer(body.phone)
    except BankNotFound:
        raise HTTPException(404, "No customer is registered with this phone number")
    except BankUnavailable:
        raise HTTPException(503, "Bank system is unavailable, please try again")

    call_id = uuid.uuid4().hex[:12]
    session = new_session(customer)
    greeting = render("welcome", {"name": customer["name"]}, session["language"])

    await svc.db.calls.insert_one({
        "_id": call_id,
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "phone_last4": body.phone[-4:],          # store only what we need (data minimisation)
        "status": "active",
        "started_at": now(),
        "ended_at": None,
        "language": session["language"],
        "intents": [],
        "turns": [{"role": "agent", "text": greeting, "reply_key": "welcome", "at": now()}],
        "resolved": [],
        "transferred": False,
        "summary": None,
    })
    await save_session(svc.redis, call_id, session)
    return StartCallResponse(call_id=call_id, customer_name=customer["name"], reply=greeting,
                             language=session["language"])


async def process_turn(svc: Services, call_id: str, text: str, stt_ms: float = 0.0) -> TurnResponse:
    """One customer turn: understand -> decide/act -> reply -> log."""
    start = perf_counter()
    session = await load_session(svc.redis, call_id)
    if session is None:
        call = await svc.db.calls.find_one({"_id": call_id}, {"status": 1})
        if not call:
            raise HTTPException(404, "Call not found")
        raise HTTPException(409, "This call has ended or timed out. Please start a new call.")

    t = perf_counter()
    nlu = await svc.nlu.understand(text, session["awaiting"])
    nlu_ms = ms_since(t)

    t = perf_counter()
    reply = await svc.agent.handle(session, nlu)
    agent_ms = ms_since(t)

    reply_text = render(reply.key, reply.params, session["language"])
    safe_text = mask_digits(text, tpin_found=bool(nlu.tpin))   # TPIN never stored
    latency = {"stt": round(stt_ms, 1), "nlu": nlu_ms, "agent_bank": agent_ms,
               "total": round(stt_ms + ms_since(start), 1)}

    customer_turn = {"role": "customer", "text": safe_text, "intent": nlu.intent, "card_type": nlu.card_type,
                     "language": nlu.language, "nlu_source": nlu.source, "at": now()}
    agent_turn = {"role": "agent", "text": reply_text, "reply_key": reply.key, "action": reply.action,
                  "latency_ms": latency, "at": now()}
    update = {"$push": {"turns": {"$each": [customer_turn, agent_turn]}},
              "$set": {"language": session["language"]}}
    if nlu.intent in ACCOUNT_INTENTS or nlu.intent == "talk_to_human":
        update["$addToSet"] = {"intents": nlu.intent}
    await svc.db.calls.update_one({"_id": call_id}, update)

    if reply.end_call:
        await finish_call(svc, call_id, session)
    else:
        await save_session(svc.redis, call_id, session)

    return TurnResponse(call_id=call_id, transcript=safe_text, reply=reply_text, intent=nlu.intent,
                        language=session["language"], nlu_source=nlu.source, action=reply.action,
                        awaiting=None if reply.end_call else session["awaiting"],
                        verified=session["verified"], call_ended=reply.end_call, latency_ms=latency)


async def finish_call(svc: Services, call_id: str, session: dict) -> None:
    await svc.db.calls.update_one({"_id": call_id, "status": "active"}, {"$set": {
        "status": "ended", "ended_at": now(), "resolved": session.get("resolved", []),
        "transferred": session.get("transferred", False), "verified": session.get("verified", False),
    }})
    await delete_session(svc.redis, call_id)
    await svc.redis.lpush(SUMMARY_QUEUE, call_id)   # the worker writes the summary
    await svc.redis.delete(STATS_KEY)


@app.post("/calls/{call_id}/turns", response_model=TurnResponse, dependencies=[Depends(rate_limited)])
async def text_turn(call_id: str, body: TurnRequest, svc: Services = Depends(services)):
    return await process_turn(svc, call_id, body.text.strip())


@app.post("/calls/{call_id}/audio", response_model=TurnResponse, dependencies=[Depends(rate_limited)])
async def audio_turn(call_id: str, file: UploadFile = File(...), language: str = Form("auto"),
                     svc: Services = Depends(services)):
    if svc.stt is None:
        raise HTTPException(503, "Voice input needs GROQ_API_KEY to be set on the server")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty audio file")
    if len(audio) > settings.max_audio_bytes:
        raise HTTPException(413, "Audio too long. Please keep voice notes under about a minute.")
    t = perf_counter()
    try:
        text = await svc.stt.transcribe(file.filename or "audio.webm", audio, language)
    except Exception as e:
        log.warning("transcription failed: %s", e)
        raise HTTPException(502, "Could not transcribe the audio, please try again")
    if not text:
        raise HTTPException(422, "Couldn't hear anything in the recording")
    return await process_turn(svc, call_id, text, stt_ms=ms_since(t))


@app.post("/calls/{call_id}/end")
async def end_call(call_id: str, svc: Services = Depends(services)):
    call = await svc.db.calls.find_one({"_id": call_id}, {"status": 1})
    if not call:
        raise HTTPException(404, "Call not found")
    if call["status"] != "active":
        raise HTTPException(409, "Call already ended")
    session = await load_session(svc.redis, call_id) or {}   # {} if the session expired
    await finish_call(svc, call_id, session)
    return {"call_id": call_id, "status": "ended", "summary": "queued"}


@app.get("/calls")
async def list_calls(limit: int = 20, status: str | None = None, svc: Services = Depends(services)):
    query = {"status": status} if status else {}
    cursor = svc.db.calls.find(query, {"turns": 0}).sort("started_at", -1).limit(min(limit, 100))
    return [doc async for doc in cursor]


@app.get("/calls/{call_id}")
async def get_call(call_id: str, svc: Services = Depends(services)):
    call = await svc.db.calls.find_one({"_id": call_id})
    if not call:
        raise HTTPException(404, "Call not found")
    return call


# ------------------------------------------------------------------ dashboard

@app.get("/stats")
async def stats(svc: Services = Depends(services)):
    cached = await svc.redis.get(STATS_KEY)
    if cached:
        return json.loads(cached) | {"cached": True}

    calls = svc.db.calls
    ended = await calls.count_documents({"status": "ended"})
    transferred = await calls.count_documents({"status": "ended", "transferred": True})
    resolved = await calls.count_documents({"status": "ended", "transferred": False,
                                            "resolved.0": {"$exists": True}})

    async def group_count(pipeline: list) -> dict:
        return {d["_id"]: d["count"] async for d in calls.aggregate(pipeline) if d["_id"] is not None}

    # Requests per call (balance, block card...), not every "yes" or TPIN turn.
    intents = await group_count([{"$unwind": "$intents"},
                                 {"$group": {"_id": "$intents", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}])
    languages = await group_count([{"$group": {"_id": "$language", "count": {"$sum": 1}}}])
    sentiment = await group_count([{"$match": {"summary": {"$ne": None}}},
                                   {"$group": {"_id": "$summary.sentiment", "count": {"$sum": 1}}}])
    nlu_sources = await group_count([
        {"$unwind": "$turns"}, {"$match": {"turns.role": "customer"}},
        {"$group": {"_id": "$turns.nlu_source", "count": {"$sum": 1}}}])

    # Latency percentiles over the most recent agent turns.
    recent = calls.find({}, {"turns.latency_ms": 1}).sort("started_at", -1).limit(200)
    totals = sorted([t["latency_ms"]["total"] async for c in recent for t in c["turns"] if "latency_ms" in t])

    def pct(p: float) -> float | None:
        return totals[min(len(totals) - 1, int(p * len(totals)))] if totals else None

    result = {
        "total_calls": await calls.count_documents({}),
        "active_calls": await calls.count_documents({"status": "active"}),
        "ended_calls": ended,
        "resolution_rate": round(resolved / ended, 3) if ended else None,
        "transfer_rate": round(transferred / ended, 3) if ended else None,
        "latency_ms": {"avg": round(mean(totals), 1) if totals else None, "p50": pct(0.5), "p95": pct(0.95)},
        "intents": intents,
        "languages": languages,
        "sentiment": sentiment,
        "nlu_sources": nlu_sources,
    }
    await svc.redis.set(STATS_KEY, json.dumps(result), ex=settings.stats_cache_ttl_seconds)
    return result | {"cached": False}


@app.get("/customers/demo")
async def demo_customers(svc: Services = Depends(services)):
    try:
        return await svc.bank.list_customers()
    except BankUnavailable:
        raise HTTPException(503, "Bank system is unavailable")


@app.get("/health")
async def health(svc: Services = Depends(services)):
    status = {"llm": "on" if svc.stt else "off (keyword rules)"}
    for name, check in (("mongo", lambda: svc.db.command("ping")), ("redis", lambda: svc.redis.ping())):
        try:
            await check()
            status[name] = "ok"
        except Exception as e:
            status[name] = f"error: {e.__class__.__name__}"
    return status
