# run command
uv run python mcp_server.py

# What you need to do
## Step 1 — Open that file. You can do it quickly by pasting this in Windows Explorer address bar:

```C:\Users\KawishaNilmani\AppData\Roaming\Claude\claude_desktop_config.json```
```%APPDATA%\Claude\claude_desktop_config.json```

## Step 2 — Copy and paste bellow json code:

```
{
  "mcpServers": {
    "generic-billing-recon": {
      "command": "uv",
      "args": [
        "--directory",
        "d:\\OneDrive - Lowcode Minds Technology Pvt Ltd\\Desktop\\banking_recon_agent",
        "run",
        "mcp_server.py"
      ]
    }
  }
}
```
## Step 4 — Fully quit and restart Claude Desktop (not just close the window — right-click the system tray icon → Quit, then reopen).

After restart, Claude Desktop will connect to the MCP server under the new name generic-billing-recon and load all 14 tools.
--------------------------------------------------------------------------------------------------------------------------------------
# Generic Billing Reconciliation Agent

An LLM-driven reconciliation agent that can reconcile **any two data sources** in any Excel workbook — for any company, any payment type, and any column structure — all driven by a single natural language prompt.

Built on the **Model Context Protocol (MCP)**, it works as a toolset that Claude Desktop (or any MCP-compatible client) can call to perform structured reconciliation without writing any code.

---

## What It Does

- Reads any Excel file from the `input/` folder
- Filters rows by any column and value the user specifies
- Matches records between two sheets using any column combination the user describes
- Writes matched/unmatched values back into the original Excel file
- Generates a colour-coded reconciliation report in the `output/` folder
- Works for **any payment type** — ACH, VISA, Wire Transfer, Vendor Invoices, or anything custom
- Zero hardcoded column names, sheet names, or file names — everything comes from the user's prompt

---

## Requirements

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Claude Desktop (for MCP usage)
- An Anthropic API key **or** Azure OpenAI credentials (for CLI usage via `main.py`)

---

## Project Structure

```
banking_recon_agent/
├── input/                          ← Place your Excel/CSV files here
├── output/                         ← Reconciliation reports are saved here
├── src/
│   ├── agents/
│   │   └── billing_agent.py        ← CLI agent with generic system prompt
│   ├── mcp_tools/
│   │   ├── prompt_parser.py        ← Tool 1:  parse user prompt into config
│   │   ├── data_loader.py          ← Tool 2:  load Excel/CSV sheets
│   │   ├── column_mapper.py        ← Tool 3:  map raw → canonical column names
│   │   ├── schema_validator.py     ← Tool 4:  validate required columns exist
│   │   ├── transaction_classifier.py ← Tool 5: filter source & bank records
│   │   ├── rule_engine.py          ← Tool 6:  get matching rules
│   │   ├── matching_engine.py      ← Tool 7:  score and match records
│   │   ├── exception_analyzer.py   ← Tool 8:  categorise exceptions
│   │   ├── gp_validator.py         ← Tool 9:  validate GP/GL totals (optional)
│   │   ├── recon_updater.py        ← Tool 10: record decisions + fill values
│   │   ├── excel_writer.py         ← Tool 11: write fill values back to Excel
│   │   ├── audit_logger.py         ← Tool 12: generate audit log entry
│   │   ├── report_generator.py     ← Tool 13: write final Excel report
│   │   └── state.py                ← Shared in-memory state for one run
│   ├── services/
│   │   └── llm_client.py           ← Anthropic / Azure OpenAI client
│   └── utils/
│       └── tool_registry.py        ← All 14 tool schemas + dispatcher
├── mcp_server.py                   ← MCP server (stdio transport)
├── main.py                         ← CLI entry point
├── pyproject.toml
├── GENERIC_BILLING_AGENT.md        ← Full design document
└── .env                            ← API keys (not committed)
```

---

## Setup

### Step 1 — Install dependencies

```bash
uv sync
```

### Step 2 — Create environment file

Create a `.env` file in the project root:

