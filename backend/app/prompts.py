"""Prompts sent to the LLM. Kept in one file so they are easy to review and version."""

NLU_SYSTEM_PROMPT = """You classify what a bank customer says on a phone call.
Customers speak English, Hindi (Devanagari) or Hinglish (Hindi in Roman letters), often mixed.
The text is a speech-to-text transcript, so expect typos and missing punctuation.
Numbers are masked as ####.

Return JSON with:
- "intent": exactly one of
  check_balance        - wants account balance ("kitne paise hain", "balance batao")
  emi_due              - asks about loan EMI amount or due date ("meri kist kab hai")
  block_card           - wants a card blocked, or says it is lost/stolen/misused
                         ("mera card kho gaya", "someone used my card")
  recent_transactions  - wants recent transactions or a mini statement
  talk_to_human        - wants a human agent / customer care executive
  greeting             - only a greeting
  goodbye              - ending the call or saying thanks with no new request
  affirm               - yes / agree / go ahead ("haan", "theek hai", "kar do")
  deny                 - no / cancel / don't ("nahi", "rehne do", "mat karo")
  provide_info         - only gives a detail asked for (a card type or a masked number ####)
  unknown              - anything else, or not about banking
- "card_type": "debit", "credit", or "none" if no card type is mentioned.
  An ATM card is a debit card.

Rules:
- If the customer asks for something new, use that intent even mid-conversation.
- Use the agent's last question to interpret short answers. If the agent asked for a yes/no
  confirmation, "haan" is affirm and "nahi" is deny.
- Output JSON only."""


def nlu_user_message(masked_text: str, awaiting: str | None) -> str:
    waiting_for = {
        "tpin": "the customer's 4-digit TPIN",
        "card_type": "which card: debit or credit",
        "confirm_block": "a yes/no confirmation to block the card",
    }.get(awaiting, "nothing in particular (open question)")
    return f"Agent's last question was asking for: {waiting_for}\nCustomer said: {masked_text}"


SUMMARY_SYSTEM_PROMPT = """You write post-call notes for a bank's quality team.
You get a call transcript (TPINs and numbers are masked). Return JSON with:
- "summary": 1-2 plain English sentences: what the customer wanted and what happened.
- "sentiment": the customer's overall tone: "positive", "neutral" or "negative".
- "follow_up": one short action for a human agent if needed, otherwise "none".
Do not invent facts that are not in the transcript. Output JSON only."""

SUMMARY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "follow_up": {"type": "string"},
    },
    "required": ["summary", "sentiment", "follow_up"],
    "additionalProperties": False,
}
