#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  🤖 Cô giáo Thắm Telegram — Trợ lý Tuyển sinh & Học tập UFM        ║
║  Tích hợp hệ thống Chatbot v4 và Đồng bộ hóa IDE Agent            ║
╚══════════════════════════════════════════════════════════════════════╝

Cách chạy:
    python3 telegram_bot.py

Yêu cầu:
    pip install requests python-dotenv

Biến môi trường:
    TELEGRAM_BOT_TOKEN    — Token từ BotFather (đã cấu hình trong .env)
    UFM_API_URL           — URL API UFM Chatbot (mặc định: http://localhost:8000)
"""

import os
import sys
import json
import time
import logging
import html
import textwrap
import threading
import subprocess
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# ══════════════════════════════════════════════════
# CẤU HÌNH
# ══════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8949307916:AAHLsSOGc7s27B-99Jpy_xhiQYWBouUGLaE"
)

UFM_API_URL = os.environ.get("UFM_API_URL", "http://localhost:8000")

# Danh sách Telegram user_id được phép dùng bot (để trống = ai cũng dùng được)
ALLOWED_USER_IDS = []

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 20
user_request_timestamps = {}

# Logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/telegram_bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
# TELEGRAM API HELPERS (Pure HTTP)
# ══════════════════════════════════════════════════

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


last_msg_was_voice = {}

def tg_request(method: str, data: dict = None, files: dict = None, timeout: float = 30.0) -> dict:
    """Gọi Telegram Bot API."""
    url = f"{TELEGRAM_API}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)
        result = resp.json()
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result}")
        return result
    except Exception as e:
        logger.error(f"Telegram API request failed: {e}")
        return {"ok": False, "error": str(e)}


def download_telegram_file(file_path: str) -> bytes:
    """Tải file âm thanh từ Telegram về bytes."""
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 200:
        return resp.content
    raise Exception(f"Failed to download file: {resp.status_code} {resp.text}")


def transcribe_voice_file(file_bytes: bytes) -> Optional[str]:
    """Chuyển đổi file âm thanh thoại OGG/OGA thành văn bản qua ASR Whisper của FPT Cloud."""
    api_key = os.environ.get("FPT_CLOUD_API_KEY")
    if not api_key:
        logger.warning("Không tìm thấy FPT_CLOUD_API_KEY trong biến môi trường.")
        return None
        
    url = "https://mkp-api.fptcloud.com/v1/audio/transcriptions"
    try:
        files = {
            "file": ("voice.oga", file_bytes, "audio/ogg")
        }
        data = {
            "model": "whisper-large-v3-turbo",
            "response_format": "json",
            "language": "vi"
        }
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=20)
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        else:
            logger.error(f"ASR transcription error {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"ASR transcription exception: {e}")
        return None


def md_to_clean_text(text: str) -> str:
    """Loại bỏ markdown formatting để TTS đọc tự nhiên."""
    import re
    clean = re.sub(r'\*\*|__|~~|`{1,3}', '', text)
    clean = re.sub(r'#{1,6}\s*', '', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
    clean = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean)
    clean = re.sub(r'^[\s]*[-*•]\s+', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'^[\s]*\d+\.\s+', '', clean, flags=re.MULTILINE)
    clean = re.sub(r'\|[^|]*\|', '', clean)
    clean = re.sub(r'-{3,}', '', clean)
    clean = re.sub(r'\n{2,}', '. ', clean)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def synthesize_to_voice(text: str) -> Optional[bytes]:
    """Tổng hợp văn bản thành giọng nói (WAV) qua FPT Cloud TTS."""
    api_key = os.environ.get("FPT_CLOUD_API_KEY")
    if not api_key:
        return None
        
    clean_text = md_to_clean_text(text)
    if not clean_text or len(clean_text) < 3:
        return None
        
    url = "https://mkp-api.fptcloud.com/v1/audio/speech"
    try:
        resp = requests.post(
            url,
            json={
                "model": "FPT.AI-VITs",
                "input": clean_text,
                "response_format": "wav",
                "voice": "std_kimngan",
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=20
        )
        if resp.status_code == 200 and len(resp.content) > 500:
            return resp.content
        else:
            logger.error(f"TTS synthesis error {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"TTS synthesis exception: {e}")
        return None


def send_voice(chat_id: int, voice_bytes: bytes, caption: str = None, reply_to: int = None) -> dict:
    """Gửi file voice note (WAV/MP3) về Telegram."""
    files = {
        "voice": ("voice.wav", voice_bytes, "audio/wav")
    }
    data = {
        "chat_id": chat_id
    }
    if caption:
        data["caption"] = caption[:1024]
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return tg_request("sendVoice", data=data, files=files)


def md_to_html(text: str) -> str:
    """Chuyển đổi Markdown sang HTML đẹp mắt phù hợp với Telegram."""
    import re
    
    # 1. Escape HTML special characters để tránh lỗi cú pháp Telegram
    text = html.escape(text, quote=False)
    
    # 2. Tách và bảo lưu các khối code blocks (```)
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(1))
        return f"CODEBLOCKPLACEHOLDER{len(code_blocks)-1}"
        
    text = re.sub(r'```(?:\w+)?\n(.*?)\n```', save_code_block, text, flags=re.DOTALL)
    text = re.sub(r'```(.*?)```', save_code_block, text, flags=re.DOTALL)
    
    # 3. Định dạng inline code `code` và bảo lưu
    inline_codes = []
    def save_inline_code(match):
        inline_codes.append(match.group(1))
        return f"INLINECODEPLACEHOLDER{len(inline_codes)-1}"
    text = re.sub(r'`([^`\n]+)`', save_inline_code, text)

    # 4. Xử lý định dạng dòng (tiêu đề, danh sách, đường kẻ ngang)
    lines = text.split("\n")
    for i in range(len(lines)):
        line = lines[i]
        stripped = line.strip()
        
        # Tiêu đề H1: # Title -> 🎓 TITLE (In đậm, viết hoa)
        if stripped.startswith("# "):
            lines[i] = f"<b>🎓 {stripped[2:].upper()}</b>"
        # Tiêu đề H2: ## Title -> 📌 Title
        elif stripped.startswith("## "):
            lines[i] = f"\n<b>📌 {stripped[3:]}</b>"
        # Tiêu đề H3: ### Title -> 🔹 Title
        elif stripped.startswith("### "):
            lines[i] = f"\n<b>🔹 {stripped[4:]}</b>"
        # Tiêu đề H4: #### Title -> 🔸 Title
        elif stripped.startswith("#### "):
            lines[i] = f"\n<b>🔸 {stripped[5:]}</b>"
        # Đường kẻ ngang
        elif stripped == "---":
            lines[i] = "──────────────────"
        # Danh sách (bullet points)
        elif stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            content = stripped[2:]
            lines[i] = f"  ▫️ {content}"
            
    text = "\n".join(lines)

    # 5. Định dạng thẻ trích dẫn [C1] -> ¹ (unicode superscript, in đậm)
    def repl_citation(match):
        num_str = match.group(1)
        superscripts = {
            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
            '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
        }
        sup = "".join(superscripts.get(c, c) for c in num_str)
        return f"<b>{sup}</b>"
    
    text = re.sub(r'\[C(\d+)\]', repl_citation, text)

    # 6. Định dạng liên kết [Text](URL) -> <a href="URL">Text</a>
    text = re.sub(r'\[([^\]\n]+)\]\(((?:https?|file)://[^\s\)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Tách và bảo lưu toàn bộ các thẻ HTML đang có (sử dụng placeholder không có dấu gạch dưới)
    html_tags = []
    def save_html_tag(match):
        html_tags.append(match.group(0))
        return f"HTMLTAGPLACEHOLDER{len(html_tags)-1}"
    text = re.sub(r'<[^>]+>', save_html_tag, text)

    # 8. Áp dụng định dạng in đậm **text** và *text*
    text = re.sub(r'(^|\s|[.,!?;:]|>)\*\*([^*\n<]+)\*\*(?=\s|$|[.,!?;:]|<)', r'\1<b>\2</b>', text)
    text = re.sub(r'(^|\s|[.,!?;:]|>)\*([^*\n<]+)\*(?=\s|$|[.,!?;:]|<)', r'\1<b>\2</b>', text)

    # 9. Áp dụng định dạng in nghiêng _text_
    text = re.sub(r'(^|\s|[.,!?;:]|>)_([^_\n<]+)_(?=\s|$|[.,!?;:]|<)', r'\1<i>\2</i>', text)

    # 10. Khôi phục các thẻ HTML đã bảo lưu
    for idx in range(len(html_tags) - 1, -1, -1):
        text = text.replace(f"HTMLTAGPLACEHOLDER{idx}", html_tags[idx])

    # 11. Khôi phục inline code dưới dạng <code>
    for idx, code in enumerate(inline_codes):
        text = text.replace(f"INLINECODEPLACEHOLDER{idx}", f"<code>{code}</code>")

    # 12. Khôi phục code blocks dưới dạng <pre>
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"CODEBLOCKPLACEHOLDER{idx}", f"<pre>{block}</pre>")

    return text




def send_message(chat_id: int, text: str, parse_mode: str = "HTML",
                 reply_to: int = None, disable_preview: bool = True) -> dict:
    """Gửi tin nhắn Telegram với HTML hoặc Plain text. Có hỗ trợ chia nhỏ và tự động fallback nếu lỗi HTML."""
    # Split the original markdown/plain text first to avoid splitting inside HTML tags
    # We split at 3800 chars to leave some buffer for HTML tags added by md_to_html
    raw_parts = split_message(text, 3800)
    
    last_result = {"ok": False}
    
    for part in raw_parts:
        if parse_mode == "HTML":
            try:
                html_part = md_to_html(part)
                payload = {
                    "chat_id": chat_id,
                    "text": html_part,
                    "reply_to_message_id": reply_to,
                    "disable_web_page_preview": disable_preview,
                    "parse_mode": "HTML"
                }
                res = tg_request("sendMessage", payload)
                if res.get("ok"):
                    last_result = res
                    continue
                else:
                    logger.error(f"Failed to send HTML chunk: {res}")
            except Exception as e:
                logger.error(f"Error converting/sending HTML chunk: {e}")
                
            # Fallback for this specific chunk if HTML failed
            logger.info("Falling back to plain text for this chunk.")
            plain_part = part.replace("*", "").replace("_", "").replace("`", "")
            payload = {
                "chat_id": chat_id,
                "text": plain_part,
                "reply_to_message_id": reply_to,
                "disable_web_page_preview": disable_preview,
            }
            res = tg_request("sendMessage", payload)
            if res.get("ok"):
                last_result = res
        else:
            payload = {
                "chat_id": chat_id,
                "text": part,
                "reply_to_message_id": reply_to,
                "disable_web_page_preview": disable_preview,
            }
            res = tg_request("sendMessage", payload)
            if res.get("ok"):
                last_result = res
                
    return last_result


def send_typing(chat_id: int):
    """Hiển thị trạng thái 'đang gõ...' cho user."""
    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})


def split_message(text: str, max_len: int = 4000) -> list:
    """Chia tin nhắn dài thành nhiều phần nhỏ."""
    if len(text) <= max_len:
        return [text]
    
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        
        split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = text.rfind(". ", 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        
        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    
    return parts


# ══════════════════════════════════════════════════
# UFM CHATBOT API CLIENT (SSE Stream Parsing)
# ══════════════════════════════════════════════════

def call_ufm_chat(message: str, session_id: str = "telegram_default") -> dict:
    """Gọi API /api/chat của UFM Chatbot và đọc kết quả stream SSE."""
    url = f"{UFM_API_URL}/api/chat"
    payload = {
        "message": message,
        "session_id": f"telegram_{session_id}",
        "gender": "",
        "voice_mode": False
    }
    
    try:
        start_time = time.time()
        # Gọi POST request ở chế độ stream=True
        resp = requests.post(url, json=payload, stream=True, timeout=120)
        latency = time.time() - start_time
        
        if resp.status_code != 200:
            return {
                "error": True,
                "status_code": resp.status_code,
                "detail": resp.text[:500]
            }
            
        full_text = ""
        sources = []
        suggestions = []
        requires_handoff = False
        co_tham_xung = "em"
        
        # Đọc dữ liệu dòng theo dòng
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: "):
                data_content = line_str[6:].strip()
                if data_content == "[DONE]":
                    continue
                try:
                    event_data = json.loads(data_content)
                    if "content" in event_data:
                        full_text += event_data["content"]
                    elif "done" in event_data and event_data["done"]:
                        sources = event_data.get("sources", [])
                        suggestions = event_data.get("suggestions", [])
                        requires_handoff = event_data.get("requires_handoff", False)
                        co_tham_xung = event_data.get("co_tham_xung", "em")
                except Exception as e:
                    logger.error(f"Lỗi phân tích SSE chunk: {e}")
                    
        return {
            "answer": full_text or "Xin lỗi, hiện tại tôi gặp sự cố khi tạo phản hồi.",
            "sources": sources,
            "suggestions": suggestions,
            "requires_handoff": requires_handoff,
            "co_tham_xung": co_tham_xung,
            "_latency": round(latency, 2)
        }
    except requests.ConnectionError:
        return {
            "error": True,
            "detail": "❌ Không thể kết nối tới UFM Chatbot API server.\n"
                      f"Server: {UFM_API_URL}\n"
                      "Hãy chắc chắn server đang chạy: `uvicorn app.main:app --port 8000` (hoặc cấu hình lại trong file .env)."
        }
    except requests.Timeout:
        return {"error": True, "detail": "⏰ Timeout — server phản hồi quá chậm (>120s)."}
    except Exception as e:
        return {"error": True, "detail": f"Lỗi không xác định: {str(e)}"}


def check_server_health() -> dict:
    """Kiểm tra trạng thái server UFM Chatbot."""
    try:
        resp = requests.get(f"{UFM_API_URL}/health/detail", timeout=5)
        if resp.status_code == 200:
            return {"online": True, "data": resp.json()}
        return {"online": False, "detail": f"HTTP {resp.status_code}"}
    except Exception:
        try:
            resp = requests.get(f"{UFM_API_URL}/health", timeout=5)
            if resp.status_code == 200:
                return {"online": True, "data": resp.json()}
            return {"online": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"online": False, "detail": f"Không thể kết nối: {str(e)}"}


# ══════════════════════════════════════════════════
# RATE LIMITING
# ══════════════════════════════════════════════════

def check_rate_limit(user_id: int) -> bool:
    """Kiểm tra rate limit. Trả về True nếu ok, False nếu bị giới hạn."""
    now = time.time()
    if user_id not in user_request_timestamps:
        user_request_timestamps[user_id] = []
    
    # Xóa các timestamp cũ hơn 60 giây
    user_request_timestamps[user_id] = [
        ts for ts in user_request_timestamps[user_id] if now - ts < 60
    ]
    
    if len(user_request_timestamps[user_id]) >= MAX_REQUESTS_PER_MINUTE:
        return False
    
    user_request_timestamps[user_id].append(now)
    return True


# ══════════════════════════════════════════════════
# FORMAT RESPONSE
# ══════════════════════════════════════════════════

def format_chat_response(data: dict) -> str:
    """Format kết quả chat thành Markdown/HTML đẹp cho Telegram."""
    if data.get("error"):
        return f"⚠️ *Lỗi:*\n{data.get('detail', 'Unknown error')}"
    
    answer = data.get("answer", "Không có phản hồi.")
    sources = data.get("sources", [])
    latency = data.get("_latency", 0)
    requires_handoff = data.get("requires_handoff", False)
    
    parts = [f"🎓 *Cô giáo Thắm UFM*\n\n{answer}"]
    
    # Sources
    if sources:
        parts.append("\n📎 *Nguồn tham khảo:*")
        for i, src in enumerate(sources[:5], 1):
            title = src.get("title", "Tài liệu")
            url = src.get("url", "#")
            parts.append(f"{i}. [{title}]({url})")
            
    # Handoff warning
    if requires_handoff:
        parts.append("\n⚠️ *Lưu ý:* Câu hỏi của bạn có tính chất phức tạp. Bạn có thể để lại thông tin liên hệ trong form hỗ trợ trên website để cán bộ đào tạo liên hệ tư vấn trực tiếp.")
        
    # Footer
    footer_items = []
    if latency:
        footer_items.append(f"⏱️ {latency}s")
    if footer_items:
        parts.append(f"\n_{' · '.join(footer_items)}_")
        
    return "\n".join(parts)


# ══════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════

def handle_start(chat_id: int, user_name: str):
    """Xử lý lệnh /start."""
    welcome = (
        "🎓 *Chào mừng đến với Cô giáo Thắm — UFM Chatbot!*\n\n"
        f"Xin chào *{user_name}*! Tôi là Cô giáo Thắm, Trợ lý Tuyển sinh và Đào tạo Sau Đại học UFM.\n\n"
        "🔹 *Gõ câu hỏi trực tiếp* — Tôi sẽ trả lời giải đáp thắc mắc tuyển sinh, đào tạo, học tập...\n"
        "🔹 `/status` — Kiểm tra trạng thái máy chủ UFM Chatbot\n"
        "🔹 `/help` — Hướng dẫn chi tiết sử dụng\n"
        "🔹 `/agent` — Gửi lệnh điều khiển IDE Agent\n"
        "🔹 `/sync` — Đồng bộ 2 chiều trực tiếp với IDE Agent\n\n"
        "💡 *Ví dụ:*\n"
        "_Điều kiện tuyển sinh thạc sĩ khóa này?_\n"
        "_Thời gian đóng học phí học kỳ mới?_\n"
        "_Hồ sơ dự thi sau đại học gồm những gì?_"
    )
    send_message(chat_id, welcome)


def handle_help(chat_id: int):
    """Xử lý lệnh /help."""
    help_text = (
        "📖 *Hướng dẫn sử dụng Cô giáo Thắm UFM Chatbot*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💬 *Chat trực tiếp*\n"
        "Gõ bất kỳ câu hỏi nào về tuyển sinh, đào tạo, quy chế học tập UFM. Tôi sẽ phân tích và phản hồi trực tiếp cho bạn.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💻 *Lệnh điều khiển IDE Agent*\n"
        "`/agent [lệnh]` — Ra lệnh trực tiếp cho AI Agent trong IDE\n"
        "Ví dụ: `/agent viết test case cho chatbot.py`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *Lệnh hệ thống*\n"
        "`/status` — Trạng thái server & API\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *Mẹo*\n"
        "• Hỏi chi tiết = câu trả lời tốt hơn\n"
        "• Hệ thống tự động xưng hô phù hợp nhờ nhận diện danh xưng của bạn"
    )
    send_message(chat_id, help_text)


def handle_status(chat_id: int):
    """Xử lý lệnh /status."""
    send_typing(chat_id)
    
    health = check_server_health()
    
    if health["online"]:
        data = health.get("data", {})
        sessions = data.get("sessions", 0)
        cache_stats = data.get("cache", {})
        
        msg = (
            "🟢 *UFM Chatbot Server — ONLINE*\n\n"
            f"📡 URL: `{UFM_API_URL}`\n"
            f"📊 Status: {data.get('status', 'ok')}\n"
            f"📚 Active Sessions: {sessions}\n"
            f"🎯 Cache size: {cache_stats.get('hits', 0)} hits / {cache_stats.get('misses', 0)} misses\n"
            f"⏰ Checked: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        msg = (
            "🔴 *UFM Chatbot Server — OFFLINE*\n\n"
            f"📡 URL: `{UFM_API_URL}`\n"
            f"❌ {health.get('detail', 'Connection refused')}\n\n"
            "💡 Khởi chạy server:\n"
            "`uvicorn app.main:app --port 8000`"
        )
    
    send_message(chat_id, msg)


def handle_chat(chat_id: int, user_id: int, text: str, message_id: int):
    """Xử lý chat pháp luật trực tiếp."""
    send_typing(chat_id)
    
    result = call_ufm_chat(text, session_id=str(user_id))
    
    msg = format_chat_response(result)
    
    # Fallback nếu HTML bị lỗi
    resp = send_message(chat_id, msg, parse_mode="HTML", reply_to=message_id)
    if not resp.get("ok"):
        # Thử lại không định dạng
        plain_msg = msg.replace("*", "").replace("_", "").replace("`", "")
        resp = send_message(chat_id, plain_msg, parse_mode=None, reply_to=message_id)
        
    # Gửi kèm tin nhắn thoại phản hồi nếu tin nhắn đến là tin nhắn thoại
    if last_msg_was_voice.get(chat_id):
        tg_request("sendChatAction", {"chat_id": chat_id, "action": "record_voice"})
        voice_bytes = synthesize_to_voice(msg)
        if voice_bytes:
            send_voice(chat_id, voice_bytes, caption="Giọng đọc Cô giáo Thắm 🎙️", reply_to=message_id)


# ══════════════════════════════════════════════════
# TELEGRAM <-> IDE AGENT SYNC CONFIGURATION
# ══════════════════════════════════════════════════

SYNC_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".telegram_sync.json"
)

active_continuous_polls = {}
stop_events = {}
last_sent_from_telegram = {}
active_polls = {}


def load_sync_config() -> dict:
    """Đọc cấu hình đồng bộ từ file."""
    if os.path.exists(SYNC_CONFIG_FILE):
        try:
            with open(SYNC_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Lỗi đọc file sync config: {e}")
    return {}


def save_sync_config(config: dict):
    """Ghi cấu hình đồng bộ xuống file."""
    try:
        with open(SYNC_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi ghi file sync config: {e}")


def get_sync_chat_id() -> Optional[int]:
    """Lấy chat_id đang được bật đồng bộ."""
    config = load_sync_config()
    if config.get("sync_enabled"):
        return config.get("chat_id")
    return None


def is_sync_enabled(chat_id: int) -> bool:
    """Kiểm tra xem chat_id này có đang được đồng bộ không."""
    config = load_sync_config()
    return config.get("sync_enabled", False) and config.get("chat_id") == chat_id


def start_continuous_polling(chat_id: int):
    """Bắt đầu thread polling liên tục cho chat_id."""
    if chat_id in active_continuous_polls:
        thread = active_continuous_polls[chat_id]
        if thread.is_alive():
            logger.info(f"Thread continuous polling cho chat {chat_id} đang chạy rồi.")
            return
            
    logger.info(f"Khởi chạy thread continuous polling mới cho chat {chat_id}")
    stop_event = threading.Event()
    stop_events[chat_id] = stop_event
    stop_event.clear()
    
    thread = threading.Thread(
        target=poll_agent_continuous_loop,
        args=(chat_id, stop_event),
        daemon=True
    )
    active_continuous_polls[chat_id] = thread
    thread.start()


def stop_continuous_polling(chat_id: int):
    """Dừng thread polling liên tục cho chat_id."""
    if chat_id in stop_events:
        logger.info(f"Dừng thread continuous polling cho chat {chat_id}")
        stop_events[chat_id].set()
        stop_events.pop(chat_id, None)
        active_continuous_polls.pop(chat_id, None)


def get_current_conversation_id() -> Optional[str]:
    """Đọc conversation_id hiện tại từ file cấu hình."""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".conversation_id"
        )
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        logger.error(f"Lỗi đọc .conversation_id: {e}")
    return None


def safe_read_lines(file_path: str, retries: int = 3, delay: float = 0.5) -> list:
    """Đọc các dòng của file an toàn, tránh lỗi Operation timed out [Errno 60] của OneDrive/macOS."""
    for attempt in range(retries):
        try:
            if not os.path.exists(file_path):
                return []
            with open(file_path, "r", encoding="utf-8") as f:
                return f.readlines()
        except OSError as e:
            logger.warning(f"Lỗi đọc file (Lần thử {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"Đã thử {retries} lần nhưng vẫn thất bại khi đọc {file_path}: {e}")
                return []
    return []


def get_latest_step_index(conversation_id: str) -> int:
    """Lấy step_index lớn nhất hiện tại từ transcript.jsonl."""
    transcript_path = f"/Users/tonguyen/.gemini/antigravity-ide/brain/{conversation_id}/.system_generated/logs/transcript.jsonl"
    max_idx = 0
    lines = safe_read_lines(transcript_path)
    for line in lines:
        if not line.strip():
            continue
        try:
            step = json.loads(line)
            idx = step.get("step_index", 0)
            if idx > max_idx:
                max_idx = idx
        except:
            pass
    return max_idx


def poll_agent_continuous_loop(chat_id: int, stop_event: threading.Event):
    """Vòng lặp poll liên tục transcript của conversation hiện tại."""
    logger.info(f"Bắt đầu vòng lặp poll continuous cho chat_id {chat_id}")
    
    last_conv_id = None
    last_idx = 0
    
    # Khởi tạo last_idx từ conversation hiện tại
    current_conv_id = get_current_conversation_id()
    if current_conv_id:
        last_conv_id = current_conv_id
        last_idx = get_latest_step_index(current_conv_id)
        logger.info(f"Khởi tạo continuous poll cho conv {current_conv_id} tại step {last_idx}")
        
    while not stop_event.is_set():
        current_conv_id = get_current_conversation_id()
        if not current_conv_id:
            time.sleep(2)
            continue
            
        # Nếu đổi sang conversation mới
        if current_conv_id != last_conv_id:
            last_conv_id = current_conv_id
            last_idx = get_latest_step_index(current_conv_id)
            send_message(
                chat_id, 
                f"🔄 *Đã tự động chuyển đồng bộ sang Conversation mới:*\n`{current_conv_id}`"
            )
            logger.info(f"Chuyển continuous poll sang conv {current_conv_id} tại step {last_idx}")
            
        transcript_path = f"/Users/tonguyen/.gemini/antigravity-ide/brain/{current_conv_id}/.system_generated/logs/transcript.jsonl"
        lines = safe_read_lines(transcript_path)
        if not lines:
            time.sleep(2)
            continue
            
        new_lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                step = json.loads(line)
                idx = step.get("step_index", 0)
                if idx > last_idx:
                    new_lines.append(step)
            except:
                pass
            
        if new_lines:
            for step in new_lines:
                idx = step.get("step_index", 0)
                last_idx = max(last_idx, idx)
                
                step_type = step.get("type")
                source = step.get("source")
                content = step.get("content", "").strip()
                
                # Tránh vọng lại tin nhắn chính user vừa gửi từ Telegram
                if step_type == "USER_INPUT":
                    sent_msgs = last_sent_from_telegram.get(chat_id, [])
                    if content in sent_msgs:
                        sent_msgs.remove(content)
                        last_sent_from_telegram[chat_id] = sent_msgs
                        continue
                    send_message(chat_id, f"👤 *User (IDE):*\n{content}")
                    
                elif step_type == "PLANNER_RESPONSE" and source == "MODEL":
                    tool_calls = step.get("tool_calls", [])
                    if content:
                        send_message(chat_id, f"🤖 *IDE Agent:*\n\n{content}")
                        if last_msg_was_voice.get(chat_id):
                            voice_bytes = synthesize_to_voice(content)
                            if voice_bytes:
                                send_voice(chat_id, voice_bytes, caption="Giọng đọc Cô giáo Thắm 🎙️")
                    if tool_calls:
                        for tc in tool_calls:
                            name = tc.get("name", "tool")
                            args = tc.get("args", {})
                            summary = args.get("toolSummary", "") or args.get("toolAction", "") or name
                            summary = summary.strip('"\'')
                            send_message(chat_id, f"🛠️ *Agent đang thực thi:* `{summary}`")
                            
                elif step_type == "ASK_QUESTION":
                    send_message(chat_id, f"❓ *IDE Agent cần anh xác nhận (vui lòng vào IDE hoặc chat trực tiếp tại đây để trả lời):*\n\n{content}")
                    
                elif step_type == "ERROR_MESSAGE":
                    send_message(chat_id, f"❌ *IDE Agent gặp lỗi:* `{content}`")
                    
        time.sleep(1.5)


def poll_agent_response(chat_id: int, conversation_id: str, start_step_index: int):
    """Poll transcript.jsonl để nhận phản hồi từ IDE Agent (cho chế độ command đơn lẻ)."""
    transcript_path = f"/Users/tonguyen/.gemini/antigravity-ide/brain/{conversation_id}/.system_generated/logs/transcript.jsonl"
    
    logger.info(f"Bắt đầu poll transcript cho conv {conversation_id} từ step_index {start_step_index}")
    
    last_idx = start_step_index
    no_update_count = 0
    max_no_update = 240  # Dừng sau 6 phút
    
    active_polls[chat_id] = True
    
    try:
        while active_polls.get(chat_id):
            lines = safe_read_lines(transcript_path)
            if not lines:
                time.sleep(2)
                continue
                
            new_lines = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    step = json.loads(line)
                    idx = step.get("step_index", 0)
                    if idx > last_idx:
                        new_lines.append(step)
                except Exception:
                    pass
                
            if new_lines:
                no_update_count = 0
                for step in new_lines:
                    idx = step.get("step_index", 0)
                    last_idx = max(last_idx, idx)
                    
                    step_type = step.get("type")
                    source = step.get("source")
                    
                    if step_type == "PLANNER_RESPONSE" and source == "MODEL":
                        content = step.get("content", "").strip()
                        tool_calls = step.get("tool_calls", [])
                        
                        if content:
                            send_message(chat_id, f"🤖 *IDE Agent:*\n\n{content}")
                            if last_msg_was_voice.get(chat_id):
                                voice_bytes = synthesize_to_voice(content)
                                if voice_bytes:
                                    send_voice(chat_id, voice_bytes, caption="Giọng đọc Cô giáo Thắm 🎙️")
                            
                        if tool_calls:
                            for tc in tool_calls:
                                name = tc.get("name", "tool")
                                args = tc.get("args", {})
                                summary = args.get("toolSummary", "") or args.get("toolAction", "") or name
                                summary = summary.strip('"\'')
                                send_message(chat_id, f"🛠️ *Agent đang thực thi:* `{summary}`")
                        
                        if not tool_calls:
                            send_message(chat_id, "✅ *IDE Agent đã hoàn thành lượt xử lý.*")
                            active_polls[chat_id] = False
                            return
                            
                    elif step_type == "ASK_QUESTION":
                        content = step.get("content", "").strip()
                        send_message(chat_id, f"❓ *IDE Agent cần anh xác nhận (vui lòng vào IDE để trả lời):*\n\n{content}")
                        active_polls[chat_id] = False
                        return
                        
                    elif step_type == "ERROR_MESSAGE":
                        content = step.get("content", "").strip()
                        send_message(chat_id, f"❌ *IDE Agent gặp lỗi:* `{content}`")
                        active_polls[chat_id] = False
                        return
            else:
                no_update_count += 1
                if no_update_count > max_no_update:
                    send_message(chat_id, "⚠️ *Thời gian chờ IDE Agent phản hồi quá lâu (Timeout 6 phút).*")
                    active_polls[chat_id] = False
                    return
                    
            time.sleep(1.5)
            
    except Exception as e:
        logger.error(f"Lỗi trong luồng poll agent: {e}")
        send_message(chat_id, f"⚠️ Gặp sự cố khi theo dõi phản hồi của Agent: {str(e)}")
    finally:
        active_polls[chat_id] = False


def handle_agent_command(chat_id: int, command_text: str):
    """Gửi lệnh đến IDE Agent qua agentapi và theo dõi phản hồi."""
    if not command_text:
        send_message(chat_id, "💻 Cú pháp: `/agent [lệnh]`\nVí dụ: `/agent viết test case cho chatbot.py`")
        return
        
    if active_polls.get(chat_id):
        send_message(chat_id, "⏳ Agent vẫn đang thực thi lệnh trước. Vui lòng đợi đến khi hoàn thành.")
        return
        
    conversation_id = get_current_conversation_id()
    if not conversation_id:
        send_message(chat_id, "❌ Không tìm thấy file `.conversation_id` hiện tại.")
        return
        
    start_step_index = get_latest_step_index(conversation_id)
    
    send_message(chat_id, f"📥 *Đang gửi lệnh đến IDE Agent...*\n💬 *Lệnh:* _{command_text}_")
    
    agentapi_path = "/Users/tonguyen/.gemini/antigravity-ide/bin/agentapi"
    try:
        result = subprocess.run(
            [agentapi_path, "send-message", conversation_id, command_text],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode != 0:
            send_message(chat_id, f"❌ Lỗi gửi lệnh đến Agent: {result.stderr or result.stdout}")
            return
            
        t = threading.Thread(
            target=poll_agent_response,
            args=(chat_id, conversation_id, start_step_index),
            daemon=True
        )
        t.start()
        
    except Exception as e:
        send_message(chat_id, f"❌ Lỗi thực thi agentapi: {str(e)}")


def handle_sync_command(chat_id: int, text: str):
    """Xử lý lệnh /sync."""
    args = text[5:].strip().lower()
    
    if args == "off":
        if is_sync_enabled(chat_id):
            stop_continuous_polling(chat_id)
            save_sync_config({"sync_enabled": False, "chat_id": None})
            send_message(chat_id, "📴 *Đã tắt đồng bộ hóa với IDE Agent.*\nBot quay lại chế độ trả lời học tập thông thường.")
        else:
            send_message(chat_id, "ℹ️ Đồng bộ hóa vốn đang ở trạng thái tắt.")
    else:
        current_conv_id = get_current_conversation_id()
        if not current_conv_id:
            send_message(chat_id, "❌ Không tìm thấy `.conversation_id` hiện tại.")
            return
            
        save_sync_config({
            "sync_enabled": True,
            "chat_id": chat_id,
            "conversation_id": current_conv_id
        })
        start_continuous_polling(chat_id)
        send_message(
            chat_id, 
            f"🔗 *Đã bật đồng bộ hóa 2 chiều với IDE Agent!*\n"
            f"Conversation ID: `{current_conv_id}`\n\n"
            f"👉 Mọi tin nhắn gửi cho bot bây giờ sẽ được tự động chuyển trực tiếp vào ô chat IDE mà không cần gõ tiền tố `/agent`.\n"
            f"👉 Để tắt đồng bộ, hãy gõ `/sync off`."
        )


def send_message_to_agent(chat_id: int, command_text: str) -> bool:
    """Gửi tin nhắn trực tiếp đến IDE Agent."""
    conversation_id = get_current_conversation_id()
    if not conversation_id:
        send_message(chat_id, "❌ Không tìm thấy `.conversation_id` hiện tại.")
        return False
        
    agentapi_path = "/Users/tonguyen/.gemini/antigravity-ide/bin/agentapi"
    try:
        result = subprocess.run(
            [agentapi_path, "send-message", conversation_id, command_text],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode != 0:
            send_message(chat_id, f"❌ Lỗi gửi lệnh đến Agent: {result.stderr or result.stdout}")
            return False
        return True
    except Exception as e:
        send_message(chat_id, f"❌ Lỗi thực thi agentapi: {str(e)}")
        return False


# ══════════════════════════════════════════════════
# MAIN POLLING LOOP
# ══════════════════════════════════════════════════

def process_update(update: dict):
    """Xử lý một update từ Telegram (hỗ trợ tin nhắn văn bản và tin nhắn thoại)."""
    msg = update.get("message")
    if not msg:
        return
    
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    user_name = msg["from"].get("first_name", "User")
    message_id = msg["message_id"]
    
    # Access control
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        send_message(chat_id, "🔒 Bạn không có quyền sử dụng bot này.")
        return
    
    # Rate limiting
    if not check_rate_limit(user_id):
        send_message(chat_id, "⏳ Bạn gửi tin nhắn quá nhanh. Vui lòng đợi một lát.")
        return

    text = ""
    is_voice = False
    
    if "voice" in msg:
        is_voice = True
        voice_info = msg["voice"]
        file_id = voice_info["file_id"]
        
        tg_request("sendChatAction", {"chat_id": chat_id, "action": "record_voice"})
        
        res = tg_request("getFile", {"file_id": file_id})
        if res.get("ok"):
            file_path = res["result"]["file_path"]
            try:
                voice_bytes = download_telegram_file(file_path)
                transcribed_text = transcribe_voice_file(voice_bytes)
                if transcribed_text:
                    text = transcribed_text
                    logger.info(f"[{user_id}] Nhận tin nhắn thoại: {text}")
                else:
                    send_message(chat_id, "⚠️ Cô giáo Thắm chưa nghe rõ tin nhắn thoại của em. Em nói rõ hơn hoặc gõ chữ nhé! 🎤")
                    return
            except Exception as e:
                logger.error(f"Failed to process voice note: {e}")
                send_message(chat_id, "❌ Lỗi hệ thống khi xử lý tin nhắn thoại của em. Hãy thử lại sau nhé.")
                return
        else:
            send_message(chat_id, "❌ Không thể tải tin nhắn thoại từ máy chủ Telegram.")
            return
    else:
        text = msg.get("text", "").strip()
        
    if not text:
        return
        
    # Lưu trạng thái loại tin nhắn cuối cùng để phản hồi tương ứng
    last_msg_was_voice[chat_id] = is_voice
    
    logger.info(f"[{user_id}] @{msg['from'].get('username', 'N/A')}: {text[:100]}")
    
    # Command routing
    if text.startswith("/start"):
        handle_start(chat_id, user_name)
    elif text.startswith("/help"):
        handle_help(chat_id)
    elif text.startswith("/status"):
        handle_status(chat_id)
    elif text.startswith("/agent"):
        command_text = text[6:].strip()
        handle_agent_command(chat_id, command_text)
    elif text.startswith("/sync"):
        handle_sync_command(chat_id, text)
    else:
        # Nếu đang đồng bộ, chuyển tiếp tin nhắn thường sang IDE
        if is_sync_enabled(chat_id):
            if chat_id not in last_sent_from_telegram:
                last_sent_from_telegram[chat_id] = []
            last_sent_from_telegram[chat_id] = [text]  # Reset list to only keep the latest
            send_message_to_agent(chat_id, text)
        else:
            # Chat học tập trực tiếp với Cô giáo Thắm
            handle_chat(chat_id, user_id, text, message_id)


_lock_socket = None

def ensure_single_instance(port: int = 12006):
    """Sử dụng socket to lock và ensure single instance."""
    import socket
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _lock_socket.bind(('127.0.0.1', port))
        _lock_socket.listen(1)
        logger.info(f"Đã thiết lập socket lock trên cổng {port} thành công.")
    except socket.error:
        logger.error(f"❌ Lỗi: Có vẻ một tiến trình telegram_bot.py khác đã chạy trên cổng {port} hoặc tiến trình cũ chưa giải phóng hoàn toàn.")
        print(f"\n❌ Lỗi: Một tiến trình telegram_bot.py khác đang chạy hoặc cổng {port} đang bận!")
        print("Vui lòng tắt tiến trình trùng lặp trước khi khởi chạy mới.")
        sys.exit(1)


def main():
    """Main polling loop — Long Polling."""
    ensure_single_instance()
    print("=" * 60)
    print("🎓  Cô giáo Thắm UFM Telegram Bot")
    print("=" * 60)
    
    # Kiểm tra kết nối Telegram
    me = tg_request("getMe")
    if me.get("ok"):
        bot_info = me["result"]
        print(f"✅ Bot: @{bot_info['username']} ({bot_info['first_name']})")
    else:
        print(f"❌ Không thể kết nối Telegram: {me}")
        sys.exit(1)
    
    # Kiểm tra UFM Chatbot server
    health = check_server_health()
    if health["online"]:
        print(f"✅ UFM Chatbot API: {UFM_API_URL} — ONLINE")
    else:
        print(f"⚠️  UFM Chatbot API: {UFM_API_URL} — OFFLINE")
        print("   Bot sẽ vẫn chạy, nhưng không thể trả lời câu hỏi trực tiếp.")
        print("   Khởi chạy server: uvicorn app.main:app --port 8000")
    
    print()
    print("📱 Mở Telegram và chat với @" + me["result"]["username"])
    print("   Nhấn Ctrl+C để dừng bot.")
    print("=" * 60)
    
    # Set bot commands
    tg_request("setMyCommands", {
        "commands": [
            {"command": "start", "description": "🏠 Bắt đầu — Giới thiệu Cô Thắm UFM"},
            {"command": "help", "description": "📖 Hướng dẫn sử dụng"},
            {"command": "status", "description": "📊 Kiểm tra trạng thái máy chủ"},
            {"command": "agent", "description": "💻 Ra lệnh cho AI Agent trong IDE"},
            {"command": "sync", "description": "🔗 Đồng bộ 2 chiều trực tiếp với IDE Agent"},
        ]
    })
    
    # Khôi phục đồng bộ nếu trước đó đang bật
    sync_config = load_sync_config()
    if sync_config.get("sync_enabled") and sync_config.get("chat_id"):
        chat_id = sync_config["chat_id"]
        print(f"🔄 Khôi phục đồng bộ liên tục với chat_id: {chat_id}")
        start_continuous_polling(chat_id)
        
    # Long polling loop
    offset = 0
    error_count = 0
    
    while True:
        try:
            result = tg_request("getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message"],
            }, timeout=35)
            
            if result.get("ok"):
                error_count = 0
                for update in result.get("result", []):
                    offset = update["update_id"] + 1
                    try:
                        process_update(update)
                    except Exception as e:
                        logger.error(f"Error processing update: {e}", exc_info=True)
            else:
                error_count += 1
                logger.warning(f"getUpdates failed (attempt {error_count})")
                time.sleep(min(error_count * 2, 30))
                
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user.")
            break
        except Exception as e:
            error_count += 1
            logger.error(f"Polling error: {e}", exc_info=True)
            time.sleep(min(error_count * 2, 30))


if __name__ == "__main__":
    # Tạo thư mục logs nếu chưa có
    os.makedirs("logs", exist_ok=True)
    main()