```env
# Anthropic (default)
ANTHROPIC_API_KEY=your_api_key_here

# Azure OpenAI (optional — overrides Anthropic when all three are set)
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_API_KEY=your_azure_key
# AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

### Step 3 — Place your input file

Copy your Excel file into the `input/` folder:

```
input/recon.xlsx
input/bank_statement.xlsx
```

---

## Usage — Claude Desktop (MCP)

This is the recommended way to use the agent. Claude Desktop connects to the MCP server and calls the tools directly in response to your natural language prompt.

### Step 1 — Start the MCP server (optional test)

You can run this to verify the server starts without errors:

```bash
uv run python mcp_server.py
```

Expected output: no errors. The server stays running and listens on stdio.

### Step 2 — Configure Claude Desktop

Open the Claude Desktop config file. Paste this path into Windows Explorer address bar:

```
%APPDATA%\Claude\claude_desktop_config.json
```

Replace the contents with:

```json
{
  "mcpServers": {
    "generic-billing-recon": {
      "command": "uv",
      "args": [
        "--directory",
        "your project folder location",
        "run",
        "mcp_server.py"
      ]
    }
  }
}
```

> **Note:** Update the `--directory` path if your project is in a different location.

### Step 3 — Restart Claude Desktop

Fully quit Claude Desktop — do not just close the window:

1. Find the Claude icon in the **Windows system tray** (bottom-right near the clock)
2. Right-click → **Quit Claude**
3. Reopen Claude Desktop

After restart, click the **hammer icon (🔨)** in the chat input area. You should see **`generic-billing-recon`** listed with all 14 tools available.

### Step 4 — Write your prompt

**Important rules when prompting:**
- Do **not** attach/upload your Excel file to the chat — place it in `input/` and reference it by name
- Tell Claude the file is already in the input folder
- Explicitly ask Claude to use the MCP tools and start with `parse_prompt`

**Example prompt:**

```
The file recon.xlsx is already in the input folder on the local MCP server.
Do not look for any uploaded files. Use the generic-billing-recon MCP tools.

I want to do a VISA banking reconciliation.
- File: recon.xlsx (already in the input folder)
- Bank Statement sheet: filter Payment Type = VISA and Txn Date between 01/05/2026 and 17/05/2026
- Match Customer and Amount columns against Accounts Receivable sheet
- If matched, update Remark column in Bank Statement sheet as 'matched', otherwise 'unmatched'
- Generate a report and save it as output_recon.xlsx in the output folder

Start with parse_prompt first, then follow all 14 tools in order.
```

---

## Usage — CLI (`main.py`)

Use this if you want to run the agent from the terminal without Claude Desktop.

```bash
# Interactive prompt
uv run python main.py

# Inline prompt
uv run python main.py --prompt "Reconcile ACH payments in bank_recon.xlsx..."

# Custom output directory
uv run python main.py --prompt "..." --output output/my_run
```

---

## How It Works — Tool Flow

The agent runs 14 MCP tools in sequence. Each tool reads from and writes to a shared in-memory state object, passing context forward to the next tool automatically.

```
User Natural Language Prompt
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 1: parse_prompt                                           │
│  LLM extracts: file, sheets, filter condition,                  │
│  match_columns, fill_columns, output_columns                    │
│  ──► state.config                                               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 2: load_data                                              │
│  Loads specified sheets from Excel/CSV into memory              │
│  ──► state.sheets  (raw DataFrames)                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 3: get_sheet_data                                         │
│  LLM inspects actual column names and sample rows               │
│  (Called for each sheet — never assume column names)            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 4: map_columns                                            │
│  Maps raw column names → canonical names via fuzzy matching     │
│  ──► state.col_maps                                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 5: validate_schema                                        │
│  Confirms user-specified columns exist in each sheet            │
│  ──► state.validated                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 6: classify_transactions                                  │
│  Filters source records by user's condition (e.g. Type=VISA)    │
│  Stores __original_row__ for write-back row mapping             │
│  ──► state.classified  { ar: [...], bank: [...] }               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 7: get_matching_rules                                     │
│  Builds rules from match_columns config                         │
│  Known types (ACH/CARD/CHECK) use pre-defined defaults          │
│  Unknown types use GENERIC defaults — both overridden by config │
│  ──► state.rules                                                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 8: find_matches                                           │
│  Scores every source row against every bank row                 │
│  Generic mode: dynamic column-pair scoring                      │
│  score >= 0.9 → confirmed │ [0.5, 0.9) → candidate             │
│  ──► state.matches  { confirmed, candidates, unmatched }        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 9: analyze_exceptions                                     │
│  Categorises: MISSING_BANK, MISSING_AR, PARTIAL_AMOUNT,         │
│  MULTI_MATCH, LOW_CONFIDENCE, PRIOR_PERIOD                      │
│  ──► state.exceptions                                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 10: validate_gp_totals  (optional)                        │
│  Compares source total vs GP/GL sheet total                     │
│  Skipped automatically if no GP sheet was specified             │
│  ──► state.gp                                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 11: update_records                                        │
│  LLM submits decision for every source row (batches of 40-50)   │
│  Each matched row includes custom_fill with fill column values  │
│  e.g. { "Remark": "matched", "Bank Date": "2026-05-11" }        │
│  ──► state.decisions                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 12: write_back_to_excel                                   │
│  Writes custom_fill values into a copy of the original file     │
│  Uses __original_row__ to find the correct Excel row            │
│  Original file is never overwritten — creates _updated copy     │
│  ──► input/recon_updated.xlsx                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 13: log_audit                                             │
│  Computes match rates, totals, exception summary                │
│  ──► state.audit                                                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Tool 14: generate_report                                       │
│  Creates colour-coded Excel report with 6 sheets:               │
│  Recon Results │ Matched List │ Exceptions │ Bank Orphans        │
│  Audit Log │ Dashboard                                          │
│  ──► output/visa_recon_20260520_143022.xlsx                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
             LLM Final Response
    Prints matched records list in output_columns format
