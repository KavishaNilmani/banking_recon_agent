"""
MCP Tool 2 — Excel / CSV Data Loader
Supports: multiple workbooks, multiple sheets, .xlsx and .csv,
          hidden sheets, auto-detected header rows.
"""

import math
import os
import pandas as pd

from src.mcp_tools import state


def _safe_str(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def _fmt_date(v) -> str:
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except Exception:
        return _safe_str(v)


def _safe_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _df_to_records(df: pd.DataFrame) -> list:
    """Convert a DataFrame to a list of dicts with cleaned values."""
    records = []
    for i, row in df.iterrows():
        r = {"__index__": int(i)}
        for col in df.columns:
            val = row[col]
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                r[col] = _fmt_date(val)
            elif isinstance(val, float):
                r[col] = _safe_float(val)
            else:
                r[col] = _safe_str(val) if isinstance(val, str) else val
        records.append(r)
    return records


def _resolve_path(file_path: str) -> str:
    for candidate in [file_path, os.path.join("input", os.path.basename(file_path))]:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"File not found: {file_path}")


def load_data(file_path: str, sheets: list, header_row: int = 0) -> dict:
    """
    Load specified sheets from an Excel or CSV file into shared state.
    Returns record counts per sheet — not the actual data.
    Call get_sheet_data to retrieve records from a loaded sheet.

    Args:
        file_path   : path to .xlsx or .csv file
        sheets      : list of sheet names to load (ignored for CSV)
        header_row  : 0-based row index of the header (default 0 = first row)
    """
    path = _resolve_path(file_path)
    ext  = os.path.splitext(path)[1].lower()
    st   = state.get()

    counts = {}

    if ext == ".csv":
        df = pd.read_csv(path, header=header_row)
        sheet_name = os.path.splitext(os.path.basename(path))[0]
        df.columns = [str(c).strip() for c in df.columns]
        st["sheets"][sheet_name] = df
        counts[sheet_name] = len(df)
    else:
        xl = pd.ExcelFile(path)
        all_sheets = xl.sheet_names

        if not sheets:
            sheets = all_sheets

        for sh in sheets:
            if sh not in all_sheets:
                counts[sh] = f"ERROR: sheet '{sh}' not found. Available: {all_sheets}"
                continue
            df = xl.parse(sh, header=header_row)
            df.columns = [str(c).strip() for c in df.columns]
            st["sheets"][sh] = df
            counts[sh] = len(df)

    return {
        "status":      "Data loaded into state.",
        "file":        path,
        "sheet_counts": counts,
        "available_sheets": list(st["sheets"].keys()),
        "next_step":   "Call map_columns for each sheet to standardise column names.",
    }


def get_sheet_data(sheet_name: str, max_rows: int = 500) -> dict:
    """
    Return raw records from a previously loaded sheet.
    Use max_rows to limit the response size (default 500).
    """
    st = state.get()
    df = st["sheets"].get(sheet_name)

    if df is None:
        loaded = list(st["sheets"].keys())
        return {"error": f"Sheet '{sheet_name}' not loaded. Loaded sheets: {loaded}"}

    records = _df_to_records(df.head(max_rows))

    return {
        "sheet":        sheet_name,
        "total_rows":   len(df),
        "returned":     len(records),
        "columns":      list(df.columns),
        "records":      records,
    }
