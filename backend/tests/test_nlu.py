import json

import pytest

from app.nlu import NLU, detect_language, extract_tpin, mask_digits, rule_based_intent


def test_tpin_is_extracted_and_masked():
    assert extract_tpin("my tpin is 1234") == "1234"
    assert mask_digits("my tpin is 1234", tpin_found=True) == "my tpin is ####"
    assert extract_tpin("1 2 3 4") == "1234"
    assert extract_tpin("call 9876543210") is None          # a phone number is not a TPIN
    assert extract_tpin("१२३४") == "1234"                    # Devanagari digits


def test_spoken_tpin_only_counts_when_we_asked_for_it():
    # "do" means "give" in Hindi, so number words are only read while awaiting a TPIN
    assert extract_tpin("ek do teen char") is None
    assert extract_tpin("ek do teen char", awaiting="tpin") == "1234"
    assert extract_tpin("एक दो तीन चार", awaiting="tpin") == "1234"
    assert mask_digits("one two three four", tpin_found=True) == "[TPIN given as words - hidden]"


@pytest.mark.parametrize("text,lang", [
    ("मेरा बैलेंस बताइए", "hi"),
    ("mera card kho gaya hai", "hinglish"),
    ("what is my account balance", "en"),
    ("yes", None),        # too short to tell: keep the call's current language
    ("1234", None),
])
def test_language_detection(text, lang):
    assert detect_language(text) == lang


@pytest.mark.parametrize("text,intent", [
    ("what is my balance", "check_balance"),
    ("mera debit card kho gaya hai", "block_card"),
    ("meri EMI kab due hai", "emi_due"),
    ("show my last transactions", "recent_transactions"),
    ("मुझे किसी इंसान से बात करनी है", "talk_to_human"),
    ("thank you bye", "goodbye"),
    ("haan", "affirm"),
    ("debit wala", "provide_info"),
    ("what is the weather today", "unknown"),
])
def test_keyword_rules(text, intent):
    assert rule_based_intent(text) == intent


def test_yes_no_wins_while_confirming():
    # Contains "block", but while confirming a block, "no" is the answer.
    assert rule_based_intent("no don't block it", awaiting="confirm_block") == "deny"
    assert rule_based_intent("haan block kar do", awaiting="confirm_block") == "affirm"


async def test_llm_result_is_used_and_cached(redis, fake_llm_factory):
    llm = fake_llm_factory(nlu_reply={"intent": "block_card", "card_type": "debit"})
    nlu = NLU(redis, llm)

    first = await nlu.understand("someone used my debit card without asking me")
    assert (first.intent, first.card_type, first.source) == ("block_card", "debit", "llm")

    second = await nlu.understand("someone used my debit card without asking me")
    assert second.source == "cache"
    assert len(llm.calls) == 1               # the repeat came from Redis, not the LLM


async def test_tpin_never_reaches_the_llm(redis, fake_llm_factory):
    llm = fake_llm_factory(nlu_reply={"intent": "provide_info", "card_type": "none"})
    result = await NLU(redis, llm).understand("my tpin is 4321", awaiting="tpin")
    assert result.tpin == "4321"
    sent = json.dumps(llm.calls[0]["messages"])
    assert "4321" not in sent and "####" in sent


async def test_falls_back_to_rules_when_llm_fails(redis, fake_llm_factory):
    llm = fake_llm_factory(error=TimeoutError("LLM too slow"))
    result = await NLU(redis, llm).understand("mera balance batao")
    assert (result.intent, result.source) == ("check_balance", "rules")


async def test_falls_back_to_rules_on_invalid_llm_output(redis, fake_llm_factory):
    llm = fake_llm_factory(nlu_reply={"intent": "transfer_money", "card_type": "none"})  # not a valid intent
    result = await NLU(redis, llm).understand("mera balance batao")
    assert result.source == "rules"
