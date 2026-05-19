"""
MCP Tool 1 — Prompt Parser
The agent calls this to commit its structured interpretation of the user's natural language prompt.
Stores the parsed config in shared state so all subsequent tools can read it.

Generic mode: supports any payment type, any column names, any company.
  - match_columns  : defines which columns to compare between source and bank sheets
  - fill_columns   : defines what values to write back into the source sheet after matching
  - output_columns : defines which columns to show in the final results list and report
"""

from src.mcp_tools import state


def parse_prompt(
    payment_type: str,
    input_file: str,
    ar_sheet: str,
    bank_sheets: list,
    ar_filter_column: str = "",
    ar_filter_values: list = None,
    amount_tolerance: float = 0.02,
    date_tolerance_days: int = 7,
    match_fields: list = None,
    gp_sheet: str = "",
    instructions: str = "",
    # --- Generic mode parameters ---
    match_columns: list = None,
    fill_columns: list = None,
    output_columns: list = None,
) -> dict:
    """
    Commit the agent's parsed understanding of the user prompt to shared state.
    All parameters are extracted by the agent from the user's natural language input.

    Generic mode (recommended):
      match_columns  — list of {source_col, bank_col, match_type, weight} objects
      fill_columns   — list of {target_col, value_type, static_value?, bank_col?} objects
      output_columns — list of column names to show in results

    match_type values: exact | numeric_tolerance | date_tolerance | fuzzy
    value_type values: static | from_bank_col | from_source_col
    """
    state.reset()

    # Normalise filter values
    ar_filter_values_norm = [v.upper() for v in (ar_filter_values or [])]

    # Derive output_columns from match_columns + fill_columns if not provided
    derived_output = []
    if not output_columns:
        for m in (match_columns or []):
            col = m.get("source_col", "")
            if col and col not in derived_output:
                derived_output.append(col)
        for f in (fill_columns or []):
            col = f.get("target_col", "")
            if col and col not in derived_output:
                derived_output.append(col)

    config = {
        "payment_type":        payment_type.upper(),
        "input_file":          input_file,
        "ar_sheet":            ar_sheet,
        "bank_sheets":         bank_sheets,
        "ar_filter_column":    ar_filter_column,
        "ar_filter_values":    ar_filter_values_norm,
        "amount_tolerance":    float(amount_tolerance),
        "date_tolerance_days": int(date_tolerance_days),
        "match_fields":        match_fields or ["amount", "reference"],
        "gp_sheet":            gp_sheet,
        "instructions":        instructions,
        # Generic mode
        "match_columns":       match_columns or [],
        "fill_columns":        fill_columns or [],
        "output_columns":      output_columns or derived_output,
    }

    state.set_config(config)

    all_sheets = [ar_sheet] + bank_sheets + ([gp_sheet] if gp_sheet else [])

    return {
        "status":   "Prompt parsed and config stored.",
        "config":   config,
        "mode":     "generic" if match_columns else "legacy",
        "next_step": f"Call load_data with file='{input_file}' and sheets={all_sheets}",
    }
