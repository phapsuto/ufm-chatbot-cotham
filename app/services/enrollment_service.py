"""app/services/enrollment_service.py — Thu thập hồ sơ nhập học qua chat"""
import json
import os
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ufm-chatbot")

DATA_DIR = "data/enrollments"

ENROLLMENT_FIELDS = {
    "step_1_personal": {
        "title": "Thông tin cá nhân",
        "fields": [
            {"key": "ho_ten", "label": "Họ và tên đầy đủ", "required": True},
            {"key": "ngay_sinh", "label": "Ngày tháng năm sinh", "required": True, "format": "DD/MM/YYYY"},
            {"key": "gioi_tinh", "label": "Giới tính", "required": True, "options": ["Nam", "Nữ", "Khác"]},
            {"key": "cmnd_cccd", "label": "Số CMND/CCCD", "required": True},
            {"key": "dia_chi", "label": "Địa chỉ thường trú", "required": True},
            {"key": "email", "label": "Email", "required": True},
            {"key": "sdt", "label": "Số điện thoại", "required": True},
        ],
    },
    "step_2_education": {
        "title": "Thông tin học vấn",
        "fields": [
            {"key": "truong_dai_hoc", "label": "Trường đại học đã tốt nghiệp", "required": True},
            {"key": "nganh_hoc", "label": "Ngành học", "required": True},
            {"key": "nam_tot_nghiep", "label": "Năm tốt nghiệp", "required": True},
            {"key": "xep_loai", "label": "Xếp loại tốt nghiệp", "required": True,
             "options": ["Xuất sắc", "Giỏi", "Khá", "Trung bình khá", "Trung bình"]},
            {"key": "nganh_dang_ky", "label": "Ngành thạc sĩ/tiến sĩ muốn đăng ký", "required": True},
            {"key": "bac_hoc", "label": "Bậc học đăng ký", "required": True, "options": ["Thạc sĩ", "Tiến sĩ"]},
        ],
    },
    "step_3_documents": {
        "title": "Hồ sơ giấy tờ",
        "description": "Upload các file scan/ảnh chụp rõ nét (PDF, JPG, PNG, tối đa 10MB/file)",
        "documents": [
            {"key": "bang_tot_nghiep", "label": "Bằng tốt nghiệp đại học (bản sao)", "required": True},
            {"key": "bang_diem", "label": "Bảng điểm toàn khóa (bản sao)", "required": True},
            {"key": "cmnd_cccd_scan", "label": "CMND/CCCD (bản sao 2 mặt)", "required": True},
            {"key": "anh_the", "label": "Ảnh thẻ 3x4 hoặc 4x6 (file ảnh)", "required": True},
            {"key": "chung_chi_ngoai_ngu", "label": "Chứng chỉ ngoại ngữ nếu có (IELTS, TOEIC...)", "required": False},
            {"key": "minh_chung_kinh_nghiem", "label": "Minh chứng kinh nghiệm làm việc nếu có", "required": False},
        ],
    },
}

VALID_DOC_KEYS = {d["key"] for d in ENROLLMENT_FIELDS["step_3_documents"]["documents"]}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _enrollment_dir(enrollment_id: str) -> str:
    return os.path.join(DATA_DIR, enrollment_id)


def _info_path(enrollment_id: str) -> str:
    return os.path.join(_enrollment_dir(enrollment_id), "info.json")


def _load_info(enrollment_id: str) -> dict | None:
    path = _info_path(enrollment_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_info(enrollment_id: str, info: dict):
    path = _info_path(enrollment_id)
    info["updated_at"] = datetime.now(timezone.utc).isoformat()
    info["completion_percent"] = _calc_completion(info)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)


def _calc_completion(info: dict) -> int:
    total = 0
    filled = 0

    # Step 1 fields
    for field in ENROLLMENT_FIELDS["step_1_personal"]["fields"]:
        if field["required"]:
            total += 1
            if info.get("step_1_personal", {}).get(field["key"]):
                filled += 1

    # Step 2 fields
    for field in ENROLLMENT_FIELDS["step_2_education"]["fields"]:
        if field["required"]:
            total += 1
            if info.get("step_2_education", {}).get(field["key"]):
                filled += 1

    # Step 3 docs
    for doc in ENROLLMENT_FIELDS["step_3_documents"]["documents"]:
        if doc["required"]:
            total += 1
            if info.get("step_3_documents", {}).get(doc["key"]):
                filled += 1

    return int((filled / max(total, 1)) * 100)


def get_enrollment_by_session(session_id: str) -> dict | None:
    """Tìm enrollment theo session_id."""
    if not os.path.exists(DATA_DIR):
        return None
    for eid in os.listdir(DATA_DIR):
        info = _load_info(eid)
        if info and info.get("session_id") == session_id:
            return info
    return None


