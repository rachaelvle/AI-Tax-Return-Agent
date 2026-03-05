/**
 * validation.js
 * Form validation for AI Tax Return Agent (FY 2025)
 *
 * Usage: Call validateStep(stepIndex) before advancing to the next step.
 *        Returns true if valid, false if errors were found.
 *
 */

// ─── Utility helpers ────────────────────────────────────────────────────────

/**
 * Remove all existing error messages and highlights from a step.
 * @param {number} stepIndex
 */
function clearErrors(stepIndex) {
  const step = document.getElementById('step' + stepIndex);
  if (!step) return;
  step.querySelectorAll('.validation-error').forEach(el => el.remove());
  step.querySelectorAll('.field-error').forEach(el => el.classList.remove('field-error'));
}

/**
 * Attach an inline error message beneath a field element.
 * @param {HTMLElement} fieldEl  – the .field wrapper (or any container)
 * @param {string}      message  – human-readable error text
 */
function showError(fieldEl, message) {
  // Avoid duplicate messages on the same field
  if (fieldEl.querySelector('.validation-error')) return;

  fieldEl.classList.add('field-error');

  const err = document.createElement('span');
  err.className = 'validation-error';
  err.setAttribute('role', 'alert');
  err.textContent = '⚠ ' + message;
  err.style.cssText = [
    'display:block',
    'color:#e05252',
    'font-size:0.78rem',
    'margin-top:0.35rem',
    'font-family:var(--mono, monospace)',
    'letter-spacing:0.01em',
  ].join(';');

  fieldEl.appendChild(err);
}

/**
 * Get the numeric value of an input by id, or 0 if blank/invalid.
 * @param {string} id
 * @returns {number}
 */
function numVal(id) {
  const el = document.getElementById(id);
  if (!el) return 0;
  const v = parseFloat(el.value);
  return isNaN(v) ? 0 : v;
}

/**
 * Return the closest ancestor that matches a CSS selector, or the element itself.
 * Falls back to the element's parentElement when no match is found.
 * @param {HTMLElement} el
 * @param {string}      selector
 * @returns {HTMLElement}
 */
function closest(el, selector) {
  return el.closest ? el.closest(selector) || el.parentElement : el.parentElement;
}

/**
 * Check if a number string has more than 2 decimal places.
 * @param {string} value - The input value
 * @returns {boolean} - true if value has more than 2 decimal places
 */
function hasTooManyDecimals(value) {
  if (!value || value.trim() === '') return false;
  const decimalMatch = value.match(/\.(\d+)$/);
  if (!decimalMatch) return false;
  return decimalMatch[1].length > 2;
}

// ─── Per-step validators ────────────────────────────────────────────────────

/**
 * Step 0 – Filing Status
 * Rule: one radio must be selected (always true given the default, but validated defensively).
 */
function validateStep0() {
  const selected = document.querySelector('input[name="filing"]:checked');
  if (!selected) {
    const grid = document.getElementById('filingStatus');
    showError(grid, 'Please select a filing status to continue.');
    return false;
  }
  return true;
}

/**
 * Step 1 – Income Sources
 * Rules:
 *   • At least one income field must contain a value greater than 0.
 *   • Every filled income field must be ≥ 0 (no negative amounts).
 *   • Federal Tax Withheld may be $0 but cannot be negative.
 *   • Federal Tax Withheld cannot exceed total gross income (sanity check).
 */
