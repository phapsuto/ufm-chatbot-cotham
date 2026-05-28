"""app/services/scoring_engine.py — AI Lead Scoring Engine (v4)"""
import math
import re
from datetime import datetime

# ── Ngành keywords for detection ──
NGANH_KEYWORDS = {
    "tai_chinh_ngan_hang": ["tài chính", "ngân hàng", "finance", "banking", "tcnh"],
    "quan_tri_kinh_doanh": ["quản trị", "kinh doanh", "mba", "qtkd", "business"],
    "ke_toan": ["kế toán", "accounting", "kiểm toán"],
    "kinh_te_hoc": ["kinh tế học", "economics", "kinh tế"],
    "quan_ly_kinh_te": ["quản lý kinh tế", "economic management"],
    "luat_kinh_te": ["luật kinh tế", "luật", "pháp luật", "law"],
    "kinh_doanh_quoc_te": ["kinh doanh quốc tế", "international business", "xuất nhập khẩu"],
    "marketing": ["marketing", "tiếp thị", "truyền thông"],
    "toan_kinh_te": ["toán kinh tế", "quantitative"],
}

NGANH_LABELS = {
    "tai_chinh_ngan_hang": "Tài chính - Ngân hàng",
    "quan_tri_kinh_doanh": "Quản trị kinh doanh",
    "ke_toan": "Kế toán",
    "kinh_te_hoc": "Kinh tế học",
    "quan_ly_kinh_te": "Quản lý kinh tế",
    "luat_kinh_te": "Luật kinh tế",
    "kinh_doanh_quoc_te": "Kinh doanh quốc tế",
    "marketing": "Marketing",
    "toan_kinh_te": "Toán kinh tế",
}

# ── Intent to behavior mapping ──
INTENT_BEHAVIOR_MAP = {
    "hoc_phi": "da_hoi_hoc_phi",
    "dieu_kien_dau_vao": "da_hoi_dieu_kien",
    "lich_hoc": "da_hoi_lich_hoc",
    "ho_so_tuyen_sinh": "da_hoi_ho_so",
    "lam_ho_so_nhap_hoc": "da_hoi_ho_so",
    "deadline": "da_hoi_deadline",
    "lien_he": "da_yeu_cau_lien_he",
    "ket_noi_tu_van_vien": "da_yeu_cau_lien_he",
}

URGENCY_KEYWORDS = ["kỳ này", "tháng này", "sắp", "gần đây", "ngay bây giờ", "gấp",
                     "tới", "tháng tới", "đợt này", "năm nay", "kỳ tuyển sinh"]

EXPERIENCE_PATTERN = re.compile(
    r'(\d+)\s*năm\s*(kinh nghiệm|kinh nghi|làm việc|công tác|đi làm)',
    re.IGNORECASE
)


def detect_nganh(text: str) -> list[str]:
    """Detect ngành names from message text."""
    text_lower = text.lower()
    found = []
    for nganh_key, keywords in NGANH_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                label = NGANH_LABELS[nganh_key]
                if label not in found:
                    found.append(label)
                break
    return found


def detect_urgency(text: str) -> str:
    """Detect urgency level from message."""
    text_lower = text.lower()
    for kw in URGENCY_KEYWORDS:
        if kw in text_lower:
            return "cao"
    return ""


def detect_experience(text: str) -> tuple[bool, int]:
    """Detect work experience mention. Returns (has_exp, years)."""
    match = EXPERIENCE_PATTERN.search(text)
    if match:
        return True, int(match.group(1))
    exp_keywords = ["đi làm", "công ty", "kinh nghiệm", "doanh nghiệp", "làm việc tại"]
    text_lower = text.lower()
    for kw in exp_keywords:
        if kw in text_lower:
            return True, 0
    return False, 0


def classify_question(message: str, intent: str) -> str:
    """Classify if question is specific or general."""
    specific_intents = {"hoc_phi", "dieu_kien_dau_vao", "lich_hoc", "ho_so_tuyen_sinh",
                        "deadline", "lam_ho_so_nhap_hoc"}
    if intent in specific_intents:
        return "specific"
    specific_keywords = ["bao nhiêu", "điều kiện", "hồ sơ", "lịch", "khi nào", "ở đâu",
                         "ai dạy", "bao lâu", "mấy tín", "chỉ tiêu"]
    if any(kw in message.lower() for kw in specific_keywords):
        return "specific"
    return "general"


