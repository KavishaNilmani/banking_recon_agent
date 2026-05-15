"""
MCP Tool 11 — Audit Logger
Generates a structured audit log entry and appends it to state.
"""

import time
from datetime import datetime
from src.mcp_tools import state


_run_start: float = time.time()


def log_audit(notes: str = "") -> dict:
    """
    Generate an audit log entry from current state and append to the audit list.
    Call this after update_records and before generate_report.
    """
    st      = state.get()
    config  = state.get_config()
    dec     = st.get("decisions", [])
    exc     = st.get("exceptions", [])
    gp      = st.get("gp", {})
    matches = st.get("matches", {})

    matched   = [d for d in dec if d["status"] == "MATCHED"]
    unmatched = [d for d in dec if d["status"] == "UNMATCHED"]
    partial   = [d for d in dec if d["status"] == "PARTIAL"]
    ar_total  = len(st["classified"].get("ar", []))
    pending   = ar_total - len(dec)

    matched_total   = sum(float(d.get("cleared_amount") or 0) for d in matched)
    unmatched_total = sum(
        float(st["classified"]["ar"][d["ar_index"]].get("amount") or 0)
        for d in unmatched
        if d["ar_index"] < len(st["classified"]["ar"])
    )

    elapsed = round(time.time() - _run_start, 1)

    exc_summary = {}
    for e in exc:
        exc_summary[e["type"]] = exc_summary.get(e["type"], 0) + 1

    entry = {
        "run_id":              st.get("run_id"),
        "timestamp":           datetime.now().isoformat(),
        "processing_time_sec": elapsed,
        "payment_type":        config.get("payment_type"),
        "input_file":          config.get("input_file"),
        "ar_sheet":            config.get("ar_sheet"),
        "bank_sheets":         config.get("bank_sheets"),
        "ar_total_records":    ar_total,
        "matched_count":       len(matched),
        "partial_count":       len(partial),
        "unmatched_count":     len(unmatched),
        "pending_count":       pending,
        "matched_total_amount":   round(matched_total, 2),
        "unmatched_total_amount": round(abs(unmatched_total), 2),
        "confirmed_matches":   len(matches.get("confirmed", [])),
        "candidate_matches":   len(matches.get("candidates", [])),
        "exception_summary":   exc_summary,
        "gp_validation":       gp.get("status", "SKIPPED"),
        "gp_difference":       gp.get("difference"),
        "recon_status": (
            "COMPLETE"  if pending == 0 and len(unmatched) == 0 else
            "PARTIAL"   if pending == 0 else
            "INCOMPLETE"
        ),
        "notes": notes,
    }

    st["audit"].append(entry)

    return {
        "audit_entry":  entry,
        "next_step":    "Call generate_report to write the final Excel output.",
    }
