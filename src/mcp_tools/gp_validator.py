"""
MCP Tool 9 — GP Validator
Compares AR payment totals against GP (General Practice / General Ledger) totals.
Used for CHECK, ECHECK, and CARD reconciliation types.
"""

from src.mcp_tools import state


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def validate_gp_totals(
    gp_sheet: str = "",
    gp_amount_column: str = "",
    gp_filter_column: str = "",
    gp_filter_values: list = None,
    ar_amount_column: str = "amount",
) -> dict:
    """
    Compare AR classified total against GP sheet total.
    Flags any discrepancy with amount and percentage difference.

    Args:
        gp_sheet          : name of the GP sheet (reads from config if empty)
        gp_amount_column  : canonical or raw column name for amounts in GP sheet
        gp_filter_column  : optional filter column in GP (e.g. 'Pymt Type')
        gp_filter_values  : optional filter values (e.g. ['ACH', 'Computer Check'])
        ar_amount_column  : canonical column for AR amounts (default 'amount')
    """
    st     = state.get()
    config = state.get_config()
    gp_sheet = gp_sheet or config.get("gp_sheet", "")

    ar_records = st["classified"].get("ar", [])
    ar_total   = sum(_safe_float(r.get(ar_amount_column)) for r in ar_records)

    result = {
        "ar_total":     round(ar_total, 2),
        "gp_total":     None,
        "difference":   None,
        "match":        None,
        "status":       "SKIPPED",
    }

    if not gp_sheet:
        result["note"] = "No GP sheet specified. GP validation skipped."
        st["gp"] = result
        return result

    gp_df = st["sheets"].get(gp_sheet)
    if gp_df is None:
        result["note"] = f"GP sheet '{gp_sheet}' not loaded."
        st["gp"] = result
        return result

    # Find amount column
    col_map   = st["col_maps"].get(gp_sheet, {})
    rev_map   = {v: k for k, v in col_map.items()}
    raw_amt   = rev_map.get(gp_amount_column, gp_amount_column)
    if raw_amt not in gp_df.columns:
        # try common names
        for candidate in ["Credit Amount", "Ck Amt", "Amount", "Debit Amount", "Credit"]:
            if candidate in gp_df.columns:
                raw_amt = candidate
                break

    # Apply filter if given
    gp_data = gp_df.copy()
    if gp_filter_column and gp_filter_values:
        raw_fcol = rev_map.get(gp_filter_column, gp_filter_column)
        if raw_fcol in gp_data.columns:
            fv_upper = [v.upper() for v in gp_filter_values]
            gp_data  = gp_data[gp_data[raw_fcol].astype(str).str.upper().isin(fv_upper)]

    gp_total = 0.0
    if raw_amt in gp_data.columns:
        gp_total = gp_data[raw_amt].apply(_safe_float).sum()

    diff = round(abs(ar_total - gp_total), 2)
    pct  = round(diff / max(abs(ar_total), 1) * 100, 2)

    result.update({
        "gp_total":   round(gp_total, 2),
        "difference": diff,
        "pct_diff":   pct,
        "match":      diff <= 0.02,
        "status":     "MATCH" if diff <= 0.02 else "MISMATCH",
        "gp_sheet":   gp_sheet,
        "gp_rows":    len(gp_data),
    })

    if not result["match"]:
        result["warning"] = f"AR total ${ar_total:,.2f} ≠ GP total ${gp_total:,.2f}. Difference: ${diff:,.2f} ({pct}%)"

    st["gp"] = result
    return result
