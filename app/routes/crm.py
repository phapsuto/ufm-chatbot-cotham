"""app/routes/crm.py — CRM Dashboard API endpoints (v4)"""
import hashlib
import json
import re
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query, Response
from pydantic import BaseModel

from app.config import settings
from app.services import crm_service

logger = logging.getLogger("ufm-chatbot")
router = APIRouter()

CRM_PASSWORD = getattr(settings, "CRM_DASHBOARD_PASSWORD", "ufm_crm_2026")


def _verify_crm_auth(x_crm_token: Optional[str] = Header(None)):
    """Verify CRM auth token."""
    if not x_crm_token:
        raise HTTPException(status_code=401, detail="CRM token required")
    expected = hashlib.sha256(CRM_PASSWORD.encode()).hexdigest()[:32]
    if x_crm_token != expected:
        raise HTTPException(status_code=403, detail="Invalid CRM token")


# ── Auth ─────────────────────────────────

class LoginRequest(BaseModel):
    password: str

@router.post("/crm/login")
async def crm_login(req: LoginRequest):
    if req.password != CRM_PASSWORD:
        raise HTTPException(status_code=401, detail="Sai mật khẩu")
    token = hashlib.sha256(CRM_PASSWORD.encode()).hexdigest()[:32]
    return {"success": True, "token": token}


# ── Dashboard Stats ──────────────────────

@router.get("/crm/dashboard/stats")
async def dashboard_stats(x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    return crm_service.get_dashboard_stats()


# ── Leads CRUD ───────────────────────────

@router.get("/crm/leads")
async def list_leads(
    x_crm_token: Optional[str] = Header(None),
    grade: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    nganh: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    _verify_crm_auth(x_crm_token)
    return crm_service.get_all_leads(
        grade=grade, status=status, nganh=nganh,
        search=search, date_from=date_from, date_to=date_to,
        page=page, per_page=per_page,
    )


@router.get("/crm/leads/{lead_id}")
async def get_lead(lead_id: str, x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    lead = crm_service.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


class LeadUpdateRequest(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    follow_up_date: Optional[str] = None
    tags: Optional[list] = None
    priority: Optional[str] = None

@router.patch("/crm/leads/{lead_id}")
async def update_lead(lead_id: str, req: LeadUpdateRequest,
                      x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    ok = crm_service.update_crm_status(
        lead_id, status=req.status, assigned_to=req.assigned_to,
        follow_up_date=req.follow_up_date, tags=req.tags, priority=req.priority,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"success": True}


class NoteRequest(BaseModel):
    author: str
    content: str

@router.post("/crm/leads/{lead_id}/notes")
async def add_note(lead_id: str, req: NoteRequest,
                   x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    ok = crm_service.add_note(lead_id, req.author, req.content)
    if not ok:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"success": True}


@router.post("/crm/leads/{lead_id}/rescore")
async def rescore_lead(lead_id: str, x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    from app.services import scoring_engine
    lead = crm_service.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    sr = scoring_engine.calculate_lead_score(lead)
    crm_service.update_crm_status(lead_id, status=sr["recommended_status"],
                                  priority=sr["recommended_priority"])
    return {"success": True, "new_score": sr["lead_score"], "grade": sr["lead_grade"]}


# ── Export ───────────────────────────────

@router.get("/crm/export/csv")
async def export_csv(
    x_crm_token: Optional[str] = Header(None),
    grade: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    _verify_crm_auth(x_crm_token)
    csv_content = crm_service.export_leads_csv(grade=grade, status=status)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ufm_crm_leads.csv"},
    )


# ── Analytics ────────────────────────────

@router.get("/crm/analytics")
async def analytics(x_crm_token: Optional[str] = Header(None)):
    _verify_crm_auth(x_crm_token)
    return crm_service.get_dashboard_stats()
