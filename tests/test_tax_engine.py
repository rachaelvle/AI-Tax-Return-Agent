"""
tests/test_tax_engine.py
Unit tests for utils/tax_engine.py — FY 2025 federal tax calculation.

Run with:  python -m unittest discover -s tests -v

All expected values below are hand-verified against the 2025 IRS tax brackets
(Rev. Proc. 2024-40) and SE-tax rules. See inline comments for the math.
"""

import sys
import os
import unittest

# Allow import from project root without installing as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.tax_engine import calculate_tax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_income(**kwargs):
    """Return a zeroed-out income dict with any field overridden."""
    fields = ["wages", "selfEmploy", "capitalGains", "rental",
              "dividend", "unemployment", "otherIncome"]
    base = {f: 0.0 for f in fields}
    base.update(kwargs)
    return base


def _base_itemized(**kwargs):
    fields = ["mortgage", "salt", "charity", "medical", "otherDeductions"]
    base = {f: 0.0 for f in fields}
    base.update(kwargs)
    return base


def _base_adjustments(**kwargs):
    fields = ["studentLoan", "ira", "hsa"]
    base = {f: 0.0 for f in fields}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# TC1 — Simple single filer, W-2 wages only, standard deduction, no credits
# ---------------------------------------------------------------------------
class TC1_SingleWagesOnly(unittest.TestCase):
    """
    Input:  wages=$50,000  |  standard  |  withheld=$6,000  |  no credits
    Math:
        taxable = $50,000 − $15,000 (std) = $35,000
        income_tax:
            $11,925 × 10%  = $1,192.50
            $23,075 × 12%  = $2,769.00   ← $35,000 − $11,925
            total          = $3,961.50
        refund = $6,000 − $3,961.50 = $2,038.50
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="single",
            income=_base_income(wages=50_000),
            withheld=6_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(),
            credits_selected=[],
            dependents=0,
            estimated_payments=0,
        )

    def test_gross_income(self):
        self.assertEqual(self.r["gross_income"], 50_000.00)

    def test_se_tax_zero(self):
        self.assertEqual(self.r["se_tax"], 0.00)

    def test_agi(self):
        self.assertEqual(self.r["agi"], 50_000.00)

    def test_std_deduction(self):
        self.assertEqual(self.r["deduction_used"], 15_000.00)

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 35_000.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 3_961.50)

    def test_marginal_rate(self):
        self.assertEqual(self.r["marginal_rate"], 12.0)   # last dollar falls in 12% bracket

    def test_effective_rate(self):
        # 3961.50 / 35000 * 100 = 11.32%
        self.assertEqual(self.r["effective_rate"], 11.32)

    def test_no_credits(self):
        self.assertEqual(self.r["total_credits"], 0.00)

    def test_total_tax_liability(self):
        self.assertEqual(self.r["total_tax_liability"], 3_961.50)

    def test_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 2_038.50)


# ---------------------------------------------------------------------------
# TC2 — MFJ, wages + capital gains, standard deduction, 2 kids, child tax credit
# ---------------------------------------------------------------------------
class TC2_MFJWithChildCredit(unittest.TestCase):
    """
    Input:  wages=$120,000  capitalGains=$20,000  |  standard  |  withheld=$22,000
            credits=[childtax]  dependents=2
    Math:
        gross = $140,000   AGI = $140,000
        taxable = $140,000 − $30,000 = $110,000
        income_tax (MFJ brackets):
            $23,850 × 10%  = $2,385.00
            $73,100 × 12%  = $8,772.00   ← $96,950 − $23,850
            $13,050 × 22%  = $2,871.00   ← $110,000 − $96,950
            total          = $14,028.00
        child tax credit = 2 × $2,000 = $4,000  (< $14,028, uncapped)
        tax after credits = $10,028.00
        refund = $22,000 − $10,028 = $11,972.00
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="mfj",
            income=_base_income(wages=120_000, capitalGains=20_000),
            withheld=22_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(),
            credits_selected=["childtax"],
            dependents=2,
            estimated_payments=0,
        )

    def test_gross_income(self):
        self.assertEqual(self.r["gross_income"], 140_000.00)

    def test_agi(self):
        self.assertEqual(self.r["agi"], 140_000.00)

    def test_std_deduction_mfj(self):
        self.assertEqual(self.r["deduction_used"], 30_000.00)

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 110_000.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 14_028.00)

    def test_marginal_rate(self):
        self.assertEqual(self.r["marginal_rate"], 22.0)

    def test_child_tax_credit(self):
        self.assertEqual(self.r["credit_detail"]["childtax"], 4_000.00)
        self.assertEqual(self.r["total_credits"], 4_000.00)

    def test_total_tax(self):
        self.assertEqual(self.r["total_tax_liability"], 10_028.00)

    def test_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 11_972.00)


