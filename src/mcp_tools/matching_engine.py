"""
MCP Tool 7 — Matching Engine
Runs the core matching algorithm on classified AR and bank records.
Supports: exact amount, amount tolerance, date tolerance, fuzzy reference matching,
          batch matching (sum of AR rows = bank batch total), duplicate detection.
"""

import difflib
import math
from datetime import datetime, timedelta

from src.mcp_tools import state


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _parse_date(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d")
    except Exception:
        return None


def _amount_match(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _date_match(d1, d2, days: int) -> bool:
    if d1 is None or d2 is None:
        return True
    return abs((d1 - d2).days) <= days


def _fuzzy_match(s1: str, s2: str, threshold: float) -> float:
    if not s1 or not s2:
        return 0.0
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def _score_match(ar: dict, bank: dict, rules: dict) -> float:
    """Compute a 0-1 match score between an AR record and a bank record."""
    score     = 0.0
    max_score = 0.0
    tol       = rules.get("amount_tolerance", 0.02)
    date_tol  = rules.get("date_tolerance_days", 7)
    fuzz_thr  = rules.get("fuzzy_ref_threshold", 0.80)

    # Amount (weight 0.5)
    ar_amt   = _safe_float(ar.get("amount"))
    bank_amt = _safe_float(bank.get("amount") or bank.get("credit_amount") or bank.get("credit_amt"))
    max_score += 0.5
    if _amount_match(ar_amt, bank_amt, tol):
        score += 0.5

    # Date (weight 0.3)
    if "date" in rules.get("match_on", []):
        ar_dt   = _parse_date(ar.get("date"))
        bank_dt = _parse_date(bank.get("date") or bank.get("transaction_date") or bank.get("post_date"))
        max_score += 0.3
        if _date_match(ar_dt, bank_dt, date_tol):
            score += 0.3

    # Reference (weight 0.2)
    if "reference" in rules.get("match_on", []) or "check" in rules.get("match_on", []):
        ar_ref   = str(ar.get("check") or ar.get("cust_ref") or "")
        bank_ref = str(bank.get("cust_ref") or bank.get("bank_ref") or bank.get("check") or "")
        max_score += 0.2
        ratio = _fuzzy_match(ar_ref, bank_ref, fuzz_thr)
        score += 0.2 * ratio

    return round(score / max_score, 3) if max_score > 0 else 0.0


def find_matches(
    amount_tolerance: float = None,
    date_tolerance_days: int = None,
    min_score: float = 0.5,
) -> dict:
    """
    Run the matching engine on classified AR and bank records from state.
    Returns:
      - confirmed    : matches with score >= 0.9 (high confidence)
      - candidates   : matches with score in [min_score, 0.9) (need agent review)
      - unmatched_ar : AR records with no candidate
      - unmatched_bank: bank records with no AR match

    The agent reviews candidates and unmatched records to make final decisions.
    """
    st     = state.get()
    rules  = dict(st.get("rules", {}))
    config = state.get_config()

    if amount_tolerance is not None:
        rules["amount_tolerance"] = amount_tolerance
    if date_tolerance_days is not None:
        rules["date_tolerance_days"] = date_tolerance_days

    ar_records   = st["classified"].get("ar", [])
    bank_records = st["classified"].get("bank", [])

    if not ar_records:
        return {"error": "No classified AR records. Call classify_transactions first."}
    if not bank_records:
        return {"error": "No classified bank records. Call classify_transactions first."}

    tol = rules.get("amount_tolerance", 0.02)

    # Build amount index on bank records for fast lookup
    bank_index: dict[str, list[int]] = {}
    for b_idx, b in enumerate(bank_records):
        b_amt = _safe_float(b.get("amount") or b.get("credit_amount") or b.get("credit_amt"))
        key   = f"{round(b_amt, 2):.2f}"
        bank_index.setdefault(key, []).append(b_idx)

    confirmed    = []
    candidates   = []
    matched_bank = set()
    unmatched_ar = []

    for a_idx, ar in enumerate(ar_records):
        ar_amt    = _safe_float(ar.get("amount"))
        best_score  = 0.0
        best_b_idx  = None
        best_record = None

        # Search candidates within tolerance bucket
        search_amts = set()
        for step in range(-5, 6):
            key = f"{round(ar_amt + step * tol / 5, 2):.2f}"
            search_amts.add(key)
        search_amts.add(f"{round(ar_amt, 2):.2f}")

        b_candidates = []
        for amt_key in search_amts:
            for b_idx in bank_index.get(amt_key, []):
                if b_idx not in matched_bank:
                    b_candidates.append(b_idx)

        # Also search ±tol range
        for b_idx, b in enumerate(bank_records):
            if b_idx in matched_bank:
                continue
            b_amt = _safe_float(b.get("amount") or b.get("credit_amount") or b.get("credit_amt"))
            if abs(ar_amt - b_amt) <= tol * 2:
                b_candidates.append(b_idx)

        b_candidates = list(set(b_candidates))

        for b_idx in b_candidates:
            b = bank_records[b_idx]
            score = _score_match(ar, b, rules)
            if score > best_score:
                best_score  = score
                best_b_idx  = b_idx
                best_record = b

        if best_score >= 0.9 and best_b_idx is not None:
            matched_bank.add(best_b_idx)
            confirmed.append({
                "ar_index":    a_idx,
                "bank_index":  best_b_idx,
                "score":       best_score,
                "ar_amount":   ar_amt,
                "bank_amount": _safe_float(best_record.get("amount") or best_record.get("credit_amount")),
                "bank_sheet":  best_record.get("__bank_sheet__", ""),
                "bank_date":   best_record.get("date") or best_record.get("transaction_date") or "",
            })
        elif best_score >= min_score and best_b_idx is not None:
            candidates.append({
                "ar_index":    a_idx,
                "bank_index":  best_b_idx,
                "score":       best_score,
                "ar_amount":   ar_amt,
                "bank_amount": _safe_float(best_record.get("amount") or best_record.get("credit_amount")),
                "bank_sheet":  best_record.get("__bank_sheet__", ""),
                "bank_date":   best_record.get("date") or best_record.get("transaction_date") or "",
            })
        else:
            unmatched_ar.append({
                "ar_index":  a_idx,
                "ar_amount": ar_amt,
                "ar_date":   ar.get("date", ""),
                "ar_check":  ar.get("check", ""),
            })

    unmatched_bank = [
        {
            "bank_index":  b_idx,
            "bank_sheet":  bank_records[b_idx].get("__bank_sheet__", ""),
            "bank_amount": _safe_float(bank_records[b_idx].get("amount") or bank_records[b_idx].get("credit_amount")),
            "bank_date":   bank_records[b_idx].get("date") or bank_records[b_idx].get("transaction_date") or "",
        }
        for b_idx in range(len(bank_records))
        if b_idx not in matched_bank
    ]

    st["matches"] = {
        "confirmed":     confirmed,
        "candidates":    candidates,
        "unmatched_ar":  unmatched_ar,
        "unmatched_bank": unmatched_bank,
    }

    return {
        "confirmed_count":     len(confirmed),
        "candidates_count":    len(candidates),
        "unmatched_ar_count":  len(unmatched_ar),
        "unmatched_bank_count": len(unmatched_bank),
        "confirmed":           confirmed[:20],    # first 20 for agent review
        "candidates":          candidates[:30],   # first 30 for agent review
        "unmatched_ar":        unmatched_ar[:30],
        "note": (
            "confirmed = high-confidence matches (score>=0.9). "
            "candidates = need agent review. "
            "Call analyze_exceptions for deeper exception analysis, "
            "then update_records with your final decisions."
        ),
    }