```

---

## Output Files

Every run produces two files:

| File | Location | Description |
|---|---|---|
| `recon_updated.xlsx` | `input/` | Copy of original file with fill columns written in (Remark, Bank Date, etc.) |
| `{type}_recon_{timestamp}.xlsx` | `output/` | Full reconciliation report with 6 sheets |

### Report Sheets

| Sheet | Contents |
|---|---|
| **Recon Results** | All source rows colour-coded: green=matched, red=unmatched, yellow=partial |
| **Matched List** | Clean table of only matched rows with output columns |
| **Exceptions** | MISSING_BANK, PARTIAL_AMOUNT, MULTI_MATCH etc. |
| **Bank Orphans** | Bank records with no matching source row |
| **Audit Log** | Run metadata, totals, match rates, GP validation |
| **Dashboard** | Summary with match rate percentage |

---

## Example Prompts

### VISA Card Reconciliation
```
The file recon.xlsx is in the input folder. Use the generic-billing-recon MCP tools.
Filter Bank Statement sheet where Payment Type = VISA and Txn Date between 01/05/2026 and 17/05/2026.
Match Customer and Amount against Accounts Receivable sheet.
Fill Remark column as 'matched' or 'unmatched'.
Start with parse_prompt.
```

### ACH Banking Reconciliation
```
The file bank_recon.xlsx is in the input folder. Use the generic-billing-recon MCP tools.
ACH reconciliation: AR sheet filter Type=ACH, match against ACH-JP sheet.
Match on Check, Amount, and Date columns.
Fill Bank=JP, Bank date from ACH-JP Date column, Amount Cleared from ACH-JP Amount column.
Show matched records at the end. Start with parse_prompt.
```

### Wire Transfer Reconciliation
```
The file wires_april.xlsx is in the input folder. Use the generic-billing-recon MCP tools.
GL sheet is the source, filter PayType=WIRE.
Match against WIRE_STMT sheet using Reference Number and Amount.
After matching, set GL Cleared=Yes and GL Bank Date from WIRE_STMT Value Date column.
Start with parse_prompt.
```

### Vendor Invoice Matching
```
The file vendor_invoices.xlsx is in the input folder. Use the generic-billing-recon MCP tools.
Source sheet: Invoices, filter Status=Pending.
Match against Payments sheet using Invoice# and Amount (within $1 tolerance).
When matched, update Status to Paid and set Paid Date from Payments Date column.
Start with parse_prompt.
```

---

## Supported LLM Providers

The agent auto-detects which provider to use based on environment variables.

| Provider | Required Environment Variables |
|---|---|
| **Anthropic** (default) | `ANTHROPIC_API_KEY` |
| **Azure OpenAI** | `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_DEPLOYMENT` |

Azure OpenAI takes priority when all three of its variables are set.

---

## Troubleshooting

**MCP tools not showing in Claude Desktop**
- Fully quit Claude Desktop from the system tray (right-click → Quit), then reopen
- Verify the `%APPDATA%\Claude\claude_desktop_config.json` has the correct path and server name
- Run `uv run python mcp_server.py` manually in a terminal to check for startup errors

**Claude is not using the MCP tools**
- Do not attach/upload your Excel file to the chat — it must be in the `input/` folder on disk
- Begin your prompt with: *"The file X is already in the input folder. Use the generic-billing-recon MCP tools. Start with parse_prompt."*

**File not found error**
- Confirm the file is in `input/` inside the project folder
- The tool accepts both `recon.xlsx` and `input/recon.xlsx` as the file path

**Column not found after matching**
- Column names are case-sensitive in the schema validator
- Use `get_sheet_data` to inspect exact column names, then reference them exactly in your prompt

---
