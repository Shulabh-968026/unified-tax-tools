"""MSS x Assure - Audit Utilities backend (slim app factory).

Modules: auth, clients, admin, clause44 (runs), msme43bh (43B(h) disallowance).
"""
import logging
import os

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from core.db import ensure_indexes, ensure_super_admin, mongo_client
from modules.admin.controller import router as admin_router
from modules.auth.controller import router as auth_router
from modules.clause44.controller import router as clause44_router
from modules.clients.controller import router as clients_router
from modules.msme43bh.controller import router as msme_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="MSS x Assure Audit Utilities")
api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(clients_router)
api.include_router(clause44_router)
api.include_router(admin_router)
api.include_router(msme_router)


@api.get("/")
async def root():
    return {"app": "mss-assure-utilities", "ok": True}


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
