"""
MCP Tool 7 — Matching Engine
Runs the core matching algorithm on classified source and bank records.

Generic mode: uses match_columns from config to score any column pair dynamically.
Legacy mode:  uses hardcoded amount/date/reference scoring (backward compatible).

match_type per column pair:
  exact              — string equality (case-insensitive)
  numeric_tolerance  — abs difference <= amount_tolerance
  date_tolerance     — abs date difference <= date_tolerance_days
  fuzzy              — SequenceMatcher ratio >= fuzzy_ref_threshold
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


def _fuzzy_ratio(s1: str, s2: str) -> float:
    if not s1 or not s2:
        return 0.0
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def _get_val(record: dict, col_name: str):
    """Look up a value by column name — tries exact, lowercase, and underscore variants."""
    v = record.get(col_name)
    if v is not None:
        return v
    v = record.get(col_name.lower())
    if v is not None:
        return v
    v = record.get(col_name.lower().replace(" ", "_"))
    return v


# ---------------------------------------------------------------------------
# Generic scoring — uses match_columns from rules config
# ---------------------------------------------------------------------------

def _score_match_generic(ar: dict, bank: dict, rules: dict) -> float:
    match_columns = rules.get("match_columns", [])
    tol      = rules.get("amount_tolerance", 0.02)
    date_tol = rules.get("date_tolerance_days", 7)
    fuzz_thr = rules.get("fuzzy_ref_threshold", 0.80)

    total_weight = sum(m.get("weight", 1.0) for m in match_columns)
    if total_weight == 0:
        total_weight = 1.0

    score     = 0.0
    max_score = 0.0

    for col_pair in match_columns:
        source_col = col_pair.get("source_col", "")
        bank_col   = col_pair.get("bank_col", "")
        mtype      = col_pair.get("match_type", "exact")
        weight     = col_pair.get("weight", 1.0) / total_weight

        ar_val   = _get_val(ar,   source_col)
        bank_val = _get_val(bank, bank_col)
        max_score += weight

        if mtype == "numeric_tolerance":
            a = _safe_float(ar_val)
            b = _safe_float(bank_val)
            if _amount_match(a, b, tol):
                score += weight

        elif mtype == "date_tolerance":
            d1 = _parse_date(ar_val)
            d2 = _parse_date(bank_val)
            if _date_match(d1, d2, date_tol):
                score += weight

        elif mtype == "fuzzy":
            ratio = _fuzzy_ratio(str(ar_val or ""), str(bank_val or ""))
            if ratio >= fuzz_thr:
                score += weight * ratio
            else:
                score += weight * ratio * 0.5   # partial credit below threshold

        else:  # exact
            av = str(ar_val or "").strip().upper()
            bv = str(bank_val or "").strip().upper()
            if av and bv and av == bv:
                score += weight

    return round(score / max_score, 3) if max_score > 0 else 0.0


def _find_matches_generic(ar_records, bank_records, rules, min_score):
    """Generic matching path — O(n*m) scan using dynamic column pairs."""
    confirmed    = []
    candidates   = []
    matched_bank = set()
    unmatched_ar = []

    for a_idx, ar in enumerate(ar_records):
        best_score  = 0.0
        best_b_idx  = None
        best_record = None

        for b_idx, bank in enumerate(bank_records):
            if b_idx in matched_bank:
                continue
            score = _score_match_generic(ar, bank, rules)
            if score > best_score:
                best_score  = score
                best_b_idx  = b_idx
                best_record = bank

        if best_score >= 0.9 and best_b_idx is not None:
            matched_bank.add(best_b_idx)
            confirmed.append(_make_match_entry(a_idx, best_b_idx, best_score, ar, best_record))
        elif best_score >= min_score and best_b_idx is not None:
            candidates.append(_make_match_entry(a_idx, best_b_idx, best_score, ar, best_record))
        else:
            unmatched_ar.append({
                "ar_index":  a_idx,
                "ar_amount": _get_val(ar, "amount") or _get_val(ar, "Amount"),
                "ar_date":   _get_val(ar, "date")   or _get_val(ar, "Date") or "",
            })

    unmatched_bank = [
        {
            "bank_index":  b_idx,
            "bank_sheet":  bank_records[b_idx].get("__bank_sheet__", ""),
            "bank_amount": _get_val(bank_records[b_idx], "amount") or _get_val(bank_records[b_idx], "Amount"),
            "bank_date":   _get_val(bank_records[b_idx], "date")   or _get_val(bank_records[b_idx], "Date") or "",
        }
        for b_idx in range(len(bank_records))
        if b_idx not in matched_bank
    ]

    return confirmed, candidates, unmatched_ar, unmatched_bank


def _make_match_entry(a_idx, b_idx, score, ar, bank):
    return {
        "ar_index":    a_idx,
        "bank_index":  b_idx,
        "score":       score,
        "ar_amount":   _safe_float(_get_val(ar,   "amount") or _get_val(ar,   "Amount")),
        "bank_amount": _safe_float(_get_val(bank, "amount") or _get_val(bank, "Amount") or _get_val(bank, "credit_amount")),
        "bank_sheet":  bank.get("__bank_sheet__", ""),
        "bank_date":   _get_val(bank, "date") or _get_val(bank, "Date") or _get_val(bank, "transaction_date") or "",
        # Carry all bank values so update_records can build custom_fill
        "bank_record": bank,
    }


# ---------------------------------------------------------------------------
# Legacy scoring — hardcoded amount/date/reference (backward compatible)
# ---------------------------------------------------------------------------

def _score_match_legacy(ar: dict, bank: dict, rules: dict) -> float:
    score     = 0.0
    max_score = 0.0
    tol       = rules.get("amount_tolerance", 0.02)
    date_tol  = rules.get("date_tolerance_days", 7)
    fuzz_thr  = rules.get("fuzzy_ref_threshold", 0.80)

    ar_amt   = _safe_float(ar.get("amount"))
    bank_amt = _safe_float(bank.get("amount") or bank.get("credit_amount") or bank.get("credit_amt"))
    max_score += 0.5
    if _amount_match(ar_amt, bank_amt, tol):
        score += 0.5

    if "date" in rules.get("match_on", []):
        ar_dt   = _parse_date(ar.get("date"))
        bank_dt = _parse_date(bank.get("date") or bank.get("transaction_date") or bank.get("post_date"))
        max_score += 0.3
        if _date_match(ar_dt, bank_dt, date_tol):
            score += 0.3

    if "reference" in rules.get("match_on", []) or "check" in rules.get("match_on", []):
        ar_ref   = str(ar.get("check") or ar.get("cust_ref") or "")
        bank_ref = str(bank.get("cust_ref") or bank.get("bank_ref") or bank.get("check") or "")
        max_score += 0.2
        ratio = _fuzzy_ratio(ar_ref, bank_ref)
        score += 0.2 * ratio

    return round(score / max_score, 3) if max_score > 0 else 0.0


def _find_matches_legacy(ar_records, bank_records, rules, min_score):
    """Legacy matching path — uses amount index + hardcoded field lookups."""
    tol = rules.get("amount_tolerance", 0.02)

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
        ar_amt      = _safe_float(ar.get("amount"))
        best_score  = 0.0
        best_b_idx  = None
        best_record = None

        search_amts = {f"{round(ar_amt + step * tol / 5, 2):.2f}" for step in range(-5, 6)}
        search_amts.add(f"{round(ar_amt, 2):.2f}")
        b_candidates = list({b_idx for amt_key in search_amts for b_idx in bank_index.get(amt_key, []) if b_idx not in matched_bank})
        for b_idx, b in enumerate(bank_records):
            if b_idx not in matched_bank:
                b_amt = _safe_float(b.get("amount") or b.get("credit_amount") or b.get("credit_amt"))
                if abs(ar_amt - b_amt) <= tol * 2:
                    b_candidates.append(b_idx)
        b_candidates = list(set(b_candidates))

        for b_idx in b_candidates:
            b = bank_records[b_idx]
            score = _score_match_legacy(ar, b, rules)
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
                "bank_record": best_record,
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
                "bank_record": best_record,
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

    return confirmed, candidates, unmatched_ar, unmatched_bank


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_matches(
    amount_tolerance: float = None,
    date_tolerance_days: int = None,
    min_score: float = 0.5,
) -> dict:
    """
    Run the matching engine on classified source and bank records from state.

    Generic mode (match_columns in rules): dynamic column-pair scoring.
    Legacy mode (no match_columns): hardcoded amount/date/reference scoring.

    Returns:
      confirmed    : matches with score >= 0.9
      candidates   : matches with score in [min_score, 0.9) — need agent review
      unmatched_ar : source records with no candidate
      unmatched_bank: bank records with no source match
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
        return {"error": "No classified source records. Call classify_transactions first."}
    if not bank_records:
        return {"error": "No classified bank records. Call classify_transactions first."}

    match_columns = rules.get("match_columns", [])

    if match_columns:
        confirmed, candidates, unmatched_ar, unmatched_bank = _find_matches_generic(
            ar_records, bank_records, rules, min_score
        )
        mode = "generic"
    else:
        confirmed, candidates, unmatched_ar, unmatched_bank = _find_matches_legacy(
            ar_records, bank_records, rules, min_score
        )
        mode = "legacy"

    st["matches"] = {
        "confirmed":      confirmed,
        "candidates":     candidates,
        "unmatched_ar":   unmatched_ar,
        "unmatched_bank": unmatched_bank,
    }

    # Strip bank_record from returned preview to keep response small
    def _strip(entries, n):
        preview = []
        for e in entries[:n]:
            p = {k: v for k, v in e.items() if k != "bank_record"}
            preview.append(p)
        return preview

    return {
        "mode":                  mode,
        "confirmed_count":       len(confirmed),
        "candidate_count":       len(candidates),
        "unmatched_ar_count":    len(unmatched_ar),
        "unmatched_bank_count":  len(unmatched_bank),
        "confirmed":             _strip(confirmed, 20),
        "candidates":            _strip(candidates, 30),
        "unmatched_ar":          unmatched_ar[:30],
        "note": (
            "confirmed = high-confidence (score>=0.9). "
            "candidates = need agent review. "
            "Call analyze_exceptions, then update_records with custom_fill for each match."
        ),
    }
