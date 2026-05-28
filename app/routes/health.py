"""app/routes/health.py — Health + OCR diagnostic endpoints"""
import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.models import HealthResponse
from app.services import cache_service, memory_service, pdf_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version="4.0.0")


@router.get("/health/detail")
async def health_detail():
    return {
        "status": "ok",
        "version": "3.0.0",
        "cache": cache_service.stats(),
        "sessions": memory_service.session_count(),
    }


@router.get("/api/health/ocr")
async def check_ocr_health():
    """Kiểm tra Tesseract OCR status."""
    return pdf_service.get_ocr_health()


class OcrTestRequest(BaseModel):
    pdf_url: str


@router.post("/api/health/ocr/test")
async def test_ocr_pdf(req: OcrTestRequest):
    """Test OCR with a specific PDF URL."""
    result = await pdf_service.read_pdf(req.pdf_url)
    if result:
        return {
            "url": req.pdf_url,
            "success": True,
            "chars": len(result),
            "text_preview": result[:300],
        }
    else:
        return {
            "url": req.pdf_url,
            "success": False,
            "error": "Could not extract text from PDF",
        }
