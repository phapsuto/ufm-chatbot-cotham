"""
app/services/tts_service.py — Gọi VieNeu-TTS Sidecar để tổng hợp giọng nói Cô Giáo Thắm.

Kiến trúc:
  Chatbot (port 8000) → HTTP → TTS Sidecar (port 23333)

Tối ưu latency:
  - Connection pooling (httpx.AsyncClient keep-alive)
  - Sentence splitting (tách câu dài → TTS từng câu → nối WAV)
  - Lazy TTS (chỉ gọi khi user bấm nút 🔊)
"""
import io
import re
import wave
import logging
import httpx

from app.config import settings

logger = logging.getLogger("ufm-chatbot")

# ── Config ─────────────────────────────────────────────────
TTS_BASE_URL = getattr(settings, "TTS_BASE_URL", "http://localhost:23333")
TTS_TIMEOUT = 60.0
# Mỗi câu gửi riêng → không cần truncate

# Shared HTTP client (connection pooling)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Lazy-init shared HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=TTS_BASE_URL,
            timeout=httpx.Timeout(TTS_TIMEOUT, connect=10.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _client


# ── Public API ─────────────────────────────────────────────
async def synthesize(text: str) -> bytes | None:
    """
    Gửi text tới TTS sidecar, nhận WAV audio bytes.
    Trả None nếu TTS không khả dụng hoặc lỗi.
    """
    if not text or not text.strip():
        return None

    # Strip markdown để TTS đọc tự nhiên
    clean_text = _strip_markdown(text)
    if not clean_text:
        return None

    try:
        client = _get_client()
        resp = await client.post(
            "/synthesize",
            json={"text": clean_text, "emotion": "natural"},
        )

        if resp.status_code == 200:
            duration = resp.headers.get("X-TTS-Duration", "?")
            sentences = resp.headers.get("X-TTS-Sentences", "?")
            logger.info(
                f"[tts] ✅ Synthesized {sentences} sentences in {duration}s "
                f"→ {len(resp.content)} bytes"
            )
            return resp.content
        else:
            logger.warning(f"[tts] ⚠️ TTS returned {resp.status_code}: {resp.text[:200]}")
            return None

    except httpx.ConnectError:
        logger.warning("[tts] ⚠️ TTS sidecar not reachable (is it running?)")
        return None
    except httpx.TimeoutException:
        logger.warning("[tts] ⚠️ TTS request timed out")
        return None
    except Exception as e:
        logger.error(f"[tts] ❌ Unexpected error: {e}")
        return None


async def is_available() -> bool:
    """Check xem TTS sidecar có đang chạy không."""
    try:
        client = _get_client()
        resp = await client.get("/health")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("ready", False)
        return False
    except Exception:
        return False


async def list_voices() -> list[dict]:
    """Lấy danh sách giọng nói preset từ TTS sidecar."""
    try:
        client = _get_client()
        resp = await client.get("/voices")
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


# ── Helpers ────────────────────────────────────────────────
def _strip_markdown(text: str) -> str:
    """Loại bỏ markdown formatting để TTS đọc tự nhiên."""
    # Bold, italic, strikethrough, code
    clean = re.sub(r'\*\*|__|~~|`{1,3}', '', text)
    # Headers
    clean = re.sub(r'#{1,6}\s*', '', clean)
    # Links [text](url) → text
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
    # Images ![alt](url) → loại bỏ
    clean = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean)
    # Bullet points
    clean = re.sub(r'^[\s]*[-*•]\s+', '', clean, flags=re.MULTILINE)
    # Numbered lists
    clean = re.sub(r'^[\s]*\d+\.\s+', '', clean, flags=re.MULTILINE)
    # Tables
    clean = re.sub(r'\|[^|]*\|', '', clean)
    clean = re.sub(r'-{3,}', '', clean)
    # Multiple spaces/newlines
    clean = re.sub(r'\n{2,}', '. ', clean)
    clean = re.sub(r'\s+', ' ', clean)

    return clean.strip()