def calculate_lead_score(lead: dict) -> dict:
    """
    Calculate lead score (0-100) with detailed breakdown.
    Returns score dict with breakdown, grade, probability.
    """
    profile_details = []
    engagement_details = []
    action_details = []
    profile_pts = 0
    engagement_pts = 0
    action_pts = 0

    # ══ PROFILE (max 25) ══
    if lead.get("trinh_do") in ("dai_hoc", "sau_dai_hoc"):
        profile_pts += 10
        profile_details.append({"diem": 10, "ly_do": "Trình độ phù hợp"})

    detail = (lead.get("chi_tiet_trinh_do") or "").lower()
    related = ["tài chính", "kinh tế", "kế toán", "quản trị", "marketing",
               "kinh doanh", "luật", "ngân hàng", "ufm"]
    if any(kw in detail for kw in related):
        profile_pts += 8
        profile_details.append({"diem": 8, "ly_do": "Ngành tốt nghiệp liên quan UFM"})

    age = datetime.now().year - lead.get("nam_sinh", 2000)
    if 22 <= age <= 45:
        profile_pts += 4
        profile_details.append({"diem": 4, "ly_do": f"Độ tuổi phù hợp ({age} tuổi)"})

    if lead.get("co_kinh_nghiem_lam_viec"):
        profile_pts += 3
        profile_details.append({"diem": 3, "ly_do": "Có kinh nghiệm làm việc"})

    profile_pts = min(profile_pts, 25)

    # ══ ENGAGEMENT (max 40) ══
    if lead.get("da_hoi_hoc_phi"):
        engagement_pts += 15
        engagement_details.append({"diem": 15, "ly_do": "Hỏi về học phí"})

    if lead.get("da_hoi_dieu_kien"):
        engagement_pts += 10
        engagement_details.append({"diem": 10, "ly_do": "Hỏi điều kiện đầu vào"})

    if lead.get("da_hoi_lich_hoc"):
        engagement_pts += 8
        engagement_details.append({"diem": 8, "ly_do": "Hỏi lịch học/hình thức"})

    if lead.get("da_hoi_ho_so"):
        engagement_pts += 8
        engagement_details.append({"diem": 8, "ly_do": "Hỏi hồ sơ đăng ký"})

    if lead.get("da_hoi_deadline"):
        engagement_pts += 7
        engagement_details.append({"diem": 7, "ly_do": "Hỏi deadline nộp hồ sơ"})

    if lead.get("da_yeu_cau_lien_he"):
        engagement_pts += 10
        engagement_details.append({"diem": 10, "ly_do": "Yêu cầu liên hệ trường"})

    if len(lead.get("nganh_hoi_toi", [])) >= 2:
        engagement_pts += 5
        engagement_details.append({"diem": 5, "ly_do": "Hỏi về 2+ ngành"})

    if lead.get("so_cau_hoi_cu_the", 0) >= 5:
        engagement_pts += 6
        engagement_details.append({"diem": 6, "ly_do": "Nhiều câu hỏi cụ thể (≥5)"})

    if lead.get("thoi_gian_chat_phut", 0) >= 10:
        engagement_pts += 4
        engagement_details.append({"diem": 4, "ly_do": "Chat > 10 phút"})

    if lead.get("so_tin_nhan", 0) >= 8:
        engagement_pts += 3
        engagement_details.append({"diem": 3, "ly_do": "Gửi 8+ tin nhắn"})

    engagement_pts = min(engagement_pts, 40)

    # ══ ACTION (max 35) ══
    if lead.get("da_nop_ho_so"):
        action_pts += 35
        action_details.append({"diem": 35, "ly_do": "Đã nộp hồ sơ đăng ký"})
    elif lead.get("ho_so_hoan_thanh_phan_tram", 0) >= 80:
        action_pts += 28
        action_details.append({"diem": 28, "ly_do": "Hồ sơ hoàn thành > 80%"})
    elif lead.get("ho_so_hoan_thanh_phan_tram", 0) >= 50:
        action_pts += 20
        action_details.append({"diem": 20, "ly_do": "Hồ sơ 50-79%"})
    elif lead.get("da_bat_dau_lam_ho_so"):
        action_pts += 12
        action_details.append({"diem": 12, "ly_do": "Đã bắt đầu làm hồ sơ"})

    if lead.get("muc_do_khan_cap") == "cao":
        action_pts += 10
        action_details.append({"diem": 10, "ly_do": "Mức độ khẩn cấp cao"})

    if lead.get("so_session", 1) >= 2:
        action_pts += 8
        action_details.append({"diem": 8, "ly_do": "Quay lại chat nhiều lần"})

    action_pts = min(action_pts, 35)

    total = min(profile_pts + engagement_pts + action_pts, 100)

    # Logistic probability
    probability = 1 / (1 + math.exp(-0.1 * (total - 55)))
    probability = round(min(max(probability, 0.02), 0.97), 3)

    # Grade
    if total >= 75:
        grade, label = "A", "🔥 Tiềm năng cao"
        rec_status, rec_priority = "hot_lead", "high"
    elif total >= 55:
        grade, label = "B", "⭐ Quan tâm"
        rec_status, rec_priority = "interested", "high"
    elif total >= 35:
        grade, label = "C", "💡 Cần theo dõi"
        rec_status, rec_priority = "follow_up", "normal"
    else:
        grade, label = "D", "❄️ Mới tiếp cận"
        rec_status, rec_priority = "new", "low"

    return {
        "lead_score": total,
        "lead_grade": grade,
        "enrollment_probability": probability,
        "enrollment_probability_pct": f"{round(probability * 100)}%",
        "score_breakdown": {
            "profile": {"diem": profile_pts, "toi_da": 25, "chi_tiet": profile_details},
            "engagement": {"diem": engagement_pts, "toi_da": 40, "chi_tiet": engagement_details},
            "action": {"diem": action_pts, "toi_da": 35, "chi_tiet": action_details},
        },
        "recommended_status": rec_status,
        "recommended_priority": rec_priority,
        "label": label,
        "score_updated_at": datetime.now().isoformat(),
    }
