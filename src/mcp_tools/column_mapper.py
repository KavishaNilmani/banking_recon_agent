"""
MCP Tool 3 — Column Mapper
AI-assisted semantic mapping: maps any column name variant to a canonical name.
Uses difflib fuzzy matching. No external dependencies.
"""

import difflib

from src.mcp_tools import state

# Canonical name → list of known aliases (case-insensitive)
CANONICAL_MAP: dict[str, list[str]] = {
    "client_id":   ["client", "client id", "clientid", "clientnum", "cust", "customer"],
    "sdi":         ["sdi", "sdi#", "account", "account no"],
    "date":        ["date", "transaction date", "trx date", "txn date", "posting date", "post date"],
    "check":       ["check", "check no", "check#", "checknum", "ref", "ref no", "reference",
                    "payment ref", "payref", "chk", "ck no"],
    "amount":      ["amount", "paymentamount", "payment amount", "amt", "credit amount",
                    "transaction amount", "debit amount", "net amount", "total amount",
                    "credit", "debit"],
    "type":        ["type", "payment type", "pay type", "category", "sub_category",
                    "subcategory", "transaction type"],
    "bank":        ["bank", "bank name", "bank source"],
    "bank_date":   ["bank date", "value date", "cleared date", "settlement date"],
    "cleared_amt": ["amount cleared", "cleared amount", "cleared", "cleared amt"],
    "open_amt":    ["amount open", "open amount", "outstanding", "balance", "open amt"],
    "remarks_1":   ["remarks 1", "remarks1", "remark 1", "remark1", "notes", "note 1"],
    "remarks_2":   ["remarks 2", "remarks2", "remark 2", "remark2", "note 2", "comment"],
    "description": ["description", "desc", "narrative", "details", "transaction detail"],
    "cust_ref":    ["customer reference", "cust ref", "customer ref", "client reference"],
    "bank_ref":    ["bank reference", "bank ref", "bank id", "trace no", "bank reference no"],
    "credit_amt":  ["credit amount", "credit amt", "credits"],
    "post_date":   ["post date", "posting date", "value date"],
    "card_type":   ["card type", "card", "visa", "mc", "mastercard", "amex"],
    "division":    ["division", "div"],
    "postage":     ["postage", "post"],
    "unapplied":   ["unapplied payments", "unapplied", "unmatched"],
}


def _best_match(raw_col: str, threshold: float = 0.6) -> str | None:
    """Return canonical name for raw_col if similarity >= threshold, else None."""
    normalized = raw_col.lower().strip()

    # Exact alias match first
    for canonical, aliases in CANONICAL_MAP.items():
        if normalized in aliases or normalized == canonical:
            return canonical

    # Fuzzy match on aliases
    best_score = 0.0
    best_canonical = None
    for canonical, aliases in CANONICAL_MAP.items():
        all_names = aliases + [canonical]
        score = max(
            difflib.SequenceMatcher(None, normalized, alias).ratio()
            for alias in all_names
        )
        if score > best_score:
            best_score = score
            best_canonical = canonical

    return best_canonical if best_score >= threshold else None


def map_columns(sheet_name: str, override_map: dict = None) -> dict:
    """
    Map raw column names in a loaded sheet to canonical names.
    Stores the mapping in state. Unmapped columns are preserved as-is.

    Args:
        sheet_name   : name of the loaded sheet to map
        override_map : optional manual overrides {raw_col: canonical_col}
    """
    st = state.get()
    df = st["sheets"].get(sheet_name)

    if df is None:
        return {"error": f"Sheet '{sheet_name}' not loaded. Call load_data first."}

    mapping      = {}
    unmapped     = []
    override_map = override_map or {}

    for col in df.columns:
        if col in override_map:
            mapping[col] = override_map[col]
        else:
            canonical = _best_match(col)
            if canonical:
                mapping[col] = canonical
            else:
                mapping[col] = col   # keep original if no match
                unmapped.append(col)

    st["col_maps"][sheet_name] = mapping

    return {
        "sheet":    sheet_name,
        "mapping":  mapping,
        "unmapped": unmapped,
        "note": (
            "Unmapped columns kept as-is. "
            "Pass override_map to correct any wrong mappings."
            if unmapped else "All columns mapped successfully."
        ),
    }
