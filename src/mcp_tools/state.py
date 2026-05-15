"""
Shared in-memory state for one agent run.
All MCP tools read from and write to this module — no data is passed between tools explicitly.
"""

from datetime import datetime

_state: dict = {}


def reset() -> None:
    global _state
    _state = {
        "run_id":    datetime.now().strftime("%Y%m%d_%H%M%S"),
        "config":    {},        # from parse_prompt
        "sheets":    {},        # sheet_name -> pd.DataFrame (raw)
        "col_maps":  {},        # sheet_name -> {raw_col: canonical_col}
        "validated": {},        # sheet_name -> {required_cols: [], missing: []}
        "classified": {
            "ar":   [],         # filtered AR records (list of dicts)
            "bank": [],         # filtered bank records (list of dicts)
        },
        "rules":     {},        # matching rules dict
        "matches":   [],        # [{ar_idx, bank_idx, score, status, fields}]
        "exceptions": [],       # exception records
        "gp":        {},        # GP validation result
        "decisions": [],        # [{ar_index, status, ...}]
        "audit":     [],        # audit log entries
        "output_path": None,
    }


def get() -> dict:
    return _state


def set_config(config: dict) -> None:
    _state["config"] = config


def get_config() -> dict:
    return _state.get("config", {})
