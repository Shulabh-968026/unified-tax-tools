"""AssureAI Audit Utilities backend (slim app factory).

Modules: auth, clients, admin, clause44 (runs), msme43bh (43B(h) disallowance).
"""
import logging
import os

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from core.db import ensure_indexes, ensure_super_admin, mongo_client
from modules.admin.controller import router as admin_router
from modules.auth.controller import router as auth_router
from modules.balance_confirmation.controller import router as bc_router
from modules.clause44.controller import router as clause44_router
from modules.clients.controller import router as clients_router
from modules.docs import router as docs_router
from modules.fixed_assets.controller import router as fixed_assets_router
from modules.fin_statement.controller import router as fs_router
from modules.msme43bh.controller import router as msme_router
from modules.gst_recon.controller import router as gst_recon_router
from modules.library import router as library_router
from modules.library import gstin_groups_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="AssureAI Audit Utilities")
api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(clients_router)
api.include_router(clause44_router)
api.include_router(admin_router)
api.include_router(msme_router)
api.include_router(gst_recon_router)
api.include_router(bc_router)
api.include_router(fixed_assets_router)
api.include_router(fs_router)
api.include_router(docs_router)
api.include_router(library_router)
api.include_router(gstin_groups_router)


@api.get("/")
async def root():
    return {"app": "assureai-utilities", "ok": True}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    try:
        await ensure_indexes()
        await ensure_super_admin()
    except Exception as e:
        log.warning(f"Startup setup issue: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
