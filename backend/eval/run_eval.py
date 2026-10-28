"""Measure how well VaaniDesk understands customers.

50 labelled utterances in English, Hindi and Hinglish (eval/utterances.jsonl).
Reports intent accuracy (overall and per language), card-type accuracy and latency.

Usage (from the backend folder):
  python -m eval.run_eval                 # keyword rules (no API key needed)
  python -m eval.run_eval --provider llm  # Groq LLM (needs GROQ_API_KEY in .env)
"""
import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter

from app.config import settings
from app.nlu import NLU

HERE = Path(__file__).parent


class NoCache:
    """Stand-in for Redis so every utterance really goes to the LLM."""
    async def get(self, key):
        return None

    async def set(self, key, value, ex=None):
        return None


async def run(provider: str) -> dict:
    llm = None
    if provider == "llm":
        if not settings.groq_api_key:
            raise SystemExit("Set GROQ_API_KEY in backend/.env to evaluate the LLM.")
        from groq import AsyncGroq
        llm = AsyncGroq(api_key=settings.groq_api_key)
    nlu = NLU(NoCache(), llm)

    rows = [json.loads(line) for line in (HERE / "utterances.jsonl").read_text(encoding="utf-8").splitlines() if line]
    by_lang, mistakes, latencies, fallbacks = defaultdict(lambda: [0, 0]), [], [], 0
    card_total = card_right = 0

    for row in rows:
        t = perf_counter()
        result = await nlu.understand(row["text"], row.get("awaiting"))
        latencies.append((perf_counter() - t) * 1000)
        if provider == "llm" and result.source != "llm":
            fallbacks += 1

        ok = result.intent == row["intent"]
        by_lang[row["language"]][0] += ok
        by_lang[row["language"]][1] += 1
        if not ok:
            mistakes.append({"text": row["text"], "expected": row["intent"], "got": result.intent})
        if "card_type" in row:
            card_total += 1
            card_right += result.card_type == row["card_type"]

    right = sum(r for r, _ in by_lang.values())
    latencies.sort()
    report = {
        "provider": provider if provider == "rules" else f"llm ({settings.llm_model})",
        "utterances": len(rows),
        "intent_accuracy": round(right / len(rows), 3),
        "accuracy_by_language": {lang: f"{r}/{n}" for lang, (r, n) in sorted(by_lang.items())},
        "card_type_accuracy": f"{card_right}/{card_total}",
        "latency_ms": {"avg": round(mean(latencies), 1), "p95": round(latencies[int(0.95 * len(latencies)) - 1], 1)},
        "llm_fallbacks": fallbacks,
        "mistakes": mistakes,
    }
    (HERE / f"results_{provider}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["rules", "llm"], default="rules")
    report = asyncio.run(run(parser.parse_args().provider))
    print(json.dumps(report, ensure_ascii=False, indent=2))
