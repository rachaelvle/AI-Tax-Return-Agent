"""
app.py – AI Tax Return Agent (FY 2025)
Flask backend: handles form submission, tax calculation, result display, and PDF generation.
"""

from flask import Flask, render_template, request, redirect, url_for, session, send_file, make_response, jsonify
import io, re, html as html_lib
from utils.tax_engine import calculate_tax
from utils.pdf_generator import generate_1040_pdf, get_pdf_response

app = Flask(__name__)
app.secret_key = "tax-agent-2025-secret-key-change-in-prod"


# ── Sanitization helper ──────────────────────────────────────────────────────

def safe_float(value, default=0.0, min_val=0.0, max_val=100_000_000.0):
    """Parse a form float safely; clamp to [min_val, max_val]."""
    try:
        v = float(str(value).strip())
        if v < min_val or v > max_val:
            return default
        # Round to 2 decimal places (cents)
        return round(v, 2)
    except (ValueError, TypeError):
        return default


def safe_str(value, allowed_values=None, default=""):
    """Sanitize a string; optionally restrict to an allowlist."""
    v = html_lib.escape(str(value).strip())
    if allowed_values and v not in allowed_values:
        return default
    return v


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    """Receive the multi-step form, validate server-side, calculate tax, store in session."""

    # ── Filing status ────────────────────────────────────────────────────────
    VALID_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}
    filing_status = safe_str(request.form.get("filing", "single"), VALID_STATUSES, "single")

    # ── Income ───────────────────────────────────────────────────────────────
    income_fields = ["wages", "selfEmploy", "capitalGains", "rental",
                     "dividend", "unemployment", "otherIncome"]
    income = {f: safe_float(request.form.get(f, 0)) for f in income_fields}
    withheld = safe_float(request.form.get("withheld", 0))

    gross_income = sum(income.values())

    # Server-side guard: at least one income source
    if gross_income <= 0:
        return redirect(url_for("index") + "?error=income_required")

    # ── Deductions ───────────────────────────────────────────────────────────
    deduction_method = safe_str(
        request.form.get("deductionMethod", "standard"),
        {"standard", "itemized"},
        "standard"
    )
    itemized = {
        "mortgage":       safe_float(request.form.get("mortgage", 0)),
        "salt":           min(safe_float(request.form.get("salt", 0)), 10_000),  # SALT cap
        "charity":        safe_float(request.form.get("charity", 0)),
        "medical":        safe_float(request.form.get("medical", 0)),
        "otherDeductions": safe_float(request.form.get("otherDeductions", 0)),
    }
    adjustments = {
        "studentLoan": min(safe_float(request.form.get("studentLoan", 0)), 2_500),
        "ira":         min(safe_float(request.form.get("ira", 0)), 23_500),
        "hsa":         min(safe_float(request.form.get("hsa", 0)), 8_550),
    }

    # ── Credits & Dependents ─────────────────────────────────────────────────
    VALID_CREDITS = {"childtax", "childcare", "eitc", "education", "savers", "ev"}
    raw_credits = request.form.getlist("credits")
    credits_selected = [c for c in raw_credits if c in VALID_CREDITS]

    dependents_raw = request.form.get("dependents", "0")
    try:
        dependents = max(0, min(int(dependents_raw), 5))
    except ValueError:
        dependents = 0

    # Remove dependent-required credits if no dependents
    if dependents == 0:
        credits_selected = [c for c in credits_selected if c not in ("childtax", "childcare")]

    estimated_payments = safe_float(request.form.get("estimatedPayments", 0))

    # ── Run tax engine ───────────────────────────────────────────────────────
    result = calculate_tax(
        filing_status=filing_status,
        income=income,
        withheld=withheld,
        deduction_method=deduction_method,
        itemized=itemized,
        adjustments=adjustments,
        credits_selected=credits_selected,
        dependents=dependents,
        estimated_payments=estimated_payments,
    )

    # Store everything in session for results page and PDF
    session["tax_data"] = {
        "filing_status": filing_status,
        "income": income,
        "withheld": withheld,
        "deduction_method": deduction_method,
        "itemized": itemized,
        "adjustments": adjustments,
        "credits_selected": credits_selected,
        "dependents": dependents,
        "estimated_payments": estimated_payments,
        "result": result,
    }

    return redirect(url_for("results"))


@app.route("/results")
def results():
    data = session.get("tax_data")
    if not data:
        return redirect(url_for("index"))
    return render_template("results.html", d=data, r=data["result"])

@app.route("/download-pdf")
def download_pdf():
    pdf_bytes, disposition = get_pdf_response(session["tax_data"], inline=False)
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = disposition
    return resp

@app.route("/view-pdf")
def view_pdf():
    pdf_bytes, disposition = get_pdf_response(session["tax_data"], inline=True)
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = disposition
    return resp


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """Return tax calculation as JSON for the frontend summary preview."""
    data = request.get_json(force=True) or {}

    VALID_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}
    filing_status = safe_str(data.get("filing", "single"), VALID_STATUSES, "single")

    income_fields = ["wages", "selfEmploy", "capitalGains", "rental",
                     "dividend", "unemployment", "otherIncome"]
    income = {f: safe_float(data.get(f, 0)) for f in income_fields}
    withheld = safe_float(data.get("withheld", 0))

    deduction_method = safe_str(
        data.get("deductionMethod", "standard"),
        {"standard", "itemized"},
        "standard"
    )
    itemized = {
        "mortgage":        safe_float(data.get("mortgage", 0)),
        "salt":            min(safe_float(data.get("salt", 0)), 10_000),
        "charity":         safe_float(data.get("charity", 0)),
        "medical":         safe_float(data.get("medical", 0)),
        "otherDeductions": safe_float(data.get("otherDeductions", 0)),
    }
    adjustments = {
        "studentLoan": min(safe_float(data.get("studentLoan", 0)), 2_500),
        "ira":         min(safe_float(data.get("ira", 0)), 23_500),
        "hsa":         min(safe_float(data.get("hsa", 0)), 8_550),
    }

    VALID_CREDITS = {"childtax", "childcare", "eitc", "education", "savers", "ev"}
    raw_credits = data.get("credits", [])
    if isinstance(raw_credits, str):
        raw_credits = [raw_credits]
    credits_selected = [c for c in raw_credits if c in VALID_CREDITS]

    try:
        dependents = max(0, min(int(data.get("dependents", 0)), 5))
    except (ValueError, TypeError):
        dependents = 0

    if dependents == 0:
        credits_selected = [c for c in credits_selected if c not in ("childtax", "childcare")]

    estimated_payments = safe_float(data.get("estimatedPayments", 0))

    result = calculate_tax(
        filing_status=filing_status,
        income=income,
        withheld=withheld,
        deduction_method=deduction_method,
        itemized=itemized,
        adjustments=adjustments,
        credits_selected=credits_selected,
        dependents=dependents,
        estimated_payments=estimated_payments,
    )
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True)
