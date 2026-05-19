"""
Generic Billing Reconciliation Agent
LLM-driven agent that orchestrates 14 MCP tools to reconcile any two data sources
in any Excel workbook for any company, any payment type, and any column structure.

Provider is auto-selected from environment variables:
  Azure OpenAI  — set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT
  Anthropic     — set ANTHROPIC_API_KEY (default)
"""

import json

from src.services.llm_client import LLMClient
from src.utils.tool_registry import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """You are a generic billing reconciliation agent. You can reconcile any two data
sources in any Excel workbook for any company, any payment type, and any column structure —
all driven entirely by the user's natural language prompt.

You have 14 MCP tools. Use them in this order for every reconciliation run:

  1.  parse_prompt         — Extract ALL intent from the user prompt: input file, sheets,
                             filter conditions, match_columns, fill_columns, output_columns.
                             CALL THIS FIRST. It resets state for a fresh run.
  2.  load_data            — Load all specified sheets from the input file.
  3.  get_sheet_data       — Inspect actual column names and sample rows for EACH sheet.
                             Always do this before any decisions — never assume column names.
  4.  map_columns          — Map raw column names to canonical names. Use override_map to
                             preserve user-specified column names exactly.
  5.  validate_schema      — Confirm user-specified match and fill columns exist in each sheet.
  6.  classify_transactions— Filter source records by the user's filter condition.
  7.  get_matching_rules   — Get rules built from match_columns config (generic) or defaults.
  8.  find_matches         — Run matching engine using dynamic column pairs.
  9.  analyze_exceptions   — Categorise all exceptions.
  10. validate_gp_totals   — Compare totals against GP/GL sheet if user specified one (optional).
  11. update_records       — Submit decisions in batches of 40-50. Include custom_fill for
                             each MATCHED/PARTIAL row with the values from fill_columns config.
  12. write_back_to_excel  — Write custom_fill values into a copy of the original Excel file.
  13. log_audit            — Generate audit log entry.
  14. generate_report      — Write final Excel report with dynamic columns (CALL LAST).

## Parsing the User Prompt

From the user's natural language, extract:

  input_file       : exact filename the user mentioned (check the input/ folder)
  ar_sheet         : the main sheet with records to reconcile (source/AR side)
  bank_sheets      : sheet(s) with reference/bank data to match against
  ar_filter_column : column and value to filter source records (e.g. Type=ACH). Empty = no filter.
  ar_filter_values : accepted filter values

  match_columns (CRITICAL — extract from user description of what to match):
    Each entry: {source_col, bank_col, match_type, weight}
    match_type: exact | numeric_tolerance | date_tolerance | fuzzy
    Example: user says "match Check column from AR to Check in ACH-JP, also Amount and Date"
    → [{source_col:"Check", bank_col:"Check", match_type:"exact", weight:0.5},
       {source_col:"Amount", bank_col:"Amount", match_type:"numeric_tolerance", weight:0.4},
       {source_col:"Date", bank_col:"Date", match_type:"date_tolerance", weight:0.1}]

  fill_columns (CRITICAL — extract from user description of what to write back):
    Each entry: {target_col, value_type, static_value?, bank_col?}
    value_type: static | from_bank_col | from_source_col
    Example: user says "fill Bank column as JP, Bank date from ACH-JP Date, Amount Cleared from ACH-JP Amount"
    → [{target_col:"Bank", value_type:"static", static_value:"JP"},
       {target_col:"Bank date", value_type:"from_bank_col", bank_col:"Date"},
       {target_col:"Amount Cleared", value_type:"from_bank_col", bank_col:"Amount"}]

  output_columns : columns to display in the final matched list
    Example: ["Check", "Amount", "Date", "Bank", "Bank date", "Amount Cleared"]

## Building custom_fill in update_records

For each MATCHED or PARTIAL decision, populate custom_fill using:
  - fill_columns with value_type="static"      → use the static_value directly
  - fill_columns with value_type="from_bank_col" → look up the bank_col value from the
    matched bank record (available in find_matches confirmed/candidates output as bank_record)
  - fill_columns with value_type="from_source_col" → look up from the AR record

Example custom_fill for a matched row:
  {"Bank": "JP", "Bank date": "2024-03-15", "Amount Cleared": 1250.00}

## Important Rules

- Call parse_prompt FIRST with all extracted parameters including match_columns,
  fill_columns, and output_columns. Never call it again mid-run.
- Call get_sheet_data for EVERY sheet — always inspect actual data before any decisions.
- Do not hardcode or assume column names — use exactly what you see in the data and
  what the user described.
- Use override_map in map_columns to preserve user-specified column names that might
  be incorrectly mapped to wrong canonical names.
- After matching, call update_records with custom_fill populated for all matched rows.
- Call write_back_to_excel to produce the updated source file with filled values.
- End your final response by listing matched records in the format the user requested
  (showing the output_columns values for each matched row).

## Decision Statuses
- MATCHED   — bank record found matching all key columns.
- PARTIAL   — bank record found but with minor discrepancy (amount/date difference).
- UNMATCHED — no bank record found.
"""


