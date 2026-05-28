"""app/services/crm_service.py — CRM Data Layer + Lead Management (v4)"""
import csv
import io
import json
import os
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.services import scoring_engine

logger = logging.getLogger("ufm-chatbot")

CRM_DIR = "data/crm"
LEADS_FILE = os.path.join(CRM_DIR, "leads.json")
ACTIVITY_LOG = os.path.join(CRM_DIR, "activity_log.jsonl")


def _ensure_dirs():
    os.makedirs(CRM_DIR, exist_ok=True)


def _load_leads() -> list[dict]:
    _ensure_dirs()
    if not os.path.exists(LEADS_FILE):
        return []
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_leads(leads: list[dict]):
    _ensure_dirs()
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2, default=str)


def _log_activity(action: str, lead_id: str, data: dict = None):
    _ensure_dirs()
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
             "lead_id": lead_id, "data": data or {}}
    try:
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _new_lead_template() -> dict:
    return {
        "lead_id": "", "session_id": "", "profile_id": "",
        "created_at": "", "updated_at": "",
        "ho_ten": "", "nam_sinh": 0, "tuoi": 0,
        "trinh_do": "", "chi_tiet_trinh_do": "",
        "contact": "", "contact_type": "",
        "so_tin_nhan": 0, "thoi_gian_chat_phut": 0,
        "thoi_gian_bat_dau": "", "thoi_gian_ket_thuc": "",
        "so_session": 1, "nganh_hoi_toi": [], "chu_de_hoi": [],
        "da_hoi_hoc_phi": False, "da_hoi_dieu_kien": False,
        "da_hoi_lich_hoc": False, "da_hoi_ho_so": False,
        "da_hoi_deadline": False, "da_yeu_cau_lien_he": False,
        "da_bat_dau_lam_ho_so": False, "ho_so_hoan_thanh_phan_tram": 0,
        "da_nop_ho_so": False,
        "so_cau_hoi_cu_the": 0, "so_cau_hoi_chung": 0,
        "co_kinh_nghiem_lam_viec": False, "so_nam_kinh_nghiem": 0,
        "nguon_biet_den_ufm": "", "muc_do_khan_cap": "",
        "chat_history_summary": "",
        "lead_score": 0, "lead_grade": "D", "enrollment_probability": 0.0,
        "enrollment_probability_pct": "0%", "score_breakdown": {},
        "score_updated_at": "",
        "status": "new", "priority": "normal", "assigned_to": "",
        "notes": [], "follow_up_date": "", "follow_up_done": False,
        "tags": [], "last_contacted": "",
        "nhan_xet_ngan": "", "goi_y_follow_up": "", "rao_can": "",
    }


# ═══════════════════════════════════
# CORE METHODS
# ═══════════════════════════════════

def create_lead(session_id: str, guest_profile: dict) -> str:
    """Create a new CRM lead from onboarding data. Returns lead_id."""
    leads = _load_leads()

    # Check if lead already exists for this session
    for lead in leads:
        if lead["session_id"] == session_id:
            return lead["lead_id"]

    now = datetime.now(timezone.utc).isoformat()
    lead = _new_lead_template()
    lead_id = f"lead_{uuid.uuid4().hex[:10]}"

    birth_year = guest_profile.get("birth_year", 0)
    lead.update({
        "lead_id": lead_id,
        "session_id": session_id,
        "profile_id": guest_profile.get("profile_id", ""),
        "created_at": now,
        "updated_at": now,
        "ho_ten": guest_profile.get("full_name", ""),
        "nam_sinh": birth_year,
        "tuoi": datetime.now().year - birth_year if birth_year else 0,
        "trinh_do": guest_profile.get("education_level", ""),
        "chi_tiet_trinh_do": guest_profile.get("education_detail", ""),
        "contact": guest_profile.get("contact", ""),
        "contact_type": guest_profile.get("contact_type", ""),
        "thoi_gian_bat_dau": now,
    })

    # Initial score
    score_result = scoring_engine.calculate_lead_score(lead)
    lead.update({
        "lead_score": score_result["lead_score"],
        "lead_grade": score_result["lead_grade"],
        "enrollment_probability": score_result["enrollment_probability"],
        "enrollment_probability_pct": score_result["enrollment_probability_pct"],
        "score_breakdown": score_result["score_breakdown"],
        "score_updated_at": score_result["score_updated_at"],
    })

    leads.append(lead)
    _save_leads(leads)
    _log_activity("create_lead", lead_id, {"ho_ten": lead["ho_ten"], "session_id": session_id})
    logger.info(f"[crm] Lead created: {lead_id} — {lead['ho_ten']} (score={lead['lead_score']})")
    return lead_id