def create_enrollment(session_id: str, profile_id: str) -> str:
    """Tạo enrollment mới."""
    enrollment_id = f"enroll_{uuid.uuid4().hex[:10]}"
    edir = _enrollment_dir(enrollment_id)
    os.makedirs(edir, exist_ok=True)
    os.makedirs(os.path.join(edir, "documents"), exist_ok=True)

    info = {
        "enrollment_id": enrollment_id,
        "profile_id": profile_id,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": "",
        "status": "in_progress",
        "step_1_personal": {},
        "step_2_education": {},
        "step_3_documents": {},
        "completion_percent": 0,
    }
    _save_info(enrollment_id, info)
    logger.info(f"[enrollment] created {enrollment_id} for session {session_id[:12]}")
    return enrollment_id


def update_enrollment_step(enrollment_id: str, step: int, data: dict) -> tuple[bool, str]:
    """Cập nhật thông tin 1 bước. Return (success, error_msg)."""
    info = _load_info(enrollment_id)
    if not info:
        return False, "Enrollment không tồn tại"

    step_key = f"step_{step}_personal" if step == 1 else f"step_{step}_education"
    fields_def = ENROLLMENT_FIELDS.get(step_key)
    if not fields_def:
        return False, f"Bước {step} không hợp lệ"

    # Validate required fields
    for field in fields_def["fields"]:
        if field["required"] and not data.get(field["key"], "").strip():
            return False, f"Thiếu thông tin bắt buộc: {field['label']}"

    info[step_key] = data
    _save_info(enrollment_id, info)
    logger.info(f"[enrollment] step {step} updated for {enrollment_id}")
    return True, ""


def save_document(enrollment_id: str, doc_key: str, file_bytes: bytes, filename: str, content_type: str) -> tuple[bool, str]:
    """Lưu file giấy tờ. Return (success, file_path_or_error)."""
    if doc_key not in VALID_DOC_KEYS:
        return False, f"Loại giấy tờ '{doc_key}' không hợp lệ"

    if content_type not in ALLOWED_CONTENT_TYPES:
        return False, f"Định dạng file không được hỗ trợ. Chỉ chấp nhận: PDF, JPG, PNG"

    if len(file_bytes) > MAX_FILE_SIZE:
        return False, f"File quá lớn ({len(file_bytes)/(1024*1024):.1f}MB). Tối đa 10MB"

    info = _load_info(enrollment_id)
    if not info:
        return False, "Enrollment không tồn tại"

    # Save file
    doc_dir = os.path.join(_enrollment_dir(enrollment_id), "documents", doc_key)
    os.makedirs(doc_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = filename.replace(" ", "_")
    save_name = f"{doc_key}_{ts}_{safe_name}"
    file_path = os.path.join(doc_dir, save_name)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Update info
    if "step_3_documents" not in info:
        info["step_3_documents"] = {}
    info["step_3_documents"][doc_key] = {
        "filename": save_name,
        "original_name": filename,
        "path": file_path,
        "content_type": content_type,
        "size_bytes": len(file_bytes),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_info(enrollment_id, info)
    logger.info(f"[enrollment] doc '{doc_key}' saved for {enrollment_id}: {save_name}")
    return True, file_path


def submit_enrollment(enrollment_id: str) -> tuple[bool, str]:
    """Submit hồ sơ - kiểm tra đủ required fields/docs."""
    info = _load_info(enrollment_id)
    if not info:
        return False, "Enrollment không tồn tại"

    missing = []

    # Check step 1
    for field in ENROLLMENT_FIELDS["step_1_personal"]["fields"]:
        if field["required"] and not info.get("step_1_personal", {}).get(field["key"]):
            missing.append(f"Bước 1: {field['label']}")

    # Check step 2
    for field in ENROLLMENT_FIELDS["step_2_education"]["fields"]:
        if field["required"] and not info.get("step_2_education", {}).get(field["key"]):
            missing.append(f"Bước 2: {field['label']}")

    # Check step 3 docs
    for doc in ENROLLMENT_FIELDS["step_3_documents"]["documents"]:
        if doc["required"] and not info.get("step_3_documents", {}).get(doc["key"]):
            missing.append(f"Bước 3: {doc['label']}")

    if missing:
        return False, "Thiếu thông tin: " + "; ".join(missing[:3])

    info["status"] = "submitted"
    _save_info(enrollment_id, info)
    logger.info(f"[enrollment] SUBMITTED {enrollment_id} (completion={info['completion_percent']}%)")
    return True, ""


def get_enrollment_status(enrollment_id: str) -> dict | None:
    info = _load_info(enrollment_id)
    if not info:
        return None
    return {
        "enrollment_id": info["enrollment_id"],
        "status": info["status"],
        "completion_percent": info["completion_percent"],
        "step_1_done": bool(info.get("step_1_personal")),
        "step_2_done": bool(info.get("step_2_education")),
        "step_3_count": sum(1 for v in info.get("step_3_documents", {}).values() if isinstance(v, dict)),
    }


def get_fields_definition() -> dict:
    """Return fields definition cho frontend rendering."""
    return ENROLLMENT_FIELDS
