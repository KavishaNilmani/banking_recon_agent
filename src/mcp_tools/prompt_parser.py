"""
MCP Tool 1 — Prompt Parser
The agent calls this to commit its structured interpretation of the user's natural language prompt.
Stores the parsed config in shared state so all subsequent tools can read it.
"""

from src.mcp_tools import state


def parse_prompt(
    payment_type: str,
    input_file: str,
    ar_sheet: str,
    bank_sheets: list,
    ar_filter_column: str,
    ar_filter_values: list,
    amount_tolerance: float = 0.02,
    date_tolerance_days: int = 7,
    match_fields: list = None,
    gp_sheet: str = "",
    instructions: str = "",
) -> dict:
    """
    Commit the agent's parsed understanding of the user prompt to shared state.
    All parameters are extracted by the agent from the user's natural language input.
    """
    state.reset()

    config = {
        "payment_type":       payment_type.upper(),
        "input_file":         input_file,
        "ar_sheet":           ar_sheet,
        "bank_sheets":        bank_sheets,
        "ar_filter_column":   ar_filter_column,
        "ar_filter_values":   [v.upper() for v in (ar_filter_values or [])],
        "amount_tolerance":   float(amount_tolerance),
        "date_tolerance_days": int(date_tolerance_days),
        "match_fields":       match_fields or ["amount", "reference"],
        "gp_sheet":           gp_sheet,
        "instructions":       instructions,
    }

    state.set_config(config)

    return {
        "status":  "Prompt parsed and config stored.",
        "config":  config,
        "next_step": f"Call load_data with file='{input_file}' and sheets={[ar_sheet] + bank_sheets + ([gp_sheet] if gp_sheet else [])}",
    }
