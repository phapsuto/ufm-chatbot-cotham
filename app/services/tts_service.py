"""
app/services/tts_service.py — FPT.AI-VITs TTS qua FPT Cloud Marketplace.

Ưu tiên: FPT Cloud VITS (sync, nhanh ~1-2s) → Fallback VieNeu Sidecar (local).

API: POST https://mkp-api.fptcloud.com/v1/audio/speech
  - model: FPT.AI-VITs
  - voice: std_kimngan (giọng nữ miền Nam, ngọt ngào)
  - response_format: wav
  - Trả WAV audio trực tiếp (sync)
"""
import re
import logging
import httpx

from app.config import settings

logger = logging.getLogger("ufm-chatbot")

# ── Config ─────────────────────────────────────────────────
FPT_CLOUD_TTS_URL = "https://mkp-api.fptcloud.com/v1/audio/speech"
FPT_TTS_MODEL = "FPT.AI-VITs"
FPT_TTS_VOICE = "std_kimngan"  # Giọng nữ miền Nam, tự nhiên
FPT_TTS_TIMEOUT = 15.0  # Cloud API nhanh hơn local

# Fallback: VieNeu-TTS sidecar (local)
TTS_SIDECAR_URL = getattr(settings, "TTS_BASE_URL", "http://localhost:23333")

# Shared HTTP clients
_fpt_client: httpx.AsyncClient | None = None
_sidecar_client: httpx.AsyncClient | None = None


def _get_fpt_client() -> httpx.AsyncClient:
    """Lazy-init FPT Cloud TTS client."""
    global _fpt_client
    if _fpt_client is None or _fpt_client.is_closed:
        _fpt_client = httpx.AsyncClient(
            timeout=httpx.Timeout(FPT_TTS_TIMEOUT, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _fpt_client


def _get_sidecar_client() -> httpx.AsyncClient:
    """Lazy-init VieNeu sidecar client (fallback)."""
    global _sidecar_client
    if _sidecar_client is None or _sidecar_client.is_closed:
        _sidecar_client = httpx.AsyncClient(
            base_url=TTS_SIDECAR_URL,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _sidecar_client


# ── Public API ─────────────────────────────────────────────
async def synthesize(text: str) -> bytes | None:
    """
    Gửi text → TTS → nhận WAV audio bytes.
    Ưu tiên FPT Cloud VITS, fallback VieNeu sidecar.
    """
    if not text or not text.strip():
        return None

    clean_text = _strip_markdown(text)
    if not clean_text or len(clean_text) < 3:
        return None

    # ═══ 1. FPT Cloud VITS (fast, cloud) ═══
    api_key = settings.FPT_CLOUD_API_KEY
    if api_key:
        result = await _synthesize_fpt_cloud(clean_text, api_key)
        if result:
            return result

    # ═══ 2. Fallback: VieNeu sidecar (local) ═══
    return await _synthesize_sidecar(clean_text)


async def _synthesize_fpt_cloud(text: str, api_key: str) -> bytes | None:
    """Gọi FPT Cloud Marketplace VITS API."""
    try:
        client = _get_fpt_client()
        resp = await client.post(
            FPT_CLOUD_TTS_URL,
            json={
                "model": FPT_TTS_MODEL,
                "input": text,
                "response_format": "wav",
                "voice": FPT_TTS_VOICE,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code == 200 and len(resp.content) > 500:
            logger.info(
                f"[tts] ✅ FPT Cloud VITS: {len(text)} chars → "
                f"{len(resp.content)} bytes in {resp.elapsed.total_seconds():.2f}s"
            )
            return resp.content
        else:
            logger.warning(
                f"[tts] ⚠️ FPT Cloud returned {resp.status_code}: "
                f"{resp.text[:200] if resp.text else 'empty'}"
            )
            return None

    except httpx.TimeoutException:
        logger.warning("[tts] ⚠️ FPT Cloud TTS timeout")
        return None
    except Exception as e:
        logger.warning(f"[tts] ⚠️ FPT Cloud TTS error: {e}")
        return None


async def _synthesize_sidecar(text: str) -> bytes | None:
    """Fallback: gọi VieNeu-TTS sidecar local."""
    try:
        client = _get_sidecar_client()
        resp = await client.post(
            "/synthesize",
            json={"text": text, "emotion": "natural"},
        )
        if resp.status_code == 200 and len(resp.content) > 500:
            logger.info(f"[tts] ✅ VieNeu sidecar: {len(resp.content)} bytes")
            return resp.content
        return None
    except httpx.ConnectError:
        logger.debug("[tts] VieNeu sidecar not running (expected if using cloud)")
        return None
    except Exception:
        return None


async def is_available() -> bool:
    """Check TTS khả dụng (FPT Cloud hoặc sidecar)."""
    # FPT Cloud: luôn available nếu có API key
    if settings.FPT_CLOUD_API_KEY:
        return True

    # Fallback: check sidecar
    try:
        client = _get_sidecar_client()
        resp = await client.get("/health")
        return resp.status_code == 200 and resp.json().get("ready", False)
    except Exception:
        return False


async def list_voices() -> list[dict]:
    """Danh sách giọng nói FPT VITS."""
    return [
        {"id": "std_kimngan", "name": "Kim Ngân", "gender": "female", "region": "Nam"},
        {"id": "std_ngochuyen", "name": "Ngọc Huyền", "gender": "female", "region": "Nam"},
        {"id": "std_minhhoang", "name": "Minh Hoàng", "gender": "male", "region": "Nam"},
        {"id": "std_thanhha", "name": "Thanh Hà", "gender": "female", "region": "Bắc"},
        {"id": "std_tienquan", "name": "Tiến Quân", "gender": "male", "region": "Bắc"},
    ]


# ── Helpers ────────────────────────────────────────────────
def _strip_markdown(text: str) -> str:
    """Loại bỏ markdown formatting để TTS đọc tự nhiên."""
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
