"""OCR-powered invoice splitter + extractor for the Fixed Assets Additions tab.

Pipeline:
    1. PDF in (single invoice or combined ledger+invoices)
    2. Single Gemini-2.5-flash call →
         { page_classifications, invoices: [...with page_range], ledger_pages }
    3. For each invoice chunk, slice the source PDF into a per-chunk PDF using pypdf.
    4. Match chunk → fa_addition row (3-pass: exact inv-no → GSTIN+total ± ₹1 → fuzzy).

Returns a preview dict the controller hands back to the frontend.
The frontend renders the preview, the auditor approves, and the controller
then persists each chunk into `fa_invoice_attachments`.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import tempfile
from io import BytesIO
from typing import Any, Dict, List, Optional

from emergentintegrations.llm.chat import (
    FileContentWithMimeType, LlmChat, UserMessage,
)
from pypdf import PdfReader, PdfWriter
from rapidfuzz import fuzz

log = logging.getLogger("fixed_assets.invoice_ocr")

GEMINI_MODEL = ("gemini", "gemini-2.5-flash")

EXTRACTION_PROMPT = """You are an expert auditor analysing a combined PDF that may contain
a Ledger Extract followed by one or more Tax Invoices, OR a single tax invoice.

For EACH page (1..N), classify it as one of:
  - "ledger_extract"           — a Tally-style ledger account page
  - "tax_invoice_first_page"   — first page of a new tax invoice (header / "TAX INVOICE" /
                                   supplier letterhead / new invoice number)
  - "tax_invoice_continuation" — a continuation page of the previous invoice (line items,
                                   annexure, T&Cs, signature block — NO new invoice header)
  - "other"                    — anything else (cover page, blank, signed challan, etc.)

If any ledger_extract pages exist, also extract:
  - detected_ledger_name — the ledger name as it appears on the ledger header,
                           e.g. "Computer GST 18%", "Plant & Machinery GST 12%",
                           "Furniture & Fixtures". Trim trailing words like
                           "Ledger Account". Empty string if no ledger page.

Group consecutive invoice pages into chunks: one chunk = one_first_page +
zero_or_more_continuation pages. Boundary signals: "TAX INVOICE" header, new IRN,
new supplier GSTIN, new invoice number.

For each invoice chunk, extract:
  - invoice_no            (string, exact, no slashes converted)
  - invoice_date_iso      (YYYY-MM-DD; convert dd-mmm-yy or dd/mm/yyyy)
  - supplier_name         (string, legal name)
  - supplier_gstin        (15-char alphanumeric; "" if not visible)
  - buyer_name            (string)
  - buyer_gstin           ("" if not visible)
  - total_value           (float, grand total INCLUSIVE of all taxes)
  - taxable_value         (float, sum before tax)
  - cgst, sgst, igst      (floats, 0 if absent)
  - description           (a single concise asset-register line in <=120 chars,
                            describing the principal asset; e.g.
                            "Sewing Machine — SIRUBA F007K-W122-356/FH (1 unit)".
                            DO NOT include freight, packing, GST in this line.)
  - line_items            (array of {desc, qty, rate, amount}; cap at 8)
  - page_range            ([start,end], 1-based, inclusive)

Rules:
  • Invoice numbers must be copied character-for-character — do NOT normalise.
  • If supplier and buyer names are swapped (rare), pick by who is TO/FROM.
  • Round all currency floats to 2 decimal places.
  • Empty list for invoices if the document contains only ledgers/other.

