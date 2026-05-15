"""
MCP Tool 12 — Report Generator
Creates a multi-sheet Excel report:
  Sheet 1: Reconciliation Results  (colour-coded by status)
  Sheet 2: Exception Report
  Sheet 3: Bank Orphans
  Sheet 4: Audit Log
  Sheet 5: Dashboard Summary
"""

import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.mcp_tools import state

GREEN  = PatternFill("solid", fgColor="C6EFCE")
RED    = PatternFill("solid", fgColor="FFC7CE")
YELLOW = PatternFill("solid", fgColor="FFEB9C")
GREY   = PatternFill("solid", fgColor="F2F2F2")
BLUE_H = PatternFill("solid", fgColor="1F497D")
BROWN  = PatternFill("solid", fgColor="7B3F00")
DASH   = PatternFill("solid", fgColor="D9E1F2")


def _hdr(ws, row, cols, fill):
    for c, h in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.fill = fill
        cell.font = Font(bold=True, color="FFFFFF" if fill != DASH else "000000")
        cell.alignment = Alignment(horizontal="center")


def _fill_row(ws, row, n_cols, fill):
    for c in range(1, n_cols + 1):
        ws.cell(row=row, column=c).fill = fill


def _auto_width(ws):
    for col in ws.columns:
        max_len = max(
            (len(str(cell.value)) if cell.value is not None else 0 for cell in col),
            default=0,
        )
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 2, 45)


