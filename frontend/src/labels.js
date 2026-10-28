// Human-readable names for what the API returns.

export const INTENT_LABELS = {
  check_balance: "Check balance",
  emi_due: "EMI details",
  block_card: "Block a card",
  recent_transactions: "Recent transactions",
  talk_to_human: "Asked for a human",
  greeting: "Greeting",
  goodbye: "Goodbye",
  affirm: "Said yes",
  deny: "Said no",
  provide_info: "Gave a detail",
  unknown: "Not understood",
};

export const LANGUAGE_LABELS = { en: "English", hi: "Hindi", hinglish: "Hinglish" };

export const SOURCE_LABELS = {
  llm: "LLM",
  rules: "Keyword rules",
  cache: "Redis cache (repeat phrase)",
};

// For use inside a sentence: "understood by the LLM in 420 ms"
export const SOURCE_IN_SENTENCE = {
  llm: "the LLM",
  rules: "keyword rules",
  cache: "the Redis cache",
};

export const ACTION_LABELS = {
  get_balance: "Fetched balance from the bank",
  get_emi: "Fetched EMI from the bank",
  get_transactions: "Fetched transactions from the bank",
  block_card: "Blocked the card at the bank",
  transfer_to_human: "Transferred to a human",
};

export const AWAITING_LABELS = {
  tpin: "TPIN",
  card_type: "which card",
  confirm_block: "a yes or no to block the card",
};

export const OUTCOME_LABELS = {
  resolved: "Resolved",
  transferred: "Handed to a human",
  unresolved: "Unresolved",
};

// Demo data only: the mock bank's TPINs, shown so a reviewer can try the flow.
// A real API never returns a PIN.
export const DEMO_TPINS = { "9876543210": "1234", "9123456780": "4321", "9988776655": "2580", "9000012345": "7890" };

export const TRY_SAYING = [
  "mera balance batao",
  "1234",
  "mera debit card kho gaya hai",
  "haan kar do",
  "when is my EMI due?",
  "मेरे पिछले लेनदेन दिखाइए",
  "I want to talk to a real person",
  "nahi, dhanyavad",
];

export const maskPhone = (p) => `${p.slice(0, 2)}••••••${p.slice(-2)}`;
