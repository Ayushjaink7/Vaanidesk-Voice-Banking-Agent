"""The dialogue manager: decides what to do after each customer turn.

It is a small state machine. The session (stored in Redis) remembers:
  pending_intent  the task in progress (e.g. block_card)
  awaiting        what we just asked for: "tpin", "card_type" or "confirm_block"
  verified        whether the TPIN check passed on this call

Guardrails enforced in code (not left to the LLM):
  1. No account data or action before the TPIN is verified.
  2. Three wrong TPINs -> stop and transfer to a human.
  3. Blocking a card needs an explicit "yes" after we read back the card.
  4. Three "didn't understand" turns in a row -> transfer to a human.
  5. If the bank API is down, say so; never guess an answer.
"""
from dataclasses import dataclass, field

from .bank_client import BankClient, BankConflict, BankNotFound, BankUnavailable
from .config import settings
from .replies import inr
from .schemas import ACCOUNT_INTENTS, NLUResult


@dataclass
class AgentReply:
    key: str                         # which reply template to use
    params: dict = field(default_factory=dict)
    action: str | None = None        # bank action performed, for the call log
    end_call: bool = False


def new_session(customer: dict) -> dict:
    return {
        "customer_id": customer["customer_id"],
        "customer_name": customer["name"],
        "language": "en",
        "verified": False,
        "tpin_attempts": 0,
        "pending_intent": None,
        "awaiting": None,
        "card_type": None,
        "card_last4": None,
        "unknown_streak": 0,
        "resolved": [],          # tasks completed on this call
        "transferred": False,
    }


class Agent:
    def __init__(self, bank: BankClient):
        self.bank = bank

    async def handle(self, s: dict, nlu: NLUResult) -> AgentReply:
        if nlu.language:                 # keep the last language we could detect
            s["language"] = nlu.language
        if nlu.card_type:
            s["card_type"] = nlu.card_type
        intent = nlu.intent

        if intent == "unknown" and not nlu.tpin:
            s["unknown_streak"] += 1
            if s["unknown_streak"] >= 3:
                s["transferred"] = True
                return AgentReply("too_many_unknown", action="transfer_to_human", end_call=True)
        else:
            s["unknown_streak"] = 0

        if intent == "goodbye":
            return AgentReply("goodbye", end_call=True)
        if intent == "talk_to_human":
            s["transferred"] = True
            return AgentReply("transfer", action="transfer_to_human", end_call=True)

        if intent in ACCOUNT_INTENTS and intent != s["pending_intent"]:
            # A new request: start that task (even if another one was half done).
            s["pending_intent"] = intent
            s["awaiting"] = None
            if intent == "block_card":
                s["card_type"], s["card_last4"] = nlu.card_type, None

        if s["pending_intent"] is None:
            # Nothing in progress, so this is small talk or an answer to "Anything else?"
            if intent == "greeting":
                return AgentReply("greet_back")
            if intent == "deny":                 # "Anything else?" -> "No"
                return AgentReply("goodbye", end_call=True)
            if intent == "affirm":               # "Anything else?" -> "Yes"
                return AgentReply("how_can_help")
            return AgentReply("didnt_understand")

        try:
            return await self._continue_task(s, nlu)
        except BankUnavailable:
            return AgentReply("bank_down")

    async def _continue_task(self, s: dict, nlu: NLUResult) -> AgentReply:
        # Guardrail 1 + 2: verify identity before touching the account.
        if not s["verified"]:
            if not nlu.tpin:
                s["awaiting"] = "tpin"
                return AgentReply("ask_tpin")
            if await self.bank.verify_tpin(s["customer_id"], nlu.tpin):
                s["verified"] = True
                s["awaiting"] = None
            else:
                s["tpin_attempts"] += 1
                left = settings.max_tpin_attempts - s["tpin_attempts"]
                if left <= 0:
                    s["transferred"] = True
                    s["awaiting"] = None
                    return AgentReply("tpin_locked", action="transfer_to_human", end_call=True)
                s["awaiting"] = "tpin"
                return AgentReply("tpin_wrong", {"left": left})

        cid, task = s["customer_id"], s["pending_intent"]

        if task == "check_balance":
            bal = await self.bank.get_balance(cid)
            self._finish(s)
            return AgentReply("balance", {"acct": bal["account_last4"], "amount": inr(bal["balance"])},
                              action="get_balance")

        if task == "emi_due":
            try:
                emi = await self.bank.get_emi(cid)
            except BankNotFound:
                self._finish(s)
                return AgentReply("no_loan", action="get_emi")
            self._finish(s)
            return AgentReply("emi", {"loan": emi["loan_type"], "amount": inr(emi["emi_amount"]),
                                      "due": emi["due_date"]}, action="get_emi")

        if task == "recent_transactions":
            txns = await self.bank.get_transactions(cid, limit=3)
            lines = "; ".join(f"{t['date'][8:]}/{t['date'][5:7]}: {t['desc']} {inr(t['amount'])}" for t in txns)
            self._finish(s)
            return AgentReply("transactions", {"n": len(txns), "lines": lines}, action="get_transactions")

        return await self._block_card(s, nlu)

    async def _block_card(self, s: dict, nlu: NLUResult) -> AgentReply:
        cid = s["customer_id"]

        if s["awaiting"] == "confirm_block":
            # Guardrail 3: only an explicit yes blocks the card.
            if nlu.intent == "affirm":
                try:
                    res = await self.bank.block_card(cid, s["card_type"])
                except BankConflict:          # already blocked (or our retry already succeeded)
                    reply = AgentReply("card_already_blocked", {"card": s["card_type"], "last4": s["card_last4"]})
                    self._finish(s)
                    return reply
                reply = AgentReply("card_blocked", {"card": s["card_type"], "last4": res["card_last4"],
                                                    "ref": res["reference_id"]}, action="block_card")
                self._finish(s)
                return reply
            if nlu.intent == "deny":
                self._finish(s, resolved=False)
                return AgentReply("block_cancelled")
            return AgentReply("confirm_block", {"card": s["card_type"], "last4": s["card_last4"]})

        cards = await self.bank.get_cards(cid)
        if not s["card_type"]:
            if len(cards) == 1:                       # only one card: no need to ask
                s["card_type"] = next(iter(cards))
            else:
                s["awaiting"] = "card_type"
                return AgentReply("ask_card_type")

        card = cards.get(s["card_type"])
        if not card:
            reply = AgentReply("no_such_card", {"card": s["card_type"]})
            self._finish(s, resolved=False)
            return reply

        s["card_last4"] = card["last4"]
        s["awaiting"] = "confirm_block"
        return AgentReply("confirm_block", {"card": s["card_type"], "last4": card["last4"]})

    @staticmethod
    def _finish(s: dict, resolved: bool = True) -> None:
        if resolved:
            s["resolved"].append(s["pending_intent"])
        s["pending_intent"] = s["awaiting"] = s["card_type"] = s["card_last4"] = None
