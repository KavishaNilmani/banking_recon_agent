"""
MCP Tool 4 — Schema Validator
Validates that required columns exist in each sheet.

Generic mode: required columns are derived from match_columns and fill_columns
              in the config — no hardcoded payment-type assumptions.
Legacy mode:  falls back to REQUIRED_COLUMNS per payment type for backward compatibility.
"""

from src.mcp_tools import state

# Legacy fallback — used only when match_columns config is empty
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


def validate_schema(
    sheet_name: str,
    sheet_role: str = "ar",
    required_columns: list = None,
) -> dict:
    """
    Validate that a loaded sheet has the required columns.

    Generic mode: derives required columns from match_columns / fill_columns config.
    Explicit override: pass required_columns directly.
    Legacy mode: uses REQUIRED_COLUMNS dict when config has no match_columns.

    Args:
        sheet_name       : name of the loaded sheet to validate
        sheet_role       : 'ar' (source sheet) or 'bank' (bank/reference sheet)
        required_columns : explicit list of required columns (overrides auto-detection)
    """
    st     = state.get()
    config = state.get_config()

    df = st["sheets"].get(sheet_name)
    if df is None:
        return {"error": f"Sheet '{sheet_name}' not loaded. Call load_data first."}

    col_map       = st["col_maps"].get(sheet_name, {})
    canonical_set = set(col_map.values())    # canonical names after mapping
    raw_col_set   = set(df.columns)          # raw column names in the actual sheet

    # Determine required column list
    if required_columns:
        required = required_columns
        mode     = "explicit"

    else:
        match_cols = config.get("match_columns", [])
        fill_cols  = config.get("fill_columns", [])

        if match_cols:
            # Generic mode: build from user-specified match/fill columns
            if sheet_role == "ar":
                required = [m["source_col"] for m in match_cols]
                # Also include fill target columns (they must exist to be written)
                required += [f["target_col"] for f in fill_cols]
            else:  # bank
                required = [m["bank_col"] for m in match_cols]
                required += [f["bank_col"] for f in fill_cols if f.get("bank_col")]
            required = list(dict.fromkeys(required))   # deduplicate, preserve order
            mode = "generic"

        else:
            # Legacy mode: use hardcoded REQUIRED_COLUMNS
            payment_type = config.get("payment_type", "ACH")
            required = REQUIRED_COLUMNS.get(payment_type, {}).get(sheet_role.lower(), [])
            mode = "legacy"

    # A column is "present" if it appears as a canonical name OR as a raw column name
    def _present(col: str) -> bool:
        return col in canonical_set or col in raw_col_set or col.lower() in canonical_set

    missing = [c for c in required if not _present(c)]
    present = [c for c in required if _present(c)]

    result = {
        "sheet":        sheet_name,
        "role":         sheet_role,
        "mode":         mode,
        "required":     required,
        "present":      present,
        "missing":      missing,
        "valid":        len(missing) == 0,
    }

    st["validated"][sheet_name] = result

    if missing:
        result["warning"] = (
            f"Columns not found: {missing}. "
            "Verify column names match exactly (case-sensitive). "
            "Use map_columns override_map to correct mappings if needed."
        )
    else:
        result["note"] = "All required columns found."

    return result
