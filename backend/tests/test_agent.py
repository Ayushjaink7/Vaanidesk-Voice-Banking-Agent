"""Conversation flows and guardrails, using the real mock bank."""
import bank_service.main as bank_app
from app.agent import Agent, new_session
from app.nlu import NLU

RAHUL = {"customer_id": "C1001", "name": "Rahul Sharma"}   # debit + credit card, home loan
PRIYA = {"customer_id": "C1002", "name": "Priya Nair"}     # debit card only, no loan


async def talk(agent, nlu, session, text):
    understood = await nlu.understand(text, session["awaiting"])
    return await agent.handle(session, understood)


async def test_balance_needs_tpin_first(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)

    r = await talk(agent, nlu, s, "what is my balance")
    assert r.key == "ask_tpin" and r.action is None          # no data before verification

    r = await talk(agent, nlu, s, "1234")
    assert r.key == "balance" and r.params["amount"] == "₹45,230.50"
    assert s["verified"] and s["resolved"] == ["check_balance"]

    r = await talk(agent, nlu, s, "meri EMI kab hai")        # already verified: no second TPIN
    assert r.key == "emi" and r.params["due"] == "2026-11-05"


async def test_three_wrong_tpins_transfer_to_human(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    await talk(agent, nlu, s, "balance batao")
    assert (await talk(agent, nlu, s, "1111")).params == {"left": 2}
    assert (await talk(agent, nlu, s, "2222")).params == {"left": 1}
    r = await talk(agent, nlu, s, "3333")
    assert r.key == "tpin_locked" and r.end_call and s["transferred"]


async def test_block_card_asks_type_then_confirms(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    assert (await talk(agent, nlu, s, "mera card kho gaya hai")).key == "ask_tpin"
    assert (await talk(agent, nlu, s, "1234")).key == "ask_card_type"     # Rahul has two cards
    r = await talk(agent, nlu, s, "credit wala")
    assert r.key == "confirm_block" and r.params["last4"] == "7710"
    assert bank_app.CUSTOMERS["C1001"]["cards"]["credit"]["status"] == "active"  # nothing done yet

    r = await talk(agent, nlu, s, "haan kar do")
    assert r.key == "card_blocked" and r.action == "block_card"
    assert bank_app.CUSTOMERS["C1001"]["cards"]["credit"]["status"] == "blocked"


async def test_saying_no_does_not_block(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    await talk(agent, nlu, s, "block my debit card")
    assert (await talk(agent, nlu, s, "1234")).key == "confirm_block"
    r = await talk(agent, nlu, s, "no don't block it")
    assert r.key == "block_cancelled" and r.action is None
    assert bank_app.CUSTOMERS["C1001"]["cards"]["debit"]["status"] == "active"


async def test_single_card_customer_is_not_asked_which_card(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(PRIYA)
    await talk(agent, nlu, s, "please block my card")
    r = await talk(agent, nlu, s, "4321")
    assert r.key == "confirm_block" and r.params == {"card": "debit", "last4": "3390"}


async def test_no_loan(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(PRIYA)
    await talk(agent, nlu, s, "when is my emi due")
    assert (await talk(agent, nlu, s, "4321")).key == "no_loan"


async def test_bank_outage_is_reported_not_guessed(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    await talk(agent, nlu, s, "balance")
    bank_app.FAILURE_RATE = 1.0                  # every bank call fails, even after retries
    r = await talk(agent, nlu, s, "1234")
    assert r.key == "bank_down"
    assert s["pending_intent"] == "check_balance"  # the request isn't lost; the customer can retry


async def test_three_unknowns_transfer_to_human(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    for _ in range(2):
        assert (await talk(agent, nlu, s, "what's the cricket score")).key == "didnt_understand"
    r = await talk(agent, nlu, s, "what's the cricket score")
    assert r.key == "too_many_unknown" and r.end_call


async def test_no_after_anything_else_ends_the_call(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    await talk(agent, nlu, s, "balance")
    await talk(agent, nlu, s, "1234")                 # reply ends with "Anything else?"
    r = await talk(agent, nlu, s, "nahi")
    assert r.key == "goodbye" and r.end_call


async def test_language_follows_the_customer(bank, redis):
    agent, nlu, s = Agent(bank), NLU(redis), new_session(RAHUL)
    await talk(agent, nlu, s, "मेरा बैलेंस बताइए")
    assert s["language"] == "hi"
    await talk(agent, nlu, s, "1234")                 # digits only: language stays Hindi
    assert s["language"] == "hi"
