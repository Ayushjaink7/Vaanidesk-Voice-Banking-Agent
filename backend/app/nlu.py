"""Understanding what the customer said (NLU = natural language understanding).

Pipeline for one utterance:
  1. Pull the TPIN out locally with a regex, then MASK all digits.
     The PIN never reaches the LLM, the cache, or the database.
  2. Detect the language locally (Devanagari -> Hindi, Hinglish words -> Hinglish).
  3. Get the intent:
       - Redis cache hit for this exact (masked) phrase -> reuse it
       - else ask the LLM for strict JSON (intent + card type)
       - if the LLM is missing, slow, or returns bad JSON -> keyword rules
"""
import hashlib
import json
import logging
import re

from pydantic import ValidationError

from .config import settings
from .prompts import NLU_SYSTEM_PROMPT, nlu_user_message
from .schemas import INTENTS, NLUResult

log = logging.getLogger("vaanidesk.nlu")

# ---------------------------------------------------------------- TPIN + masking

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Spoken digits (used only while the agent is waiting for a TPIN,
# because words like "do" also mean "give" in Hindi).
NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "saat": "7", "aath": "8", "nau": "9",
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
}

# 4+ digits, optionally separated by spaces or hyphens ("1 2 3 4", "12-34")
DIGIT_RUN = re.compile(r"(?<!\d)\d(?:[\s-]?\d){3,}(?!\d)")


def _words_to_digits(text: str) -> str:
    # Split on spaces/punctuation (not \w: Hindi vowel signs aren't "word" characters).
    tokens = re.findall(r"[^\s,.;!?।]+|[\s,.;!?।]+", text)
    return "".join(NUMBER_WORDS.get(t.lower(), t) for t in tokens)


def extract_tpin(text: str, awaiting: str | None = None) -> str | None:
    """Return a 4-digit TPIN if the text contains exactly one 4-digit number."""
    candidate = text.translate(DEVANAGARI_DIGITS)
    if awaiting == "tpin":
        candidate = _words_to_digits(candidate)
    runs = [re.sub(r"[\s-]", "", m) for m in DIGIT_RUN.findall(candidate)]
    four_digit = [r for r in runs if len(r) == 4]
    return four_digit[0] if len(four_digit) == 1 else None


def mask_digits(text: str, tpin_found: bool = False) -> str:
    """Hide numbers before text is sent to the LLM or stored."""
    masked = DIGIT_RUN.sub("####", text.translate(DEVANAGARI_DIGITS))
    if tpin_found and "####" not in masked:
        # The PIN was spoken as words ("one two three four"): hide the whole turn.
        return "[TPIN given as words - hidden]"
    return masked


# ---------------------------------------------------------------- language

HINGLISH_MARKERS = {
    "hai", "hain", "mera", "meri", "mere", "mujhe", "karna", "karo", "kya", "kitna", "kitne",
    "kab", "nahi", "nahin", "haan", "ji", "wala", "wali", "batao", "bataiye", "chahiye",
    "paisa", "paise", "gaya", "gayi", "kho", "aur", "bhai", "theek", "thik", "accha", "acha",
    "dijiye", "hua", "bacha", "bache", "abhi", "bhi", "kijiye", "karwana", "rehne", "kar",
}


def detect_language(text: str) -> str | None:
    """'hi', 'hinglish', 'en', or None when the utterance is too short to tell."""
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    if any(w in HINGLISH_MARKERS for w in words):
        return "hinglish"
    return "en" if len(words) >= 3 else None


# ---------------------------------------------------------------- keyword rules

KEYWORDS = {
    "talk_to_human": ["human", "agent", "customer care", "representative", "real person", "executive",
                      "kisi se baat", "insaan", "इंसान", "एजेंट", "अधिकारी"],
    "block_card": ["block", "lost", "stolen", "freeze", "chori", "kho gaya", "kho gayi", "band kar",
                   "ब्लॉक", "खो", "चोरी", "बंद कर"],
    "emi_due": ["emi", "installment", "instalment", "kist", "kisht", "loan", "ईएमआई", "किस्त", "लोन"],
    "recent_transactions": ["transaction", "statement", "recent payment", "last payment", "len den",
                            "lenden", "ट्रांजैक्शन", "लेनदेन", "स्टेटमेंट"],
    "check_balance": ["balance", "how much money", "kitna paisa", "kitne paise", "paise kitne",
                      "बैलेंस", "कितने पैसे", "कितना पैसा"],
    "goodbye": ["bye", "goodbye", "thank you", "thanks", "that's all", "dhanyavad", "shukriya",
                "bas itna", "धन्यवाद", "शुक्रिया"],
    "greeting": ["hello", "hi", "hey", "namaste", "namaskar", "good morning", "नमस्ते", "नमस्कार"],
    "affirm": ["yes", "yeah", "yep", "sure", "confirm", "go ahead", "haan", "han", "ok", "okay",
               "theek hai", "thik hai", "kar do", "हाँ", "हां", "ठीक है", "कर दो"],
    "deny": ["no", "nope", "don't", "dont", "cancel", "nahi", "nahin", "mat", "rehne do",
             "नहीं", "मत", "रहने दो"],
}


