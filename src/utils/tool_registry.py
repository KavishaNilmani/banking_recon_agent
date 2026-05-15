"""
Tool Registry — all 13 MCP tool schemas (Anthropic tool_use format) + dispatcher.
One place to register tools; agent.py imports from here.
"""

import json
import traceback

from src.mcp_tools.prompt_parser        import parse_prompt
from src.mcp_tools.data_loader          import load_data, get_sheet_data
from src.mcp_tools.column_mapper        import map_columns
from src.mcp_tools.schema_validator     import validate_schema
from src.mcp_tools.transaction_classifier import classify_transactions
from src.mcp_tools.rule_engine          import get_matching_rules
from src.mcp_tools.matching_engine      import find_matches
from src.mcp_tools.exception_analyzer   import analyze_exceptions
from src.mcp_tools.gp_validator         import validate_gp_totals
from src.mcp_tools.recon_updater        import update_records
from src.mcp_tools.audit_logger         import log_audit
from src.mcp_tools.report_generator     import generate_report


# ---------------------------------------------------------------------------
# Tool definitions — JSON schema (Anthropic tool_use format)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [

    # ── 1. parse_prompt ──────────────────────────────────────────────────
    {
        "name": "parse_prompt",
        "description": (
            "Commit your structured interpretation of the user's natural language prompt. "
            "Call this FIRST to store the reconciliation config — payment type, input file, "
            "sheets, filter columns, tolerances, and any special instructions. "
            "Resets all state for a fresh run."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_type":        {"type": "string", "description": "ACH / ECHECK / CARD / CHECK"},
                "input_file":          {"type": "string", "description": "Path to the input Excel/CSV file."},
                "ar_sheet":            {"type": "string", "description": "Name of the AR (Accounts Receivable) sheet."},
                "bank_sheets":         {"type": "array",  "items": {"type": "string"}, "description": "Bank data sheet names."},
                "ar_filter_column":    {"type": "string", "description": "AR column used to filter by payment type (e.g. 'Type')."},
                "ar_filter_values":    {"type": "array",  "items": {"type": "string"}, "description": "Values to keep (e.g. ['ACH'])."},
                "amount_tolerance":    {"type": "number", "description": "Max dollar difference for a match (default 0.02)."},
                "date_tolerance_days": {"type": "integer","description": "Max day difference for date matching (default 7)."},
                "match_fields":        {"type": "array",  "items": {"type": "string"}, "description": "Fields to match on: amount, reference, date."},
                "gp_sheet":            {"type": "string", "description": "GP / GL sheet name for totals validation (optional)."},
                "instructions":        {"type": "string", "description": "Any special instructions from the user prompt."},
            },
            "required": ["payment_type", "input_file", "ar_sheet", "bank_sheets", "ar_filter_column", "ar_filter_values"],
        },
    },

    # ── 2. load_data ─────────────────────────────────────────────────────
    {
        "name": "load_data",
        "description": (
            "Load specified sheets from an Excel (.xlsx) or CSV file into memory. "
            "Supports hidden sheets, multi-sheet workbooks, and auto header detection. "
            "Returns record counts — not the actual data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path":  {"type": "string", "description": "Path to the Excel or CSV file."},
                "sheets":     {"type": "array",  "items": {"type": "string"}, "description": "Sheet names to load. Empty = load all sheets."},
                "header_row": {"type": "integer","description": "0-based header row index (default 0)."},
            },
            "required": ["file_path"],
        },
    },

    # ── 2b. get_sheet_data ───────────────────────────────────────────────
    {
        "name": "get_sheet_data",
        "description": (
            "Return raw records from a previously loaded sheet so you can inspect the data. "
            "Use max_rows to limit large sheets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name": {"type": "string",  "description": "Name of a loaded sheet."},
                "max_rows":   {"type": "integer", "description": "Max rows to return (default 500)."},
            },
            "required": ["sheet_name"],
        },
    },

    # ── 3. map_columns ───────────────────────────────────────────────────
    {
        "name": "map_columns",
        "description": (
            "Map raw column names in a loaded sheet to canonical names using fuzzy AI-assisted matching. "
            "Canonical names: client_id, date, check, amount, type, bank, cust_ref, bank_ref, description, etc. "
            "Pass override_map to correct any wrong auto-mappings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name":   {"type": "string", "description": "Name of the loaded sheet to map."},
                "override_map": {
                    "type": "object",
                    "description": "Manual overrides: {raw_col_name: canonical_name}.",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["sheet_name"],
        },
    },

    # ── 4. validate_schema ───────────────────────────────────────────────
    {
        "name": "validate_schema",
        "description": (
            "Validate that a sheet has all required canonical columns for the current payment type. "
            "sheet_role: 'ar' checks AR required columns, 'bank' checks bank required columns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name": {"type": "string", "description": "Sheet to validate."},
                "sheet_role": {"type": "string", "enum": ["ar", "bank"], "description": "'ar' or 'bank'."},
            },
            "required": ["sheet_name"],
        },
    },

    # ── 5. classify_transactions ─────────────────────────────────────────
    {
        "name": "classify_transactions",
        "description": (
            "Filter AR and bank records by payment type and store them in state for matching. "
            "Uses the filter columns and values you set in parse_prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ar_sheet":            {"type": "string", "description": "AR sheet name."},
                "bank_sheets":         {"type": "array",  "items": {"type": "string"}, "description": "Bank sheet names."},
                "ar_filter_column":    {"type": "string", "description": "AR column to filter on (raw or canonical)."},
                "ar_filter_values":    {"type": "array",  "items": {"type": "string"}, "description": "Values to keep in AR."},
                "bank_filter_column":  {"type": "string", "description": "Bank column to filter on (optional)."},
                "bank_filter_values":  {"type": "array",  "items": {"type": "string"}, "description": "Values to keep in bank (optional)."},
            },
            "required": ["ar_sheet", "bank_sheets"],
        },
    },

    # ── 6. get_matching_rules ────────────────────────────────────────────
    {
        "name": "get_matching_rules",
        "description": (
            "Retrieve default matching rules for the payment type. "
            "You may pass overrides to customise any rule based on user instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_type": {"type": "string", "description": "ACH / ECHECK / CARD / CHECK. Reads from config if empty."},
                "overrides":    {
                    "type": "object",
                    "description": "Rule overrides: e.g. {amount_tolerance: 0.05, date_tolerance_days: 3}.",
                    "additionalProperties": True,
                },
            },
            "required": [],
        },
    },

    # ── 7. find_matches ──────────────────────────────────────────────────
    {
        "name": "find_matches",
        "description": (
            "Run the matching engine on classified AR and bank records. "
            "Returns: confirmed (score>=0.9), candidates (need review), unmatched_ar, unmatched_bank. "
            "Review candidates and unmatched records, then call update_records with your decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_tolerance":    {"type": "number",  "description": "Override amount tolerance."},
                "date_tolerance_days": {"type": "integer", "description": "Override date tolerance."},
                "min_score":           {"type": "number",  "description": "Minimum score to appear as candidate (default 0.5)."},
            },
            "required": [],
        },
    },

    # ── 8. analyze_exceptions ────────────────────────────────────────────
    {
        "name": "analyze_exceptions",
        "description": (
            "Analyse match results and categorise all exceptions: "
            "MISSING_BANK, MISSING_AR, DUPLICATE, PARTIAL_AMOUNT, MULTI_MATCH, PRIOR_PERIOD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_period_prefix": {
                    "type": "string",
                    "description": "Prefix to detect prior-period records (e.g. 'JP04' for April JP).",
                },
            },
            "required": [],
        },
    },

    # ── 9. validate_gp_totals ────────────────────────────────────────────
    {
        "name": "validate_gp_totals",
        "description": (
            "Compare AR classified total against the GP / GL totals sheet. "
            "Used for CHECK, ECHECK, and CARD reconciliation. Skipped if no GP sheet specified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gp_sheet":          {"type": "string", "description": "GP sheet name (reads from config if empty)."},
                "gp_amount_column":  {"type": "string", "description": "Amount column in GP sheet (canonical or raw)."},
                "gp_filter_column":  {"type": "string", "description": "Filter column in GP (e.g. 'Pymt Type')."},
                "gp_filter_values":  {"type": "array",  "items": {"type": "string"}, "description": "Values to filter GP by."},
                "ar_amount_column":  {"type": "string", "description": "Canonical AR amount column (default 'amount')."},
            },
            "required": [],
        },
    },

    # ── 10. update_records ───────────────────────────────────────────────
    {
        "name": "update_records",
        "description": (
            "Submit your reconciliation decisions for AR records. Call multiple times in batches of 40-50. "
            "Each decision: ar_index, status (MATCHED/PARTIAL/UNMATCHED), bank, bank_index, "
            "cleared_amount, open_amount, bank_date, remarks_1, remarks_2, reasoning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "decisions": {
                    "type": "array",
                    "description": "List of reconciliation decisions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ar_index":       {"type": "integer", "description": "AR record index."},
                            "status":         {"type": "string",  "enum": ["MATCHED", "PARTIAL", "UNMATCHED"]},
                            "bank":           {"type": "string",  "description": "Bank sheet name or source."},
                            "bank_index":     {"type": "integer", "description": "Matched bank record index (null if unmatched)."},
                            "cleared_amount": {"type": "number",  "description": "Amount cleared in bank."},
                            "open_amount":    {"type": "number",  "description": "Remaining open amount."},
                            "bank_date":      {"type": "string",  "description": "Bank transaction date YYYY-MM-DD."},
                            "remarks_1":      {"type": "string",  "description": "Short status remark."},
                            "remarks_2":      {"type": "string",  "description": "Additional context."},
                            "reasoning":      {"type": "string",  "description": "Agent reasoning (audit trail)."},
                        },
                        "required": ["ar_index", "status"],
                    },
                },
            },
            "required": ["decisions"],
        },
    },

    # ── 11. log_audit ────────────────────────────────────────────────────
    {
        "name": "log_audit",
        "description": (
            "Generate a structured audit log entry from the current run state. "
            "Call this after all update_records calls and before generate_report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "Any additional notes for the audit log."},
            },
            "required": [],
        },
    },

    # ── 12. generate_report ──────────────────────────────────────────────
    {
        "name": "generate_report",
        "description": (
            "Write the final reconciliation Excel report with 5 sheets: "
            "Recon Results (colour-coded), Exceptions, Bank Orphans, Audit Log, Dashboard. "
            "Call this last, after log_audit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string", "description": "Output directory (default: 'output')."},
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_DISPATCH = {
    "parse_prompt":           lambda i: parse_prompt(**i),
    "load_data":              lambda i: load_data(**i),
    "get_sheet_data":         lambda i: get_sheet_data(**i),
    "map_columns":            lambda i: map_columns(**i),
    "validate_schema":        lambda i: validate_schema(**i),
    "classify_transactions":  lambda i: classify_transactions(**i),
    "get_matching_rules":     lambda i: get_matching_rules(**i),
    "find_matches":           lambda i: find_matches(**i),
    "analyze_exceptions":     lambda i: analyze_exceptions(**i),
    "validate_gp_totals":     lambda i: validate_gp_totals(**i),
    "update_records":         lambda i: update_records(**i),
    "log_audit":              lambda i: log_audit(**i),
    "generate_report":        lambda i: generate_report(**i),
}


def execute_tool(name: str, inputs: dict) -> str:
    try:
        fn = _DISPATCH.get(name)
        if fn is None:
            result = {"error": f"Unknown tool: '{name}'. Available: {list(_DISPATCH)}"}
        else:
            result = fn(inputs)
    except Exception as exc:
        result = {"error": str(exc), "traceback": traceback.format_exc()}
    return json.dumps(result, default=str)