# ---------------------------------------------------------------------------
# TC3 — Self-employed single filer, itemized deductions, above-the-line adjustments
# ---------------------------------------------------------------------------
class TC3_SelfEmployedItemized(unittest.TestCase):
    """
    Input:  selfEmploy=$100,000  |  itemized (mortgage=$15k, SALT=$10k, charity=$5k)
            studentLoan=$2,500  ira=$7,000  |  no credits  |  withheld=$0
    Math:
        se_tax        = $100,000 × 0.1413             = $14,130.00
        se_deduction  = $14,130 / 2                   = $7,065.00
        adj_total     = $2,500 + $7,000 + $7,065      = $16,565.00
        AGI           = $100,000 − $16,565            = $83,435.00
        itemized_tot  = $15,000 + $10,000 + $5,000    = $30,000   (> std $15,000)
        taxable       = $83,435 − $30,000             = $53,435.00
        income_tax (single):
            $11,925 × 10%  = $1,192.50
            $36,550 × 12%  = $4,386.00   ← $48,475 − $11,925
             $4,960 × 22%  = $1,091.20   ← $53,435 − $48,475
            total          = $6,669.70
        total_tax = $6,669.70 + $14,130 = $20,799.70
        balance_due = $0 − $20,799.70 = −$20,799.70
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="single",
            income=_base_income(selfEmploy=100_000),
            withheld=0,
            deduction_method="itemized",
            # Note: app.py caps SALT at $10,000 before calling calculate_tax;
            # we mirror that here.
            itemized=_base_itemized(mortgage=15_000, salt=10_000, charity=5_000),
            adjustments=_base_adjustments(studentLoan=2_500, ira=7_000),
            credits_selected=[],
            dependents=0,
            estimated_payments=0,
        )

    def test_se_tax(self):
        self.assertEqual(self.r["se_tax"], 14_130.00)

    def test_se_deduction(self):
        self.assertEqual(self.r["se_deduction"], 7_065.00)

    def test_adj_total(self):
        self.assertEqual(self.r["adj_total"], 16_565.00)

    def test_agi(self):
        self.assertEqual(self.r["agi"], 83_435.00)

    def test_itemized_beats_standard(self):
        self.assertEqual(self.r["deduction_used"], 30_000.00)
        self.assertIn("Itemized", self.r["deduction_label"])

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 53_435.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 6_669.70)

    def test_total_tax(self):
        self.assertEqual(self.r["total_tax_liability"], 20_799.70)

    def test_balance_due(self):
        self.assertFalse(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], -20_799.70)


# ---------------------------------------------------------------------------
# TC4 — Head of Household, 3 dependents, credits capped by income tax
# ---------------------------------------------------------------------------
class TC4_HOHCreditsCapped(unittest.TestCase):
    """
    Input:  wages=$75,000  dividend=$5,000  |  standard  |  hsa=$4,000
            credits=[childtax, ev]  dependents=3  |  withheld=$12,000
    Math:
        gross = $80,000   adj_total = $4,000 (hsa)   AGI = $76,000
        std_deduction (hoh) = $22,500
        taxable = $76,000 − $22,500 = $53,500
        income_tax (HOH brackets):
            $17,000 × 10%  = $1,700.00
            $36,500 × 12%  = $4,380.00   ← $53,500 − $17,000
            total          = $6,080.00
        credits = 3×$2,000 + $7,500 = $13,500  → capped at $6,080
        tax_after_credits = $0
        refund = $12,000 − $0 = $12,000
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="hoh",
            income=_base_income(wages=75_000, dividend=5_000),
            withheld=12_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(hsa=4_000),
            credits_selected=["childtax", "ev"],
            dependents=3,
            estimated_payments=0,
        )

    def test_agi(self):
        self.assertEqual(self.r["agi"], 76_000.00)

    def test_std_deduction_hoh(self):
        self.assertEqual(self.r["deduction_used"], 22_500.00)

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 53_500.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 6_080.00)

    def test_credits_before_cap(self):
        # Raw credits = 3×$2,000 + $7,500 = $13,500 but capped at income_tax
        self.assertEqual(self.r["credit_detail"]["childtax"], 6_000.00)
        self.assertEqual(self.r["credit_detail"]["ev"], 7_500.00)

    def test_credits_capped(self):
        self.assertEqual(self.r["total_credits"], 6_080.00)

    def test_total_tax_zero(self):
        self.assertEqual(self.r["total_tax_liability"], 0.00)

    def test_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 12_000.00)


