"""
app/services/asr_service.py — Dịch vụ nhận dạng giọng nói ASR qua FPT Cloud Marketplace.

API: POST https://mkp-api.fptcloud.com/v1/audio/transcriptions
  - Tương thích với cấu trúc OpenAI audio transcription.
  - Sử dụng chung FPT_CLOUD_API_KEY từ file cấu hình .env.
"""
import io
import wave
import logging
import httpx
from app.config import settings

logger = logging.getLogger("ufm-chatbot")

FPT_CLOUD_ASR_URL = "https://mkp-api.fptcloud.com/v1/audio/transcriptions"
FPT_ASR_MODEL = "whisper-large-v3-turbo"
FPT_ASR_TIMEOUT = 12.0

_asr_client: httpx.AsyncClient | None = None


def _get_asr_client() -> httpx.AsyncClient:
    global _asr_client
    if _asr_client is None or _asr_client.is_closed:
        _asr_client = httpx.AsyncClient(
            timeout=httpx.Timeout(FPT_ASR_TIMEOUT, connect=5.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _asr_client


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Chuyển đổi dữ liệu PCM 16-bit thô thành định dạng WAV hoàn chỉnh."""
    wav_io = io.BytesIO()
    with wave.open(wav_io, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_io.getvalue()


async def transcribe(pcm_data: bytes) -> str | None:
    """
    Chuyển đổi mảng byte PCM thành WAV và gọi FPT Cloud ASR API.
    """
    if not pcm_data or len(pcm_data) < 3200:  # Ít hơn 0.1 giây âm thanh
        return None

    api_key = settings.FPT_CLOUD_API_KEY
    if not api_key:
        logger.warning("[asr] Không tìm thấy FPT_CLOUD_API_KEY trong cấu hình.")
        return None

    # Chuyển PCM sang WAV
    wav_data = pcm_to_wav(pcm_data)

    try:
        client = _get_asr_client()
        files = {
            "file": ("voice.wav", wav_data, "audio/wav")
        }
        data = {
            "model": FPT_ASR_MODEL,
            "response_format": "json",
            "language": "vi"
        }
        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        resp = await client.post(
            FPT_CLOUD_ASR_URL,
            headers=headers,
            data=data,
            files=files
        )

        if resp.status_code == 200:
            result = resp.json()
            text = result.get("text", "").strip()
            logger.info(f"[asr] ✅ Nhận dạng thành công: '{text[:60]}...' ({len(pcm_data)} bytes)")
            return text
        else:
            logger.error(f"[asr] ❌ FPT Cloud ASR trả về mã {resp.status_code}: {resp.text[:200]}")
            return None

    except httpx.TimeoutException:
        logger.error("[asr] ⏳ Lỗi hết thời gian chờ (Timeout) khi gọi FPT ASR API.")
        return None
    except Exception as e:
        logger.error(f"[asr] 💥 Lỗi ngoại lệ trong quá trình nhận dạng: {e}")
        return None
