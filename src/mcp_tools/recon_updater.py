"""
MCP Tool 10 — Reconciliation Updater
Records the agent's final reconciliation decisions for each AR record.
Accumulates decisions across multiple calls.
"""

from src.mcp_tools import state


def _safe_str(v) -> str:
    return "" if v is None else str(v).strip()


def update_records(decisions: list) -> dict:
    """
    Submit reconciliation decisions for AR records.
    Can be called multiple times — decisions accumulate in state.

    Each decision dict:
        ar_index       (int)    — AR record index from classified records
        status         (str)    — MATCHED / PARTIAL / UNMATCHED
        bank           (str)    — bank sheet or source name
        bank_index     (int)    — index of matched bank record (None if unmatched)
        cleared_amount (float)  — amount matched in bank
        open_amount    (float)  — remaining open amount (0 if fully cleared)
        bank_date      (str)    — bank transaction date YYYY-MM-DD
        remarks_1      (str)    — short status remark
        remarks_2      (str)    — extra context
        reasoning      (str)    — agent's full reasoning (audit trail)
    """
    st = state.get()
    ar_records = st["classified"].get("ar", [])
    total_ar   = len(ar_records)

    if not ar_records:
        return {"error": "No classified AR records. Call classify_transactions first."}

    saved  = []
    errors = []

    for d in decisions:
        ar_idx = d.get("ar_index")
        if ar_idx is None or not (0 <= int(ar_idx) < total_ar):
            errors.append(f"Invalid ar_index: {ar_idx}")
            continue

        st["decisions"].append({
            "ar_index":      int(ar_idx),
            "status":        _safe_str(d.get("status", "UNMATCHED")).upper(),
            "bank":          _safe_str(d.get("bank", "")),
            "bank_index":    d.get("bank_index"),
            "cleared_amount": d.get("cleared_amount", 0) or 0,
            "open_amount":   d.get("open_amount", 0) or 0,
            "bank_date":     _safe_str(d.get("bank_date", "")),
            "remarks_1":     _safe_str(d.get("remarks_1", "")),
            "remarks_2":     _safe_str(d.get("remarks_2", "")),
            "reasoning":     _safe_str(d.get("reasoning", "")),
        })
        saved.append(int(ar_idx))

    total_saved = len(st["decisions"])
    remaining   = total_ar - total_saved

    return {
        "saved_this_call":  len(saved),
        "errors":           errors,
        "total_saved":      total_saved,
        "total_ar":         total_ar,
        "remaining":        remaining,
        "next_step": (
            "All decisions submitted — call log_audit then generate_report."
            if remaining <= 0
            else f"{remaining} AR records still need decisions. Continue calling update_records."
        ),
    }
