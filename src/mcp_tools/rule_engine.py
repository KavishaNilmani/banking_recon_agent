"""
MCP Tool 6 — Rule Engine
Returns matching rules for any payment type.
Known types (ACH/ECHECK/CARD/CHECK) use pre-defined defaults.
Unknown/custom types use GENERIC defaults and build match_on from match_columns config.
"""

from src.mcp_tools import state

DEFAULT_RULES: dict[str, dict] = {
    "ACH": {
        "match_on":               ["amount", "reference"],
        "amount_tolerance":       0.02,
        "date_tolerance_days":    7,
        "fuzzy_ref_threshold":    0.85,
        "allow_batch_matching":   True,
        "duplicate_handling":     "flag",
        "prior_period_action":    "unmatched",
        "description": "ACH: match by amount + reference. Supports batch totals.",
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
        "fuzzy_ref_threshold":    0.0,
        "allow_batch_matching":   True,
        "card_types":             ["VISA", "MC", "MASTERCARD", "AMEX"],
        "duplicate_handling":     "flag",
        "description": "CARD: match by amount + card type + date. Bank sends daily batches.",
    },
    "CHECK": {
        "match_on":               ["amount", "check", "date"],
        "amount_tolerance":       0.01,
        "date_tolerance_days":    5,
        "fuzzy_ref_threshold":    0.90,
        "allow_batch_matching":   False,
        "duplicate_handling":     "flag",
        "compare_gp_totals":      True,
        "description": "CHECK: match by check number + amount. Compare AR totals with GP.",
    },
    "GENERIC": {
        "match_on":               [],        # filled dynamically from match_columns config
        "amount_tolerance":       0.02,
        "date_tolerance_days":    7,
        "fuzzy_ref_threshold":    0.80,
        "allow_batch_matching":   False,
        "duplicate_handling":     "flag",
        "description": "GENERIC: match fields defined by user's match_columns in parse_prompt.",
    },
}


def get_matching_rules(payment_type: str = "", overrides: dict = None) -> dict:
    """
    Return matching rules for the payment type.
    Known types use DEFAULT_RULES as a base; unknown types use GENERIC.
    match_columns from config always overrides the match_on list and is passed
    to the matching engine for dynamic scoring.

    Args:
        payment_type : any string — ACH / ECHECK / CARD / CHECK or custom. Reads from config if empty.
        overrides    : dict of rule overrides from user instructions
    """
    st = state.get()
    config = state.get_config()

    if not payment_type:
        payment_type = config.get("payment_type", "GENERIC")

    payment_type = payment_type.upper()

    # Use known rules if recognized, else fall back to GENERIC
    base_key = payment_type if payment_type in DEFAULT_RULES else "GENERIC"
    rules = dict(DEFAULT_RULES[base_key])

    # Apply config-level tolerance overrides (from parse_prompt)
    if config.get("amount_tolerance") is not None:
        rules["amount_tolerance"] = config["amount_tolerance"]
    if config.get("date_tolerance_days") is not None:
        rules["date_tolerance_days"] = config["date_tolerance_days"]

    # If the user specified match_columns, inject them into rules for the matching engine
    match_columns = config.get("match_columns", [])
    if match_columns:
        rules["match_on"] = [m["source_col"] for m in match_columns]
        rules["match_columns"] = match_columns   # full spec for _score_match_generic

    # Apply agent-provided overrides last
    if overrides:
        rules.update(overrides)

    st["rules"] = rules

    mode = "generic" if match_columns else ("known" if base_key != "GENERIC" else "generic-default")

    return {
        "payment_type": payment_type,
        "rules_base":   base_key,
        "mode":         mode,
        "rules":        rules,
        "next_step":    "Call find_matches to run the matching engine.",
    }
