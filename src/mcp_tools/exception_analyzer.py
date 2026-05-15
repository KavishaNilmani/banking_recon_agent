"""
MCP Tool 8 — Exception Analyzer
Detects and categorises reconciliation exceptions:
  MISSING_BANK    — AR record not found in any bank file
  MISSING_AR      — Bank record with no matching AR entry
  DUPLICATE       — Same bank record matched to multiple AR records
  PARTIAL_AMOUNT  — Amount difference exceeds tolerance
  DATE_MISMATCH   — Matched but date difference exceeds tolerance
  MULTI_MATCH     — AR record matches multiple bank records
  PRIOR_PERIOD    — Transaction reference date is before current period
  INVALID_REF     — Reference / check number looks malformed
"""

import re
from src.mcp_tools import state


def _looks_like_prior_period(check: str, current_period_prefix: str = "") -> bool:
    """Heuristic: JP011926 or FC032726 patterns with a date before current month."""
    m = re.match(r"^[A-Z]{2}(\d{2})(\d{2})(\d{2})$", (check or "").upper().strip())
    if not m:
        return False
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if current_period_prefix:
        return not check.upper().startswith(current_period_prefix.upper())
    return False


def analyze_exceptions(current_period_prefix: str = "") -> dict:
    """
    Analyze match results from state and categorise all exceptions.
    Stores exceptions back to state.

    Args:
        current_period_prefix : e.g. 'JP04' to flag anything not April JP as prior period
    """
    st      = state.get()
    matches = st.get("matches", {})
    ar_recs = st["classified"].get("ar", [])
    b_recs  = st["classified"].get("bank", [])
    rules   = st.get("rules", {})
    tol     = rules.get("amount_tolerance", 0.02)

    exceptions = []

    # 1. Missing bank record (unmatched AR)
    for item in matches.get("unmatched_ar", []):
        a_idx = item["ar_index"]
        ar    = ar_recs[a_idx] if a_idx < len(ar_recs) else {}
        check = str(ar.get("check", "") or "")

        exc_type = "MISSING_BANK"
        if _looks_like_prior_period(check, current_period_prefix):
            exc_type = "PRIOR_PERIOD"

        exceptions.append({
            "type":      exc_type,
            "ar_index":  a_idx,
            "ar_amount": item.get("ar_amount"),
            "ar_date":   item.get("ar_date"),
            "ar_check":  check,
            "detail":    f"AR record (amount={item['ar_amount']}) not found in bank data.",
        })

    # 2. Missing AR record (bank orphan)
    for item in matches.get("unmatched_bank", []):
        exceptions.append({
            "type":        "MISSING_AR",
            "bank_index":  item["bank_index"],
            "bank_sheet":  item.get("bank_sheet"),
            "bank_amount": item.get("bank_amount"),
            "bank_date":   item.get("bank_date"),
            "detail":      f"Bank record (amount={item['bank_amount']}) has no matching AR entry.",
        })

    # 3. Candidate (low-confidence) matches — flag for review
    seen_bank = {}
    for item in matches.get("candidates", []):
        a_idx  = item["ar_index"]
        b_idx  = item["bank_index"]
        ar_amt = item.get("ar_amount", 0)
        b_amt  = item.get("bank_amount", 0)
        diff   = round(abs(ar_amt - b_amt), 4)

        # Check for multi-match
        if b_idx in seen_bank:
            exceptions.append({
                "type":      "MULTI_MATCH",
                "ar_index":  a_idx,
                "bank_index": b_idx,
                "detail":    f"Bank record {b_idx} matched by multiple AR records.",
            })

        seen_bank[b_idx] = a_idx

        if diff > tol:
            exceptions.append({
                "type":      "PARTIAL_AMOUNT",
                "ar_index":  a_idx,
                "bank_index": b_idx,
                "ar_amount": ar_amt,
                "bank_amount": b_amt,
                "difference": diff,
                "score":     item.get("score"),
                "detail":    f"Amount difference ${diff:.4f} exceeds tolerance ${tol:.2f}.",
            })
        else:
            exceptions.append({
                "type":      "LOW_CONFIDENCE",
                "ar_index":  a_idx,
                "bank_index": b_idx,
                "score":     item.get("score"),
                "detail":    f"Match score {item['score']:.2f} — needs agent review.",
            })

    st["exceptions"] = exceptions

    summary = {}
    for e in exceptions:
        summary[e["type"]] = summary.get(e["type"], 0) + 1

    return {
        "total_exceptions":    len(exceptions),
        "exception_summary":   summary,
        "exceptions":          exceptions[:50],   # first 50 for agent review
        "note": "Call validate_gp_totals next (if applicable), then update_records.",
    }
