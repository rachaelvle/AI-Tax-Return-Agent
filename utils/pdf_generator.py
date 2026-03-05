"""
pdf_generator.py – Fills the real IRS Form 1040 (TY 2025) template with computed tax data.

Strategy:
  1. Load the cached IRS f1040.pdf template (downloads from irs.gov on first use).
  2. Fill every dollar-amount field via AcroForm (pypdf update_page_form_field_values).
  3. Set the filing-status checkbox by directly writing /V and /AS on the correct
     widget annotation — no overlay needed.
  4. Fall back to a styled reportlab-only summary if the template or pypdf is
     unavailable.

AcroForm field mapping (2025 IRS Form 1040, verified from widget annotations):
  Page 1 – Income
    f1_47  Line 1a  Wages (W-2 box 1)
    f1_57  Line 1z  Total wages (= 1a when no other sub-lines)
    f1_59  Line 2b  Taxable interest
    f1_61  Line 3b  Ordinary dividends
    f1_70  Line 7   Capital gain or (loss)
    f1_72  Line 8   Additional income (Schedule 1 total)
    f1_73  Line 9   Total income
    f1_74  Line 10  Adjustments to income (Schedule 1)
    f1_75  Line 11  Adjusted Gross Income

  Page 2 – Tax, Credits, Payments
    f2_02  Line 12  Standard or itemized deduction
    f2_04  Line 14  Add lines 12 + 13 (QBI = 0)
    f2_05  Line 15  Taxable income
    f2_06  Line 16  Tax
    f2_09  Line 18  Add lines 16 + 17 (AMT = 0)
    f2_10  Line 19  Child tax credit / credits for other dependents
    f2_12  Line 21  Total credits
    f2_13  Line 22  Tax after credits
    f2_14  Line 23  Other taxes (self-employment tax)
    f2_15  Line 24  Total tax
    f2_17  Line 25a Federal income tax withheld (W-2)
    f2_20  Line 25d Total withholding
    f2_21  Line 26  Estimated tax payments
    f2_28  Line 34  Total payments
    f2_29  Line 35a Amount overpaid (refund)
    f2_34  Line 37  Amount you owe
"""

import io
import os
import urllib.request
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

try:
    import logging

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

# ── Paths ─────────────────────────────────────────────────────────────────────
IRS_1040_URL = "https://www.irs.gov/pub/irs-pdf/f1040.pdf"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
TEMPLATE_PATH = os.path.join(ASSETS_DIR, "f1040_template.pdf")

# ── Label maps ────────────────────────────────────────────────────────────────
CREDIT_LABELS = {
    "childtax": "Child Tax Credit",
    "childcare": "Child & Dependent Care Credit",
    "eitc": "Earned Income Credit",
    "education": "Education Credits (Form 8863)",
    "savers": "Saver's Credit (Form 8880)",
    "ev": "EV / Clean Energy Credit (Form 8936)",
}

INCOME_LABELS = {
    "wages": "Wages, Salaries, Tips (W-2)",
    "selfEmploy": "Self-Employment Income (Schedule C)",
    "capitalGains": "Capital Gains / Investment Income",
    "rental": "Rental Income (Schedule E)",
    "dividend": "Dividends & Interest (1099-DIV/INT)",
    "unemployment": "Unemployment Compensation (1099-G)",
    "otherIncome": "Other Income",
}


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt(n):
    """Dollar string with $ sign (used by the fallback reportlab layout)."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        v = 0.0
    if v < 0:
        return f"(${abs(v):,.2f})"
    return f"${v:,.2f}"


def _fv(n):
    """Format a value for an IRS AcroForm field: integer with commas, no $."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return ""
    return f"{int(round(abs(v))):,}"  # e.g. "75,000"


# ── Template management ───────────────────────────────────────────────────────

