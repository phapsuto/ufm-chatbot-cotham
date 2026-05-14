"""app/routes/handoff.py"""
from fastapi import APIRouter
from app.models import HandoffRequest, HandoffResponse
from app.services import handoff_service, memory_service

router = APIRouter()

@router.post("/api/handoff", response_model=HandoffResponse)
async def handoff(req: HandoffRequest):
    transcript = memory_service.get_conversation_history(req.session_id)
    ok = await handoff_service.save_lead(req, transcript)
    if ok:
        return HandoffResponse(success=True, message="Đăng ký thành công! Khoa Sau Đại học UFM sẽ liên hệ anh/chị sớm nhất ạ 🎓")
    return HandoffResponse(success=False, message="Có lỗi xảy ra, vui lòng thử lại ạ")