function validateStep1() {
  const incomeIds = ['wages', 'selfEmploy', 'capitalGains', 'rental', 'dividend', 'unemployment', 'otherIncome'];
  let valid = true;
  let totalIncome = 0;

  // Check each income field for negative values or if it has too many decimals
  incomeIds.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const v = parseFloat(el.value);
    if (hasTooManyDecimals(el.value)) {
      showError(closest(el, '.field'), 'Amount cannot have more than 2 decimal places (cents).');
      valid = false;
    } else if (el.value.trim() !== '' && (isNaN(v) || v < 0)) {
      showError(closest(el, '.field'), 'Amount cannot be negative.');
      valid = false;
    } else if (!isNaN(v) && v > 0) {
      totalIncome += v;
    }
  });

  // At least one income source required
  if (valid && totalIncome === 0) {
    const firstField = document.getElementById('step1').querySelector('.field');
    showError(firstField, 'Please enter income for at least one source.');
    valid = false;
  }

  // Withheld tax validation
  const withheldEl = document.getElementById('withheld');
  if (withheldEl) {
    const withheld = parseFloat(withheldEl.value);
    if (hasTooManyDecimals(withheldEl.value)) {
      showError(closest(withheldEl, '.field'), 'Amount cannot have more than 2 decimal places (cents).');
      valid = false;
    } else if (withheldEl.value.trim() !== '' && (isNaN(withheld) || withheld < 0)) {
      showError(closest(withheldEl, '.field'), 'Federal tax withheld cannot be negative.');
      valid = false;
    } else if (!isNaN(withheld) && withheld > totalIncome && totalIncome > 0) {
      showError(
        closest(withheldEl, '.field'),
        'Withheld amount ($' + withheld.toLocaleString() + ') exceeds your total gross income. Please double-check.'
      );
      valid = false;
    }
  }

  // Cap on unrealistic single income entries (>$100M triggers a warning, not a block)
  incomeIds.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const v = parseFloat(el.value);
    if (!isNaN(v) && v > 100_000_000) {
      showError(closest(el, '.field'), 'This figure looks unusually high. Please verify the amount.');
      // Warn only — do not set valid = false
    }
  });

  return valid;
}

/**
 * Step 2 – Deductions
 * Rules:
 *   • Deduction method must be selected (always valid given <select> default).
 *   • If itemized: all visible deduction fields must be ≥ 0.
 *   • SALT cap: cannot exceed $10,000 (2025 federal cap).
 *   • Above-the-line adjustments must be ≥ 0.
 *   • IRA contribution cap: $7,000 (or $8,000 if 50+; we use $8,000 as a safe upper bound).
 *   • Student loan interest deduction cap: $2,500.
 *   • HSA cap: $4,300 (self-only) / $8,550 (family) – we warn above $8,550.
 */
function validateStep2() {
  let valid = true;
  const method = document.getElementById('deductionMethod')?.value;

  if (method === 'itemized') {
    const itemizedIds = ['mortgage', 'salt', 'charity', 'medical', 'otherDeductions'];

    itemizedIds.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const v = parseFloat(el.value);
      if (hasTooManyDecimals(el.value)) {
        showError(closest(el, '.field'), 'Amount cannot have more than 2 decimal places (cents).');
        valid = false;
      } else if (el.value.trim() !== '' && (isNaN(v) || v < 0)) {
        showError(closest(el, '.field'), 'Amount cannot be negative.');
        valid = false;
      }
    });

    // SALT cap warning/error
    const saltEl = document.getElementById('salt');
    if (saltEl) {
      const salt = parseFloat(saltEl.value);
      if (!isNaN(salt) && salt > 10_000) {
        showError(
          closest(saltEl, '.field'),
          'The federal SALT deduction is capped at $10,000. Only $10,000 will be applied.'
        );
        // Informational — do not block
      }
    }

    // Mortgage interest sanity
    const mortgageEl = document.getElementById('mortgage');
    if (mortgageEl) {
      const mortgage = parseFloat(mortgageEl.value);
      if (!isNaN(mortgage) && mortgage > 750_000) {
        showError(
          closest(mortgageEl, '.field'),
          'Mortgage interest deduction is limited to loans up to $750,000. Please verify.'
        );
      }
    }
  }

  // Above-the-line adjustments
  const adjustmentIds = ['studentLoan', 'ira', 'hsa'];
  adjustmentIds.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const v = parseFloat(el.value);
    if (hasTooManyDecimals(el.value)) {
      showError(closest(el, '.field'), 'Amount cannot have more than 2 decimal places (cents).');
      valid = false;
    } else if (el.value.trim() !== '' && (isNaN(v) || v < 0)) {
      showError(closest(el, '.field'), 'Amount cannot be negative.');
      valid = false;
    }
  });

  // Student loan interest cap
  const sliEl = document.getElementById('studentLoan');
  if (sliEl) {
    const sli = parseFloat(sliEl.value);
    if (!isNaN(sli) && sli > 2_500) {
      showError(
        closest(sliEl, '.field'),
        'The student loan interest deduction is capped at $2,500. Only $2,500 will be applied.'
      );
    }
  }

  // IRA/401(k) cap
  const iraEl = document.getElementById('ira');
  if (iraEl) {
    const ira = parseFloat(iraEl.value);
    if (!isNaN(ira) && ira > 23_500) {
      showError(
        closest(iraEl, '.field'),
        '401(k) employee contribution limit for 2025 is $23,500 ($31,000 if age 50+). Please verify.'
      );
    }
  }

  // HSA cap
  const hsaEl = document.getElementById('hsa');
  if (hsaEl) {
    const hsa = parseFloat(hsaEl.value);
    if (!isNaN(hsa) && hsa > 8_550) {
      showError(
        closest(hsaEl, '.field'),
        'HSA contribution limit for 2025 is $4,300 (self-only) or $8,550 (family). Please verify.'
      );
    }
  }

  return valid;
}

