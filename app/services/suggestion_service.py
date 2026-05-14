"""app/services/suggestion_service.py — Gợi ý câu hỏi thông minh theo ngữ cảnh (v3)"""
import logging
from app.services import llm_service

logger = logging.getLogger("ufm-chatbot")

HANDOFF_KEYWORDS = ["tư vấn viên", "nhân viên", "người thật", "gọi lại", "liên hệ trực tiếp", "gặp trực tiếp"]

# Fallback khi LLM không sinh được suggestions
SUGGESTION_FALLBACK = {
    "chuong_trinh_thac_si": [
        "Học phí thạc sĩ khoảng bao nhiêu?",
        "Thời gian học thạc sĩ là bao lâu?",
        "Cần chuẩn bị hồ sơ gì để đăng ký?",
    ],
    "chuong_trinh_tien_si": [
        "Điều kiện đầu vào tiến sĩ như thế nào?",
        "Thời gian học tiến sĩ kéo dài bao lâu?",
        "Học phí tiến sĩ bao nhiêu một năm?",
    ],
    "hoc_phi": [
        "Có học bổng hoặc ưu đãi học phí không?",
        "Được đóng học phí theo từng học kỳ không?",
        "Điều kiện đầu vào chương trình này?",
    ],
    "dieu_kien_dau_vao": [
        "Hồ sơ cần chuẩn bị những gì?",
        "Khi nào có thể nộp hồ sơ?",
        "Học phí cụ thể là bao nhiêu?",
    ],
    "ho_so_tuyen_sinh": [
        "Thời hạn nộp hồ sơ đợt này?",
        "Có thể nộp hồ sơ online không?",
        "Điều kiện tiếng Anh yêu cầu gì?",
    ],
    "lich_hoc_su_kien": [
        "Khai giảng đợt gần nhất khi nào?",
        "Có học vào tối hay cuối tuần không?",
        "Hồ sơ cần chuẩn bị gì?",
    ],
    "luan_van_luan_an": [
        "Quy trình bảo vệ luận văn thế nào?",
        "Thời gian viết luận văn bao lâu?",
        "Có hỗ trợ hướng dẫn luận văn không?",
    ],
    "general": [
        "Trường có những ngành thạc sĩ nào?",
        "Điều kiện đầu vào gồm những gì?",
        "Học phí sau đại học UFM bao nhiêu?",
    ],
}


def generate_contextual_suggestions(
    answer: str,
    query: str,
    intent: str,
    asked_about: list[str],
) -> list[str]:
    """Dùng LLM sinh câu gợi ý phù hợp với nội dung vừa trả lời."""
    try:
        prompt = f"""Dựa vào câu hỏi và câu trả lời dưới đây về chương trình sau đại học UFM, hãy đề xuất đúng 3 câu hỏi tiếp theo mà người dùng có thể muốn hỏi. Các câu phải:
- Liên quan trực tiếp đến nội dung vừa trả lời
- Ngắn gọn, rõ ràng, dưới 12 từ
- Tự nhiên như người hỏi thật
- Khác nhau, không lặp ý
- Không hỏi lại điều vừa được trả lời rồi
- Chỉ về chương trình sau đại học UFM

Câu hỏi người dùng: {query}
Câu trả lời của cô Thắm: {answer[:500]}

Trả về đúng 3 câu, mỗi câu trên một dòng, không đánh số, không thêm gì khác."""

        response = llm_service.get_quick_response(prompt, max_tokens=150)

        # Parse response
        lines = [line.strip().lstrip("0123456789.-) ") for line in response.strip().split("\n") if line.strip()]
        suggestions = [l for l in lines if 5 < len(l) < 60 and "?" in l or len(l) > 10][:3]

        if len(suggestions) >= 2:
            logger.info(f"[suggest] LLM generated {len(suggestions)} suggestions")
            return suggestions[:3]
    except Exception as e:
        logger.warning(f"[suggest] LLM failed, using fallback: {e}")

    # Fallback
    pool = SUGGESTION_FALLBACK.get(intent, SUGGESTION_FALLBACK["general"])
    return pool[:3]


def get_suggestions(intent: str, asked_about: list[str]) -> list[str]:
    """Fallback-only suggestions (dùng khi không cần LLM)."""
    pool = SUGGESTION_FALLBACK.get(intent, SUGGESTION_FALLBACK["general"])
    return pool[:3]


def check_handoff_trigger(query: str) -> bool:
    msg = query.lower()
    return any(kw in msg for kw in HANDOFF_KEYWORDS)