def _has(text: str, phrase: str) -> bool:
    if re.fullmatch(r"[a-z']+", phrase):              # single English/Roman word: whole word (+ plural)
        return re.search(rf"\b{re.escape(phrase)}(s|es)?\b", text) is not None
    return phrase in text                               # multi-word or Devanagari: substring


def find_card_type(text: str) -> str | None:
    t = text.lower()
    if "debit" in t or "atm card" in t or "डेबिट" in t:
        return "debit"
    if "credit" in t or "क्रेडिट" in t:
        return "credit"
    return None


def rule_based_intent(text: str, awaiting: str | None = None, tpin: str | None = None) -> str:
    t = text.lower()
    matches = lambda intent: any(_has(t, p) for p in KEYWORDS[intent])

    # While waiting for a yes/no, a yes/no answer wins over everything else.
    if awaiting == "confirm_block":
        if matches("deny"):
            return "deny"
        if matches("affirm"):
            return "affirm"
    if awaiting == "tpin" and tpin:
        return "provide_info"

    for intent in ("talk_to_human", "block_card", "emi_due", "recent_transactions",
                   "check_balance", "goodbye", "greeting", "affirm", "deny"):
        if matches(intent):
            return intent
    if find_card_type(t) or tpin:
        return "provide_info"
    return "unknown"


# ---------------------------------------------------------------- the NLU service

NLU_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "card_type": {"type": "string", "enum": ["debit", "credit", "none"]},
    },
    "required": ["intent", "card_type"],
    "additionalProperties": False,
}


class NLU:
    def __init__(self, redis, llm_client=None):
        self.redis = redis
        self.llm = llm_client  # an AsyncGroq client, or None for rules-only

    async def understand(self, text: str, awaiting: str | None = None) -> NLUResult:
        tpin = extract_tpin(text, awaiting)
        masked = mask_digits(text, tpin_found=bool(tpin))
        language = detect_language(text)

        intent, card_type, source = await self._intent(masked, awaiting, tpin)
        return NLUResult(intent=intent, card_type=card_type or find_card_type(masked),
                         tpin=tpin, language=language, source=source)

    async def _intent(self, masked: str, awaiting: str | None, tpin: str | None):
        if self.llm is not None:
            key = "nlu:" + hashlib.sha256(f"{awaiting}|{masked.lower().strip()}".encode()).hexdigest()
            cached = await self.redis.get(key)
            if cached:
                data = json.loads(cached)
                return data["intent"], data["card_type"], "cache"
            try:
                intent, card_type = await self._ask_llm(masked, awaiting)
                await self.redis.set(key, json.dumps({"intent": intent, "card_type": card_type}),
                                     ex=settings.nlu_cache_ttl_seconds)
                return intent, card_type, "llm"
            except Exception as e:  # timeout, API error, bad JSON: never break the call
                log.warning("LLM NLU failed, using rules: %s", e)
        return rule_based_intent(masked, awaiting, tpin), None, "rules"

    async def _ask_llm(self, masked: str, awaiting: str | None):
        resp = await self.llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": NLU_SYSTEM_PROMPT},
                      {"role": "user", "content": nlu_user_message(masked, awaiting)}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "nlu_result", "strict": True, "schema": NLU_JSON_SCHEMA}},
            temperature=0,
            reasoning_effort="low",
            include_reasoning=False,
            timeout=settings.llm_timeout_seconds,
        )
        data = json.loads(resp.choices[0].message.content)
        try:
            # Validate even though the schema is strict: never trust model output blindly.
            result = NLUResult(intent=data["intent"],
                               card_type=None if data["card_type"] == "none" else data["card_type"])
        except (KeyError, ValidationError) as e:
            raise ValueError(f"LLM returned invalid NLU JSON: {data}") from e
        return result.intent, result.card_type