Return ONLY valid JSON, no markdown fences, no commentary:
{
  "page_classifications": [{"page": 1, "kind": "ledger_extract"}, ...],
  "detected_ledger_name": "Computer GST 18%",
  "invoices": [...],
  "ledger_pages": [1, ...]
}
"""


# ============================================================ Helpers
_INVNO_NORM = re.compile(r"[\s/\\\-\._]+")


def _norm_invno(s: str) -> str:
    """Strip separators for fuzzy comparison while preserving order."""
    return _INVNO_NORM.sub("", (s or "").strip().lower())


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # strip leading ```json or ```
        s = s.split("```", 2)[1]
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.rstrip("`").strip()
    return s


def slice_pdf(src_bytes: bytes, page_range: List[int]) -> bytes:
    """Return a new PDF containing only the inclusive 1-based page_range."""
    if not page_range or len(page_range) != 2:
        raise ValueError("page_range must be [start, end] (1-based, inclusive)")
    start, end = int(page_range[0]), int(page_range[1])
    reader = PdfReader(BytesIO(src_bytes))
    n = len(reader.pages)
    start = max(1, start)
    end = min(n, end)
    if start > end:
        raise ValueError(f"Empty page range {start}-{end} in {n}-page PDF")
    writer = PdfWriter()
    for i in range(start - 1, end):
        writer.add_page(reader.pages[i])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ============================================================ Gemini call
async def gemini_extract(pdf_bytes: bytes) -> Dict[str, Any]:
    """Run the splitter+extractor in a single Gemini vision call.
    Returns the parsed dict; raises ValueError on parse failure.
    Retries up to 3 times on transient upstream failures (502/503/network)."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY not configured in backend environment.")

    # The SDK only takes a file_path; persist briefly so it can read it.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tf.write(pdf_bytes)
        tmp_path = tf.name

    raw: Optional[str] = None
    last_err: Optional[Exception] = None
    try:
        for attempt in range(1, 4):
            chat = LlmChat(
                api_key=api_key,
                session_id=f"fa-invoice-ocr-{attempt}",
                system_message=("You extract structured tax invoice data with extreme precision. "
                                 "Never invent values. Output strict JSON only."),
            ).with_model(*GEMINI_MODEL).with_params(temperature=0.1)
            msg = UserMessage(
                text=EXTRACTION_PROMPT,
                file_contents=[FileContentWithMimeType(mime_type="application/pdf",
                                                      file_path=tmp_path)],
            )
            try:
                raw = await chat.send_message(msg)
                break
            except Exception as e:  # noqa: BLE001
                txt = str(e).lower()
                # Retry only on transient upstream failures
                transient = ("502" in txt or "503" in txt or "504" in txt
                             or "bad gateway" in txt or "timeout" in txt
                             or "temporarily" in txt or "rate" in txt)
                last_err = e
                log.warning("Gemini call attempt %d failed (%s): %s",
                            attempt, "transient" if transient else "permanent", e)
                if not transient or attempt == 3:
                    raise
                # Exponential backoff: 3s, 8s
                await asyncio.sleep(3 * attempt + (attempt - 1) * 2)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if raw is None:
        raise ValueError(f"Gemini call failed after retries: {last_err}")

    cleaned = _strip_code_fences(raw or "")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("Gemini returned non-JSON; first 400 chars: %r", (raw or "")[:400])
        raise ValueError(f"Gemini returned non-JSON: {e}")

    # Defensive normalisation
    invs = data.get("invoices") or []
    for inv in invs:
        inv["invoice_no"]      = (inv.get("invoice_no") or "").strip()
        inv["supplier_name"]   = (inv.get("supplier_name") or "").strip()
        inv["supplier_gstin"]  = (inv.get("supplier_gstin") or "").strip().upper()
        inv["buyer_gstin"]     = (inv.get("buyer_gstin") or "").strip().upper()
        inv["description"]     = (inv.get("description") or "").strip()[:200]
        for k in ("total_value", "taxable_value", "cgst", "sgst", "igst"):
            try:
                inv[k] = round(float(inv.get(k) or 0), 2)
            except (TypeError, ValueError):
                inv[k] = 0.0
        pr = inv.get("page_range") or []
        if isinstance(pr, list) and len(pr) == 2:
            inv["page_range"] = [int(pr[0]), int(pr[1])]
        else:
            inv["page_range"] = [1, 1]
        inv["line_items"] = (inv.get("line_items") or [])[:8]

    return {
        "page_classifications": data.get("page_classifications") or [],
        "invoices":             invs,
        "ledger_pages":         data.get("ledger_pages") or [],
        "detected_ledger_name": (data.get("detected_ledger_name") or "").strip(),
    }


# ============================================================ Matching
def match_invoice_to_addition(
    invoice: Dict[str, Any],
    additions: List[Dict[str, Any]],
    *, tol_rupees: float = 1.0, tol_pct: float = 0.005,
) -> Optional[Dict[str, Any]]:
    """3-pass match: exact inv-no → GSTIN+total ± ₹1 → fuzzy inv-no.

    Skips additions that are merged children or discount-credit pseudo-rows.
    Returns {addition_id, score, method, why} or None.
    """
    eligible = [
        a for a in additions
        if not (a.get("parent_addition_id") or "")
        and (a.get("source") or "addition") != "discount_credit"
    ]
    if not eligible:
        return None

    inv_no_n  = _norm_invno(invoice.get("invoice_no"))
    gstin     = invoice.get("supplier_gstin") or ""
    total     = float(invoice.get("total_value") or 0)
    sup_name  = invoice.get("supplier_name") or ""

    # Pass 1 — exact normalised invoice number match
    if inv_no_n:
        for a in eligible:
            if _norm_invno(a.get("invoice_no")) == inv_no_n:
                return {"addition_id": a["addition_id"], "score": 100, "method": "exact_inv_no",
                        "why": f"invoice_no '{a.get('invoice_no')}' matches"}

    # Pass 2 — GSTIN + total ±tolerance (or party_name + total when GSTIN missing)
    if total > 0:
        tol = max(tol_rupees, total * tol_pct)
        for a in eligible:
            a_total = float(a.get("invoice_cost") or 0)
            if abs(a_total - total) > tol:
                continue
            # Prefer GSTIN match where available
            if gstin and (a.get("party_gstin") or "").upper() == gstin:
                return {"addition_id": a["addition_id"], "score": 95,
                        "method": "gstin_plus_total",
                        "why": f"₹{a_total} ≈ ₹{total} & GSTIN {gstin}"}
            # Fallback to party_name fuzzy + total
            if sup_name and a.get("party_name"):
                ratio = fuzz.token_set_ratio(sup_name, a["party_name"])
                if ratio >= 80:
                    return {"addition_id": a["addition_id"], "score": 90,
                            "method": "party_plus_total",
                            "why": f"₹{a_total} ≈ ₹{total} & party '{a['party_name']}' ({ratio})"}

    # Pass 3 — fuzzy invoice number within same supplier (party fuzzy ≥80)
    if inv_no_n and sup_name:
        best = None
        for a in eligible:
            a_inv_n = _norm_invno(a.get("invoice_no"))
            if not a_inv_n:
                continue
            inv_score = fuzz.ratio(inv_no_n, a_inv_n)
            if inv_score < 85:
                continue
            party_score = fuzz.token_set_ratio(sup_name, a.get("party_name") or "") if a.get("party_name") else 0
            if party_score < 70:
                continue
            score = (inv_score + party_score) / 2
            if not best or score > best["score"]:
                best = {"addition_id": a["addition_id"], "score": int(score),
                        "method": "fuzzy_inv_no",
                        "why": f"inv-no fuzz {inv_score} & party fuzz {party_score}"}
        if best:
            return best

    return None


