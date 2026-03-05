"""
pdf_generator.py – Generates a mock IRS Form 1040 (FY 2025) as a PDF.
Uses reportlab for layout. Mimics the structure and line numbers of a real 1040.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
import io
from datetime import date

CREDIT_LABELS = {
    "childtax":  "Child Tax Credit",
    "childcare": "Child & Dependent Care Credit",
    "eitc":      "Earned Income Credit",
    "education": "Education Credits (Form 8863)",
    "savers":    "Saver's Credit (Form 8880)",
    "ev":        "EV / Clean Energy Credit (Form 8936)",
}

INCOME_LABELS = {
    "wages":        "Wages, Salaries, Tips (W-2)",
    "selfEmploy":   "Self-Employment Income (Schedule C)",
    "capitalGains": "Capital Gains / Investment Income",
    "rental":       "Rental Income (Schedule E)",
    "dividend":     "Dividends & Interest (1099-DIV/INT)",
    "unemployment": "Unemployment Compensation (1099-G)",
    "otherIncome":  "Other Income",
}


def fmt(n):
    """Format a number as a dollar string."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        v = 0.0
    if v < 0:
        return f"(${abs(v):,.2f})"
    return f"${v:,.2f}"


def generate_1040_pdf(data: dict) -> bytes:
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

    # ── Custom styles ────────────────────────────────────────────────────────
    title_style = ParagraphStyle("title", parent=styles["Normal"],
        fontSize=16, fontName="Helvetica-Bold", alignment=TA_CENTER,
        textColor=colors.HexColor("#1a1a2e"), spaceAfter=2)
    sub_style = ParagraphStyle("sub", parent=styles["Normal"],
        fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#555"))
    section_style = ParagraphStyle("section", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#ffffff"),
        backColor=colors.HexColor("#1a1a2e"),
        leftIndent=4, spaceBefore=10, spaceAfter=2)
    label_style = ParagraphStyle("label", parent=styles["Normal"],
        fontSize=8.5, textColor=colors.HexColor("#333"))
    note_style = ParagraphStyle("note", parent=styles["Normal"],
        fontSize=7, textColor=colors.HexColor("#888"), alignment=TA_CENTER)

    def section_row(text):
        return Table(
            [[Paragraph(f"  {text}", section_style)]],
            colWidths=[7.3 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )

    def data_row(line, description, amount, highlight=False):
        bg = colors.HexColor("#f0f7f0") if highlight else colors.white
        txt_color = colors.HexColor("#1a6e2a") if highlight else colors.black
        return Table(
            [[
                Paragraph(str(line), ParagraphStyle("ln", parent=styles["Normal"], fontSize=7.5,
                    textColor=colors.HexColor("#999"), alignment=TA_CENTER)),
                Paragraph(description, ParagraphStyle("desc", parent=styles["Normal"], fontSize=8.5)),
                Paragraph(fmt(amount), ParagraphStyle("amt", parent=styles["Normal"], fontSize=8.5,
                    alignment=TA_RIGHT, textColor=txt_color,
                    fontName="Helvetica-Bold" if highlight else "Helvetica")),
            ]],
            colWidths=[0.4 * inch, 5.5 * inch, 1.4 * inch],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e0e0e0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
            ])
        )

    elements = []

    # ── Header ────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("DEPARTMENT OF THE TREASURY — INTERNAL REVENUE SERVICE", note_style),
    ]]
    elements.append(Spacer(1, 0.1 * inch))

    title_table = Table(
        [[
            Paragraph("Form <b>1040</b>", ParagraphStyle("t1", parent=styles["Normal"],
                fontSize=22, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a1a2e"))),
            Paragraph("U.S. Individual Income Tax Return<br/><font size=9 color='#555'>Tax Year January 1 – December 31, 2025</font>",
                ParagraphStyle("t2", parent=styles["Normal"], fontSize=12, leftIndent=4)),
            Paragraph(f"<b>MOCK / ESTIMATED</b><br/><font size=7 color='#888'>Generated {date.today().strftime('%B %d, %Y')}</font>",
                ParagraphStyle("t3", parent=styles["Normal"], fontSize=9, alignment=TA_RIGHT,
                    textColor=colors.HexColor("#c0392b"))),
        ]],
        colWidths=[1.5 * inch, 4.0 * inch, 1.8 * inch],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 1.5, colors.HexColor("#1a1a2e")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    elements.append(title_table)
    elements.append(Spacer(1, 0.12 * inch))

    # ── Filer Info ────────────────────────────────────────────────────────────
    info_data = [
        ["Filing Status:", r["status_label"], "Dependents:", str(r["dependents"]),
         "Deduction Method:", r.get("deduction_label", "Standard")],
    ]
    info_table = Table(info_data, colWidths=[1.1*inch, 1.8*inch, 0.9*inch, 0.6*inch, 1.25*inch, 1.55*inch],
        style=TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
            ("FONTNAME", (4, 0), (4, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ddd")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    elements.append(info_table)
    elements.append(Spacer(1, 0.15 * inch))

    # ── Part I: Income ────────────────────────────────────────────────────────
    elements.append(section_row("PART I — INCOME"))
    line = 1
    for field, label in INCOME_LABELS.items():
        v = income.get(field, 0)
        if v and v > 0:
            elements.append(data_row(line, label, v))
        line += 1
    elements.append(data_row("8", "Total Gross Income", r["gross_income"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # ── Part II: Adjustments ──────────────────────────────────────────────────
    elements.append(section_row("PART II — ADJUSTMENTS TO INCOME (Above-the-Line)"))
    adj_items = [
        ("9",  "Student Loan Interest Deduction (max $2,500)", adjustments.get("studentLoan", 0)),
        ("10", "IRA / 401(k) Contributions Deduction (max $23,500)", adjustments.get("ira", 0)),
        ("11", "HSA Contributions Deduction (max $8,550)", adjustments.get("hsa", 0)),
        ("12", "Deductible Part of Self-Employment Tax", r.get("se_deduction", 0)),
    ]
    for ln, desc, amt in adj_items:
        if amt and amt > 0:
            elements.append(data_row(ln, desc, amt))
    elements.append(data_row("13", "Total Adjustments", r["adj_total"]))
    elements.append(data_row("14", "Adjusted Gross Income (Line 8 − Line 13)", r["agi"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # ── Part III: Deductions & Taxable Income ─────────────────────────────────
    elements.append(section_row("PART III — DEDUCTIONS & TAXABLE INCOME"))
    elements.append(data_row("15", f"Deduction ({r.get('deduction_label', 'Standard')})", r["deduction_used"]))
    if data.get("deduction_method") == "itemized" and r.get("itemized_total", 0) > 0:
        for field, lbl in [("mortgage","Mortgage Interest"),("salt","State & Local Taxes (SALT, capped $10k)"),
                           ("charity","Charitable Contributions"),("medical","Medical Expenses"),
                           ("otherDeductions","Other Itemized Deductions")]:
            v = itemized.get(field, 0)
            if v > 0:
                elements.append(data_row("  ", f"   └ {lbl}", v))
    elements.append(data_row("16", "Taxable Income (Line 14 − Line 15)", r["taxable_income"], highlight=True))
    elements.append(Spacer(1, 0.06 * inch))

    # ── Part IV: Tax ──────────────────────────────────────────────────────────
    elements.append(section_row("PART IV — TAX COMPUTATION"))
    elements.append(data_row("17", "Federal Income Tax (2025 Tax Tables)", r["income_tax"]))
    if r.get("se_tax", 0) > 0:
        elements.append(data_row("18", "Self-Employment Tax (Schedule SE)", r["se_tax"]))
    elements.append(data_row("19", f"Effective Rate: {r['effective_rate']}%  ·  Marginal Rate: {r['marginal_rate']}%",
        r["income_tax"] + r.get("se_tax", 0)))
    elements.append(Spacer(1, 0.06 * inch))

    # ── Part V: Credits ───────────────────────────────────────────────────────
    if credits_selected:
        elements.append(section_row("PART V — NONREFUNDABLE CREDITS"))
        for i, credit in enumerate(credits_selected):
            amt = r.get("credit_detail", {}).get(credit, 0)
            lbl = CREDIT_LABELS.get(credit, credit)
            elements.append(data_row(f"20{chr(97+i)}", lbl, amt))
        elements.append(data_row("21", "Total Credits Applied", r["total_credits"]))
        elements.append(Spacer(1, 0.06 * inch))

    # ── Part VI: Payments & Result ────────────────────────────────────────────
    elements.append(section_row("PART VI — PAYMENTS & REFUND / BALANCE DUE"))
    elements.append(data_row("22", "Total Tax Liability", r["total_tax_liability"]))
    elements.append(data_row("23", "Federal Income Tax Withheld (W-2 Box 2)", data.get("withheld", 0)))
    if data.get("estimated_payments", 0) > 0:
        elements.append(data_row("24", "Estimated Tax Payments (Quarterly)", data["estimated_payments"]))
    elements.append(data_row("25", "Total Payments", r["total_payments"]))
    elements.append(Spacer(1, 0.1 * inch))

    # Final result box
    result_label = "ESTIMATED REFUND" if r["is_refund"] else "BALANCE DUE TO IRS"
    result_color = colors.HexColor("#1a6e2a") if r["is_refund"] else colors.HexColor("#c0392b")
    result_table = Table(
        [[
            Paragraph(result_label, ParagraphStyle("rl", parent=styles["Normal"],
                fontSize=11, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_LEFT)),
            Paragraph(fmt(abs(r["refund_or_owed"])), ParagraphStyle("ra", parent=styles["Normal"],
                fontSize=14, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_RIGHT)),
        ]],
        colWidths=[5.3 * inch, 2.0 * inch],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), result_color),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (0, 0), 12),
            ("RIGHTPADDING", (-1, 0), (-1, 0), 12),
            ("ROUNDEDCORNERS", [4]),
        ])
    )
    elements.append(result_table)
    elements.append(Spacer(1, 0.25 * inch))

    # ── Disclaimer ────────────────────────────────────────────────────────────
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccc")))
    elements.append(Spacer(1, 0.06 * inch))
    elements.append(Paragraph(
        "⚠ IMPORTANT DISCLAIMER: This is a <b>mock, estimated tax return</b> generated by an AI tool for "
        "informational and educational purposes only. It does <b>not</b> constitute an official IRS filing. "
        "Tax calculations are simplified and may not reflect your actual tax liability. "
        "Always consult a licensed tax professional or use IRS-approved software for your official return. "
        "Do <b>not</b> submit this document to the IRS.",
        ParagraphStyle("disc", parent=styles["Normal"], fontSize=6.5, textColor=colors.HexColor("#888"),
            alignment=TA_CENTER, leading=10)
    ))



def get_pdf_response(data: dict, inline: bool = False):
    """
    Returns (pdf_bytes, content_disposition) tuple.
    inline=True  → browser renders/previews the PDF  (View button)
    inline=False → browser downloads the PDF          (Download button)
    """
    pdf_bytes = generate_1040_pdf(data)
    disposition = (
        'inline; filename="Form1040_FY2025_Estimated.pdf"'
        if inline else
        'attachment; filename="Form1040_FY2025_Estimated.pdf"'
    )
    return pdf_bytes, disposition