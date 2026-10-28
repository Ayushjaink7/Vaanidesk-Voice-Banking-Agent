"""End-to-end through HTTP: API -> agent -> bank -> MongoDB/Redis -> worker."""
from app import worker
from app.config import settings
from app.main import app, build_services
from app.storage import SUMMARY_QUEUE


async def start(api, phone="9876543210"):
    r = await api.post("/calls", json={"phone": phone})
    assert r.status_code == 201
    return r.json()["call_id"]


async def say(api, call_id, text):
    return await api.post(f"/calls/{call_id}/turns", json={"text": text})


async def test_full_call_with_summary_and_stats(api, db, redis):
    call_id = await start(api)

    r = (await say(api, call_id, "mera balance batao")).json()
    assert r["intent"] == "check_balance" and r["awaiting"] == "tpin" and r["language"] == "hinglish"

    r = (await say(api, call_id, "1234")).json()
    assert "₹45,230.50" in r["reply"] and r["action"] == "get_balance"
    assert r["transcript"] == "####"                       # the API never echoes the PIN
    assert set(r["latency_ms"]) == {"stt", "nlu", "agent_bank", "total"}

    r = (await say(api, call_id, "nahi, dhanyavad")).json()
    assert r["call_ended"]

    # Stored transcript has the PIN masked.
    call = await db.calls.find_one({"_id": call_id})
    customer_texts = [t["text"] for t in call["turns"] if t["role"] == "customer"]
    assert "1234" not in " ".join(customer_texts) and "####" in customer_texts
    assert call["status"] == "ended" and call["intents"] == ["check_balance"]

    # The worker picks the job from Redis and writes the summary.
    assert await redis.lrange(SUMMARY_QUEUE, 0, -1) == [call_id]
    assert await worker.handle_one(db, redis, llm=None, timeout=1) == call_id
    summary = (await api.get(f"/calls/{call_id}")).json()["summary"]
    assert summary["disposition"] == "resolved" and summary["sentiment"] == "positive"

    stats = (await api.get("/stats")).json()
    assert stats["resolution_rate"] == 1.0 and stats["intents"]["check_balance"] == 1
    assert stats["cached"] is False
    assert (await api.get("/stats")).json()["cached"] is True   # second read comes from Redis


async def test_unknown_phone_is_404(api):
    assert (await api.post("/calls", json={"phone": "1111111111"})).status_code == 404


async def test_cannot_talk_on_an_ended_call(api):
    call_id = await start(api)
    assert (await api.post(f"/calls/{call_id}/end")).status_code == 200
    assert (await say(api, call_id, "balance")).status_code == 409
    assert (await api.post(f"/calls/{call_id}/end")).status_code == 409


async def test_rate_limit(api, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    call_id = await start(api)
    codes = [(await say(api, call_id, "hello")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


async def test_audio_needs_api_key(api):
    call_id = await start(api)
    r = await api.post(f"/calls/{call_id}/audio", files={"file": ("a.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 503


async def test_audio_turn_with_transcription(db, redis, bank, fake_llm_factory, api):
    llm = fake_llm_factory(nlu_reply={"intent": "check_balance", "card_type": "none"},
                           transcript="मेरा बैलेंस बताइए")
    app.state.services = build_services(db, redis, bank, llm_client=llm)
    call_id = await start(api)
    r = await api.post(f"/calls/{call_id}/audio", data={"language": "hi"},
                       files={"file": ("a.webm", b"fake-audio", "audio/webm")})
    body = r.json()
    assert r.status_code == 200
    assert body["transcript"] == "मेरा बैलेंस बताइए" and body["language"] == "hi"
    assert body["nlu_source"] == "llm" and "TPIN" in body["reply"]
