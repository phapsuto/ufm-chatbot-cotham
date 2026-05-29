"""app/models.py — Pydantic models cho API (v3)"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    gender: str = ""  # "nam" hoặc "nu" — để Cô Thắm xưng hô đúng
    voice_mode: bool = False  # True = voice chat → trả lời ngắn gọn văn nói


class SourceItem(BaseModel):
    url: str
    title: str
    type: str = "webpage"  # "webpage" or "pdf"


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []
    suggestions: list[str] = []
    requires_handoff: bool = False
    session_id: str


class HandoffRequest(BaseModel):
    name: str
    phone: str
    email: str = ""
    interest: str
    session_id: str = ""


class HandoffResponse(BaseModel):
    success: bool
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str = "4.0.0"


# ══════════════════════════════════
# PHẦN 1: Onboarding Gate Models
# ══════════════════════════════════

class GuestProfile(BaseModel):
    full_name: str
    birth_year: int
    gender: str = ""  # "nam" | "nu"
    education_level: str  # "dai_hoc" | "sau_dai_hoc" | "cao_dang" | "khac"
    education_detail: str = ""
    contact: str
    contact_type: str = ""  # "email" | "phone" — auto detect
    consent_given: bool
    created_at: str = ""
    session_id: str = ""


class GuestProfileResponse(BaseModel):
    success: bool
    session_id: str
    message: str
    profile_id: str = ""


# ══════════════════════════════════
# PHẦN 2: Enrollment Models
# ══════════════════════════════════

class EnrollmentStartRequest(BaseModel):
    session_id: str


class EnrollmentInfoRequest(BaseModel):
    enrollment_id: str
    step: int  # 1 or 2
    data: dict


class EnrollmentSubmitRequest(BaseModel):
    enrollment_id: str
