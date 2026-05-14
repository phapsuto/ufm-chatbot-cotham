"""app/routes/guest.py — Onboarding Gate: đăng ký thông tin khách trước khi chat"""
import csv
import json
import os
import re
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models import GuestProfile, GuestProfileResponse
from app.services import memory_service, crm_service

logger = logging.getLogger("ufm-chatbot")
router = APIRouter()

DATA_DIR = "data"
GUESTS_JSON = os.path.join(DATA_DIR, "guests.json")
GUESTS_CSV = os.path.join(DATA_DIR, "guests.csv")


def _ensure_data_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(GUESTS_JSON):
        with open(GUESTS_JSON, "w", encoding="utf-8") as f:
            json.dump([], f)
    if not os.path.exists(GUESTS_CSV):
        with open(GUESTS_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "profile_id", "session_id", "full_name", "birth_year",
                "education_level", "education_detail", "contact",
                "contact_type", "consent_given", "created_at",
            ])


def _detect_contact_type(contact: str) -> str:
    contact = contact.strip()
    if "@" in contact and "." in contact:
        return "email"
    return "phone"


def _validate_phone(phone: str) -> bool:
    clean = re.sub(r"[\s\-\.]", "", phone)
    return bool(re.match(r"^0\d{8,10}$", clean))


def _validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


@router.post("/guest/register", response_model=GuestProfileResponse)
async def register_guest(profile: GuestProfile):
    """Đăng ký thông tin khách trước khi chat."""

    # Validate required fields
    if not profile.full_name.strip():
        raise HTTPException(status_code=400, detail="Họ và tên không được để trống")

    current_year = datetime.now().year
    if not (1940 <= profile.birth_year <= current_year - 16):
        raise HTTPException(status_code=400, detail=f"Năm sinh phải từ 1940 đến {current_year - 16}")

    if not profile.contact.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập email hoặc số điện thoại")

    if not profile.consent_given:
        raise HTTPException(status_code=400, detail="Bạn cần đồng ý điều khoản bảo mật trước khi tiếp tục")

    # Auto detect contact type
    contact_type = _detect_contact_type(profile.contact)
    if contact_type == "phone" and not _validate_phone(profile.contact):
        raise HTTPException(status_code=400, detail="Số điện thoại không hợp lệ (bắt đầu bằng 0, 9-11 chữ số)")
    if contact_type == "email" and not _validate_email(profile.contact):
        raise HTTPException(status_code=400, detail="Email không hợp lệ")

    # Generate IDs
    profile_id = str(uuid.uuid4())[:12]
    session_id = profile.session_id or f"session_{uuid.uuid4().hex[:16]}"
    created_at = datetime.now(timezone.utc).isoformat()

    record = {
        "profile_id": profile_id,
        "session_id": session_id,
        "full_name": profile.full_name.strip(),
        "birth_year": profile.birth_year,
        "education_level": profile.education_level,
        "education_detail": profile.education_detail.strip(),
        "contact": profile.contact.strip(),
        "contact_type": contact_type,
        "consent_given": True,
        "created_at": created_at,
    }

    # Save to JSON
    _ensure_data_files()
    try:
        with open(GUESTS_JSON, "r", encoding="utf-8") as f:
            guests = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        guests = []

    guests.append(record)
    with open(GUESTS_JSON, "w", encoding="utf-8") as f:
        json.dump(guests, f, ensure_ascii=False, indent=2)

    # Save to CSV
    with open(GUESTS_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            record["profile_id"], record["session_id"], record["full_name"],
            record["birth_year"], record["education_level"],
            record["education_detail"], record["contact"],
            record["contact_type"], record["consent_given"], record["created_at"],
        ])

    # Store in memory service
    session = memory_service.get_or_create_session(session_id)
    session["context"]["guest_profile"] = record
    session["context"]["user_name"] = record["full_name"]

    # Create CRM lead for scoring pipeline
    try:
        lead_id = crm_service.create_lead(session_id, record)
        session["context"]["lead_id"] = lead_id
    except Exception as e:
        logger.error(f"[crm] Failed to create lead: {e}")

    logger.info(f"[guest] registered: {record['full_name']} ({contact_type}) → session {session_id[:12]}")

    return GuestProfileResponse(
        success=True,
        session_id=session_id,
        message=f"Chào mừng {record['full_name']}! Bạn có thể bắt đầu chat với Cô Thắm.",
        profile_id=profile_id,
    )
