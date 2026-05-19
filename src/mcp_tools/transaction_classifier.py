"""
MCP Tool 5 — Transaction Classifier
Filters source and bank records by payment type/condition and stores them in state.
Stores __original_row__ on each source record so write_back_to_excel can locate
the correct row in the original Excel file.
"""

import math
import pandas as pd

from src.mcp_tools import state


def _safe_str(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def _safe_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _fmt_date(v) -> str:
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except Exception:
        return _safe_str(v)


def _row_to_dict(row: pd.Series, col_map: dict, classified_index: int, original_row: int = None) -> dict:
    """Convert a DataFrame row to a dict using the canonical column map."""
    d = {"__index__": classified_index}
    if original_row is not None:
        d["__original_row__"] = original_row   # 0-based original DataFrame index for write-back
    for raw_col, canonical in col_map.items():
        val = row.get(raw_col)
        if pd.api.types.is_datetime64_any_dtype(type(val)):
            d[canonical] = _fmt_date(val)
        elif isinstance(val, float):
            d[canonical] = _safe_float(val)
        else:
            d[canonical] = _safe_str(val) if isinstance(val, str) else val
    return d


def classify_transactions(
    ar_sheet: str,
    bank_sheets: list,
    ar_filter_column: str = "",
    ar_filter_values: list = None,
    bank_filter_column: str = "",
    bank_filter_values: list = None,
) -> dict:
    """
    Filter source and bank records by payment type/condition and store in state.

    Args:
        ar_sheet           : source sheet name
        bank_sheets        : list of bank sheet names
        ar_filter_column   : column to filter source records on (raw or canonical)
        ar_filter_values   : accepted values (e.g. ['ACH'])
        bank_filter_column : column to filter bank records on (optional)
        bank_filter_values : accepted bank values (optional)
    """
    st       = state.get()
    config   = state.get_config()
    ar_filter_values   = [v.upper() for v in (ar_filter_values   or config.get("ar_filter_values", []))]
    ar_filter_column   = ar_filter_column   or config.get("ar_filter_column", "")
    bank_filter_values = [v.upper() for v in (bank_filter_values or [])]

    # ---- Source (AR) records ----
    ar_df   = st["sheets"].get(ar_sheet)
    ar_map  = st["col_maps"].get(ar_sheet, {})
    rev_map = {v: k for k, v in ar_map.items()}   # canonical -> raw

    if ar_df is None:
        return {"error": f"Source sheet '{ar_sheet}' not loaded."}

    # Resolve filter column (could be canonical or raw)
    raw_filter_col = rev_map.get(ar_filter_column, ar_filter_column)
    if ar_filter_values and raw_filter_col in ar_df.columns:
        mask        = ar_df[raw_filter_col].astype(str).str.upper().isin(ar_filter_values)
        ar_filtered = ar_df[mask].copy()    # preserve original DataFrame index
    else:
        ar_filtered = ar_df.copy()

    # Build classified records — store original row index for write-back
    ar_records = []
    for classified_i, (orig_idx, row) in enumerate(ar_filtered.iterrows()):
        rec = _row_to_dict(row, ar_map, classified_i, original_row=int(orig_idx))
        ar_records.append(rec)

    st["classified"]["ar"] = ar_records

    # ---- Bank records ----
    bank_records = []
    bank_counts  = {}
    for sh in bank_sheets:
        df    = st["sheets"].get(sh)
        b_map = st["col_maps"].get(sh, {})
        if df is None:
            bank_counts[sh] = "ERROR: not loaded"
            continue

        if bank_filter_values and bank_filter_column:
            b_rev    = {v: k for k, v in b_map.items()}
            raw_bcol = b_rev.get(bank_filter_column, bank_filter_column)
            if raw_bcol in df.columns:
                mask = df[raw_bcol].astype(str).str.upper().isin(bank_filter_values)
                df   = df[mask].copy()

        recs = [_row_to_dict(row, b_map, i) for i, row in df.reset_index(drop=True).iterrows()]
        for r in recs:
            r["__bank_sheet__"] = sh
        bank_records.extend(recs)
        bank_counts[sh] = len(recs)

    st["classified"]["bank"] = bank_records

    return {
        "ar_records_classified":   len(ar_records),
        "bank_records_classified": len(bank_records),
        "bank_sheet_breakdown":    bank_counts,
        "note": "__original_row__ stored on each source record for Excel write-back.",
        "next_step": "Call get_matching_rules to retrieve matching rules.",
    }
