"""MongoDB connection singleton + workspace-shared schema indexes."""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent  # /app/backend
load_dotenv(ROOT_DIR / ".env")
log = logging.getLogger("db")

mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

SUPER_ADMIN_EMAIL = "mssandco@gmail.com"


async def ensure_indexes():
    # Drop legacy per-user uniqueness; the workspace is shared.
    try:
        await db.clients.drop_index("user_id_1_file_number_1")
    except Exception:
        pass
    # Workspace-wide unique file_number
    try:
        await db.clients.create_index("file_number", unique=True)
    except Exception as e:
        log.warning(f"Could not create file_number unique index (likely duplicates): {e}")
    await db.runs.create_index([("client_id", 1), ("period", 1)])
    await db.user_sessions.create_index("session_token", unique=True)
    await db.users.create_index("email", unique=True)
    await db.invitations.create_index("email", unique=True)
    # GST Recon Phase D — invoice-level voucher matching
    await db.gst_recon_invoices.create_index([("run_id", 1), ("source", 1), ("period", 1)])
    await db.gst_recon_invoices.create_index([("run_id", 1), ("direction", 1), ("period", 1)])
    # Client Library — indexes that drive the per-engagement file lookup.
    await db.client_files.create_index(
        [("firm_id", 1), ("client_id", 1), ("period", 1), ("file_type", 1), ("version_no", -1)],
    )
    await db.client_files.create_index([("file_id", 1)], unique=True)
    await db.client_files.create_index([("soft_deleted_at", 1)])


async def ensure_super_admin():
    """Idempotently ensure SUPER_ADMIN_EMAIL has role 'super_admin'."""
    from datetime import datetime, timezone
    import uuid
    user = await db.users.find_one({"email": SUPER_ADMIN_EMAIL}, {"_id": 0})
    if user:
        if user.get("role") != "super_admin":
            await db.users.update_one({"email": SUPER_ADMIN_EMAIL}, {"$set": {"role": "super_admin"}})
    else:
        await db.users.insert_one({
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": SUPER_ADMIN_EMAIL,
            "name": "",
            "picture": "",
            "role": "super_admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    # Backfill role for legacy users
    await db.users.update_many({"role": {"$exists": False}}, {"$set": {"role": "user"}})
