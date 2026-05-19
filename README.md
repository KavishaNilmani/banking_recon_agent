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

# flow
User Prompt
    │
    ▼
parse_prompt ──► state.config  (match_columns, fill_columns, output_columns)
    │
    ▼
load_data ──────► state.sheets  (raw DataFrames)
    │
    ▼
get_sheet_data ─► LLM sees actual column names
    │
    ▼
map_columns ────► state.col_maps  (raw → canonical)
    │
    ▼
validate_schema ► checks user columns exist
    │
    ▼
classify_transactions ─► state.classified  (filtered dicts with __original_row__)
    │
    ▼
get_matching_rules ────► state.rules  (match_columns injected)
    │
    ▼
find_matches ──────────► state.matches  (confirmed/candidates + bank_record)
    │
    ▼
analyze_exceptions ────► state.exceptions
    │
    ▼
update_records ────────► state.decisions  (with custom_fill per matched row)
    │
    ▼
write_back_to_excel ───► input/bank_recon_updated.xlsx  (fills matched rows in source)
    │
    ▼
log_audit ─────────────► state.audit
    │
    ▼
generate_report ────────► output/ach_recon_TIMESTAMP.xlsx  (6-sheet report)
