"""
MCP Tool 6 — Rule Engine
Returns default matching rules for each payment type.
The agent may override any rule based on user instructions.
"""

from src.mcp_tools import state

DEFAULT_RULES: dict[str, dict] = {
    "ACH": {
        "match_on":               ["amount", "reference"],
        "amount_tolerance":       0.02,
        "date_tolerance_days":    7,
        "fuzzy_ref_threshold":    0.85,
        "allow_batch_matching":   True,   # FC ACH: sum of AR rows = bank batch total
        "duplicate_handling":     "flag",
        "prior_period_action":    "unmatched",
        "description": "ACH: match by payment amount + check/reference number. FC bank uses batch totals.",
    },
    "ECHECK": {
        "match_on":               ["amount", "reference", "date"],
        "amount_tolerance":       0.02,
        "date_tolerance_days":    3,
        "fuzzy_ref_threshold":    0.80,
        "allow_batch_matching":   False,
        "duplicate_handling":     "flag",
        "prior_period_action":    "unmatched",
        "description": "ECHECK: match by amount + reference + date (stricter date tolerance).",
    },
    "CARD": {
        "match_on":               ["amount", "card_type", "date"],
        "amount_tolerance":       0.02,
        "date_tolerance_days":    5,
        "fuzzy_ref_threshold":    0.0,   # no reference matching for cards
        "allow_batch_matching":   True,  # card settlements are daily batches
        "card_types":             ["VISA", "MC", "MASTERCARD", "AMEX"],
        "duplicate_handling":     "flag",
        "description": "CARD: match by amount + card type (VISA/MC/AMEX) + date. Bank sends daily batches.",
    },
    "CHECK": {
        "match_on":               ["amount", "check", "date"],
        "amount_tolerance":       0.01,
        "date_tolerance_days":    5,
        "fuzzy_ref_threshold":    0.90,
        "allow_batch_matching":   False,
        "duplicate_handling":     "flag",
        "compare_gp_totals":      True,
        "description": "CHECK: match by check number + amount. Compare AR daily totals with GP totals.",
    },
}


def get_matching_rules(payment_type: str = "", overrides: dict = None) -> dict:
    """
    Return default matching rules for the payment type.
    The agent can pass overrides to customise any rule from the user prompt.

    Args:
        payment_type : ACH / ECHECK / CARD / CHECK (reads from state config if empty)
        overrides    : dict of rule overrides from user instructions
    """
    st = state.get()
    if not payment_type:
        payment_type = state.get_config().get("payment_type", "ACH")

    payment_type = payment_type.upper()
    rules = dict(DEFAULT_RULES.get(payment_type, DEFAULT_RULES["ACH"]))

    # Apply config-level overrides (from parse_prompt)
    config = state.get_config()
    if config.get("amount_tolerance") is not None:
        rules["amount_tolerance"] = config["amount_tolerance"]
    if config.get("date_tolerance_days") is not None:
        rules["date_tolerance_days"] = config["date_tolerance_days"]

    # Apply agent-provided overrides
    if overrides:
        rules.update(overrides)

    st["rules"] = rules

    return {
        "payment_type": payment_type,
        "rules":        rules,
        "next_step":    "Call find_matches to run the matching engine.",
    }
