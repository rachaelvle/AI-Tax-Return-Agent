"""
tax_engine.py – 2025 Federal Tax Calculation Logic
Implements progressive tax brackets, standard/itemized deductions,
above-the-line adjustments, and simplified credit estimates.
"""

# ── 2025 Standard Deductions ─────────────────────────────────────────────────
STANDARD_DEDUCTIONS = {
    "single": 15_000,
    "mfj":    30_000,
    "mfs":    15_000,
    "hoh":    22_500,
    "qss":    30_000,
}

STATUS_LABELS = {
    "single": "Single",
    "mfj":    "Married Filing Jointly",
    "mfs":    "Married Filing Separately",
    "hoh":    "Head of Household",
    "qss":    "Qualifying Surviving Spouse",
}

# ── 2025 Federal Tax Brackets (taxable income upper bound, marginal rate) ────
# Source: IRS Rev. Proc. 2024-40 inflation adjustments
TAX_BRACKETS = {
    "single": [
        (11_925,  0.10),
        (48_475,  0.12),
        (103_350, 0.22),
        (197_300, 0.24),
        (250_525, 0.32),
        (626_350, 0.35),
        (float("inf"), 0.37),
    ],
    "mfj": [
        (23_850,  0.10),
        (96_950,  0.12),
        (206_700, 0.22),
        (394_600, 0.24),
        (501_050, 0.32),
        (751_600, 0.35),
        (float("inf"), 0.37),
    ],
    "mfs": [
        (11_925,  0.10),
        (48_475,  0.12),
        (103_350, 0.22),
        (197_300, 0.24),
        (250_525, 0.32),
        (375_800, 0.35),
        (float("inf"), 0.37),
    ],
    "hoh": [
        (17_000,  0.10),
        (64_850,  0.12),
        (103_350, 0.22),
        (197_300, 0.24),
        (250_500, 0.32),
        (626_350, 0.35),
        (float("inf"), 0.37),
    ],
    "qss": [
        (23_850,  0.10),
        (96_950,  0.12),
        (206_700, 0.22),
        (394_600, 0.24),
        (501_050, 0.32),
        (751_600, 0.35),
        (float("inf"), 0.37),
    ],
}

# ── Simplified credit amounts (2025 estimates) ────────────────────────────────
CREDIT_AMOUNTS = {
    "childtax":  2_000,   # per dependent (applied below)
    "childcare":   600,   # simplified flat estimate
    "eitc":      3_995,   # max for 2 children (simplified)
    "education": 2_500,   # American Opportunity Credit max
    "savers":    1_000,   # Saver's Credit (simplified)
    "ev":        7_500,   # Clean Vehicle Credit
}

# ── Self-employment tax rate ─────────────────────────────────────────────────
SE_TAX_RATE = 0.1413   # 15.3% × 0.9235 net earnings factor = effective rate on gross SE income


def _calc_bracket_tax(taxable_income: float, status: str) -> float:
    """Apply progressive 2025 brackets and return gross tax amount."""
    brackets = TAX_BRACKETS.get(status, TAX_BRACKETS["single"])
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in brackets:
        if taxable_income <= prev_limit:
            break
        taxable_in_bracket = min(taxable_income, limit) - prev_limit
        tax += taxable_in_bracket * rate
        prev_limit = limit
    return round(tax, 2)

# effective tax rate is total tax divided by taxable income, expressed as a percentage
def _effective_rate(tax: float, taxable_income: float) -> float:
    if taxable_income <= 0:
        return 0.0
    return round((tax / taxable_income) * 100, 2) 

# For marginal rate, we find the bracket that the last dollar falls into and return that rate
def _marginal_rate(taxable_income: float, status: str) -> float:
    brackets = TAX_BRACKETS.get(status, TAX_BRACKETS["single"])
    prev = 0.0
    for limit, rate in brackets:
        if taxable_income <= limit:
            return rate * 100
        prev = limit
    return brackets[-1][1] * 100 # should never reach here due to float("inf") but just in case