def detect_fa_ledger_id(detected_name: str, run_ledgers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fuzzy-match the OCR-detected ledger name against the run's actual ledgers.
    Returns {fa_ledger_id, name, score} on confident match (≥85), else None."""
    if not detected_name or not run_ledgers:
        return None
    best = None
    for L in run_ledgers:
        name = (L.get("name") or "").strip()
        if not name:
            continue
        score = max(
            fuzz.token_set_ratio(detected_name, name),
            fuzz.partial_ratio(detected_name.lower(), name.lower()),
        )
        if score >= 85 and (best is None or score > best["score"]):
            best = {"fa_ledger_id": L.get("fa_ledger_id"), "name": name, "score": int(score)}
    return best


# ============================================================ Orchestrator
async def split_extract_and_match(
    *, pdf_bytes: bytes, additions: List[Dict[str, Any]],
    run_ledgers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """High-level entry point used by the controller.

    Returns:
        {
          "page_classifications": [...],
          "ledger_pages":         [...],
          "chunks": [
            {
              "chunk_index":   int,
              "page_range":    [s,e],
              "extraction":    {invoice_no, supplier_name, ..., description, ...},
              "match":         {addition_id, score, method, why} | None,
              "pdf_size":      int,           # bytes of the per-chunk PDF
              "pdf_b64":       str,           # gzipped + base64 (caller persists)
            }, ...
          ],
          "single_invoice": bool,             # convenience flag for the UI
          "summary": {
            "pages_total": int, "invoices_detected": int,
            "matched": int, "unmatched": int,
          }
        }
    """
    import base64
    import gzip

    parsed = await gemini_extract(pdf_bytes)
    invoices = parsed["invoices"]

    chunks: List[Dict[str, Any]] = []
    matched = 0
    for idx, inv in enumerate(invoices):
        try:
            chunk_pdf = slice_pdf(pdf_bytes, inv["page_range"])
        except Exception as e:  # noqa: BLE001
            log.warning("slice_pdf failed for chunk %d (%s): %s", idx, inv.get("page_range"), e)
            continue
        match = match_invoice_to_addition(inv, additions)
        if match:
            matched += 1
        chunks.append({
            "chunk_index": idx,
            "page_range":  inv["page_range"],
            "extraction":  inv,
            "match":       match,
            "pdf_size":    len(chunk_pdf),
            "pdf_b64":     base64.b64encode(gzip.compress(chunk_pdf)).decode("ascii"),
        })

    n_pages = len(parsed["page_classifications"]) or len(PdfReader(BytesIO(pdf_bytes)).pages)
    detected_ledger = detect_fa_ledger_id(parsed["detected_ledger_name"], run_ledgers or [])
    return {
        "page_classifications": parsed["page_classifications"],
        "ledger_pages":         parsed["ledger_pages"],
        "detected_ledger_name": parsed["detected_ledger_name"],
        "detected_fa_ledger_id": (detected_ledger or {}).get("fa_ledger_id") or "",
        "detected_fa_ledger":   detected_ledger,
        "chunks":               chunks,
        "single_invoice":       len(chunks) == 1 and not parsed["ledger_pages"],
        "summary": {
            "pages_total":       n_pages,
            "invoices_detected": len(invoices),
            "matched":           matched,
            "unmatched":         len(chunks) - matched,
        },
    }
