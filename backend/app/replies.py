"""What the agent says, in English, Hindi and Hinglish.

Replies are templates filled with data from the bank API. The LLM never
writes the reply, so it can never invent a balance or a due date:
the LLM understands, the code decides and speaks.
"""
from datetime import date

TEMPLATES = {
    "welcome": {
        "en": "Namaste {name}, welcome to Demo Bank. I can help with your balance, EMI, recent transactions or blocking a card. You can speak in English or Hindi. How can I help?",
        "hinglish": "Namaste {name}, Demo Bank mein aapka swagat hai. Main balance, EMI, recent transactions ya card block karne mein madad kar sakta hoon. Aap English ya Hindi mein baat kar sakte hain. Bataiye, kya madad karoon?",
        "hi": "नमस्ते {name}, डेमो बैंक में आपका स्वागत है। मैं बैलेंस, ईएमआई, हाल के लेनदेन या कार्ड ब्लॉक करने में मदद कर सकता हूँ। आप अंग्रेज़ी या हिंदी में बात कर सकते हैं। बताइए, क्या मदद करूँ?",
    },
    "how_can_help": {
        "en": "Sure. What would you like to do: check balance, EMI details, recent transactions, or block a card?",
        "hinglish": "Ji zaroor. Aap kya karna chahenge: balance, EMI, recent transactions ya card block?",
        "hi": "जी ज़रूर। आप क्या करना चाहेंगे: बैलेंस, ईएमआई, हाल के लेनदेन या कार्ड ब्लॉक?",
    },
    "greet_back": {
        "en": "Hello! How can I help you today?",
        "hinglish": "Namaste! Bataiye, main aapki kya madad kar sakta hoon?",
        "hi": "नमस्ते! बताइए, मैं आपकी क्या मदद कर सकता हूँ?",
    },
    "didnt_understand": {
        "en": "Sorry, I didn't get that. I can help with your balance, EMI, recent transactions or blocking a card.",
        "hinglish": "Maaf kijiye, main samajh nahi paaya. Main balance, EMI, recent transactions ya card block karne mein madad kar sakta hoon.",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। मैं बैलेंस, ईएमआई, हाल के लेनदेन या कार्ड ब्लॉक करने में मदद कर सकता हूँ।",
    },
    "ask_tpin": {
        "en": "For your security, please tell me your 4-digit TPIN.",
        "hinglish": "Aapki suraksha ke liye, kripya apna 4 digit TPIN bataiye.",
        "hi": "आपकी सुरक्षा के लिए, कृपया अपना 4 अंकों का TPIN बताइए।",
    },
    "tpin_wrong": {
        "en": "That TPIN didn't match. You have {left} attempt(s) left. Please try again.",
        "hinglish": "TPIN match nahi hua. Aapke paas {left} attempt bache hain. Kripya dobara bataiye.",
        "hi": "TPIN मेल नहीं खाया। आपके पास {left} प्रयास बचे हैं। कृपया दोबारा बताइए।",
    },
    "tpin_locked": {
        "en": "Sorry, the TPIN didn't match 3 times. For your safety I'm transferring you to a customer care executive.",
        "hinglish": "Maaf kijiye, TPIN 3 baar galat hua. Aapki suraksha ke liye main aapko customer care executive se jod raha hoon.",
        "hi": "माफ़ कीजिए, TPIN 3 बार गलत हुआ। आपकी सुरक्षा के लिए मैं आपको कस्टमर केयर अधिकारी से जोड़ रहा हूँ।",
    },
    "ask_card_type": {
        "en": "Which card should I block: your debit card or your credit card?",
        "hinglish": "Kaunsa card block karna hai: debit card ya credit card?",
        "hi": "कौन सा कार्ड ब्लॉक करना है: डेबिट कार्ड या क्रेडिट कार्ड?",
    },
    "confirm_block": {
        "en": "Just to confirm: block your {card} card ending {last4}? Please say yes or no.",
        "hinglish": "Confirm kar dijiye: aapka {card} card jiske last 4 digit {last4} hain, block kar doon? Haan ya nahi bataiye.",
        "hi": "कृपया पुष्टि करें: आपका {card} कार्ड, जिसके आख़िरी 4 अंक {last4} हैं, ब्लॉक कर दूँ? हाँ या नहीं बताइए।",
    },
    "card_blocked": {
        "en": "Done. Your {card} card ending {last4} is now blocked. Reference number {ref}. Anything else?",
        "hinglish": "Ho gaya. Aapka {card} card ({last4}) ab block ho gaya hai. Reference number {ref}. Aur kuch?",
        "hi": "हो गया। आपका {card} कार्ड ({last4}) अब ब्लॉक हो गया है। रेफ़रेंस नंबर {ref}। और कुछ?",
    },
    "card_already_blocked": {
        "en": "Your {card} card ending {last4} is already blocked. Anything else?",
        "hinglish": "Aapka {card} card ({last4}) pehle se block hai. Aur kuch?",
        "hi": "आपका {card} कार्ड ({last4}) पहले से ब्लॉक है। और कुछ?",
    },
    "no_such_card": {
        "en": "I couldn't find a {card} card on your account. Anything else I can help with?",
        "hinglish": "Aapke account par koi {card} card nahi mila. Aur kuch madad karoon?",
        "hi": "आपके खाते पर कोई {card} कार्ड नहीं मिला। और कुछ मदद करूँ?",
    },
    "block_cancelled": {
        "en": "Okay, I have not blocked the card. Anything else?",
        "hinglish": "Theek hai, card block nahi kiya. Aur kuch?",
        "hi": "ठीक है, कार्ड ब्लॉक नहीं किया। और कुछ?",
    },
    "balance": {
        "en": "Your available balance in account ending {acct} is {amount}. Anything else?",
        "hinglish": "Aapke account ({acct}) mein available balance {amount} hai. Aur kuch?",
        "hi": "आपके खाते ({acct}) में उपलब्ध बैलेंस {amount} है। और कुछ?",
    },
    "emi": {
        "en": "Your {loan} EMI of {amount} is due on {due}. Anything else?",
        "hinglish": "Aapke {loan} ki EMI {amount} hai, jo {due} ko due hai. Aur kuch?",
        "hi": "आपके {loan} की ईएमआई {amount} है, जो {due} को देय है। और कुछ?",
    },
    "no_loan": {
        "en": "I don't see any active loan on your account. Anything else?",
        "hinglish": "Aapke account par koi active loan nahi hai. Aur kuch?",
        "hi": "आपके खाते पर कोई सक्रिय लोन नहीं है। और कुछ?",
    },
    "transactions": {
        "en": "Your last {n} transactions: {lines}. Anything else?",
        "hinglish": "Aapke last {n} transactions: {lines}. Aur kuch?",
        "hi": "आपके पिछले {n} लेनदेन: {lines}। और कुछ?",
    },
    "transfer": {
        "en": "Sure, I'm connecting you to a customer care executive. Please stay on the line.",
        "hinglish": "Ji, main aapko customer care executive se jod raha hoon. Kripya line par bane rahiye.",
        "hi": "जी, मैं आपको कस्टमर केयर अधिकारी से जोड़ रहा हूँ। कृपया लाइन पर बने रहिए।",
    },
    "too_many_unknown": {
        "en": "I'm having trouble understanding. Let me connect you to a customer care executive.",
        "hinglish": "Mujhe samajhne mein dikkat ho rahi hai. Main aapko customer care executive se jod raha hoon.",
        "hi": "मुझे समझने में दिक्कत हो रही है। मैं आपको कस्टमर केयर अधिकारी से जोड़ रहा हूँ।",
    },
    "goodbye": {
        "en": "Thank you for calling Demo Bank. Have a good day!",
        "hinglish": "Demo Bank ko call karne ke liye dhanyavaad. Aapka din shubh ho!",
        "hi": "डेमो बैंक को कॉल करने के लिए धन्यवाद। आपका दिन शुभ हो!",
    },
    "bank_down": {
        "en": "Sorry, our banking system is not responding right now. Please try again in a moment.",
        "hinglish": "Maaf kijiye, abhi banking system jawab nahi de raha. Kripya thodi der baad koshish kijiye.",
        "hi": "माफ़ कीजिए, अभी बैंकिंग सिस्टम जवाब नहीं दे रहा। कृपया थोड़ी देर बाद कोशिश कीजिए।",
    },
}

CARD_NAMES = {"hi": {"debit": "डेबिट", "credit": "क्रेडिट"}}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def inr(amount: float) -> str:
    """Indian number format: 128940 -> ₹1,28,940.00"""
    sign = "-" if amount < 0 else ""
    whole, paise = f"{abs(amount):.2f}".split(".")
    last3, rest = whole[-3:], whole[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f"{sign}₹{','.join(groups + [last3])}.{paise}"


def nice_date(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    months = MONTHS_HI if lang == "hi" else MONTHS_EN
    return f"{d.day} {months[d.month - 1]} {d.year}"


def render(key: str, params: dict, lang: str) -> str:
    lang = lang if lang in ("en", "hi", "hinglish") else "en"
    params = dict(params)
    if "card" in params:
        params["card"] = CARD_NAMES.get(lang, {}).get(params["card"], params["card"])
    if "due" in params:
        params["due"] = nice_date(params["due"], lang)
    return TEMPLATES[key][lang].format(**params)