def generate_report(output_dir: str = "output") -> dict:
    """
    Write the final multi-sheet Excel reconciliation report.
    Call this after log_audit.
    """
    st      = state.get()
    config  = state.get_config()
    dec     = st.get("decisions", [])
    exc     = st.get("exceptions", [])
    audit   = st.get("audit", [{}])[-1]
    ar_recs = st["classified"].get("ar", [])
    b_recs  = st["classified"].get("bank", [])

    if not ar_recs:
        return {"error": "No classified AR records."}
    if not dec:
        return {"error": "No decisions recorded. Call update_records first."}

    os.makedirs(output_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    ptype = config.get("payment_type", "RECON").upper()
    path = os.path.join(output_dir, f"{ptype.lower()}_recon_{ts}.xlsx")

    wb = Workbook()
    decision_map = {d["ar_index"]: d for d in dec}

    # -----------------------------------------------------------------------
    # Sheet 1 — Reconciliation Results
    # -----------------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Recon Results"
    hdrs = ["AR Index", "Client", "Date", "Check/Ref", "AR Amount",
            "Status", "Bank", "Bank Date", "Cleared Amt", "Open Amt",
            "Remarks 1", "Remarks 2", "Agent Reasoning"]
    _hdr(ws1, 1, hdrs, BLUE_H)

    row = 2
    for i, ar in enumerate(ar_recs):
        d = decision_map.get(i, {})
        status = d.get("status", "PENDING")
        vals = [
            i,
            ar.get("client_id") or ar.get("client") or "",
            ar.get("date", ""),
            ar.get("check") or ar.get("cust_ref") or "",
            ar.get("amount"),
            status,
            d.get("bank", ""),
            d.get("bank_date", ""),
            d.get("cleared_amount", ""),
            d.get("open_amount", ""),
            d.get("remarks_1", ""),
            d.get("remarks_2", ""),
            d.get("reasoning", ""),
        ]
        for c, v in enumerate(vals, 1):
            ws1.cell(row=row, column=c, value=v).alignment = Alignment(wrap_text=False)
        fill = GREEN if status == "MATCHED" else RED if status == "UNMATCHED" else YELLOW if status == "PARTIAL" else GREY
        _fill_row(ws1, row, len(hdrs), fill)
        row += 1

    _auto_width(ws1)
    ws1.freeze_panes = "A2"

    # -----------------------------------------------------------------------
    # Sheet 2 — Exception Report
    # -----------------------------------------------------------------------
    ws2 = wb.create_sheet("Exceptions")
    e_hdrs = ["Type", "AR Index", "Bank Index", "Bank Sheet", "AR Amount", "Bank Amount", "Difference", "Detail"]
    _hdr(ws2, 1, e_hdrs, BROWN)

    for row_i, e in enumerate(exc, 2):
        vals = [
            e.get("type"), e.get("ar_index"), e.get("bank_index"), e.get("bank_sheet"),
            e.get("ar_amount"), e.get("bank_amount"),
            e.get("difference"), e.get("detail"),
        ]
        for c, v in enumerate(vals, 1):
            ws2.cell(row=row_i, column=c, value=v)
        _fill_row(ws2, row_i, len(e_hdrs), RED if "MISSING" in str(e.get("type")) else YELLOW)

    _auto_width(ws2)

    # -----------------------------------------------------------------------
    # Sheet 3 — Bank Orphans
    # -----------------------------------------------------------------------
    ws3 = wb.create_sheet("Bank Orphans")
    o_hdrs = ["Bank Sheet", "Bank Index", "Date", "Amount", "Description"]
    _hdr(ws3, 1, o_hdrs, BROWN)

    matched_bank_idx = {d.get("bank_index") for d in dec if d.get("bank_index") is not None}
    row_o = 2
    for b_idx, b in enumerate(b_recs):
        if b_idx not in matched_bank_idx:
            vals = [
                b.get("__bank_sheet__", ""),
                b_idx,
                b.get("date") or b.get("transaction_date") or b.get("post_date") or "",
                b.get("amount") or b.get("credit_amount"),
                b.get("description") or b.get("transaction_description") or "",
            ]
            for c, v in enumerate(vals, 1):
                ws3.cell(row=row_o, column=c, value=v)
            _fill_row(ws3, row_o, len(o_hdrs), RED)
            row_o += 1

    _auto_width(ws3)

    # -----------------------------------------------------------------------
    # Sheet 4 — Audit Log
    # -----------------------------------------------------------------------
    ws4 = wb.create_sheet("Audit Log")
    ws4.column_dimensions["A"].width = 35
    ws4.column_dimensions["B"].width = 28

    audit_rows = [
        ("--- RUN INFORMATION ---",              ""),
        ("Run ID",                               audit.get("run_id", "")),
        ("Timestamp",                            audit.get("timestamp", "")),
        ("Processing Time (sec)",                audit.get("processing_time_sec")),
        ("Agent Model",                          os.environ.get("ANTHROPIC_MODEL", os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""))),
        ("", ""),
        ("--- INPUT ---",                        ""),
        ("Payment Type",                         audit.get("payment_type")),
        ("Input File",                           audit.get("input_file")),
        ("AR Sheet",                             audit.get("ar_sheet")),
        ("Bank Sheets",                          str(audit.get("bank_sheets", []))),
        ("", ""),
        ("--- RESULTS ---",                      ""),
        ("Total AR Records",                     audit.get("ar_total_records")),
        ("Matched",                              audit.get("matched_count")),
        ("Partial",                              audit.get("partial_count")),
        ("Unmatched",                            audit.get("unmatched_count")),
        ("Pending (no decision)",                audit.get("pending_count")),
        ("", ""),
        ("--- AMOUNTS ---",                      ""),
        ("Matched Total",                        f"${audit.get('matched_total_amount', 0):,.2f}"),
        ("Unmatched Total",                      f"${audit.get('unmatched_total_amount', 0):,.2f}"),
        ("", ""),
        ("--- EXCEPTIONS ---",                   ""),
        *[(f"  {k}", v) for k, v in audit.get("exception_summary", {}).items()],
        ("", ""),
        ("--- GP VALIDATION ---",                ""),
        ("GP Status",                            audit.get("gp_validation")),
        ("GP Difference",                        audit.get("gp_difference")),
        ("", ""),
        ("--- STATUS ---",                       ""),
        ("Reconciliation Status",               audit.get("recon_status")),
        ("Notes",                                audit.get("notes", "")),
        ("", ""),
        ("--- COLOUR LEGEND ---",                ""),
        ("GREEN",                                "MATCHED"),
        ("RED",                                  "UNMATCHED"),
        ("YELLOW",                               "PARTIAL"),
        ("GREY",                                 "PENDING"),
    ]

    for r, (label, val) in enumerate(audit_rows, 1):
        ca = ws4.cell(row=r, column=1, value=label)
        cb = ws4.cell(row=r, column=2, value=val)
        if label.startswith("---"):
            ca.font = Font(bold=True)
            ca.fill = DASH
        legend = {"GREEN": GREEN, "RED": RED, "YELLOW": YELLOW, "GREY": GREY}
        if label in legend:
            cb.fill = legend[label]

    # -----------------------------------------------------------------------
    # Sheet 5 — Dashboard Summary
    # -----------------------------------------------------------------------
    ws5 = wb.create_sheet("Dashboard")
    ws5.column_dimensions["A"].width = 30
    ws5.column_dimensions["B"].width = 20

    matched_cnt   = audit.get("matched_count", 0)
    unmatched_cnt = audit.get("unmatched_count", 0)
    partial_cnt   = audit.get("partial_count", 0)
    total_ar      = audit.get("ar_total_records", 1) or 1
    match_rate    = round(matched_cnt / total_ar * 100, 1)

    dash_rows = [
        ("BILLING RECONCILIATION DASHBOARD", ""),
        ("Payment Type",        ptype),
        ("Run Date",            datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("", ""),
        ("Match Rate",          f"{match_rate}%"),
        ("Matched",             matched_cnt),
        ("Partial",             partial_cnt),
        ("Unmatched",           unmatched_cnt),
        ("Total AR Records",    total_ar),
        ("", ""),
        ("Matched Amount",      f"${audit.get('matched_total_amount', 0):,.2f}"),
        ("Unmatched Amount",    f"${audit.get('unmatched_total_amount', 0):,.2f}"),
        ("", ""),
        ("Reconciliation Status", audit.get("recon_status", "")),
    ]

    for r, (label, val) in enumerate(dash_rows, 1):
        ca = ws5.cell(row=r, column=1, value=label)
        cb = ws5.cell(row=r, column=2, value=val)
        if r == 1:
            ca.font = Font(bold=True, size=14)
        if label == "Match Rate":
            cb.font = Font(bold=True, size=16, color="375623")
        if label == "Reconciliation Status":
            status_fill = GREEN if val == "COMPLETE" else YELLOW if val == "PARTIAL" else RED
            cb.fill = status_fill

    _auto_width(ws5)

    wb.save(path)
    st["output_path"] = path

    return {
        "output_file":   path,
        "sheets":        ["Recon Results", "Exceptions", "Bank Orphans", "Audit Log", "Dashboard"],
        "audit_summary": {
            "matched_count":          matched_cnt,
            "unmatched_count":        unmatched_cnt,
            "partial_count":          partial_cnt,
            "matched_total_amount":   audit.get("matched_total_amount", 0),
            "unmatched_total_amount": audit.get("unmatched_total_amount", 0),
            "recon_status":           audit.get("recon_status"),
        },
        "status": "Report generated successfully.",
    }