def update_chat_behavior(session_id: str, message: str, intent: str):
    """Update lead behavior after each chat message. Auto re-scores."""
    leads = _load_leads()
    lead = None
    idx = -1
    for i, l in enumerate(leads):
        if l["session_id"] == session_id:
            lead = l
            idx = i
            break
    if lead is None:
        return

    now = datetime.now(timezone.utc).isoformat()
    lead["so_tin_nhan"] = lead.get("so_tin_nhan", 0) + 1
    lead["updated_at"] = now
    lead["thoi_gian_ket_thuc"] = now

    # Calculate chat duration
    try:
        start = datetime.fromisoformat(lead["thoi_gian_bat_dau"])
        end = datetime.fromisoformat(now)
        lead["thoi_gian_chat_phut"] = max(int((end - start).total_seconds() / 60), 1)
    except Exception:
        pass

    # Map intent to behavior flags
    behavior_flag = scoring_engine.INTENT_BEHAVIOR_MAP.get(intent)
    if behavior_flag and not lead.get(behavior_flag):
        lead[behavior_flag] = True

    # Also detect from message keywords (backup — intent detection may miss)
    msg_lower = message.lower()
    kw_behavior = {
        "da_hoi_hoc_phi": ["học phí", "hoc phi", "bao nhiêu tiền", "chi phí", "học bổng"],
        "da_hoi_dieu_kien": ["điều kiện", "yêu cầu", "đầu vào", "toeic", "ielts"],
        "da_hoi_lich_hoc": ["lịch học", "khai giảng", "thời khóa biểu", "hình thức học"],
        "da_hoi_ho_so": ["hồ sơ", "giấy tờ", "thủ tục", "cần gì", "nộp đơn"],
        "da_hoi_deadline": ["hạn nộp", "deadline", "khi nào hết hạn", "đợt tuyển", "thời hạn"],
        "da_yeu_cau_lien_he": ["liên hệ", "số điện thoại", "email trường", "gặp ai"],
    }
    for flag, keywords in kw_behavior.items():
        if not lead.get(flag):
            if any(kw in msg_lower for kw in keywords):
                lead[flag] = True

    # Track topics
    if intent and intent not in lead.get("chu_de_hoi", []):
        lead.setdefault("chu_de_hoi", []).append(intent)

    # Detect ngành
    nganh_found = scoring_engine.detect_nganh(message)
    for n in nganh_found:
        if n not in lead.get("nganh_hoi_toi", []):
            lead.setdefault("nganh_hoi_toi", []).append(n)

    # Detect urgency
    urgency = scoring_engine.detect_urgency(message)
    if urgency:
        lead["muc_do_khan_cap"] = urgency

    # Detect experience
    has_exp, years = scoring_engine.detect_experience(message)
    if has_exp:
        lead["co_kinh_nghiem_lam_viec"] = True
        if years > 0:
            lead["so_nam_kinh_nghiem"] = max(lead.get("so_nam_kinh_nghiem", 0), years)

    # Classify question
    q_type = scoring_engine.classify_question(message, intent)
    if q_type == "specific":
        lead["so_cau_hoi_cu_the"] = lead.get("so_cau_hoi_cu_the", 0) + 1
    else:
        lead["so_cau_hoi_chung"] = lead.get("so_cau_hoi_chung", 0) + 1

    # Re-score
    score_result = scoring_engine.calculate_lead_score(lead)
    old_score = lead.get("lead_score", 0)
    lead.update({
        "lead_score": score_result["lead_score"],
        "lead_grade": score_result["lead_grade"],
        "enrollment_probability": score_result["enrollment_probability"],
        "enrollment_probability_pct": score_result["enrollment_probability_pct"],
        "score_breakdown": score_result["score_breakdown"],
        "score_updated_at": score_result["score_updated_at"],
    })

    # Auto-upgrade status if score crosses threshold
    if lead["status"] == "new" and score_result["lead_score"] >= 35:
        lead["status"] = score_result["recommended_status"]
        lead["priority"] = score_result["recommended_priority"]

    leads[idx] = lead
    _save_leads(leads)

    if score_result["lead_score"] != old_score:
        logger.info(f"[crm] Score update: {lead['ho_ten']} {old_score}→{score_result['lead_score']} ({score_result['lead_grade']})")