# ---------------------------------------------------------------------------
# TC5 — High-income single filer hitting the 37% top bracket
# ---------------------------------------------------------------------------
class TC5_TopBracketSingle(unittest.TestCase):
    """
    Input:  wages=$800,000  |  standard  |  withheld=$300,000  |  no credits
    Math:
        taxable = $800,000 − $15,000 = $785,000
        income_tax (single, all 7 brackets):
            $11,925  × 10%  =    $1,192.50
            $36,550  × 12%  =    $4,386.00
            $54,875  × 22%  =   $12,072.50
            $93,950  × 24%  =   $22,548.00
            $53,225  × 32%  =   $17,032.00
           $375,825  × 35%  =  $131,538.75
           $158,650  × 37%  =   $58,700.50
            total           =  $247,470.25
        refund = $300,000 − $247,470.25 = $52,529.75
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="single",
            income=_base_income(wages=800_000),
            withheld=300_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(),
            credits_selected=[],
            dependents=0,
            estimated_payments=0,
        )

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 785_000.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 247_470.25)

    def test_marginal_rate(self):
        self.assertEqual(self.r["marginal_rate"], 37.0)

    def test_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 52_529.75)


# ---------------------------------------------------------------------------
# TC6 — Zero taxable income (large IRA contribution wipes out taxable income)
# ---------------------------------------------------------------------------
class TC6_ZeroTaxableIncome(unittest.TestCase):
    """
    Input:  wages=$20,000  |  standard  |  ira=$5,000  |  withheld=$2,000
    Math:
        adj_total = $5,000   AGI = $15,000
        std_deduction = $15,000   taxable = $0
        income_tax = $0   total_tax = $0
        refund = $2,000
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="single",
            income=_base_income(wages=20_000),
            withheld=2_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(ira=5_000),
            credits_selected=[],
            dependents=0,
            estimated_payments=0,
        )

    def test_agi(self):
        self.assertEqual(self.r["agi"], 15_000.00)

    def test_taxable_income_zero(self):
        self.assertEqual(self.r["taxable_income"], 0.00)

    def test_income_tax_zero(self):
        self.assertEqual(self.r["income_tax"], 0.00)

    def test_total_tax_zero(self):
        self.assertEqual(self.r["total_tax_liability"], 0.00)

    def test_full_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 2_000.00)


# ---------------------------------------------------------------------------
# TC7 — Married Filing Separately, EV credit capped by income tax
# ---------------------------------------------------------------------------
class TC7_MFSWithEVCredit(unittest.TestCase):
    """
    Input:  wages=$60,000  |  standard  |  credits=[ev]  |  withheld=$10,000
    Math:
        taxable = $60,000 − $15,000 = $45,000  (MFS std = $15,000)
        income_tax (MFS — same thresholds as single for lower brackets):
            $11,925 × 10%  = $1,192.50
            $33,075 × 12%  = $3,969.00   ← $45,000 − $11,925
            total          = $5,161.50
        EV credit $7,500 → capped at $5,161.50 (non-refundable)
        total_tax = $0
        refund = $10,000
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="mfs",
            income=_base_income(wages=60_000),
            withheld=10_000,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(),
            credits_selected=["ev"],
            dependents=0,
            estimated_payments=0,
        )

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 45_000.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 5_161.50)

    def test_ev_credit_capped(self):
        # Raw EV = $7,500 but income_tax is only $5,161.50
        self.assertEqual(self.r["total_credits"], 5_161.50)

    def test_total_tax_zero(self):
        self.assertEqual(self.r["total_tax_liability"], 0.00)

    def test_refund(self):
        self.assertTrue(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], 10_000.00)


# ---------------------------------------------------------------------------
# TC8 — Estimated quarterly payments reduce balance due
# ---------------------------------------------------------------------------
class TC8_EstimatedPayments(unittest.TestCase):
    """
    Input:  selfEmploy=$80,000  |  standard  |  withheld=$0  |  est_payments=$10,000
    Math:
        se_tax       = $80,000 × 0.1413 = $11,304.00
        se_deduction = $11,304 / 2      =  $5,652.00
        adj_total    = $5,652
        AGI          = $80,000 − $5,652 = $74,348
        taxable      = $74,348 − $15,000 = $59,348
        income_tax (single):
            $11,925 × 10%  =  $1,192.50
            $36,550 × 12%  =  $4,386.00
            $10,873 × 22%  =  $2,392.06   ← $59,348 − $48,475
            total          =  $7,970.56
        total_tax = $7,970.56 + $11,304 = $19,274.56
        total_payments = $0 + $10,000 = $10,000
        balance_due = $10,000 − $19,274.56 = −$9,274.56
    """

    def setUp(self):
        self.r = calculate_tax(
            filing_status="single",
            income=_base_income(selfEmploy=80_000),
            withheld=0,
            deduction_method="standard",
            itemized=_base_itemized(),
            adjustments=_base_adjustments(),
            credits_selected=[],
            dependents=0,
            estimated_payments=10_000,
        )

    def test_se_tax(self):
        self.assertEqual(self.r["se_tax"], 11_304.00)

    def test_se_deduction(self):
        self.assertEqual(self.r["se_deduction"], 5_652.00)

    def test_agi(self):
        self.assertEqual(self.r["agi"], 74_348.00)

    def test_taxable_income(self):
        self.assertEqual(self.r["taxable_income"], 59_348.00)

    def test_income_tax(self):
        self.assertEqual(self.r["income_tax"], 7_970.56)

    def test_total_tax(self):
        self.assertEqual(self.r["total_tax_liability"], 19_274.56)

    def test_total_payments(self):
        self.assertEqual(self.r["total_payments"], 10_000.00)

    def test_balance_due(self):
        self.assertFalse(self.r["is_refund"])
        self.assertEqual(self.r["refund_or_owed"], -9_274.56)


if __name__ == "__main__":
    unittest.main(verbosity=2)
