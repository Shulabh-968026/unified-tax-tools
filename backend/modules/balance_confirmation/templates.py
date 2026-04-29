"""Default email templates seeded on first use.

Each template is HTML with Jinja-style `{{placeholder}}` tokens. The Phase 3
sending engine will render with python's `string.Template`-equivalent
substitution (we'll use Jinja2 Sandbox once we wire actual sending).

AssureAI brand: #047857 emerald-700 (professional green, calm, audit-ready).
"""
from __future__ import annotations
from typing import List

ASSUREAI_GREEN = "#047857"


# ---------------------------------------------------------------- Customers (Trade Receivables)
CUSTOMER_DEFAULT = {
    "kind": "customer",
    "name": "Customer Confirmation — Standard",
    "subject": "Confirmation of Balance — M/s {{client_name}} as on {{as_at_date}}",
    "html_body": """\
<p>Dear {{contact_name_or_party}},</p>

<p>As part of the statutory audit of <strong>{{client_name}}</strong> for the
financial year ended <strong>{{as_at_date}}</strong>, we are reconciling
balances of trade receivables.</p>

<p>As per our books, the balance receivable from your good self as on
{{as_at_date}} is:</p>

<p style="font-size:18px;font-weight:600;color:#047857;
          padding:10px 16px;border-left:3px solid #047857;
          background:#ECFDF5;display:inline-block;">
  {{closing_balance_inr}} {{dr_cr}}
</p>

<p>We request you to kindly confirm the above balance directly to us by
clicking the button below. If you do not agree, please share your statement
of account so we can reconcile.</p>

<p style="margin:24px 0;">
  <a href="{{response_link}}"
     style="display:inline-block;padding:10px 22px;background:#047857;color:#FFF;
            font-weight:600;text-decoration:none;border-radius:4px;">
    Confirm or dispute balance
  </a>
</p>

<p style="font-size:12px;color:#52524E;">
  This request is sent in pursuance of our statutory audit. Your confirmation
  is required only for audit verification — it does not change any balance
  due. The link is valid until the audit is signed off.
</p>

<p>Thank you for your cooperation.</p>
<p>Yours faithfully,<br/>
   <strong>{{auditor_name}}</strong><br/>
   {{auditor_firm}}<br/>
   For and on behalf of {{client_name}}</p>
""",
}

# ---------------------------------------------------------------- Vendors (Trade Payables)
VENDOR_DEFAULT = {
    "kind": "vendor",
    "name": "Vendor Confirmation — Statement Match",
    "subject": "Confirmation of Balance — M/s {{client_name}} as on {{as_at_date}}",
    "html_body": """\
<p>Dear {{contact_name_or_party}},</p>

<p>As part of the statutory audit of <strong>{{client_name}}</strong> for the
financial year ended <strong>{{as_at_date}}</strong>, we are required to
verify trade payables outstanding to vendors.</p>

<p>As per our books, the balance payable to your firm as on {{as_at_date}} is:</p>

<p style="font-size:18px;font-weight:600;color:#047857;
          padding:10px 16px;border-left:3px solid #047857;
          background:#ECFDF5;display:inline-block;">
  {{closing_balance_inr}} {{dr_cr}}
</p>

<p>We request you to either:</p>
<ul>
  <li>Confirm the above balance, OR</li>
  <li>Share your statement of account so we may reconcile any difference
      (including invoices in transit, debit notes, advances, etc.).</li>
</ul>

<p>The attached ledger extract reflects all transactions during the year for
your reference. A signed authorisation letter from our client is also
attached.</p>

<p style="margin:24px 0;">
  <a href="{{response_link}}"
     style="display:inline-block;padding:10px 22px;background:#047857;color:#FFF;
            font-weight:600;text-decoration:none;border-radius:4px;">
    Confirm or dispute balance
  </a>
</p>

<p>Yours faithfully,<br/>
   <strong>{{auditor_name}}</strong><br/>
   {{auditor_firm}}<br/>
   For and on behalf of {{client_name}}</p>
""",
}

# ---------------------------------------------------------------- Banks
BANK_DEFAULT = {
    "kind": "bank",
    "name": "Bank Confirmation — Independent Verification",
    "subject": "Confirmation of Balance — M/s {{client_name}} as on {{as_at_date}}",
    "html_body": """\
<p>The Branch Manager,<br/>
   <strong>{{party_name}}</strong><br/>
   {{address}}</p>

<p>Dear Sir / Madam,</p>

<p><strong>Sub: Bank Confirmation as on {{as_at_date}} — {{client_name}}
   {{client_gstin}}</strong></p>

<p>As part of the statutory audit of our client M/s {{client_name}} for the
financial year ended {{as_at_date}}, we request you to provide the
following information directly to us in the format prescribed by the
Institute of Chartered Accountants of India:</p>

<ol>
  <li>Balance in all current / cash credit / overdraft / fixed deposit /
      loan accounts of the client as on {{as_at_date}}.</li>
  <li>Particulars of all securities / hypothecations / mortgages / liens
      held by the bank against the client.</li>
  <li>Particulars of guarantees, letters of credit, and other contingent
      liabilities outstanding.</li>
  <li>Particulars of bills under collection / discounting outstanding.</li>
  <li>Interest accrued but not due / paid during the year.</li>
  <li>Particulars of any other facilities or arrangements held with the
      bank as on the said date.</li>
  <li>Particulars of any overdues / NPA classification, if applicable.</li>
</ol>

<p>The duly authorised letter from the client is attached. Please reply to
this email or use the secure link below.</p>

<p style="margin:24px 0;">
  <a href="{{response_link}}"
     style="display:inline-block;padding:10px 22px;background:#047857;color:#FFF;
            font-weight:600;text-decoration:none;border-radius:4px;">
    Submit confirmation online
  </a>
</p>

<p>Thanking you,</p>
<p>Yours faithfully,<br/>
   <strong>{{auditor_name}}</strong><br/>
   {{auditor_firm}}<br/>
   For and on behalf of {{client_name}}</p>
""",
}


def all_defaults() -> List[dict]:
    return [CUSTOMER_DEFAULT, VENDOR_DEFAULT, BANK_DEFAULT]


# Standard placeholders we expose in the UI for autocomplete
STANDARD_PLACEHOLDERS = [
    "client_name",
    "client_gstin",
    "as_at_date",
    "party_name",
    "contact_name_or_party",
    "closing_balance_inr",
    "dr_cr",
    "response_link",
    "auditor_name",
    "auditor_firm",
    "address",
]