def update_enrollment_progress(session_id: str, pct: int, submitted: bool):
    """Update enrollment form progress."""
    leads = _load_leads()
    for i, lead in enumerate(leads):
        if lead["session_id"] == session_id:
            lead["da_bat_dau_lam_ho_so"] = True
            lead["ho_so_hoan_thanh_phan_tram"] = pct
            lead["da_nop_ho_so"] = submitted
            lead["updated_at"] = datetime.now(timezone.utc).isoformat()
            # Re-score
            sr = scoring_engine.calculate_lead_score(lead)
            lead.update({k: sr[k] for k in ["lead_score", "lead_grade",
                         "enrollment_probability", "enrollment_probability_pct",
                         "score_breakdown", "score_updated_at"]})
            if submitted:
                lead["status"] = "enrolled"
                lead["priority"] = "high"
            leads[i] = lead
            _save_leads(leads)
            _log_activity("enrollment_update", lead["lead_id"],
                          {"pct": pct, "submitted": submitted, "score": lead["lead_score"]})
            return
    

def update_llm_analysis(session_id: str, analysis: dict):
    """Merge LLM analysis into lead record."""
    leads = _load_leads()
    for i, lead in enumerate(leads):
        if lead["session_id"] == session_id:
            if analysis.get("muc_do_khan_cap"):
                lead["muc_do_khan_cap"] = analysis["muc_do_khan_cap"]
            if analysis.get("co_kinh_nghiem"):
                lead["co_kinh_nghiem_lam_viec"] = True
            if analysis.get("so_nam_kinh_nghiem"):
                lead["so_nam_kinh_nghiem"] = analysis["so_nam_kinh_nghiem"]
            if analysis.get("nhan_xet_ngan"):
                lead["nhan_xet_ngan"] = analysis["nhan_xet_ngan"]
            if analysis.get("goi_y_follow_up"):
                lead["goi_y_follow_up"] = analysis["goi_y_follow_up"]
            if analysis.get("rao_can"):
                lead["rao_can"] = analysis["rao_can"]
            if analysis.get("nganh_quan_tam_chinh"):
                nganh = analysis["nganh_quan_tam_chinh"]
                if nganh not in lead.get("nganh_hoi_toi", []):
                    lead.setdefault("nganh_hoi_toi", []).append(nganh)
                lead.setdefault("tags", [])
                tag = nganh.lower().replace(" ", "_")
                if tag not in lead["tags"]:
                    lead["tags"].append(tag)
            # Re-score
            sr = scoring_engine.calculate_lead_score(lead)
            lead.update({k: sr[k] for k in ["lead_score", "lead_grade",
                         "enrollment_probability", "enrollment_probability_pct",
                         "score_breakdown", "score_updated_at"]})
            leads[i] = lead
            _save_leads(leads)
            _log_activity("llm_analysis", lead["lead_id"], analysis)
            return


# ═══════════════════════════════════
# QUERY METHODS
# ═══════════════════════════════════

def get_lead_by_session(session_id: str) -> Optional[dict]:
    for lead in _load_leads():
        if lead["session_id"] == session_id:
            return lead
    return None


def get_lead_by_id(lead_id: str) -> Optional[dict]:
    for lead in _load_leads():
        if lead["lead_id"] == lead_id:
            return lead
    return None


def get_all_leads(grade: str = None, status: str = None, nganh: str = None,
                  search: str = None, date_from: str = None, date_to: str = None,
                  page: int = 1, per_page: int = 20) -> dict:
    """Get leads with filters and pagination."""
    leads = _load_leads()

    # Filters
    if grade:
        leads = [l for l in leads if l.get("lead_grade") == grade.upper()]
    if status:
        leads = [l for l in leads if l.get("status") == status]
    if nganh:
        leads = [l for l in leads if nganh.lower() in str(l.get("nganh_hoi_toi", [])).lower()]
    if search:
        s = search.lower()
        leads = [l for l in leads if s in l.get("ho_ten", "").lower()
                 or s in l.get("contact", "").lower()]
    if date_from:
        leads = [l for l in leads if l.get("created_at", "") >= date_from]
    if date_to:
        leads = [l for l in leads if l.get("created_at", "") <= date_to]

    # Sort by score desc
    leads.sort(key=lambda x: x.get("lead_score", 0), reverse=True)

    total = len(leads)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page

    return {"leads": leads[start:start + per_page], "total": total, "page": page, "pages": pages}


