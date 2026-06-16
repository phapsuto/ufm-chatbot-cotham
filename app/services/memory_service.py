"""app/services/memory_service.py — Bộ nhớ hội thoại + xưng hô + SQLite context persistence"""
import time
import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("ufm-chatbot")

SESSION_TTL = 7200  # 2 giờ
MAX_SESSIONS = 200

# SQLite DB Path cho User Memory
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "user_session_memory.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _init_db():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_context (
                session_id TEXT PRIMARY KEY,
                interested_level TEXT,
                interested_major TEXT,
                asked_about TEXT,
                user_name TEXT,
                pronoun_role TEXT,
                guest_profile TEXT,
                last_active REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[memory] Init database error: {e}")

# Chạy init db
_init_db()

_sessions: dict[str, dict] = {}


def _new_session(session_id: str) -> dict:
    now = time.time()
    return {
        "session_id": session_id,
        "created_at": now,
        "last_active": now,
        "messages": [],
        "context": {
            "interested_level": None,
            "interested_major": None,
            "asked_about": [],
            "user_name": None,
            "pronoun_role": None,
            "guest_profile": None,
        },
    }

def _save_context_to_db(session_id: str, ctx: dict, last_active: float):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO session_context (session_id, interested_level, interested_major, asked_about, user_name, pronoun_role, guest_profile, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                interested_level=excluded.interested_level,
                interested_major=excluded.interested_major,
                asked_about=excluded.asked_about,
                user_name=excluded.user_name,
                pronoun_role=excluded.pronoun_role,
                guest_profile=excluded.guest_profile,
                last_active=excluded.last_active
        """, (
            session_id,
            ctx.get("interested_level"),
            ctx.get("interested_major"),
            json.dumps(ctx.get("asked_about") or []),
            ctx.get("user_name"),
            json.dumps(ctx.get("pronoun_role")),
            json.dumps(ctx.get("guest_profile")),
            last_active
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[memory] Save context error: {e}")

def _load_session_from_db(session_id: str) -> dict | None:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT interested_level, interested_major, asked_about, user_name, pronoun_role, guest_profile, last_active FROM session_context WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
            
        interested_level, interested_major, asked_about_str, user_name, pronoun_role_str, guest_profile_str, last_active = row
        
        # Load messages
        cursor.execute("SELECT role, content, timestamp FROM session_messages WHERE session_id = ? ORDER BY id DESC LIMIT 10", (session_id,))
        msg_rows = cursor.fetchall()
        conn.close()
        
        messages = [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(msg_rows)]
        
        return {
            "session_id": session_id,
            "created_at": last_active,
            "last_active": last_active,
            "messages": messages,
            "context": {
                "interested_level": interested_level,
                "interested_major": interested_major,
                "asked_about": json.loads(asked_about_str) if asked_about_str else [],
                "user_name": user_name,
                "pronoun_role": json.loads(pronoun_role_str) if pronoun_role_str else None,
                "guest_profile": json.loads(guest_profile_str) if guest_profile_str else None,
            }
        }
    except Exception as e:
        logger.error(f"[memory] Load session error: {e}")
        return None

# ═══════════════════════════════════
# HELPER: Lấy tên riêng (chữ cuối)
# ═══════════════════════════════════

def extract_first_name(full_name: str) -> str:
    """Lấy tên riêng (chữ cuối) từ họ tên đầy đủ."""
    parts = full_name.strip().split()
    return parts[-1] if parts else full_name


# ═══════════════════════════════════
# PRONOUN DETECTION
# ═══════════════════════════════════

def detect_pronoun_role(query: str) -> dict:
    q = query.lower().strip()

    senior_patterns = {
        "cô": ["cô đang", "cô muốn", "cô hỏi", "cô cần", "hướng dẫn cô", "cho cô hỏi", "cô quan tâm", "cô tốt nghiệp"],
        "thầy": ["thầy đang", "thầy muốn", "thầy hỏi", "thầy cần", "hướng dẫn thầy", "cho thầy hỏi", "thầy quan tâm", "thầy tốt nghiệp"],
        "chú": ["chú đang", "chú muốn", "chú hỏi", "chú cần", "hướng dẫn chú", "cho chú hỏi", "chú quan tâm", "chú tốt nghiệp"],
        "bác": ["bác đang", "bác muốn", "bác hỏi", "bác cần", "hướng dẫn bác", "cho bác hỏi", "bác quan tâm", "bác tốt nghiệp"]
    }
    for title, patterns in senior_patterns.items():
        if any(p in q for p in patterns) or q.startswith(f"{title} "):
            return {"user_calls_self": title, "co_tham_calls_user": title, "co_tham_xung": "em"}

    em_patterns = [
        "em tốt nghiệp", "em đang", "em muốn", "em học", "em làm",
        "em có", "em cần", "em hỏi", "em đã", "em chưa",
        "cho em hỏi", "em ơi", "dạ em", "thưa cô", "em xin",
        "em quan tâm", "em thấy", "em biết", "em nghĩ", "em dự định",
    ]
    if any(p in q for p in em_patterns) or q.startswith("em "):
        return {"user_calls_self": "em", "co_tham_calls_user": "em", "co_tham_xung": "cô"}

    anh_patterns = [
        "anh muốn", "anh cần", "anh đang", "anh học", "cho anh",
        "anh hỏi", "anh có", "anh đã", "anh ơi", "anh quan tâm",
        "anh tốt nghiệp", "anh làm", "anh dự định", "anh biết",
    ]
    if any(p in q for p in anh_patterns) or q.startswith("anh "):
        return {"user_calls_self": "anh", "co_tham_calls_user": "anh", "co_tham_xung": "em"}

    chi_patterns = [
        "chị muốn", "chị cần", "chị đang", "chị học", "cho chị",
        "chị hỏi", "chị có", "chị đã", "chị ơi", "chị quan tâm",
        "chị tốt nghiệp", "chị làm", "chị dự định", "chị biết",
    ]
    if any(p in q for p in chi_patterns) or q.startswith("chị "):
        return {"user_calls_self": "chị", "co_tham_calls_user": "chị", "co_tham_xung": "em"}

    return {"user_calls_self": None, "co_tham_calls_user": "bạn", "co_tham_xung": "em"}


def _suggest_pronoun_by_age(birth_year: int) -> dict:
    current_year = datetime.now().year
    age = current_year - birth_year

    if age <= 26:
        return {"co_tham_calls_user": "em", "co_tham_xung": "cô"}
    else:
        return {"co_tham_calls_user": "anh/chị", "co_tham_xung": "em"}


# ═══════════════════════════════════
# SESSION MANAGEMENT
# ═══════════════════════════════════

def get_or_create_session(session_id: str) -> dict:
    cleanup_expired_sessions()
    
    if session_id not in _sessions:
        # Thử load từ SQLite DB trước
        saved_session = _load_session_from_db(session_id)
        if saved_session:
            _sessions[session_id] = saved_session
            logger.info(f"[memory] loaded session {session_id[:12]} from SQLite DB")
        else:
            _sessions[session_id] = _new_session(session_id)
            logger.info(f"[memory] new session {session_id[:12]}")
            
    _sessions[session_id]["last_active"] = time.time()
    
    # Save/update SQLite DB
    _save_context_to_db(session_id, _sessions[session_id]["context"], _sessions[session_id]["last_active"])
    
    return _sessions[session_id]


def add_message(session_id: str, role: str, content: str) -> None:
    session = get_or_create_session(session_id)
    now = time.time()
    session["messages"].append({"role": role, "content": content, "timestamp": now})
    if len(session["messages"]) > 10:
        session["messages"] = session["messages"][-10:]
        
    # SQLite save message
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("INSERT INTO session_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)", (session_id, role, content, now))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[memory] Save message error: {e}")


def update_context(session_id: str, intent: str, query: str) -> None:
    session = get_or_create_session(session_id)
    ctx = session["context"]
    msg = query.lower()

    if ctx["pronoun_role"] is None:
        pronoun = detect_pronoun_role(query)
        if pronoun["user_calls_self"] is None and ctx.get("guest_profile"):
            age_suggestion = _suggest_pronoun_by_age(ctx["guest_profile"]["birth_year"])
            pronoun["co_tham_calls_user"] = age_suggestion["co_tham_calls_user"]
            pronoun["co_tham_xung"] = age_suggestion["co_tham_xung"]
        ctx["pronoun_role"] = pronoun
        logger.info(f"[memory] pronoun detected: xưng={pronoun['co_tham_xung']}, gọi={pronoun['co_tham_calls_user']}")

    if "thạc sĩ" in msg or "cao học" in msg:
        ctx["interested_level"] = "thac_si"
    if "tiến sĩ" in msg or "phd" in msg:
        ctx["interested_level"] = "tien_si"

    nganh_map = {
        "tài chính": "Tài chính - Ngân hàng", "ngân hàng": "Tài chính - Ngân hàng",
        "quản trị kinh doanh": "Quản trị kinh doanh", "kế toán": "Kế toán",
        "marketing": "Marketing", "kinh tế học": "Kinh tế học",
        "quản lý kinh tế": "Quản lý kinh tế", "luật": "Luật kinh tế",
        "kinh doanh quốc tế": "Kinh doanh quốc tế", "toán kinh tế": "Toán kinh tế",
    }
    for kw, name in nganh_map.items():
        if kw in msg:
            ctx["interested_major"] = name

    if intent not in ctx["asked_about"]:
        ctx["asked_about"].append(intent)
        
    # Đồng bộ xuống SQLite DB
    _save_context_to_db(session_id, ctx, session["last_active"])


def update_pronoun_early(session_id: str, query: str) -> None:
    session = get_or_create_session(session_id)
    ctx = session["context"]
    if ctx["pronoun_role"] is None:
        pronoun = detect_pronoun_role(query)
        if pronoun["user_calls_self"] is None and ctx.get("guest_profile"):
            age_suggestion = _suggest_pronoun_by_age(ctx["guest_profile"]["birth_year"])
            pronoun["co_tham_calls_user"] = age_suggestion["co_tham_calls_user"]
            pronoun["co_tham_xung"] = age_suggestion["co_tham_xung"]
        ctx["pronoun_role"] = pronoun
        logger.info(f"[memory] early pronoun: xưng={pronoun['co_tham_xung']}, gọi={pronoun['co_tham_calls_user']}")
        
        # Đồng bộ xuống SQLite DB
        _save_context_to_db(session_id, ctx, session["last_active"])


def get_search_expansion_keywords(session_id: str, current_query: str) -> str:
    session = get_or_create_session(session_id)
    ctx = session["context"]
    
    msg = current_query.lower()
    current_level = None
    if "thạc sĩ" in msg or "cao học" in msg:
        current_level = "thạc sĩ"
    elif "tiến sĩ" in msg or "phd" in msg:
        current_level = "tiến sĩ"
        
    current_major = None
    nganh_map = {
        "tài chính": "Tài chính - Ngân hàng", "ngân hàng": "Tài chính - Ngân hàng",
        "quản trị kinh doanh": "Quản trị kinh doanh", "kế toán": "Kế toán",
        "marketing": "Marketing", "kinh tế học": "Kinh tế học",
        "quản lý kinh tế": "Quản lý kinh tế", "luật": "Luật kinh tế",
        "kinh doanh quốc tế": "Kinh doanh quốc tế", "toán kinh tế": "Toán kinh tế",
    }
    for kw, name in nganh_map.items():
        if kw in msg:
            current_major = name
            break

    level = current_level
    if not level and ctx.get("interested_level"):
        level = "thạc sĩ" if ctx["interested_level"] == "thac_si" else "tiến sĩ"
        
    major = current_major or ctx.get("interested_major")
    
    keywords = []
    if level:
        keywords.append(level)
    if major:
        keywords.append(major)
        
    return " ".join(keywords)


def get_conversation_history(session_id: str, max_messages: int = 6) -> list[dict]:
    session = get_or_create_session(session_id)
    msgs = session["messages"][-max_messages:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def get_context_summary(session_id: str) -> str:
    session = get_or_create_session(session_id)
    ctx = session["context"]
    parts = []

    pronoun = ctx.get("pronoun_role") or {}
    co_xung = pronoun.get("co_tham_xung", "em")
    co_goi = pronoun.get("co_tham_calls_user", "bạn")
    parts.append(f"[XƯNG HÔ] Cô Thắm xưng là '{co_xung}', gọi người dùng là '{co_goi}'. Phải nhất quán suốt cuộc trò chuyện.")

    guest = ctx.get("guest_profile")
    if guest:
        full_name = guest.get("full_name", "")
        first_name = extract_first_name(full_name)
        birth_year = guest.get("birth_year", 0)
        current_year = datetime.now().year
        age = current_year - birth_year if birth_year else 0

        parts.append(f"[TÊN GỌI] Tên đầy đủ: {full_name}. Tên riêng để gọi: {first_name} (chữ cuối trong tên).")

        if age > 0:
            suggested = _suggest_pronoun_by_age(birth_year)
            parts.append(
                f"[TUỔI] Người dùng sinh năm {birth_year}, khoảng {age} tuổi. "
                f"Gợi ý xưng hô ban đầu: xưng '{suggested['co_tham_xung']}', gọi '{suggested['co_tham_calls_user']}'. "
                f"Nhưng ưu tiên cách họ tự xưng trong chat."
            )

        edu = guest.get("education_level", "")
        edu_detail = guest.get("education_detail", "")
        if edu:
            edu_labels = {
                "dai_hoc": "Đại học",
                "sau_dai_hoc": "Sau đại học",
                "cao_dang": "Cao đẳng hoặc khác",
            }
            edu_text = edu_labels.get(edu, edu)
            if edu_detail:
                edu_text += f" ({edu_detail})"
            parts.append(f"[HỌC VẤN] Trình độ hiện tại: {edu_text}")

        gender = guest.get("gender") or ctx.get("user_gender", "")
        if gender:
            gender_label = "nam" if gender == "nam" else "nữ"
            pronoun_for_user = "anh" if gender == "nam" else "chị"
            parts.append(f"[GIỚI TÍNH] Người dùng là {gender_label}. Gọi họ là '{pronoun_for_user}' khi phù hợp.")

    if ctx["interested_level"]:
        level = "Thạc sĩ" if ctx["interested_level"] == "thac_si" else "Tiến sĩ"
        parts.append(f"Học viên quan tâm bậc: {level}")
    if ctx["interested_major"]:
        parts.append(f"Ngành quan tâm: {ctx['interested_major']}")
    if ctx["asked_about"]:
        parts.append(f"Đã hỏi về: {', '.join(ctx['asked_about'][-5:])}")

    return "\n".join(parts)


def cleanup_expired_sessions() -> None:
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["last_active"] > SESSION_TTL]
    for sid in expired:
        del _sessions[sid]
    if expired:
        logger.info(f"[memory] cleaned {len(expired)} expired sessions")
    if len(_sessions) > MAX_SESSIONS:
        oldest = sorted(_sessions, key=lambda s: _sessions[s]["last_active"])
        for sid in oldest[:len(_sessions) - MAX_SESSIONS]:
            del _sessions[sid]


def session_count() -> int:
    return len(_sessions)
