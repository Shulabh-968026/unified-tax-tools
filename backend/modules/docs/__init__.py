"""User-facing documentation: HTML + PDF served from a single source of truth.

Architecture
------------
One Jinja2 template per module under `templates/{key}.html`.  Both endpoints
render the SAME template — only the styling layer differs:

    /api/docs/{key}        →  full screen page (browser nav, sticky TOC, link
                              to download PDF, soft motion/hover affordances)
    /api/docs/{key}.pdf    →  WeasyPrint with the print stylesheet — zero
                              navigation chrome, hard A4 page-breaks, page
                              numbers in footer, URLs printed inline.

Because both paths render `templates/{key}.html` with the same context, there
is exactly one place to update content.  WeasyPrint switches on
`@media print` blocks defined in `templates/_doc.css`.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from modules.auth.controller import get_current_user

router = APIRouter(prefix="/docs", tags=["docs"])

_HERE = Path(__file__).resolve().parent
_TEMPLATE_DIR = _HERE / "templates"
_ASSET_DIR = _HERE / "assets"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Module catalogue — every entry needs a `templates/{key}.html` file.
# Keep this list ordered the way they appear in the product.
# ---------------------------------------------------------------------------
MODULES: List[Dict[str, str]] = [
    {
        "key":   "clause-44",
        "title": "Clause 44 of Form 3CD — Expense Bifurcation",
        "tagline": "Classify every books-of-account expense into the four GST cohorts "
                   "demanded by Clause 44 and ship a working-paper your reviewer will "
                   "sign without questions.",
        "version": "v1.0",
        "reading_time_min": 8,
    },
]
MODULE_BY_KEY = {m["key"]: m for m in MODULES}


_DOC_CSS = (_HERE / "assets" / "_doc.css").read_text(encoding="utf-8")


def _common_context(meta: Dict[str, str], *, for_pdf: bool) -> Dict:
    """Context passed to every template render."""
    return {
        "meta": meta,
        "modules": MODULES,
        "for_pdf": for_pdf,
        "css": _DOC_CSS,
        "generated_at": datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC"),
        "brand": "AssureAI Utilities",
        "byline": "AssureAI · Audit Utilities",
        "support_email": os.environ.get("DOCS_SUPPORT_EMAIL", "support@assureai.app"),
    }


@router.get("", include_in_schema=False)
async def list_docs(
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Index page (login-gated)."""
    await get_current_user(request, session_token, authorization)
    tpl = _env.get_template("_index.html")
    return HTMLResponse(tpl.render(_common_context({"key": "_index"}, for_pdf=False)))


@router.get("/{key}.pdf", include_in_schema=False)
async def get_doc_pdf(
    key: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    if key not in MODULE_BY_KEY:
        raise HTTPException(404, f"No readme for module '{key}'")
    # Late import — WeasyPrint pulls 5+ heavy native libs
    from weasyprint import HTML  # type: ignore

    tpl = _env.get_template(f"{key}.html")
    html_str = tpl.render(_common_context(MODULE_BY_KEY[key], for_pdf=True))

    buf = io.BytesIO()
    HTML(string=html_str, base_url=str(_TEMPLATE_DIR)).write_pdf(buf)
    pdf = buf.getvalue()
    fname = f"AssureAI_{key.replace('-', '_')}_user_guide.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.get("/{key}", include_in_schema=False)
async def get_doc_html(
    key: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    await get_current_user(request, session_token, authorization)
    if key not in MODULE_BY_KEY:
        raise HTTPException(404, f"No readme for module '{key}'")
    tpl = _env.get_template(f"{key}.html")
    html = tpl.render(_common_context(MODULE_BY_KEY[key], for_pdf=False))
    return HTMLResponse(html)


# Small static asset mount for the inline SVG illustrations and CSS.  We do
# NOT use FastAPI's StaticFiles since the assets are bundled inside the
# python module — instead we serve byte-for-byte from disk.
@router.get("/{key}/_asset/{name}", include_in_schema=False)
async def get_doc_asset(
    key: str,
    name: str,
    request: Request,
    session_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """Serves anything under `modules/docs/assets/{key}/{name}`.  Used for
    SVG illustrations, screenshots and the shared print CSS."""
    await get_current_user(request, session_token, authorization)
    p = (_ASSET_DIR / key / name).resolve()
    if not str(p).startswith(str(_ASSET_DIR.resolve())) or not p.is_file():
        raise HTTPException(404, "Asset not found")
    suffix = p.suffix.lower()
    media = {
        ".css":  "text/css",
        ".svg":  "image/svg+xml",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return Response(content=p.read_bytes(), media_type=media)