# ═══════════════════════════════════
# CRM ACTIONS (staff)
# ═══════════════════════════════════

def update_crm_status(lead_id: str, status: str = None, assigned_to: str = None,
                      follow_up_date: str = None, tags: list = None,
                      priority: str = None) -> bool:
    leads = _load_leads()
    for i, lead in enumerate(leads):
        if lead["lead_id"] == lead_id:
            if status:
                lead["status"] = status
            if assigned_to is not None:
                lead["assigned_to"] = assigned_to
            if follow_up_date is not None:
                lead["follow_up_date"] = follow_up_date
            if tags is not None:
                lead["tags"] = tags
            if priority:
                lead["priority"] = priority
            lead["updated_at"] = datetime.now(timezone.utc).isoformat()
            leads[i] = lead
            _save_leads(leads)
            _log_activity("status_update", lead_id,
                          {"status": status, "assigned_to": assigned_to})
            return True
    return False


def add_note(lead_id: str, author: str, content: str) -> bool:
    leads = _load_leads()
    for i, lead in enumerate(leads):
        if lead["lead_id"] == lead_id:
            lead.setdefault("notes", []).append({
                "author": author, "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            lead["updated_at"] = datetime.now(timezone.utc).isoformat()
            leads[i] = lead
            _save_leads(leads)
            _log_activity("add_note", lead_id, {"author": author})
            return True
    return False


def export_leads_csv(grade: str = None, status: str = None) -> str:
    """Export leads to CSV string."""
    result = get_all_leads(grade=grade, status=status, per_page=10000)
    leads = result["leads"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Họ tên", "Tuổi", "Trình độ", "Liên hệ", "Ngành quan tâm",
                      "Score", "Grade", "Xác suất ĐK", "Số tin nhắn", "Thời gian chat (phút)",
                      "Status", "Priority", "Assigned", "Ghi chú AI", "Ngày tạo"])
    for l in leads:
        writer.writerow([
            l.get("ho_ten"), l.get("tuoi"), l.get("trinh_do"),
            l.get("contact"), ", ".join(l.get("nganh_hoi_toi", [])),
            l.get("lead_score"), l.get("lead_grade"),
            l.get("enrollment_probability_pct"), l.get("so_tin_nhan"),
            l.get("thoi_gian_chat_phut"), l.get("status"),
            l.get("priority"), l.get("assigned_to"),
            l.get("nhan_xet_ngan"), l.get("created_at", "")[:10],
        ])
    return output.getvalue()


def get_dashboard_stats() -> dict:
    """Dashboard KPI summary."""
    leads = _load_leads()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_today = sum(1 for l in leads if l.get("created_at", "")[:10] == today)

    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    status_counts = {}
    nganh_counts = {}

    for l in leads:
        g = l.get("lead_grade", "D")
        grade_counts[g] = grade_counts.get(g, 0) + 1
        s = l.get("status", "new")
        status_counts[s] = status_counts.get(s, 0) + 1
        for n in l.get("nganh_hoi_toi", []):
            nganh_counts[n] = nganh_counts.get(n, 0) + 1

    # Daily leads for last 7 days
    from collections import defaultdict
    daily = defaultdict(int)
    for l in leads:
        day = l.get("created_at", "")[:10]
        if day:
            daily[day] += 1
    daily_sorted = sorted(daily.items())[-7:]

    # Top ngành
    top_nganh = sorted(nganh_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Hot leads needing contact
    hot_uncontacted = [
        {"ho_ten": l["ho_ten"], "lead_score": l["lead_score"],
         "nganh": l.get("nganh_hoi_toi", [])[:2], "contact": l["contact"],
         "thoi_gian_chat_phut": l.get("thoi_gian_chat_phut", 0)}
        for l in leads
        if l.get("lead_grade") == "A" and not l.get("last_contacted")
    ][:5]

    return {
        "total_leads": len(leads),
        "hot_leads": grade_counts.get("A", 0),
        "interested": grade_counts.get("B", 0),
        "enrolled": status_counts.get("enrolled", 0),
        "new_today": new_today,
        "grade_distribution": grade_counts,
        "status_distribution": status_counts,
        "daily_leads": daily_sorted,
        "top_nganh": top_nganh,
        "hot_uncontacted": hot_uncontacted,
    }