def calculate_tax(
    filing_status: str,
    income: dict,
    withheld: float,
    deduction_method: str,
    itemized: dict,
    adjustments: dict,
    credits_selected: list,
    dependents: int,
    estimated_payments: float,
) -> dict:
    """
    Full federal tax calculation for FY 2025.

    Returns a dict with all intermediate values and the final
    refund/balance-due amount.
    """

    # ── 1. Gross Income ──────────────────────────────────────────────────────
    gross_income = round(sum(income.values()), 2)

    # ── 2. Self-employment tax (half is above-the-line deductible) ───────────
    se_income = income.get("selfEmploy", 0.0)
    se_tax = round(se_income * SE_TAX_RATE, 2) if se_income > 0 else 0.0
    se_deduction = round(se_tax / 2, 2)           # deductible half

    # ── 3. Above-the-line adjustments (AGI reductions) ───────────────────────
    adj_total = round(
        adjustments.get("studentLoan", 0)
        + adjustments.get("ira", 0)
        + adjustments.get("hsa", 0)
        + se_deduction,
        2,
    )
    agi = round(max(0.0, gross_income - adj_total), 2)

    # ── 4. Deduction ─────────────────────────────────────────────────────────
    std_deduction = STANDARD_DEDUCTIONS.get(filing_status, 15_000)

    if deduction_method == "itemized":
        itemized_total = round(sum(itemized.values()), 2)
        # Always use whichever is higher
        deduction_used = max(itemized_total, std_deduction)
        deduction_label = (
            "Itemized" if itemized_total >= std_deduction else "Standard (itemized didn't exceed standard)"
        )
    else:
        deduction_used = std_deduction
        deduction_label = "Standard"

    # ── 5. Taxable Income ────────────────────────────────────────────────────
    taxable_income = round(max(0.0, agi - deduction_used), 2)

    # ── 6. Income Tax ────────────────────────────────────────────────────────
    income_tax = _calc_bracket_tax(taxable_income, filing_status)
    effective_rate = _effective_rate(income_tax, taxable_income)
    marginal_rate = _marginal_rate(taxable_income, filing_status)

    # ── 7. Credits ───────────────────────────────────────────────────────────
    total_credits = 0.0
    credit_detail = {}
    for credit in credits_selected:
        if credit == "childtax":
            amount = CREDIT_AMOUNTS["childtax"] * dependents
        else:
            amount = CREDIT_AMOUNTS.get(credit, 0)
        credit_detail[credit] = amount
        total_credits += amount

    # Credits can't reduce below zero (non-refundable simplified)
    total_credits = round(min(total_credits, income_tax), 2)

    # ── 8. Total Tax After Credits ───────────────────────────────────────────
    tax_after_credits = round(max(0.0, income_tax - total_credits), 2)

    # Add self-employment tax back (not offset by credits in simplified model)
    total_tax_liability = round(tax_after_credits + se_tax, 2)

    # ── 9. Payments ──────────────────────────────────────────────────────────
    total_payments = round(withheld + estimated_payments, 2)

    # ── 10. Refund / Balance Due ─────────────────────────────────────────────
    refund_or_owed = round(total_payments - total_tax_liability, 2)

    return {
        # Income summary
        "gross_income":       gross_income,
        "se_tax":             se_tax,
        "se_deduction":       se_deduction,
        "adj_total":          adj_total,
        "agi":                agi,
        # Deductions
        "std_deduction":      std_deduction,
        "itemized_total":     round(sum(itemized.values()), 2) if deduction_method == "itemized" else 0,
        "deduction_used":     deduction_used,
        "deduction_label":    deduction_label,
        # Tax
        "taxable_income":     taxable_income,
        "income_tax":         income_tax,
        "effective_rate":     effective_rate,
        "marginal_rate":      marginal_rate,
        # Credits
        "credit_detail":      credit_detail,
        "total_credits":      total_credits,
        # Final
        "total_tax_liability": total_tax_liability,
        "total_payments":     total_payments,
        "refund_or_owed":     refund_or_owed,
        "is_refund":          refund_or_owed >= 0,
        # Labels
        "status_label":       STATUS_LABELS.get(filing_status, filing_status),
        "dependents":         dependents,
    }
