"""
MCP Tool 4 — Schema Validator
Validates that required columns exist in each sheet for the given payment type.
"""

from src.mcp_tools import state

# Required canonical columns per payment type per sheet role
REQUIRED_COLUMNS: dict[str, dict[str, list[str]]] = {
    "ACH": {
        "ar":   ["client_id", "date", "check", "amount", "type"],
        "bank": ["date", "amount"],
    },
    "ECHECK": {
        "ar":   ["client_id", "date", "check", "amount", "type"],
        "bank": ["date", "amount", "cust_ref"],
    },
    "CARD": {
        "ar":   ["client_id", "date", "amount", "type"],
        "bank": ["date", "amount", "type"],
    },
    "CHECK": {
        "ar":   ["client_id", "date", "check", "amount", "type"],
        "bank": ["date", "amount"],
    },
}


def validate_schema(sheet_name: str, sheet_role: str = "ar") -> dict:
    """
    Validate that a loaded sheet has the required canonical columns for the
    current payment type. Reads config and column maps from state.

    Args:
        sheet_name : name of the sheet to validate
        sheet_role : 'ar' or 'bank' — determines which required-column list to use
    """
    st     = state.get()
    config = state.get_config()

    df = st["sheets"].get(sheet_name)
    if df is None:
        return {"error": f"Sheet '{sheet_name}' not loaded."}

    payment_type = config.get("payment_type", "ACH")
    col_map      = st["col_maps"].get(sheet_name, {})
    canonical_cols = set(col_map.values())

    required = REQUIRED_COLUMNS.get(payment_type, {}).get(sheet_role.lower(), [])
    missing  = [c for c in required if c not in canonical_cols]
    present  = [c for c in required if c in canonical_cols]

    result = {
        "sheet":        sheet_name,
        "role":         sheet_role,
        "payment_type": payment_type,
        "required":     required,
        "present":      present,
        "missing":      missing,
        "valid":        len(missing) == 0,
    }

    st["validated"][sheet_name] = result

    if missing:
        result["warning"] = (
            f"Missing columns: {missing}. "
            "Use map_columns with override_map to fix, or proceed if columns exist under different names."
        )

    return result
