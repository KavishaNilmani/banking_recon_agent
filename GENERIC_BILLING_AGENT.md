# Generic Billing Reconciliation Agent

## Table of Contents

1. [What Is This](#1-what-is-this)
2. [Why Generic](#2-why-generic)
3. [How It Works — End-to-End](#3-how-it-works--end-to-end)
4. [Architecture Overview](#4-architecture-overview)
5. [Key Concept: What the User Must Provide](#5-key-concept-what-the-user-must-provide)
6. [New Config Parameters in parse_prompt](#6-new-config-parameters-in-parse_prompt)
7. [Tool-by-Tool Changes](#7-tool-by-tool-changes)
8. [New Tool: write_back_to_excel](#8-new-tool-write_back_to_excel)
9. [State Schema Changes](#9-state-schema-changes)
10. [System Prompt Changes](#10-system-prompt-changes)
11. [Example Prompts and How They Map](#11-example-prompts-and-how-they-map)
12. [Current vs Generic Comparison](#12-current-vs-generic-comparison)
13. [File Change Summary](#13-file-change-summary)
14. [Implementation Order](#14-implementation-order)

---

## 1. What Is This

The **Generic Billing Reconciliation Agent** is an LLM-driven agent that can reconcile **any two data sources** in any Excel workbook, for any company, any payment type, and any column structure — all driven by a single natural language prompt from the user.

It uses the same agentic loop (Claude or Azure OpenAI + 14 MCP tools) as the current billing agent, but removes every hardcoded assumption about column names, sheet names, payment types, and file names.

---

## 2. Why Generic

### Current System — Specific Problems

The current agent is built for one specific company's reconciliation process. These things are hardcoded:

| What Is Hardcoded | Where | Problem |
|---|---|---|
| Payment types: ACH, ECHECK, CARD, CHECK only | `schema_validator.py`, `rule_engine.py`, `billing_agent.py` | Any other payment type fails or falls back to wrong rules |
| Required columns per payment type | `schema_validator.py` — `REQUIRED_COLUMNS` dict | Assumes every company uses the same column names |
| Matching field lookups: `amount`, `check`, `cust_ref` | `matching_engine.py` — `_score_match()` | Can only match on these specific canonical field names |
| Match weights: amount=0.5, date=0.3, reference=0.2 | `matching_engine.py` | Fixed for all scenarios |
| Output report columns: Client, Date, Check/Ref, Bank, etc. | `report_generator.py` — hardcoded `hdrs` list | Report always shows these columns even if not relevant |
| No fill-back support | All tools | Cannot write matched values back into specific columns |
| No Excel write-back tool | `tool_registry.py` | Cannot update the original file with matched data |

### Generic System — What Changes

- **Zero hardcoded column names** — user tells the agent which columns to use
- **Zero hardcoded payment types** — any string is valid ("ACH", "Wire Transfer", "Stripe", "Vendor Invoice")
- **Zero hardcoded sheet names** — user specifies exactly which sheets to load
- **Zero hardcoded file names** — user provides the file in the prompt
- **Dynamic match logic** — match on whatever columns the user specifies
- **Dynamic fill-back** — write matched values into any target columns the user specifies
- **Dynamic report** — output shows the columns the user cares about

---

## 3. How It Works — End-to-End

### Step-by-Step Flow

```
User types natural language prompt
         │
         ▼
┌─────────────────────────────────┐
│   billing_agent.py              │
│   Generic SYSTEM_PROMPT         │
│   LLM reads user prompt         │
│   Agentic loop begins           │
└──────────────┬──────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 1: parse_prompt                                    │
│  LLM extracts from user prompt:                          │
│  - payment_type  (any string)                            │
│  - input_file    (exact filename user mentioned)         │
│  - source_sheet  (the sheet with records to reconcile)   │
│  - bank_sheets   (list of sheets with bank/match data)   │
│  - filter_column + filter_values (e.g. Type=ACH)         │
│  - match_columns (which columns to match on + weights)   │
│  - fill_columns  (what to write back after matching)     │
│  - output_columns (what to show in final list/report)    │
│  All stored in state config for downstream tools         │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 2: load_data                                       │
│  Loads specified sheets from the Excel/CSV file          │
│  No changes needed — already generic                     │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 3: get_sheet_data (for each sheet)                 │
│  LLM inspects actual column names and sample data        │
│  Confirms user-specified columns actually exist          │
│  No changes needed — already generic                     │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 4: map_columns (for each sheet)                    │
│  Maps raw column names to canonical names via fuzzy      │
│  matching. LLM can use override_map for exact control.   │
│  Minor enhancement: extend CANONICAL_MAP if needed       │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 5: validate_schema (for each sheet)                │
│  NOW DYNAMIC: validates the specific columns the user    │
│  mentioned in their prompt exist in the loaded sheets    │
│  (replaces hardcoded REQUIRED_COLUMNS per payment type)  │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 6: classify_transactions                           │
│  Filters source sheet rows by user's filter condition    │
│  (e.g. Type=ACH). Already generic — no changes needed.   │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 7: get_matching_rules                              │
│  NOW DYNAMIC: builds match_on list from user's           │
│  match_columns config instead of hardcoded per type.     │
│  Falls back to GENERIC rules for unknown payment types.  │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 8: find_matches                                    │
│  NOW DYNAMIC: _score_match() reads match_columns from    │
│  config and compares user-specified column pairs         │
│  instead of hardcoded amount/date/check lookups.         │
│  Scores each pair by type: number/date/string            │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 9: analyze_exceptions                              │
│  Categorises MISSING_BANK, MISSING_AR, PARTIAL,          │
│  MULTI_MATCH etc. Already mostly generic.                │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 10: validate_gp_totals (optional)                  │
│  Skipped if no GP/GL sheet specified. Already generic.   │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 11: update_records                                 │
│  NOW EXTENDED: each decision includes custom_fill dict   │
│  with user-specified column values to write back         │
│  e.g. {"Bank": "JP", "Bank date": "2024-03-15"}          │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 12: write_back_to_excel  ← NEW TOOL                │
│  Writes custom_fill values back into a copy of the       │
│  original Excel file for the matched rows.               │
│  Creates: input/bank_recon_updated.xlsx                  │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 13: log_audit                                      │
│  Generates structured audit entry. No changes needed.    │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 14: generate_report                                │
│  NOW DYNAMIC: Recon Results sheet uses output_columns    │
│  from config instead of hardcoded column list.           │
│  Includes matched list summary tab.                      │
└──────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  LLM FINAL RESPONSE                                      │
│  Prints matched records list in the format user asked.   │
│  Confirms which rows were filled and with what values.   │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Architecture Overview

```
main.py
  └── BillingReconAgent (src/agents/billing_agent.py)
        ├── Generic SYSTEM_PROMPT
        ├── LLMClient (Anthropic or Azure OpenAI)
        └── Agentic Loop
              └── MCP Tools (src/utils/tool_registry.py)
                    ├── parse_prompt         ← CHANGED (new params)
                    ├── load_data            ← no change
                    ├── get_sheet_data       ← no change
                    ├── map_columns          ← minor enhancement
                    ├── validate_schema      ← CHANGED (dynamic)
                    ├── classify_transactions← no change
                    ├── get_matching_rules   ← CHANGED (generic fallback)
                    ├── find_matches         ← CHANGED (dynamic scoring)
                    ├── analyze_exceptions   ← no change
                    ├── validate_gp_totals   ← no change
                    ├── update_records       ← CHANGED (custom_fill)
                    ├── write_back_to_excel  ← NEW TOOL
                    ├── log_audit            ← no change
                    └── generate_report      ← CHANGED (dynamic columns)

Shared State (src/mcp_tools/state.py)
  └── config
        ├── payment_type
        ├── input_file
        ├── source_sheet (was ar_sheet)
        ├── bank_sheets
        ├── filter_column / filter_values
        ├── match_columns          ← NEW
        ├── fill_columns           ← NEW
        ├── output_columns         ← NEW
        └── tolerances
```

---

## 5. Key Concept: What the User Must Provide

The user writes a natural language prompt. The LLM extracts these six things from it:

| # | What User Provides | Example from Prompt |
|---|---|---|
| 1 | **Input file** | `bank_recon.xlsx` |
| 2 | **Sheets to use** | `AR` sheet (source), `ACH-JP` sheet (bank/match data) |
| 3 | **Filter condition** | AR sheet → `Type` column → keep only `ACH` rows |
| 4 | **Which columns to match on** | Match `Check` column from AR to `Check` in ACH-JP; also `Amount` and `Date` |
| 5 | **What to fill back** | Fill AR `Bank`=`JP`, AR `Bank date`=ACH-JP's `Date`, AR `Amount Cleared`=ACH-JP's `Amount` |
| 6 | **What to show in results** | List the matched records with Check, Amount, Date, Bank, Bank date, Amount Cleared |

Everything else (tolerances, match scoring, report format) is either derived from the above or uses sensible defaults.

---

## 6. New Config Parameters in parse_prompt

### New Parameters Added

```python
def parse_prompt(
    # --- existing params (unchanged) ---
    payment_type: str,
    input_file: str,
    ar_sheet: str,           # renamed alias: source_sheet also accepted
    bank_sheets: list,
    ar_filter_column: str,
    ar_filter_values: list,
    amount_tolerance: float = 0.02,
    date_tolerance_days: int = 7,
    gp_sheet: str = "",
    instructions: str = "",

    # --- NEW PARAMS ---
    match_columns: list = None,
    fill_columns: list = None,
    output_columns: list = None,
) -> dict:
```

### `match_columns` — defines how to match records

A list of column pair objects. Each object tells the engine which column from the source sheet to compare against which column from the bank sheet.

```json
"match_columns": [
  {
    "source_col": "Check",
    "bank_col":   "Check",
    "match_type": "exact",
    "weight":     0.5
  },
  {
    "source_col": "Amount",
    "bank_col":   "Amount",
    "match_type": "numeric_tolerance",
    "weight":     0.4
  },
  {
    "source_col": "Date",
    "bank_col":   "Date",
    "match_type": "date_tolerance",
    "weight":     0.1
  }
]
```

**match_type values:**
- `exact` — strings must match exactly (or fuzzy if threshold set)
- `numeric_tolerance` — numbers within `amount_tolerance` dollars
- `date_tolerance` — dates within `date_tolerance_days` days
- `fuzzy` — fuzzy string similarity above a threshold

**weight:** how much this column contributes to the overall match score (all weights should sum to 1.0). If not provided, weights are distributed equally.

---

### `fill_columns` — defines what to write back after matching

A list of fill instruction objects. Each object tells the agent what value to write into which column of the source sheet for matched rows.

```json
"fill_columns": [
  {
    "target_col":   "Bank",
    "value_type":   "static",
    "static_value": "JP"
  },
  {
    "target_col":  "Bank date",
    "value_type":  "from_bank_col",
    "bank_col":    "Date"
  },
  {
    "target_col":  "Amount Cleared",
    "value_type":  "from_bank_col",
    "bank_col":    "Amount"
  }
]
```

**value_type values:**
- `static` — write the same fixed string for all matched rows (e.g. always write "JP")
- `from_bank_col` — copy the value from a specific bank sheet column for that matched row
- `from_source_col` — copy from another column in the source sheet

---

### `output_columns` — defines what to show in the results list

A simple list of column names the user wants in the output.

```json
"output_columns": ["Check", "Amount", "Date", "Bank", "Bank date", "Amount Cleared"]
```

If not provided, defaults to all `match_columns` + all `fill_columns` targets.

---

## 7. Tool-by-Tool Changes

### Tool 1: `parse_prompt` — `prompt_parser.py`

**Change type:** Add new parameters

- Add `match_columns: list` parameter
- Add `fill_columns: list` parameter
- Add `output_columns: list` parameter
- Remove restriction that `payment_type` must be ACH/ECHECK/CARD/CHECK — accept any string
- Store all three new params in state config

**Before:**
```python
config = {
    "payment_type": payment_type.upper(),   # only ACH/ECHECK/CARD/CHECK
    "input_file": input_file,
    "ar_sheet": ar_sheet,
    "bank_sheets": bank_sheets,
    ...
}
```

**After:**
```python
config = {
    "payment_type": payment_type.upper(),   # any string now
    "input_file": input_file,
    "ar_sheet": ar_sheet,
    "bank_sheets": bank_sheets,
    "match_columns": match_columns or [],   # NEW
    "fill_columns": fill_columns or [],     # NEW
    "output_columns": output_columns or [], # NEW
    ...
}
```

---

### Tool 2 & 2b: `load_data` / `get_sheet_data` — `data_loader.py`

**Change type:** None required

Already fully generic — loads any file, any sheet, any columns.

---

### Tool 3: `map_columns` — `column_mapper.py`

**Change type:** Minor enhancement

The `CANONICAL_MAP` currently maps known banking column variants to canonical names. This is still useful as a starting point, but for truly generic operation:
- The LLM should use `override_map` when it knows the exact column names from the user's prompt
- Unmapped columns are already kept as-is (no breaking change)
- Optionally: extend `CANONICAL_MAP` with more universal aliases

No breaking changes needed. LLM handles custom columns via `override_map`.

---

### Tool 4: `validate_schema` — `schema_validator.py`

**Change type:** Replace hardcoded dict with dynamic validation

**Before:**
```python
REQUIRED_COLUMNS = {
    "ACH":    {"ar": ["client_id", "date", "check", "amount", "type"], ...},
    "ECHECK": {"ar": [...], ...},
    "CARD":   {"ar": [...], ...},
    "CHECK":  {"ar": [...], ...},
}

def validate_schema(sheet_name, sheet_role="ar"):
    required = REQUIRED_COLUMNS.get(payment_type, {}).get(sheet_role, [])
    # fails for any unknown payment type
```

**After:**
```python
def validate_schema(sheet_name, sheet_role="ar", required_columns=None):
    config = state.get_config()
    
    if required_columns:
        required = required_columns          # explicit override
    else:
        # Build required list from user's match_columns and fill_columns
        match_cols = config.get("match_columns", [])
        fill_cols  = config.get("fill_columns", [])
        
        if sheet_role == "ar":
            # source_col from match_columns + target_col from fill_columns
            required = [m["source_col"] for m in match_cols] + \
                       [f["target_col"] for f in fill_cols]
        else:  # bank
            # bank_col from match_columns + bank_col from fill_columns
            required = [m["bank_col"] for m in match_cols] + \
                       [f.get("bank_col") for f in fill_cols if f.get("bank_col")]
    
    # validate these columns exist in the sheet's col_map
    ...
```

---

### Tool 5: `classify_transactions` — `transaction_classifier.py`

**Change type:** None required

Already accepts `ar_filter_column` and `ar_filter_values` as parameters. Fully generic.

---

### Tool 6: `get_matching_rules` — `rule_engine.py`

**Change type:** Add GENERIC fallback + build match_on from config

**Before:**
```python
DEFAULT_RULES = {
    "ACH":    {"match_on": ["amount", "reference"], ...},
    "ECHECK": {"match_on": ["amount", "reference", "date"], ...},
    "CARD":   {"match_on": ["amount", "card_type", "date"], ...},
    "CHECK":  {"match_on": ["amount", "check", "date"], ...},
}

rules = dict(DEFAULT_RULES.get(payment_type, DEFAULT_RULES["ACH"]))
# unknown types fall back to ACH rules silently
```

**After:**
```python
DEFAULT_RULES["GENERIC"] = {
    "match_on":             [],         # filled from match_columns config
    "amount_tolerance":     0.02,
    "date_tolerance_days":  7,
    "fuzzy_ref_threshold":  0.80,
    "allow_batch_matching": False,
    "duplicate_handling":   "flag",
    "description": "Generic: match fields defined by user prompt.",
}

def get_matching_rules(payment_type="", overrides=None):
    config = state.get_config()
    
    # Use known rules if type is recognized, else GENERIC
    rules = dict(DEFAULT_RULES.get(payment_type, DEFAULT_RULES["GENERIC"]))
    
    # Override match_on from user's match_columns config
    match_columns = config.get("match_columns", [])
    if match_columns:
        rules["match_on"] = [m["source_col"] for m in match_columns]
        rules["match_columns"] = match_columns   # full definition for engine
    ...
```

---

### Tool 7: `find_matches` — `matching_engine.py`

**Change type:** Rewrite `_score_match()` to use dynamic column pairs

This is the most important code change. The scoring function currently hardcodes which fields to compare.

**Before:**
```python
def _score_match(ar, bank, rules):
    # HARDCODED field lookups:
    ar_amt   = ar.get("amount")
    bank_amt = bank.get("amount") or bank.get("credit_amount") or bank.get("credit_amt")
    ar_ref   = str(ar.get("check") or ar.get("cust_ref") or "")
    bank_ref = str(bank.get("cust_ref") or bank.get("bank_ref") or bank.get("check") or "")
    ar_dt    = _parse_date(ar.get("date"))
    bank_dt  = _parse_date(bank.get("date") or bank.get("transaction_date") ...)
    
    # Fixed weights: amount=0.5, date=0.3, reference=0.2
```

**After:**
```python
def _score_match(ar, bank, rules):
    match_columns = rules.get("match_columns", [])
    
    if not match_columns:
        # fallback to legacy behavior for backward compatibility
        return _score_match_legacy(ar, bank, rules)
    
    score     = 0.0
    max_score = 0.0
    tol       = rules.get("amount_tolerance", 0.02)
    date_tol  = rules.get("date_tolerance_days", 7)
    fuzz_thr  = rules.get("fuzzy_ref_threshold", 0.80)
    
    # Distribute weights equally if not specified
    total_weight = sum(m.get("weight", 1.0) for m in match_columns)
    
    for col_pair in match_columns:
        source_col  = col_pair["source_col"]
        bank_col    = col_pair["bank_col"]
        match_type  = col_pair.get("match_type", "exact")
        weight      = col_pair.get("weight", 1.0) / total_weight
        
        ar_val   = ar.get(source_col)   # dynamic lookup
        bank_val = bank.get(bank_col)   # dynamic lookup
        max_score += weight
        
        if match_type == "numeric_tolerance":
            a = _safe_float(ar_val)
            b = _safe_float(bank_val)
            if _amount_match(a, b, tol):
                score += weight
                
        elif match_type == "date_tolerance":
            d1 = _parse_date(ar_val)
            d2 = _parse_date(bank_val)
            if _date_match(d1, d2, date_tol):
                score += weight
                
        elif match_type == "fuzzy":
            ratio = _fuzzy_match(str(ar_val or ""), str(bank_val or ""), fuzz_thr)
            score += weight * ratio
            
        else:  # exact
            if str(ar_val or "").strip().upper() == str(bank_val or "").strip().upper():
                score += weight
    
    return round(score / max_score, 3) if max_score > 0 else 0.0
```

---

### Tool 8: `analyze_exceptions` — `exception_analyzer.py`

**Change type:** None required

Already generic enough — works on match results in state regardless of column types.

---

### Tool 9: `validate_gp_totals` — `gp_validator.py`

**Change type:** None required

Fully parameterized — skipped automatically when no GP sheet is provided.

---

### Tool 10: `update_records` — `recon_updater.py`

**Change type:** Add `custom_fill` dict to each decision

**Before:**
```python
# Each decision has fixed fields only:
{
    "ar_index": 3,
    "status": "MATCHED",
    "bank": "ACH-JP",
    "bank_index": 7,
    "cleared_amount": 1250.00,
    "open_amount": 0,
    "bank_date": "2024-03-15",
    "remarks_1": "Matched by Check+Amount",
    "remarks_2": "",
    "reasoning": "..."
}
```

**After:**
```python
# Each decision also carries custom_fill for write-back:
{
    "ar_index": 3,
    "status": "MATCHED",
    "bank": "ACH-JP",
    "bank_index": 7,
    "cleared_amount": 1250.00,
    "open_amount": 0,
    "bank_date": "2024-03-15",
    "remarks_1": "Matched by Check+Amount",
    "remarks_2": "",
    "reasoning": "...",
    "custom_fill": {            # NEW — user-defined fill values
        "Bank":           "JP",
        "Bank date":      "2024-03-15",
        "Amount Cleared": 1250.00
    }
}
```

The `custom_fill` dict is stored in state along with the decision. The `write_back_to_excel` tool reads it to update the source sheet.

---

### Tool 11: `log_audit` — `audit_logger.py`

**Change type:** None required

Already reads dynamically from state. No changes needed.

---

### Tool 13: `generate_report` — `report_generator.py`

**Change type:** Make Sheet 1 columns dynamic

**Before:**
```python
hdrs = ["AR Index", "Client", "Date", "Check/Ref", "AR Amount",
        "Status", "Bank", "Bank Date", "Cleared Amt", "Open Amt",
        "Remarks 1", "Remarks 2", "Agent Reasoning"]
# always these 13 columns regardless of what user asked for
```

**After:**
```python
config = state.get_config()
output_columns = config.get("output_columns", [])

# Build column headers from user's output_columns + standard status columns
if output_columns:
    hdrs = output_columns + ["Status", "Agent Reasoning"]
else:
    # fallback to legacy default columns
    hdrs = ["AR Index", "Date", "Amount", "Status", "Bank",
            "Bank Date", "Cleared Amt", "Open Amt", "Remarks 1", "Remarks 2", "Agent Reasoning"]

# Write row values by looking up each column from ar record + decision
for i, ar in enumerate(ar_recs):
    d = decision_map.get(i, {})
    custom_fill = d.get("custom_fill", {})
    
    vals = []
    for col in output_columns:
        # Check custom_fill first (user-defined filled values), then AR record
        val = custom_fill.get(col) or ar.get(col) or ar.get(col.lower().replace(" ", "_"), "")
        vals.append(val)
    
    vals += [d.get("status"), d.get("reasoning")]
    ...
```

**New Sheet: Matched Records List**

Add a 6th sheet to the report: "Matched List" — a clean table showing only the rows that were MATCHED, with only the `output_columns` the user specified. This directly answers the user's "Give the list in here after finding and filling the data" request.

---

## 8. New Tool: `write_back_to_excel`

**File:** `src/mcp_tools/excel_writer.py`

This tool writes the matched and filled data back into a copy of the original Excel file.

### Why This Tool Is Needed

The current system generates a separate output report. But users often want the original Excel file updated with the reconciliation results — specifically filling in columns like "Bank", "Bank date", "Amount Cleared" directly in the source sheet rows.

### What It Does

1. Opens the original input Excel file
2. Loads the source/AR sheet
3. For each matched AR record, writes the `custom_fill` values into the specified columns
4. Saves a new copy with suffix `_updated` (never overwrites the original)
5. Returns the path to the updated file

### Tool Definition

```python
def write_back_to_excel(
    source_sheet: str,           # which sheet to update (e.g. "AR")
    output_suffix: str = "_updated"  # suffix for the output filename
) -> dict:
```

The tool reads `fill_columns` config and `decisions` (with `custom_fill`) from state — no need to pass them explicitly, keeping the tool call simple.

### Output

Creates: `input/bank_recon_updated.xlsx` (same directory as input, with `_updated` appended before `.xlsx`)

---

## 9. State Schema Changes

The shared state (`src/mcp_tools/state.py`) needs the following additions to the `config` key:

```python
# In state.reset(), config is empty dict — populated by parse_prompt
# New fields added to config by parse_prompt:

config = {
    # --- existing ---
    "payment_type":       "ACH",
    "input_file":         "bank_recon.xlsx",
    "ar_sheet":           "AR",
    "bank_sheets":        ["ACH-JP"],
    "ar_filter_column":   "Type",
    "ar_filter_values":   ["ACH"],
    "amount_tolerance":   0.02,
    "date_tolerance_days": 7,
    "gp_sheet":           "",
    "instructions":       "",
    
    # --- NEW ---
    "match_columns": [
        {"source_col": "Check",  "bank_col": "Check",  "match_type": "exact",             "weight": 0.5},
        {"source_col": "Amount", "bank_col": "Amount", "match_type": "numeric_tolerance",  "weight": 0.4},
        {"source_col": "Date",   "bank_col": "Date",   "match_type": "date_tolerance",     "weight": 0.1},
    ],
    "fill_columns": [
        {"target_col": "Bank",           "value_type": "static",       "static_value": "JP"},
        {"target_col": "Bank date",      "value_type": "from_bank_col","bank_col": "Date"},
        {"target_col": "Amount Cleared", "value_type": "from_bank_col","bank_col": "Amount"},
    ],
    "output_columns": ["Check", "Amount", "Date", "Bank", "Bank date", "Amount Cleared"],
}
```

The `decisions` list in state also stores the new `custom_fill` dict per decision:

```python
"decisions": [
    {
        "ar_index": 3,
        "status": "MATCHED",
        "bank": "ACH-JP",
        "bank_index": 7,
        "cleared_amount": 1250.00,
        "open_amount": 0.0,
        "bank_date": "2024-03-15",
        "remarks_1": "Matched",
        "remarks_2": "",
        "reasoning": "...",
        "custom_fill": {          # NEW
            "Bank": "JP",
            "Bank date": "2024-03-15",
            "Amount Cleared": 1250.00
        }
    },
    ...
]
```

---

## 10. System Prompt Changes

### Current SYSTEM_PROMPT (specific — to be replaced)

```
You are a senior billing reconciliation analyst. You reconcile payments between
an Accounts Receivable (AR) system and bank statements for all payment types:
ACH, ECHECK, CARD (VISA, MC, AMEX), and CHECK.
...
```

### New SYSTEM_PROMPT (generic)

```
You are a generic billing reconciliation agent. You can reconcile any two data 
sources in any Excel workbook for any company, any payment type, and any column 
structure — all driven by the user's natural language prompt.

You have 14 MCP tools. Use them in this order for every reconciliation run:

  1.  parse_prompt         — Extract ALL intent from user prompt: file, sheets,
                             filter conditions, match_columns, fill_columns,
                             output_columns. CALL FIRST. Resets state.
  2.  load_data            — Load specified sheets from the input file.
  3.  get_sheet_data       — Inspect actual column names and sample data for each sheet.
  4.  map_columns          — Map raw column names to canonical names. Use override_map
                             for columns the user named explicitly in their prompt.
  5.  validate_schema      — Confirm user-specified columns exist in each sheet.
  6.  classify_transactions— Filter source sheet rows by user's filter condition.
  7.  get_matching_rules   — Get rules built from user's match_columns config.
  8.  find_matches         — Run matching engine using dynamic column pairs.
  9.  analyze_exceptions   — Categorise all exceptions.
  10. validate_gp_totals   — Compare totals if user specified a GL/GP sheet (optional).
  11. update_records       — Submit decisions with custom_fill values for each matched row.
  12. write_back_to_excel  — Write fill values back into a copy of the original file.
  13. log_audit            — Generate audit log entry.
  14. generate_report      — Write final Excel report with dynamic columns (CALL LAST).

## How to Parse the User Prompt

From the user's natural language, extract:
- input_file       : the exact filename the user mentioned
- source_sheet     : the main sheet with records to reconcile (the "AR side")
- bank_sheets      : list of sheets with reference/bank data to match against
- filter_condition : any column=value filter to apply to the source sheet
- match_columns    : which columns to compare, and how (exact/numeric/date/fuzzy)
- fill_columns     : what values to write back after matching (static or from bank col)
- output_columns   : which columns to show in the final results list

## Important Rules

- Call parse_prompt FIRST with all extracted parameters including match_columns,
  fill_columns, and output_columns.
- Call get_sheet_data for EVERY sheet before making any decisions — always inspect
  the actual data. Never assume column names.
- Do not hardcode column names. Use what the user said and what you see in the data.
- After matching, call update_records with custom_fill populated for matched rows.
- Call write_back_to_excel to produce the updated source file.
- End your response by listing the matched records in the format the user asked for.
```

---

## 11. Example Prompts and How They Map

### Example 1 — The ACH Banking Reconciliation (Original Example)

**User Prompt:**
> "I want to do ACH banking reconciliation. In the input folder, I have bank_recon.xlsx. There has AR sheet and an ACH-JP sheet. You need to access the bank_recon.xlsx AR sheet, find the 'Type' column, and filter the Type=ACH. In the ACH-JP sheet has 'Check' column, and it has data. You need to find the same data that is in the ACH-JP sheet 'Check' column, 'Amount' column, and 'Date' column from the AR sheet 'Check' column, 'Amount' column, and 'Date' column. If you found, fill the AR sheet 'Bank' column as JP, 'Bank date' column as the relevant data in the 'Date' column that in the ACH-JP, and 'Amount Cleared' column as the relevant data in the 'Amount' column that in the ACH-JP. Give the list in here after finding and filling the data."

**LLM extracts for parse_prompt:**
```json
{
  "payment_type": "ACH",
  "input_file": "bank_recon.xlsx",
  "ar_sheet": "AR",
  "bank_sheets": ["ACH-JP"],
  "ar_filter_column": "Type",
  "ar_filter_values": ["ACH"],
  "match_columns": [
    {"source_col": "Check",  "bank_col": "Check",  "match_type": "exact",            "weight": 0.5},
    {"source_col": "Amount", "bank_col": "Amount", "match_type": "numeric_tolerance", "weight": 0.4},
    {"source_col": "Date",   "bank_col": "Date",   "match_type": "date_tolerance",    "weight": 0.1}
  ],
  "fill_columns": [
    {"target_col": "Bank",           "value_type": "static",       "static_value": "JP"},
    {"target_col": "Bank date",      "value_type": "from_bank_col","bank_col": "Date"},
    {"target_col": "Amount Cleared", "value_type": "from_bank_col","bank_col": "Amount"}
  ],
  "output_columns": ["Check", "Amount", "Date", "Bank", "Bank date", "Amount Cleared"]
}
```

---

### Example 2 — Wire Transfer Reconciliation (Different Company)

**User Prompt:**
> "Reconcile wire transfers. File is wires_april.xlsx in the input folder. GL sheet is the source, filter PayType=WIRE. Match against WIRE_STMT sheet using Reference Number and Amount. After matching, set GL Cleared=Yes and GL Bank Date from WIRE_STMT Value Date."

**LLM extracts for parse_prompt:**
```json
{
  "payment_type": "WIRE",
  "input_file": "wires_april.xlsx",
  "ar_sheet": "GL",
  "bank_sheets": ["WIRE_STMT"],
  "ar_filter_column": "PayType",
  "ar_filter_values": ["WIRE"],
  "match_columns": [
    {"source_col": "Reference Number", "bank_col": "Reference Number", "match_type": "exact",            "weight": 0.6},
    {"source_col": "Amount",           "bank_col": "Amount",           "match_type": "numeric_tolerance", "weight": 0.4}
  ],
  "fill_columns": [
    {"target_col": "Cleared",   "value_type": "static",       "static_value": "Yes"},
    {"target_col": "Bank Date", "value_type": "from_bank_col","bank_col": "Value Date"}
  ],
  "output_columns": ["Reference Number", "Amount", "Cleared", "Bank Date"]
}
```

---

### Example 3 — Vendor Invoice Matching (Completely Different Domain)

**User Prompt:**
> "I need to match vendor invoices. Source file is vendor_invoices.xlsx. Sheet Invoices has all invoices, filter Status=Pending. Match against Payments sheet using Invoice# and Amount (within $1). When matched, update Invoices Status to Paid, and set Paid Date from Payments Date column. Show me the list of matched invoices."

**LLM extracts for parse_prompt:**
```json
{
  "payment_type": "VENDOR_INVOICE",
  "input_file": "vendor_invoices.xlsx",
  "ar_sheet": "Invoices",
  "bank_sheets": ["Payments"],
  "ar_filter_column": "Status",
  "ar_filter_values": ["Pending"],
  "amount_tolerance": 1.0,
  "match_columns": [
    {"source_col": "Invoice#", "bank_col": "Invoice#", "match_type": "exact",            "weight": 0.6},
    {"source_col": "Amount",   "bank_col": "Amount",   "match_type": "numeric_tolerance", "weight": 0.4}
  ],
  "fill_columns": [
    {"target_col": "Status",    "value_type": "static",       "static_value": "Paid"},
    {"target_col": "Paid Date", "value_type": "from_bank_col","bank_col": "Date"}
  ],
  "output_columns": ["Invoice#", "Amount", "Status", "Paid Date"]
}
```

---

## 12. Current vs Generic Comparison

| Aspect | Current (Specific) | Generic |
|---|---|---|
| Payment types supported | ACH, ECHECK, CARD, CHECK only | Any string |
| Column names | Hardcoded (client_id, check, amount, etc.) | User-defined via match_columns |
| Match fields | Fixed: amount + date + reference | User-defined: any column pairs |
| Match weights | Fixed: 0.5 / 0.3 / 0.2 | User-defined or distributed equally |
| Fill-back support | None | Full: static values or from bank column |
| Excel write-back | None | New `write_back_to_excel` tool |
| Report columns | Hardcoded 13-column layout | Dynamic from output_columns |
| Schema validation | Fixed required columns per type | Validates user-specified columns |
| Matching rules | Fixed rules per type | Built from user's match_columns |
| Works for unknown company | No | Yes |
| Works for custom column names | No | Yes |
| Input file name | Must be specific file | Any file user mentions |

---

## 13. File Change Summary

| File | Change Type | Effort | Priority |
|---|---|---|---|
| `src/mcp_tools/prompt_parser.py` | Add 3 new params: `match_columns`, `fill_columns`, `output_columns` | Medium | **1 — Highest** |
| `src/mcp_tools/matching_engine.py` | Rewrite `_score_match()` to use dynamic column pairs | Medium | **2** |
| `src/mcp_tools/excel_writer.py` | **New file** — `write_back_to_excel` tool | Medium | **3** |
| `src/utils/tool_registry.py` | Register `write_back_to_excel`; update `parse_prompt` schema | Small | **4** |
| `src/mcp_tools/schema_validator.py` | Replace `REQUIRED_COLUMNS` dict with dynamic validation from config | Small | **5** |
| `src/mcp_tools/rule_engine.py` | Add `GENERIC` fallback; build `match_on` from `match_columns` config | Small | **6** |
| `src/mcp_tools/recon_updater.py` | Add `custom_fill` dict to each decision schema | Small | **7** |
| `src/mcp_tools/report_generator.py` | Make Sheet 1 columns dynamic; add "Matched List" sheet | Medium | **8** |
| `src/agents/billing_agent.py` | Replace `SYSTEM_PROMPT` with generic version | Small | **9** |
| `main.py` | Update description strings (remove "ACH, ECHECK..." references) | Tiny | **10** |
| `src/mcp_tools/state.py` | No code change needed — config dict is already open-ended | None | — |
| `src/mcp_tools/data_loader.py` | No change needed | None | — |
| `src/mcp_tools/transaction_classifier.py` | No change needed | None | — |
| `src/mcp_tools/exception_analyzer.py` | No change needed | None | — |
| `src/mcp_tools/gp_validator.py` | No change needed | None | — |
| `src/mcp_tools/audit_logger.py` | No change needed | None | — |

**Total files to change:** 9 existing + 1 new file

---

## 14. Implementation Order

Implement in this order — each phase builds on the previous:

### Phase 1 — Foundation (parse_prompt + state)
Files: `prompt_parser.py`, `tool_registry.py` (schema update for parse_prompt)

This unlocks everything. Once parse_prompt stores `match_columns`, `fill_columns`, and `output_columns` in state, all downstream tools can read them.

### Phase 2 — Dynamic Matching (matching_engine + rule_engine)
Files: `matching_engine.py`, `rule_engine.py`

The core algorithm becomes generic. Any column pair can now be used for scoring.

### Phase 3 — Write-Back (new tool + recon_updater)
Files: `excel_writer.py` (new), `recon_updater.py`, `tool_registry.py` (register new tool)

The agent can now fill values back into the source Excel file.

### Phase 4 — Validation + Schema (schema_validator)
Files: `schema_validator.py`

Validation now checks user-specified columns instead of hardcoded ones.

### Phase 5 — Output (report_generator + billing_agent)
Files: `report_generator.py`, `billing_agent.py`, `main.py`

Report and agent prompt become fully generic.

---

*Document generated: 2026-05-15*
*Project: banking_recon_agent — Generic Billing Agent Design*