class BillingReconAgent:
    def __init__(self, user_prompt: str, output_dir: str = "output"):
        self.client      = LLMClient()
        self.user_prompt = user_prompt
        self.output_dir  = output_dir
        self.messages: list       = []
        self.tool_calls_log: list = []

    def _user(self, content) -> None:
        self.messages.append({"role": "user", "content": content})

    def _assistant(self, response) -> None:
        self.messages.append({"role": "assistant", "content": response._raw_content})

    def _handle_tool_calls(self, message) -> list:
        results = []
        for block in message.content:
            if block.type != "tool_use":
                continue

            name   = block.name
            inputs = block.input
            tid    = block.id

            print(f"\n  [Tool]    {name}")
            if inputs:
                preview = json.dumps(inputs)
                print(f"  [Input]   {preview[:220]}{'...' if len(preview) > 220 else ''}")

            raw_output = execute_tool(name, inputs)
            output_obj = json.loads(raw_output)

            self.tool_calls_log.append({"tool": name, "input": inputs, "output": output_obj})

            if "error" in output_obj:
                print(f"  [Result]  ERROR: {output_obj['error']}")
            elif name == "parse_prompt":
                cfg = output_obj.get("config", {})
                print(f"  [Result]  Config stored — type={cfg.get('payment_type')}  file={cfg.get('input_file')}  mode={output_obj.get('mode')}")
            elif name == "load_data":
                print(f"  [Result]  Loaded: {output_obj.get('sheet_counts', {})}")
            elif name == "get_sheet_data":
                print(f"  [Result]  {output_obj.get('total_rows')} rows | cols={output_obj.get('columns', [])[:6]}")
            elif name == "map_columns":
                print(f"  [Result]  Mapped {len(output_obj.get('mapping', {}))} columns for '{output_obj.get('sheet')}'")
            elif name == "validate_schema":
                print(f"  [Result]  {'VALID' if output_obj.get('valid') else 'INVALID'} | missing={output_obj.get('missing', [])}")
            elif name == "classify_transactions":
                print(f"  [Result]  Source={output_obj.get('ar_records_classified')}  Bank={output_obj.get('bank_records_classified')}")
            elif name == "get_matching_rules":
                print(f"  [Result]  Rules for {output_obj.get('payment_type')} (mode={output_obj.get('mode')})")
            elif name == "find_matches":
                print(f"  [Result]  Confirmed={output_obj.get('confirmed_count')}  Candidates={output_obj.get('candidate_count')}  Unmatched={output_obj.get('unmatched_ar_count')}")
            elif name == "analyze_exceptions":
                print(f"  [Result]  {output_obj.get('total_exceptions')} exceptions — {output_obj.get('exception_summary', {})}")
            elif name == "validate_gp_totals":
                print(f"  [Result]  GP {output_obj.get('status')}  diff=${output_obj.get('difference')}")
            elif name == "update_records":
                print(f"  [Result]  Saved {output_obj.get('saved_this_call')} | Total: {output_obj.get('total_saved')}/{output_obj.get('total_ar')} | Remaining: {output_obj.get('remaining')}")
            elif name == "write_back_to_excel":
                print(f"  [Result]  Written {output_obj.get('filled_cells')} cells → {output_obj.get('output_file')}")
            elif name == "log_audit":
                entry = output_obj.get("audit_entry", {})
                print(f"  [Result]  Status={entry.get('recon_status')}  Matched={entry.get('matched_count')}  Unmatched={entry.get('unmatched_count')}")
            elif name == "generate_report":
                print(f"  [Result]  Report → {output_obj.get('output_file')} | Sheets={output_obj.get('sheets')}")

            results.append({
                "type":        "tool_result",
                "tool_use_id": tid,
                "content":     raw_output,
            })
        return results

    def run(self) -> dict:
        print("\n" + "=" * 68)
        print("  Generic Billing Reconciliation Agent")
        print("=" * 68)
        print(f"  Provider : {self.client.provider}  |  Model: {self.client.model}")
        print(f"  Output   : {self.output_dir}")
        print("=" * 68)

        self._user(
            f"{self.user_prompt}\n\n"
            f"Save the output report to: {self.output_dir}\n\n"
            "Work through all 14 tools in order. Inspect the actual data with get_sheet_data "
            "before any decisions. Build custom_fill from fill_columns for each matched row. "
            "End by listing the matched records in the output_columns format the user requested."
        )

        turn         = 0
        final_result = {}

        while True:
            turn += 1
            print(f"\n[Turn {turn}]  Calling {self.client.provider}...")

            response = self.client.create_message(
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
                max_tokens=8192,
            )

            self._assistant(response)

            for block in response.content:
                if hasattr(block, "text") and block.text.strip():
                    print(f"\n[Agent]\n{block.text}\n")

            if response.stop_reason == "end_turn":
                print("\n[Agent]  Task complete.")
                for block in response.content:
                    if hasattr(block, "text"):
                        final_result["agent_summary"] = block.text
                break

            if response.stop_reason == "tool_use":
                tool_results = self._handle_tool_calls(response)
                self._user(tool_results)
                continue

            print(f"[Agent]  Unexpected stop_reason: {response.stop_reason}")
            break

        for entry in reversed(self.tool_calls_log):
            if entry["tool"] == "generate_report" and "audit_summary" in entry["output"]:
                final_result["audit"]       = entry["output"]["audit_summary"]
                final_result["output_file"] = entry["output"].get("output_file")
                break

        print("\n" + "=" * 68)
        print("  Reconciliation Complete")
        if "audit" in final_result:
            a = final_result["audit"]
            print(f"  Matched    : {a.get('matched_count')}  (${a.get('matched_total_amount', 0):,.2f})")
            print(f"  Partial    : {a.get('partial_count')}")
            print(f"  Unmatched  : {a.get('unmatched_count')}  (${a.get('unmatched_total_amount', 0):,.2f})")
            print(f"  Status     : {a.get('recon_status')}")
            print(f"  Report     : {final_result.get('output_file')}")
        print("=" * 68 + "\n")

        return final_result
