# AI Tax Return Agent — FY 2025

A Flask-powered prototype of an AI agent that automates federal tax return preparation: collecting user input, running progressive tax calculations, and generating a mock Form 1040 PDF.

## Project Structure

```
AI-Tax-Return-Agent/
├── app.py                    ← Flask routes, form handling, input sanitization
├── requirements.txt          ← Dependencies (Flask, ReportLab)
├── templates/
│   ├── index.html            ← Multi-step intake form (5 steps)
│   └── results.html          ← Tax breakdown results page
├── static/
│   ├── css/style.css         ← Full responsive stylesheet
│   └── js/validation.js      ← Client-side form validation
└── utils/
    ├── tax_engine.py         ← 2025 federal tax calculation engine
    └── pdf_generator.py      ← Mock Form 1040 PDF builder (ReportLab)
|
├── tests/
│   ├── index.html            ← test cases and math to show correctness
└── 
```

## Setup & Run

```bash
# 1. Create a virtual environment (optional but recommended)
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the development server
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## System Architecture

```
Browser (HTML/CSS/JS)
    │
    │  GET /           → Welcome + 5-step form
    │  POST /submit    → Form data
    ▼
Flask (app.py)
    │
    ├─ Input sanitization (safe_float, safe_str, allowlist checks)
    │
    ├─ Tax Engine (utils/tax_engine.py)
    │     Gross income → AGI → Taxable income → Brackets → Credits → Liability
    │
    ├─ Session storage (Flask session, no database)
    │
    └─ Jinja2 templates (results.html) + PDF (utils/pdf_generator.py)
              │
              ▼
    GET /results      → Rendered results page
    GET /download-pdf → PDF file download
    GET /view-pdf     → PDF inline browser view
```

---

## Data Flow

1. **User fills 5-step form** in the browser (filing status → income → deductions → credits → review)
2. **Client-side validation** (`validation.js`) checks each step before advancing
3. **"Submit Return"** POSTs all field values as a hidden HTML form to `POST /submit`
4. **Server sanitizes** every input: floats are clamped `[0, $100M]`, strings are allowlist-validated, HTML is escaped
5. **`calculate_tax()`** runs the full calculation pipeline and returns an intermediate-value dict
6. **Result stored** in the Flask session (encrypted cookie; no database)
7. **Browser redirected** to `GET /results` — Jinja2 renders the breakdown using session data
8. **PDF available** at `/download-pdf` (attachment) or `/view-pdf` (inline preview)

---

## Tax Calculation Logic (`utils/tax_engine.py`)

| Step | Description |
|---|---|
| 1 | Sum all income sources → **Gross Income** |
| 2 | Calculate self-employment tax (15.3%), half is deductible |
| 3 | Apply above-the-line adjustments (student loan, IRA/401k, HSA, SE deduction) → **AGI** |
| 4 | Compare standard vs. itemized deduction; apply whichever is larger |
| 5 | `Gross Income − Adjustments − Deduction` = **Taxable Income** |
| 6 | Apply 2025 progressive brackets (7 rates: 10%–37%) → **Income Tax** |
| 7 | Apply non-refundable credits (Child Tax, EITC, Education, etc.) |
| 8 | Add SE tax back → **Total Tax Liability** |
| 9 | `Total Payments − Total Liability` = **Refund** (positive) or **Balance Due** (negative) |

**2025 standard deductions:** Single $15,000 · MFJ $30,000 · HoH $22,500 · MFS $15,000 · QSS $30,000

**2025 tax brackets** (single): 10% → $11,925 · 12% → $48,475 · 22% → $103,350 · 24% → $197,300 · 32% → $250,525 · 35% → $626,350 · 37%+

## Security

| Measure | Implementation |
|---|---|
| Input sanitization | `safe_float()` clamps to `[0, 100_000_000]`; `safe_str()` HTML-escapes all strings |
| Allowlist validation | Filing status, deduction method, and credit types checked against fixed sets |
| Server-side enforcement | All caps (SALT $10k, IRA $23.5k, etc.) applied server-side regardless of client input |
| Session storage | No database; data lives in an encrypted Flask session cookie for one browser session |
| Client-side validation | `validation.js` prevents most invalid submissions before they reach the server |

**Production hardening needed before any real deployment:**
- Replace `app.secret_key` with a cryptographically random value stored in an environment variable
- Enable HTTPS (TLS termination at reverse proxy)
- Add CSRF token protection
- Implement rate limiting on `POST /submit`

## Compliance Considerations (Production)

A real-world tax filing system would require:

- **IRS e-filing authorization** — Software must be accepted by the IRS Modernized e-File (MeF) system
- **Data encryption at rest and in transit** — All PII (SSN, income, address) must be encrypted
- **GDPR / CCPA** — If serving EU/California residents: explicit consent, data deletion rights, privacy policy
- **SOC 2 / IRS Publication 4557** — Security standards for handling taxpayer data
- **Audit logging** — Immutable logs of all data access and modifications
- **PII minimization** — This prototype stores no PII; production must handle SSNs, addresses, bank info securely

This prototype intentionally omits all of the above and is scoped to educational demonstration only.

## User Flow

```
Welcome screen
    ↓  "Begin My Return"
Step 1 — Filing Status
    ↓  Continue →
Step 2 — Income Sources (W-2, self-employment, capital gains, rental, etc.)
    ↓  Continue →
Step 3 — Deductions (standard or itemized) + above-the-line adjustments
    ↓  Continue →
Step 4 — Credits & Dependents + estimated payments
    ↓  Continue →
Step 5 — Summary & Review
    ↓  Submit Return ↗  (POST /submit)
Results Page — Full breakdown: income → AGI → taxable income → tax → credits → refund/due
    ├─  Download Form 1040 PDF
    ├─  View PDF inline
    └─  Start New Return
```

# Challenges 
- There was a bug in how self employment tax was calculated and how the child tax credit applied. 