/**
 * Step 3 – Credits & Dependents
 * Rules:
 *   • Dependents select must have a valid value (0–5); always satisfied by <select>.
 *   • Child Tax Credit / Child & Dependent Care require ≥ 1 dependent.
 *   • Estimated tax payments field must be ≥ 0.
 *   • EITC is generally unavailable for investment income > $11,600 (2025 limit) — warn only.
 */
function validateStep3() {
  let valid = true;

  const dependentsEl = document.getElementById('dependents');
  const dependents = dependentsEl ? parseInt(dependentsEl.value, 10) : 0;

  // Credits that require dependents
  const dependentCredits = {
    childtax: 'Child Tax Credit',
    childcare: 'Child & Dependent Care Credit',
  };

  Object.entries(dependentCredits).forEach(([value, label]) => {
    const checkbox = document.querySelector(`#creditsGrid input[value="${value}"]`);
    if (checkbox && checkbox.checked && dependents === 0) {
      const fieldEl = closest(checkbox, '.field') || document.getElementById('creditsGrid');
      showError(fieldEl, `${label} requires at least 1 dependent. Please update your dependents or uncheck this credit.`);
      valid = false;
    }
  });

  // EITC + investment income warning
  const eitcCheckbox = document.querySelector('#creditsGrid input[value="eitc"]');
  if (eitcCheckbox && eitcCheckbox.checked) {
    const investmentIncome = numVal('capitalGains') + numVal('dividend') + numVal('rental');
    if (investmentIncome > 11_600) {
      const fieldEl = document.getElementById('creditsGrid');
      showError(fieldEl, 'Earned Income Credit is not available if investment/passive income exceeds $11,600 (2025 limit).');
      valid = false;
    }
  }

  // Estimated payments
  const estEl = document.getElementById('estimatedPayments');
  if (estEl) {
    const est = parseFloat(estEl.value);
    if (hasTooManyDecimals(estEl.value)) {
      showError(closest(estEl, '.field'), 'Amount cannot have more than 2 decimal places (cents).');
      valid = false;
    } else if (estEl.value.trim() !== '' && (isNaN(est) || est < 0)) {
      showError(closest(estEl, '.field'), 'Estimated payments cannot be negative.');
      valid = false;
    }
    if (!isNaN(est) && est > 1_000_000) {
      showError(closest(estEl, '.field'), 'This figure looks unusually high. Please verify the amount.');
    }
  }

  return valid;
}

// ─── Step 4 – Summary (read-only, no validation needed) ─────────────────────
function validateStep4() {
  return true;
}

// ─── Inject required CSS once ────────────────────────────────────────────────

