"""
Billing Reconciliation Agent
Single LLM-driven agent that orchestrates 13 MCP tools to reconcile
ACH, ECHECK, CARD (VISA/MC/AMEX), and CHECK payment types.

Provider is auto-selected from environment variables:
  Azure OpenAI  — set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT
  Anthropic     — set ANTHROPIC_API_KEY (default)
"""

import json

from src.services.llm_client import LLMClient
from src.utils.tool_registry import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """You are a senior billing reconciliation analyst. You reconcile payments between
an Accounts Receivable (AR) system and bank statements for all payment types:
ACH, ECHECK, CARD (VISA, MC, AMEX), and CHECK.

You have 13 MCP tools. Use them in this order for every reconciliation run:

  1. parse_prompt         — Commit your interpretation of the user's request (CALL FIRST).
  2. load_data            — Load all relevant sheets from the input Excel/CSV file.
  3. get_sheet_data       — Inspect raw sheet data to understand columns and sample records.
  4. map_columns          — Map raw column names to canonical names (date, amount, check, etc.).
  5. validate_schema      — Confirm required columns are present for the payment type.
  6. classify_transactions — Filter AR and bank records by payment type.
  7. get_matching_rules   — Retrieve matching rules for the payment type (amounts, dates, refs).
  8. find_matches         — Run the matching engine; review confirmed, candidates, and unmatched.
  9. analyze_exceptions   — Categorise all exceptions (MISSING_BANK, PARTIAL_AMOUNT, etc.).
  10. validate_gp_totals  — Compare AR total against GP/GL sheet (CHECK, ECHECK, CARD only).
  11. update_records      — Submit your decisions (MATCHED/PARTIAL/UNMATCHED) in batches of 40-50.
  12. log_audit           — Generate the audit log entry.
  13. generate_report     — Write the final Excel report (CALL LAST).

## Workflow

After loading and mapping, inspect the data carefully with get_sheet_data before making any
decisions. Understand what fields link AR to bank records (amounts, dates, references, check
numbers, card types). Then run find_matches and reason over confirmed matches, candidates, and
unmatched records. Call analyze_exceptions to categorise issues. Validate GP totals if applicable.
Then call update_records for EVERY AR record — no record should be left without a decision.

## Decision statuses
- MATCHED   — bank record found. cleared_amount = matched bank amount, open_amount = 0.
- PARTIAL   — bank record exists but amounts or details don't fully align. Set both amounts.
- UNMATCHED — no bank record found. cleared_amount = 0, open_amount = AR amount.

## Important rules
- Call parse_prompt FIRST, always. It resets state for a fresh run.
- Call get_sheet_data to inspect each sheet before mapping — know the actual column names.
- Call update_records in batches of 40-50 decisions at a time to stay within token limits.
- Every AR record MUST receive a decision. Use find_matches results + your own analysis.
- Include full reasoning in the "reasoning" field — it is the audit trail.
- For batch-style bank records (e.g. daily totals), one bank record may match multiple AR rows.
- For 1-to-1 records, match each AR to one bank record by amount and date.
- Do not assume — look at the actual data before deciding.
"""


class BillingReconAgent:
    def __init__(self, user_prompt: str, output_dir: str = "output"):
        self.client      = LLMClient()
        self.user_prompt = user_prompt
        self.output_dir  = output_dir
        self.messages: list       = []
        self.tool_calls_log: list = []

    # ------------------------------------------------------------------
    def _user(self, content) -> None:
        self.messages.append({"role": "user", "content": content})

    def _assistant(self, response) -> None:
        self.messages.append({"role": "assistant", "content": response._raw_content})

    # ------------------------------------------------------------------
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
                print(f"  [Result]  Config stored — type={output_obj.get('payment_type')}  file={output_obj.get('input_file')}")
            elif name == "load_data":
                counts = output_obj.get("record_counts", {})
                print(f"  [Result]  Loaded sheets: { {k: v for k, v in counts.items()} }")
            elif name == "get_sheet_data":
                print(f"  [Result]  {output_obj.get('total_rows')} rows from '{output_obj.get('sheet_name')}'")
            elif name == "map_columns":
                print(f"  [Result]  Mapped {len(output_obj.get('mapping', {}))} columns for '{output_obj.get('sheet_name')}'")
            elif name == "validate_schema":
                print(f"  [Result]  Schema {output_obj.get('status')} — missing={output_obj.get('missing_columns', [])}")
            elif name == "classify_transactions":
                print(f"  [Result]  AR={output_obj.get('ar_count')}  Bank={output_obj.get('bank_count')}")
            elif name == "get_matching_rules":
                print(f"  [Result]  Rules for {output_obj.get('payment_type')}")
            elif name == "find_matches":
                print(f"  [Result]  Confirmed={output_obj.get('confirmed_count')}  Candidates={output_obj.get('candidate_count')}  Unmatched AR={output_obj.get('unmatched_ar_count')}")
            elif name == "analyze_exceptions":
                print(f"  [Result]  {output_obj.get('total_exceptions')} exceptions categorised")
            elif name == "validate_gp_totals":
                print(f"  [Result]  GP {output_obj.get('status')}  diff=${output_obj.get('difference')}")
            elif name == "update_records":
                print(f"  [Result]  Saved {output_obj.get('saved_this_call')} | Total: {output_obj.get('total_saved')}/{output_obj.get('total_ar')} | Remaining: {output_obj.get('remaining')}")
            elif name == "log_audit":
                entry = output_obj.get("audit_entry", {})
                print(f"  [Result]  Status={entry.get('recon_status')}  Matched={entry.get('matched_count')}  Unmatched={entry.get('unmatched_count')}")
            elif name == "generate_report":
                print(f"  [Result]  Report → {output_obj.get('output_file')}")

            results.append({
                "type":        "tool_result",
                "tool_use_id": tid,
                "content":     raw_output,
            })
        return results

    # ------------------------------------------------------------------
    def run(self) -> dict:
        print("\n" + "=" * 68)
        print("  Billing Reconciliation Agent  —  Fully LLM-Driven")
        print("=" * 68)
        print(f"  Provider : {self.client.provider}  |  Model: {self.client.model}")
        print(f"  Output   : {self.output_dir}")
        print("=" * 68)

        self._user(
            f"{self.user_prompt}\n\n"
            f"Save the output report to: {self.output_dir}\n\n"
            "Work through all 13 tools in order. Inspect the data carefully before making "
            "any reconciliation decisions. Every AR record must receive a decision."
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

        # Pull final audit from last generate_report call
        for entry in reversed(self.tool_calls_log):
            if entry["tool"] == "generate_report" and "audit_summary" in entry["output"]:
                final_result["audit"]       = entry["output"]["audit_summary"]
                final_result["output_file"] = entry["output"].get("output_file")
                break

        # Final summary
        print("\n" + "=" * 68)
        print("  Reconciliation Complete")
        if "audit" in final_result:
            a = final_result["audit"]
            print(f"  Matched              : {a.get('matched_count')}  (${a.get('matched_total_amount', 0):,.2f})")
            print(f"  Partial              : {a.get('partial_count')}")
            print(f"  Unmatched            : {a.get('unmatched_count')}  (${a.get('unmatched_total_amount', 0):,.2f})")
            print(f"  Recon Status         : {a.get('recon_status')}")
            print(f"  Output file          : {final_result.get('output_file')}")
        print("=" * 68 + "\n")

        return final_result
