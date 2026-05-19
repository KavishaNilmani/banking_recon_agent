"""
Tool Registry — all 14 MCP tool schemas (Anthropic tool_use format) + dispatcher.
One place to register tools; agent.py and mcp_server.py import from here.
"""

import json
import traceback

from src.mcp_tools.prompt_parser          import parse_prompt
from src.mcp_tools.data_loader            import load_data, get_sheet_data
from src.mcp_tools.column_mapper          import map_columns
from src.mcp_tools.schema_validator       import validate_schema
from src.mcp_tools.transaction_classifier import classify_transactions
from src.mcp_tools.rule_engine            import get_matching_rules
from src.mcp_tools.matching_engine        import find_matches
from src.mcp_tools.exception_analyzer     import analyze_exceptions
from src.mcp_tools.gp_validator           import validate_gp_totals
from src.mcp_tools.recon_updater          import update_records
from src.mcp_tools.excel_writer           import write_back_to_excel
from src.mcp_tools.audit_logger           import log_audit
from src.mcp_tools.report_generator       import generate_report


# ---------------------------------------------------------------------------
# Tool definitions — JSON schema (Anthropic tool_use format)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [

    # ── 1. parse_prompt ──────────────────────────────────────────────────
    {
        "name": "parse_prompt",
        "description": (
            "Commit your structured interpretation of the user's natural language prompt. "
            "Call this FIRST to store the reconciliation config. Resets all state for a fresh run.\n\n"
            "GENERIC MODE — extract these from the user prompt:\n"
            "  match_columns  : which columns to compare between source and bank sheets\n"
            "  fill_columns   : what values to write back into the source sheet after matching\n"
            "  output_columns : which columns to show in the final results list\n\n"
            "match_type values: exact | numeric_tolerance | date_tolerance | fuzzy\n"
            "value_type values: static | from_bank_col | from_source_col"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_type":        {"type": "string", "description": "Any payment type string: ACH, WIRE, CARD, VENDOR_INVOICE, etc."},
                "input_file":          {"type": "string", "description": "Path or filename of the input Excel/CSV file."},
                "ar_sheet":            {"type": "string", "description": "Name of the source sheet (AR, GL, Invoices, etc.)."},
                "bank_sheets":         {"type": "array",  "items": {"type": "string"}, "description": "Bank/reference data sheet names."},
                "ar_filter_column":    {"type": "string", "description": "Column to filter source records on (e.g. 'Type'). Empty = no filter."},
                "ar_filter_values":    {"type": "array",  "items": {"type": "string"}, "description": "Values to keep (e.g. ['ACH']). Empty = keep all."},
                "amount_tolerance":    {"type": "number", "description": "Max dollar difference for numeric_tolerance matching (default 0.02)."},
                "date_tolerance_days": {"type": "integer","description": "Max day difference for date_tolerance matching (default 7)."},
                "gp_sheet":            {"type": "string", "description": "GP/GL totals sheet for validation (optional, leave empty to skip)."},
                "instructions":        {"type": "string", "description": "Any special instructions from the user prompt."},
                "match_columns": {
                    "type": "array",
                    "description": "Column pairs defining how to match source records to bank records.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_col": {"type": "string", "description": "Column name in the source/AR sheet (use canonical name if mapped, else raw name)."},
                            "bank_col":   {"type": "string", "description": "Column name in the bank sheet (use canonical name if mapped, else raw name)."},
                            "match_type": {"type": "string", "enum": ["exact", "numeric_tolerance", "date_tolerance", "fuzzy"],
                                          "description": "exact=string match, numeric_tolerance=within amount_tolerance, date_tolerance=within date_tolerance_days, fuzzy=string similarity."},
                            "weight":     {"type": "number", "description": "Contribution to match score 0-1. Weights are auto-normalised."},
                        },
                        "required": ["source_col", "bank_col"],
                    },
                },
                "fill_columns": {
                    "type": "array",
                    "description": "Fill instructions — what to write back into source sheet rows after matching.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target_col":   {"type": "string", "description": "Column in source sheet to fill."},
                            "value_type":   {"type": "string", "enum": ["static", "from_bank_col", "from_source_col"],
                                            "description": "static=fixed string, from_bank_col=copy from bank sheet column, from_source_col=copy from another source column."},
                            "static_value": {"type": "string", "description": "The fixed value to write (required when value_type=static)."},
                            "bank_col":     {"type": "string", "description": "Bank sheet column to copy value from (required when value_type=from_bank_col)."},
                        },
                        "required": ["target_col", "value_type"],
                    },
                },
                "output_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column names to show in the final matched list and report. Defaults to match_columns + fill_columns targets.",
                },
            },
            "required": ["payment_type", "input_file", "ar_sheet", "bank_sheets"],
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
            "Return raw records from a previously loaded sheet so you can inspect actual "
            "column names and sample data. Always call this before making any decisions. "
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
            "Map raw column names in a loaded sheet to canonical names using fuzzy matching. "
            "Use override_map to explicitly control mapping for columns named in the user prompt. "
            "Unmapped columns are kept as-is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name":   {"type": "string", "description": "Name of the loaded sheet to map."},
                "override_map": {
                    "type": "object",
                    "description": "Manual overrides: {raw_col_name: canonical_or_keep_name}.",
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
            "Validate that a sheet has all required columns. "
            "In generic mode, checks the columns specified in match_columns and fill_columns config. "
            "sheet_role: 'ar' checks source sheet columns, 'bank' checks bank sheet columns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet_name":        {"type": "string", "description": "Sheet to validate."},
                "sheet_role":        {"type": "string", "enum": ["ar", "bank"], "description": "'ar' for source sheet, 'bank' for bank/reference sheet."},
                "required_columns":  {"type": "array", "items": {"type": "string"}, "description": "Explicit list of required columns (overrides auto-detection from config)."},
            },
            "required": ["sheet_name"],
        },
    },

    # ── 5. classify_transactions ─────────────────────────────────────────
    {
        "name": "classify_transactions",
        "description": (
            "Filter source and bank records by the specified conditions and store them in state for matching. "
            "Uses the filter columns and values from parse_prompt config."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ar_sheet":            {"type": "string", "description": "Source sheet name."},
                "bank_sheets":         {"type": "array",  "items": {"type": "string"}, "description": "Bank/reference sheet names."},
                "ar_filter_column":    {"type": "string", "description": "Source column to filter on (raw or canonical)."},
                "ar_filter_values":    {"type": "array",  "items": {"type": "string"}, "description": "Values to keep in source."},
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
            "Retrieve matching rules. In generic mode, rules are built from the match_columns config. "
            "For known payment types (ACH/ECHECK/CARD/CHECK), default rules are used as a base. "
            "Unknown types use GENERIC defaults. Pass overrides to customise any rule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_type": {"type": "string", "description": "Payment type string. Reads from config if empty."},
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
            "Run the matching engine on classified source and bank records. "
            "In generic mode, scores matches using the column pairs defined in match_columns config. "
            "Returns: confirmed (score>=0.9), candidates (need review), unmatched_ar, unmatched_bank."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_tolerance":    {"type": "number",  "description": "Override amount tolerance for numeric_tolerance columns."},
                "date_tolerance_days": {"type": "integer", "description": "Override date tolerance for date_tolerance columns."},
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
            "MISSING_BANK, MISSING_AR, PARTIAL_AMOUNT, MULTI_MATCH, LOW_CONFIDENCE, PRIOR_PERIOD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_period_prefix": {
                    "type": "string",
                    "description": "Prefix to detect prior-period records (optional).",
                },
            },
            "required": [],
        },
    },

    # ── 9. validate_gp_totals ────────────────────────────────────────────
    {
        "name": "validate_gp_totals",
        "description": (
            "Compare source classified total against a GP/GL totals sheet. "
            "Skipped automatically if no GP sheet was specified in parse_prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gp_sheet":          {"type": "string", "description": "GP sheet name (reads from config if empty)."},
                "gp_amount_column":  {"type": "string", "description": "Amount column in GP sheet (canonical or raw)."},
                "gp_filter_column":  {"type": "string", "description": "Filter column in GP (optional)."},
                "gp_filter_values":  {"type": "array",  "items": {"type": "string"}, "description": "Values to filter GP by."},
                "ar_amount_column":  {"type": "string", "description": "Canonical source amount column (default 'amount')."},
            },
            "required": [],
        },
    },

    # ── 10. update_records ───────────────────────────────────────────────
    {
        "name": "update_records",
        "description": (
            "Submit reconciliation decisions for source records. Call multiple times in batches of 40-50. "
            "Include custom_fill with the values to write back into fill_columns for each matched row. "
            "Each decision: ar_index, status (MATCHED/PARTIAL/UNMATCHED), custom_fill, reasoning, etc."
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
                            "ar_index":       {"type": "integer", "description": "Source record index (from classified records)."},
                            "status":         {"type": "string",  "enum": ["MATCHED", "PARTIAL", "UNMATCHED"]},
                            "bank":           {"type": "string",  "description": "Bank sheet name or source identifier."},
                            "bank_index":     {"type": "integer", "description": "Matched bank record index (null if unmatched)."},
                            "cleared_amount": {"type": "number",  "description": "Amount cleared in bank."},
                            "open_amount":    {"type": "number",  "description": "Remaining open amount (0 if fully matched)."},
                            "bank_date":      {"type": "string",  "description": "Bank transaction date YYYY-MM-DD."},
                            "remarks_1":      {"type": "string",  "description": "Short status remark."},
                            "remarks_2":      {"type": "string",  "description": "Additional context."},
                            "reasoning":      {"type": "string",  "description": "Agent reasoning (audit trail)."},
                            "custom_fill":    {
                                "type": "object",
                                "description": "User-defined fill values to write back: {column_name: value}. Build from fill_columns config.",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["ar_index", "status"],
                    },
                },
            },
            "required": ["decisions"],
        },
    },

    # ── 11. write_back_to_excel ──────────────────────────────────────────
    {
        "name": "write_back_to_excel",
        "description": (
            "Write the custom_fill values from matched decisions back into a copy of the original "
            "input Excel file. Creates a new file with '_updated' suffix — never overwrites the original. "
            "Call this after update_records and before log_audit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_sheet":  {"type": "string",  "description": "Sheet to update (reads ar_sheet from config if empty)."},
                "output_suffix": {"type": "string",  "description": "Suffix before .xlsx extension (default: _updated)."},
                "header_row":    {"type": "integer", "description": "0-based header row index (default 0, matches load_data header_row)."},
            },
            "required": [],
        },
    },

    # ── 12. log_audit ────────────────────────────────────────────────────
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

    # ── 13. generate_report ──────────────────────────────────────────────
    {
        "name": "generate_report",
        "description": (
            "Write the final reconciliation Excel report. "
            "In generic mode, the Recon Results sheet uses output_columns from config. "
            "Sheets: Recon Results (colour-coded), Matched List, Exceptions, Bank Orphans, Audit Log, Dashboard. "
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
    "write_back_to_excel":    lambda i: write_back_to_excel(**i),
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