(function injectValidationStyles() {
  if (document.getElementById('validation-styles')) return;
  const style = document.createElement('style');
  style.id = 'validation-styles';
  style.textContent = `
    .field-error input,
    .field-error select,
    .field-error textarea {
      border-color: #e05252 !important;
      box-shadow: 0 0 0 2px rgba(224, 82, 82, 0.18) !important;
    }
    .field-error .prefix-wrap {
      border-color: #e05252 !important;
      box-shadow: 0 0 0 2px rgba(224, 82, 82, 0.18) !important;
    }
    .validation-error {
      animation: validationFadeIn 0.2s ease;
    }
    @keyframes validationFadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);
})();

// ─── Public API ──────────────────────────────────────────────────────────────

/**
 * Validate all inputs on a given step.
 * Clears previous errors first, then runs the appropriate validator.
 *
 * @param  {number}  stepIndex  – 0-based step index matching the step<N> IDs
 * @returns {boolean}           – true if the step passes all validation rules
 */
function validateStep(stepIndex) {
  clearErrors(stepIndex);

  const validators = [
    validateStep0, // Step 1 – Filing Status
    validateStep1, // Step 2 – Income
    validateStep2, // Step 3 – Deductions
    validateStep3, // Step 4 – Credits & Dependents
    validateStep4, // Step 5 – Summary (no-op)
  ];

  const validator = validators[stepIndex];
  if (typeof validator !== 'function') {
    console.warn('validateStep: no validator defined for step', stepIndex);
    return true;
  }

  const result = validator();

  if (!result) {
    // Scroll the first error into view
    const firstError = document.getElementById('step' + stepIndex)?.querySelector('.validation-error');
    if (firstError) {
      firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  return result;
}

// ─── App state ───────────────────────────────────────────────────────────────

let currentStep = 0;
const totalSteps = 5;

// ─── UI helpers ──────────────────────────────────────────────────────────────

function fmt(n) {
  return '$' + (parseFloat(n) || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function val(id) { return parseFloat(document.getElementById(id)?.value) || 0; }

function toggleCheck(el) {
  el.classList.toggle('checked');
  el.querySelector('input').checked = el.classList.contains('checked');
}

function toggleItemized() {
  const method = document.getElementById('deductionMethod').value;
  const fields = document.getElementById('itemizedFields');
  fields.style.display = method === 'itemized' ? 'flex' : 'none';
}

function updateProgress() {
  for (let i = 0; i < totalSteps; i++) {
    const seg = document.getElementById('seg' + i);
    seg.classList.remove('active', 'done');
    if (i < currentStep) seg.classList.add('done');
    else if (i === currentStep) seg.classList.add('active');
  }
}

// ─── Navigation ──────────────────────────────────────────────────────────────

async function next() {
  if (!validateStep(currentStep)) return;
  if (currentStep === totalSteps - 2) await buildSummary();
  document.getElementById('step' + currentStep).classList.remove('active');
  currentStep = Math.min(currentStep + 1, totalSteps - 1);
  document.getElementById('step' + currentStep).classList.add('active');
  updateProgress();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function prev() {
  document.getElementById('step' + currentStep).classList.remove('active');
  currentStep = Math.max(currentStep - 1, 0);
  document.getElementById('step' + currentStep).classList.add('active');
  updateProgress();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ─── Summary (calls backend) ─────────────────────────────────────────────────

async function buildSummary() {
  document.getElementById('summaryContent').innerHTML =
    '<div style="padding:1rem;color:#888;font-family:var(--mono,monospace);font-size:0.85rem;">Calculating…</div>';
  document.getElementById('resultBox').innerHTML = '';

  const payload = {
    filing:            document.querySelector('input[name="filing"]:checked')?.value || 'single',
    wages:             val('wages'),
    selfEmploy:        val('selfEmploy'),
    capitalGains:      val('capitalGains'),
    rental:            val('rental'),
    dividend:          val('dividend'),
    unemployment:      val('unemployment'),
    otherIncome:       val('otherIncome'),
    withheld:          val('withheld'),
    deductionMethod:   document.getElementById('deductionMethod').value,
    mortgage:          val('mortgage'),
    salt:              val('salt'),
    charity:           val('charity'),
    medical:           val('medical'),
    otherDeductions:   val('otherDeductions'),
    studentLoan:       val('studentLoan'),
    ira:               val('ira'),
    hsa:               val('hsa'),
    credits:           [...document.querySelectorAll('#creditsGrid input:checked')].map(c => c.value),
    dependents:        parseInt(document.getElementById('dependents').value || '0'),
    estimatedPayments: val('estimatedPayments'),
  };

  const resp = await fetch('/api/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const r = await resp.json();

  const html = `
    <div class="summary-section">
      <h3>Filing Info</h3>
      <div class="summary-row"><span class="lbl">Filing Status</span><span class="val">${r.status_label}</span></div>
      <div class="summary-row"><span class="lbl">Dependents</span><span class="val">${r.dependents}</span></div>
    </div>
    <div class="summary-section">
      <h3>Income</h3>
      <div class="summary-row"><span class="lbl">Gross Income</span><span class="val">${fmt(r.gross_income)}</span></div>
      <div class="summary-row"><span class="lbl">Adjustments</span><span class="val">− ${fmt(r.adj_total)}</span></div>
      <div class="summary-row"><span class="lbl">Adjusted Gross Income</span><span class="val">${fmt(r.agi)}</span></div>
    </div>
    <div class="summary-section">
      <h3>Deductions & Taxable Income</h3>
      <div class="summary-row"><span class="lbl">${r.deduction_label} Deduction</span><span class="val">− ${fmt(r.deduction_used)}</span></div>
      <div class="summary-row"><span class="lbl">Taxable Income</span><span class="val">${fmt(r.taxable_income)}</span></div>
    </div>
    <div class="summary-section">
      <h3>Tax & Payments</h3>
      <div class="summary-row"><span class="lbl">Estimated Tax Owed</span><span class="val">${fmt(r.total_tax_liability)}</span></div>
      <div class="summary-row"><span class="lbl">Tax Credits Applied</span><span class="val">− ${fmt(r.total_credits)}</span></div>
      <div class="summary-row"><span class="lbl">Taxes Withheld / Paid</span><span class="val">− ${fmt(r.total_payments)}</span></div>
    </div>
    <div class="summary-total">
      <span class="lbl">${r.is_refund ? 'Estimated Refund' : 'Balance Due'}</span>
      <span class="val ${r.is_refund ? '' : 'result-negative'}">${fmt(Math.abs(r.refund_or_owed))}</span>
    </div>`;

  document.getElementById('summaryContent').innerHTML = html;

  const rbHtml = `
    <div class="result-box" style="margin-top:1.5rem">
      <div class="result-label">${r.is_refund ? 'You are owed a refund of' : 'You owe an additional'}</div>
      <div class="result-amount ${r.is_refund ? 'result-positive' : 'result-negative'}">${fmt(Math.abs(r.refund_or_owed))}</div>
      <div class="result-type">${r.is_refund ? 'Estimated federal refund' : 'Balance due to IRS'} · FY2025</div>
    </div>`;
  document.getElementById('resultBox').innerHTML = rbHtml;
}

// ─── Form submission ──────────────────────────────────────────────────────────

function submitReturn() {
  if (!validateStep(currentStep)) return;

  const form = document.createElement('form');
  form.method = 'POST';
  form.action = '/submit';

  function addField(name, value) {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }

  addField('filing', document.querySelector('input[name="filing"]:checked')?.value || 'single');

  ['wages','selfEmploy','capitalGains','rental','dividend','unemployment','otherIncome'].forEach(id => {
    addField(id, document.getElementById(id)?.value || '0');
  });
  addField('withheld', document.getElementById('withheld')?.value || '0');

  addField('deductionMethod', document.getElementById('deductionMethod')?.value || 'standard');
  ['mortgage','salt','charity','medical','otherDeductions'].forEach(id => {
    addField(id, document.getElementById(id)?.value || '0');
  });

  ['studentLoan','ira','hsa'].forEach(id => {
    addField(id, document.getElementById(id)?.value || '0');
  });

  document.querySelectorAll('#creditsGrid input:checked').forEach(cb => {
    addField('credits', cb.value);
  });

  addField('dependents', document.getElementById('dependents')?.value || '0');
  addField('estimatedPayments', document.getElementById('estimatedPayments')?.value || '0');

  document.body.appendChild(form);
  form.submit();
}

// ─── Welcome screen ───────────────────────────────────────────────────────────

function startApp() {
  const welcome = document.getElementById('welcome');
  const app = document.getElementById('app');
  welcome.classList.add('hide');
  setTimeout(() => {
    welcome.style.display = 'none';
    app.classList.add('visible');
  }, 700);
}

// ─── Initialisation ───────────────────────────────────────────────────────────

document.querySelectorAll('#creditsGrid input[type="checkbox"]').forEach(checkbox => {
  checkbox.addEventListener('change', function() {
    this.parentElement.classList.toggle('checked', this.checked);
  });
  checkbox.parentElement.classList.toggle('checked', checkbox.checked);
});

document.querySelectorAll('#filingStatus .radio-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('#filingStatus .radio-item').forEach(r => r.classList.remove('selected'));
    item.classList.add('selected');
    item.querySelector('input').checked = true;
  });
});

document.getElementById('itemizedFields').style.display = 'none';