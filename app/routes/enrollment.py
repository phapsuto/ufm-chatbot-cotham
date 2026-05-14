"""app/routes/enrollment.py — Endpoints thu thập hồ sơ nhập học"""
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.models import EnrollmentStartRequest, EnrollmentSubmitRequest
from app.services import enrollment_service, memory_service

logger = logging.getLogger("ufm-chatbot")
router = APIRouter()


@router.post("/enrollment/start")
async def start_enrollment(req: EnrollmentStartRequest):
    """Tạo enrollment mới cho session."""
    session = memory_service.get_or_create_session(req.session_id)
    profile = session["context"].get("guest_profile")
    if not profile:
        raise HTTPException(status_code=400, detail="Chưa đăng ký thông tin. Vui lòng hoàn tất onboarding trước.")

    # Check if already has enrollment
    existing = enrollment_service.get_enrollment_by_session(req.session_id)
    if existing:
        return {
            "success": True,
            "enrollment_id": existing["enrollment_id"],
            "message": "Bạn đã có hồ sơ đăng ký. Tiếp tục điền thông tin.",
            "status": existing["status"],
            "completion_percent": existing["completion_percent"],
        }

    profile_id = profile.get("profile_id", "")
    enrollment_id = enrollment_service.create_enrollment(req.session_id, profile_id)

    return {
        "success": True,
        "enrollment_id": enrollment_id,
        "message": "Đã tạo hồ sơ đăng ký mới.",
        "fields": enrollment_service.get_fields_definition(),
    }


@router.post("/enrollment/info")
async def update_enrollment_info(
    enrollment_id: str = Form(...),
    step: int = Form(...),
    data: str = Form(...),
):
    """Cập nhật thông tin text cho bước 1 hoặc 2."""
    import json
    try:
        parsed_data = json.loads(data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Dữ liệu không hợp lệ")

    if step not in (1, 2):
        raise HTTPException(status_code=400, detail="Bước phải là 1 hoặc 2")

    success, error = enrollment_service.update_enrollment_step(enrollment_id, step, parsed_data)
    if not success:
        raise HTTPException(status_code=400, detail=error)

    status = enrollment_service.get_enrollment_status(enrollment_id)
    return {
        "success": True,
        "message": f"Đã lưu thông tin bước {step}",
        "completion_percent": status["completion_percent"] if status else 0,
    }


@router.post("/enrollment/upload")
async def upload_document(
    enrollment_id: str = Form(...),
    doc_key: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload giấy tờ cho hồ sơ."""
    # Read file bytes
    file_bytes = await file.read()

    success, result = enrollment_service.save_document(
        enrollment_id=enrollment_id,
        doc_key=doc_key,
        file_bytes=file_bytes,
        filename=file.filename or "unknown",
        content_type=file.content_type or "",
    )

    if not success:
        raise HTTPException(status_code=400, detail=result)

    status = enrollment_service.get_enrollment_status(enrollment_id)
    return {
        "success": True,
        "message": f"Đã upload {file.filename}",
        "file_path": result,
        "completion_percent": status["completion_percent"] if status else 0,
    }


@router.post("/enrollment/submit")
async def submit_enrollment(req: EnrollmentSubmitRequest):
    """Submit hồ sơ hoàn chỉnh."""
    success, error = enrollment_service.submit_enrollment(req.enrollment_id)
    if not success:
        raise HTTPException(status_code=400, detail=error)

    return {
        "success": True,
        "message": "Hồ sơ đã được nộp thành công! Bộ phận tuyển sinh UFM sẽ kiểm tra và liên hệ lại trong vòng 2-3 ngày làm việc.",
    }


@router.get("/enrollment/status/{enrollment_id}")
async def get_enrollment_status(enrollment_id: str):
    """Lấy trạng thái hồ sơ."""
    status = enrollment_service.get_enrollment_status(enrollment_id)
    if not status:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ")
    return status


@router.get("/enrollment/fields")
async def get_enrollment_fields():
    """Lấy cấu trúc fields để frontend render form."""
    return enrollment_service.get_fields_definition()