def _get_template() -> Optional[bytes]:
    """Return cached IRS 1040 PDF bytes, downloading from irs.gov if needed."""
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "rb") as f:
            return f.read()
    try:
        os.makedirs(ASSETS_DIR, exist_ok=True)
        req = urllib.request.Request(
            IRS_1040_URL, headers={"User-Agent": "TaxEstimator/1.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(data)
        return data
    except Exception:
        return None


# ── Filing-status checkbox ────────────────────────────────────────────────────

# The five filing-status checkboxes all carry the short name c1_8[n] but have
# unique AP export values in their Normal appearance dictionary:
#   /1 = Single   /2 = MFJ   /3 = MFS   /4 = HOH   /5 = QSS
_FILING_EXPORT = {
    "single": "/1",
    "mfj":    "/2",
    "mfs":    "/3",
    "hoh":    "/4",
    "qss":    "/5",
}


def _set_filing_status(page, filing_status: str) -> None:
    """
    Activate the correct filing-status checkbox on page 1 by writing /V and /AS
    directly on each widget annotation whose /T starts with 'c1_8'.

    Matched checkbox  → /AS = /V = export value (e.g. /1)
    All other c1_8    → /AS = /V = /Off
    """
    target = _FILING_EXPORT.get(filing_status, "/1")

    for ref in page.get("/Annots", []):
        annot = ref.get_object() if hasattr(ref, "get_object") else ref
        if str(annot.get("/T", ""))[:5] != "c1_8[":
            continue
        ap_n = annot.get("/AP", {}).get("/N")
        if ap_n is None:
            continue
        try:
            ap_obj = ap_n.get_object() if hasattr(ap_n, "get_object") else ap_n
            exports = [k for k in ap_obj.keys() if k != "/Off"]
        except Exception:
            continue
        if not exports:
            continue

        export_val = exports[0]
        new_state = NameObject(export_val if export_val == target else "/Off")
        annot[NameObject("/V")]  = new_state
        annot[NameObject("/AS")] = new_state


# ── IRS template filler ───────────────────────────────────────────────────────

def _fill_irs_template(data: dict) -> Optional[bytes]:
    """
    Fill the IRS 1040 template with computed tax data.
    Returns filled PDF bytes, or None if the template can't be loaded.
    """
    template_bytes = _get_template()
    if not template_bytes:
        return None

    r = data["result"]
    income = data.get("income", {})
    withheld = float(data.get("withheld", 0) or 0)
    est_pay = float(data.get("estimated_payments", 0) or 0)

    wages = float(income.get("wages", 0) or 0)
    div = float(income.get("dividend", 0) or 0)
    cap = float(income.get("capitalGains", 0) or 0)
    # Income reported via Schedule 1 (self-employment, rental, unemployment, other)
    sched1 = (
        float(income.get("selfEmploy", 0) or 0)
        + float(income.get("rental", 0) or 0)
        + float(income.get("unemployment", 0) or 0)
        + float(income.get("otherIncome", 0) or 0)
    )

    tc = float(r.get("total_credits", 0) or 0)
    se = float(r.get("se_tax", 0) or 0)
    income_tax = float(r["income_tax"])
    tax_after_credits = max(0.0, income_tax - tc)

    # ── Page 1: income fields ────────────────────────────────────────────────
    p1: dict[str, str] = {}
    if wages:
        p1["f1_47[0]"] = _fv(wages)   # Line 1a  wages
        p1["f1_57[0]"] = _fv(wages)   # Line 1z  total wages
    if div:
        p1["f1_59[0]"] = _fv(div)     # Line 2b  taxable interest
        p1["f1_61[0]"] = _fv(div)     # Line 3b  ordinary dividends
    if cap:
        p1["f1_70[0]"] = _fv(cap)     # Line 7   capital gain/(loss)
    if sched1:
        p1["f1_72[0]"] = _fv(sched1)  # Line 8   additional income (Sch 1)
    p1["f1_73[0]"] = _fv(r["gross_income"])   # Line 9   total income
    if r["adj_total"]:
        p1["f1_74[0]"] = _fv(r["adj_total"]) # Line 10  adjustments
    p1["f1_75[0]"] = _fv(r["agi"])            # Line 11  AGI

    # ── Page 2: tax / credits / payments ────────────────────────────────────
    p2: dict[str, str] = {}
    p2["f2_02[0]"] = _fv(r["deduction_used"])          # Line 12  deduction
    p2["f2_04[0]"] = _fv(r["deduction_used"])          # Line 14  (= 12, QBI = 0)
    p2["f2_05[0]"] = _fv(r["taxable_income"])          # Line 15  taxable income
    p2["f2_06[0]"] = _fv(income_tax)                   # Line 16  tax
    p2["f2_09[0]"] = _fv(income_tax)                   # Line 18  (= 16, AMT = 0)
    if tc:
        p2["f2_10[0]"] = _fv(tc)                       # Line 19  credits
        p2["f2_12[0]"] = _fv(tc)                       # Line 21  total credits
    p2["f2_13[0]"] = _fv(tax_after_credits)            # Line 22  tax after credits
    if se:
        p2["f2_14[0]"] = _fv(se)                       # Line 23  SE tax
    p2["f2_15[0]"] = _fv(r["total_tax_liability"])     # Line 24  total tax
    if withheld:
        p2["f2_17[0]"] = _fv(withheld)                 # Line 25a W-2 withholding
        p2["f2_20[0]"] = _fv(withheld)                 # Line 25d total withholding
    if est_pay:
        p2["f2_21[0]"] = _fv(est_pay)                  # Line 26  estimated payments
    p2["f2_28[0]"] = _fv(r["total_payments"])          # Line 34  total payments
    if r["is_refund"]:
        p2["f2_29[0]"] = _fv(abs(r["refund_or_owed"])) # Line 35a refund
    else:
        p2["f2_34[0]"] = _fv(abs(r["refund_or_owed"])) # Line 37  amount owed

    # ── Fill form fields ─────────────────────────────────────────────────────
    reader = PdfReader(io.BytesIO(template_bytes))
    writer = PdfWriter()
    writer.append(reader)

    writer.update_page_form_field_values(writer.pages[0], p1, auto_regenerate=False)
    writer.update_page_form_field_values(writer.pages[1], p2, auto_regenerate=False)
    _set_filing_status(writer.pages[0], data.get("filing_status", "single"))

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


# ── Fallback: styled reportlab summary ───────────────────────────────────────

def _fallback_pdf(data: dict) -> bytes:
    """
    Pure-reportlab styled summary used when the IRS template is unavailable.
    Mimics the structure and line numbers of the real 1040.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    r = data["result"]
    income = data.get("income", {})
    adjustments = data.get("adjustments", {})
    itemized = data.get("itemized", {})
    credits_selected = data.get("credits_selected", [])

    title_style = ParagraphStyle(
        "title", parent=styles["Normal"],
        fontSize=16, fontName="Helvetica-Bold", alignment=TA_CENTER,
        textColor=colors.HexColor("#1a1a2e"), spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica-Bold",
        textColor=colors.white,
        backColor=colors.HexColor("#1a1a2e"),
        leftIndent=4, spaceBefore=10, spaceAfter=2,
    )

    def section_row(text):
        return Table(
            [[Paragraph(f"  {text}", section_style)]],
            colWidths=[7.3 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]),
        )

    def data_row(line, description, amount, highlight=False):
        bg = colors.HexColor("#f0f7f0") if highlight else colors.white
        txt_color = colors.HexColor("#1a6e2a") if highlight else colors.black
        return Table(
            [[
                Paragraph(str(line), ParagraphStyle(
                    "ln", parent=styles["Normal"], fontSize=7.5,
                    textColor=colors.HexColor("#999"), alignment=TA_CENTER,
                )),
                Paragraph(description, ParagraphStyle(
                    "desc", parent=styles["Normal"], fontSize=8.5,
                )),
                Paragraph(fmt(amount), ParagraphStyle(
                    "amt", parent=styles["Normal"], fontSize=8.5,
                    alignment=TA_RIGHT, textColor=txt_color,
                    fontName="Helvetica-Bold" if highlight else "Helvetica",
                )),
            ]],
            colWidths=[0.4 * inch, 5.5 * inch, 1.4 * inch],
            style=TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), bg),
                ("LINEBELOW",    (0, 0), (-1, -1), 0.3, colors.HexColor("#e0e0e0")),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("LEFTPADDING",  (1, 0), (1, 0),   6),
            ]),
        )

    elements = []

    # Header
    title_table = Table(
        [[
            Paragraph("Form <b>1040</b>", ParagraphStyle(
                "t1", parent=styles["Normal"],
                fontSize=22, fontName="Helvetica-Bold",
                textColor=colors.HexColor("#1a1a2e"),
            )),
            Paragraph(
                "U.S. Individual Income Tax Return<br/>"
                "<font size=9 color='#555'>Tax Year January 1 – December 31, 2025</font>",
                ParagraphStyle("t2", parent=styles["Normal"], fontSize=12, leftIndent=4),
            ),
            Paragraph(
                f"<b>ESTIMATED</b><br/>"
                f"<font size=7 color='#888'>Generated {date.today().strftime('%B %d, %Y')}</font>",
                ParagraphStyle(
                    "t3", parent=styles["Normal"], fontSize=9,
                    alignment=TA_RIGHT, textColor=colors.HexColor("#c0392b"),
                ),
            ),
        ]],
        colWidths=[1.5 * inch, 4.0 * inch, 1.8 * inch],
        style=TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW",    (0, 0), (-1, -1), 1.5, colors.HexColor("#1a1a2e")),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ]),
    )
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(title_table)
    elements.append(Spacer(1, 0.12 * inch))

    # Filer Info
    info_table = Table(
        [[
            "Filing Status:", r["status_label"],
            "Dependents:", str(r["dependents"]),
            "Deduction:", r.get("deduction_label", "Standard"),
        ]],
        colWidths=[1.1*inch, 1.8*inch, 0.9*inch, 0.6*inch, 1.0*inch, 1.75*inch],
        style=TableStyle([
            ("FONTSIZE",     (0, 0), (-1, -1), 8),
            ("FONTNAME",     (0, 0), (0, 0),   "Helvetica-Bold"),
            ("FONTNAME",     (2, 0), (2, 0),   "Helvetica-Bold"),
            ("FONTNAME",     (4, 0), (4, 0),   "Helvetica-Bold"),
            ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
            ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ]),
    )
    elements.append(info_table)
    elements.append(Spacer(1, 0.15 * inch))

    # Part I – Income
    elements.append(section_row("PART I — INCOME"))
    line = 1
    for field, label in INCOME_LABELS.items():
        v = income.get(field, 0)
        if v and v > 0:
            elements.append(data_row(line, label, v))
        line += 1
    elements.append(data_row("9", "Total Gross Income", r["gross_income"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # Part II – Adjustments
    elements.append(section_row("PART II — ADJUSTMENTS TO INCOME (Above-the-Line)"))
    for ln, desc, amt in [
        ("10a", "Student Loan Interest Deduction",         adjustments.get("studentLoan", 0)),
        ("10b", "IRA / 401(k) Contributions Deduction",   adjustments.get("ira", 0)),
        ("10c", "HSA Contributions Deduction",             adjustments.get("hsa", 0)),
        ("10d", "Deductible Part of Self-Employment Tax",  r.get("se_deduction", 0)),
    ]:
        if amt and amt > 0:
            elements.append(data_row(ln, desc, amt))
    elements.append(data_row("10", "Total Adjustments",                   r["adj_total"]))
    elements.append(data_row("11", "Adjusted Gross Income (Line 9 − 10)", r["agi"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # Part III – Deductions & Taxable Income
    elements.append(section_row("PART III — DEDUCTIONS & TAXABLE INCOME"))
    elements.append(data_row("12", f"Deduction ({r.get('deduction_label', 'Standard')})", r["deduction_used"]))
    if data.get("deduction_method") == "itemized" and r.get("itemized_total", 0) > 0:
        for field, lbl in [
            ("mortgage",        "Mortgage Interest"),
            ("salt",            "State & Local Taxes (SALT, capped $10k)"),
            ("charity",         "Charitable Contributions"),
            ("medical",         "Medical Expenses"),
            ("otherDeductions", "Other Itemized Deductions"),
        ]:
            v = itemized.get(field, 0)
            if v > 0:
                elements.append(data_row("  ", f"   └ {lbl}", v))
    elements.append(data_row("15", "Taxable Income (Line 11 − 12)", r["taxable_income"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # Part IV – Tax
    elements.append(section_row("PART IV — TAX COMPUTATION"))
    elements.append(data_row("16", "Federal Income Tax (2025 Tax Tables)", r["income_tax"]))
    if r.get("se_tax", 0) > 0:
        elements.append(data_row("23", "Self-Employment Tax (Schedule SE)", r["se_tax"]))
    elements.append(data_row("24",
        f"Total Tax  ·  Effective Rate: {r['effective_rate']}%  ·  Marginal Rate: {r['marginal_rate']}%",
        r["total_tax_liability"],
    ))
    elements.append(Spacer(1, 0.06 * inch))

    # Part V – Credits
    if credits_selected:
        elements.append(section_row("PART V — NONREFUNDABLE CREDITS"))
        for i, credit in enumerate(credits_selected):
            amt = r.get("credit_detail", {}).get(credit, 0)
            lbl = CREDIT_LABELS.get(credit, credit)
            elements.append(data_row(f"19{chr(97+i)}", lbl, amt))
        elements.append(data_row("21", "Total Credits Applied", r["total_credits"]))
        elements.append(Spacer(1, 0.06 * inch))

    # Part VI – Payments & Result
    elements.append(section_row("PART VI — PAYMENTS & REFUND / BALANCE DUE"))
    elements.append(data_row("24", "Total Tax Liability", r["total_tax_liability"]))
    elements.append(data_row("25a", "Federal Income Tax Withheld (W-2 Box 2)", data.get("withheld", 0)))
    if data.get("estimated_payments", 0) > 0:
        elements.append(data_row("26", "Estimated Tax Payments (Quarterly)", data["estimated_payments"]))
    elements.append(data_row("34", "Total Payments", r["total_payments"]))
    elements.append(Spacer(1, 0.1 * inch))

    # Result box
    result_label = "ESTIMATED REFUND" if r["is_refund"] else "BALANCE DUE TO IRS"
    result_color = colors.HexColor("#1a6e2a") if r["is_refund"] else colors.HexColor("#c0392b")
    result_table = Table(
        [[
            Paragraph(result_label, ParagraphStyle(
                "rl", parent=styles["Normal"],
                fontSize=11, fontName="Helvetica-Bold",
                textColor=colors.white, alignment=TA_LEFT,
            )),
            Paragraph(fmt(abs(r["refund_or_owed"])), ParagraphStyle(
                "ra", parent=styles["Normal"],
                fontSize=14, fontName="Helvetica-Bold",
                textColor=colors.white, alignment=TA_RIGHT,
            )),
        ]],
        colWidths=[5.3 * inch, 2.0 * inch],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), result_color),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("LEFTPADDING",  (0, 0), (0, 0),   12),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 12),
        ]),
    )
    elements.append(result_table)
    elements.append(Spacer(1, 0.25 * inch))

    # Disclaimer
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccc")))
    elements.append(Spacer(1, 0.06 * inch))
    elements.append(Paragraph(
        "IMPORTANT DISCLAIMER: This is a <b>mock, estimated tax return</b> generated by an AI tool "
        "for informational and educational purposes only. It does <b>not</b> constitute an official "
        "IRS filing. Tax calculations are simplified and may not reflect your actual tax liability. "
        "Always consult a licensed tax professional or use IRS-approved software for your official "
        "return. Do <b>not</b> submit this document to the IRS.",
        ParagraphStyle(
            "disc", parent=styles["Normal"], fontSize=6.5,
            textColor=colors.HexColor("#888"), alignment=TA_CENTER, leading=10,
        ),
    ))

    doc.build(elements)
    buf.seek(0)
    return buf.read()


# ── Public API ────────────────────────────────────────────────────────────────

def generate_1040_pdf(data: dict) -> bytes:
    """
    Generate a 1040 PDF.
    Tries the IRS-template approach first; falls back to the styled summary.
    """
    if HAS_PYPDF:
        result = _fill_irs_template(data)
        if result:
            return result
    return _fallback_pdf(data)


def get_pdf_response(data: dict, inline: bool = False):
    """
    Returns (pdf_bytes, content_disposition).
    inline=True  → browser previews the PDF  (View button)
    inline=False → browser downloads the PDF (Download button)
    """
    pdf_bytes = generate_1040_pdf(data)
    disposition = (
        'inline; filename="Form1040_FY2025_Estimated.pdf"'
        if inline else
        'attachment; filename="Form1040_FY2025_Estimated.pdf"'
    )
    return pdf_bytes, disposition
