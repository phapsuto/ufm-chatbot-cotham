"""app/main.py — FastAPI application entry point (v3)"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes import chat, health, handoff, guest, enrollment, crm
from app.services import cache_service, memory_service, kb_service
from app.services.reranker_service import init_bge_reranker

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG_MODE else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ufm-chatbot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🎓 Cô giáo Thắm UFM Chatbot v4 — CRM + AI Lead Scoring")
    logger.info(f"   Model: {settings.FPT_CLOUD_DEFAULT_MODEL}")
    logger.info(f"   Domain: {settings.ALLOWED_DOMAIN}")
    # Ensure data directories exist
    for d in ["data", "data/enrollments", "data/crm"]:
        os.makedirs(d, exist_ok=True)
    # Khởi tạo Knowledge Base (BM25 + Vector) — chạy ở đây thay vì module level
    kb_service.init_kb()
    # Khởi tạo BGE-M3 ONNX Reranker (~500MB, CPU)
    init_bge_reranker()
    yield
    memory_service.cleanup_expired_sessions()
    logger.info("👋 Chatbot đã tắt.")


app = FastAPI(title="Cô giáo Thắm — UFM Chatbot", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(chat.router)
app.include_router(health.router)
app.include_router(handoff.router)
app.include_router(guest.router, prefix="/api")
app.include_router(enrollment.router, prefix="/api")
app.include_router(crm.router, prefix="/api")

# CRM Dashboard static files
if os.path.isdir("static/crm"):
    app.mount("/crm", StaticFiles(directory="static/crm", html=True), name="crm")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/admin/clear-cache")
async def admin_clear_cache(secret: str = "ufm2026"):
    if secret != "ufm2026":
        raise HTTPException(status_code=403, detail="Forbidden")
    cache_service.clear_all()
    return {"message": "Cache đã được xóa thành công"}
