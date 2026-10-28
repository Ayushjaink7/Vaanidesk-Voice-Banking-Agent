"""Speech-to-text with Whisper (via Groq)."""
from .config import settings

# A short prompt "biases" Whisper towards words we expect on a banking call,
# which helps with domain terms and Hinglish (contextual biasing).
BIAS_PROMPT = ("Bank customer care call. Words: balance, EMI, TPIN, debit card, credit card, "
               "block, transaction, statement, loan, haan, nahi, theek hai.")


class SpeechToText:
    def __init__(self, groq_client):
        self.client = groq_client

    async def transcribe(self, filename: str, audio: bytes, language: str = "auto") -> str:
        kwargs = {"language": language} if language in ("en", "hi") else {}
        resp = await self.client.audio.transcriptions.create(
            file=(filename, audio),
            model=settings.stt_model,
            prompt=BIAS_PROMPT,
            temperature=0,
            response_format="json",
            timeout=20,
            **kwargs,
        )
        return resp.text.strip()
