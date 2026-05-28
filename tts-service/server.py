"""
tts-service/server.py — VieNeu-TTS v2 Sidecar API Server
Phục vụ tổng hợp giọng nói tiếng Việt cho UFM Chatbot (Cô Giáo Thắm).
Model: VieNeu-TTS-v2 GGUF Q8 (~500MB, CPU)
Voice: Thục Đoan (nữ, miền Nam, nhẹ nhàng)
"""
import io
import re
import time
import wave
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("tts-service")

# ── Global TTS engine ─────────────────────────────────────
_tts = None
_default_voice = None
_voice_name = "default"

PREFERRED_VOICES = ["Thục Đoan", "thuc_doan", "Dung", "dung"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load TTS model once at startup — avoid cold-start per request."""
    global _tts, _default_voice, _voice_name
    logger.info("🔄 Loading VieNeu-TTS v2 model...")
    start = time.time()

    try:
        from vieneu import Vieneu
        _tts = Vieneu(emotion="natural")

        # Tìm giọng nữ miền Nam
        voices = _tts.list_preset_voices()
        logger.info(f"📋 Available voices: {[d for d, _ in voices]}")

        for preferred in PREFERRED_VOICES:
            for desc, vid in voices:
                if preferred.lower() in desc.lower() or preferred.lower() in vid.lower():
                    _default_voice = _tts.get_preset_voice(vid)
                    _voice_name = desc
                    logger.info(f"✅ Selected voice: {desc} (ID: {vid})")
                    break
            if _default_voice:
                break

        if not _default_voice:
            _voice_name = voices[0][0] if voices else "default"
            logger.info(f"⚠️ Preferred voice not found, using: {_voice_name}")

        elapsed = time.time() - start
        logger.info(f"✅ TTS model loaded in {elapsed:.1f}s — Voice: {_voice_name}")
    except Exception as e:
        logger.error(f"❌ Failed to load TTS model: {e}")
        raise

    yield

    logger.info("🛑 TTS service shutting down")


app = FastAPI(title="VieNeu-TTS Sidecar", version="1.0.0", lifespan=lifespan)


# ── Models ─────────────────────────────────────────────────
class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    emotion: str = "natural"


class VoiceInfo(BaseModel):
    name: str
    id: str


# ── Helpers ────────────────────────────────────────────────
def _split_sentences(text: str) -> list[str]:
    """Tách text thành câu ngắn để TTS nhanh hơn."""
    # Strip markdown formatting
    clean = re.sub(r'\*\*|__|~~|`|#{1,6}\s*', '', text)
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)  # [text](url) → text
    clean = re.sub(r'[-*•]\s+', '', clean)  # Bullet points
    clean = re.sub(r'\s+', ' ', clean).strip()

    if not clean:
        return []

    # Tách theo dấu câu
    sentences = re.split(r'(?<=[.!?;:])\s+|\n+', clean)
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 1]


def _audio_to_wav_bytes(audio_data) -> bytes:
    """Convert audio data from vieneu to WAV bytes."""
    buf = io.BytesIO()
    _tts.save(audio_data, buf)
    buf.seek(0)
    return buf.read()


def _concat_wav_bytes(parts: list[bytes]) -> bytes:
    """Nối nhiều WAV files thành 1."""
    if not parts:
        return b""
    if len(parts) == 1:
        return parts[0]

    # Đọc params từ file đầu tiên
    with io.BytesIO(parts[0]) as f:
        with wave.open(f, 'rb') as w:
            params = w.getparams()
            frames = [w.readframes(w.getnframes())]

    # Đọc frames từ các file còn lại
    for p in parts[1:]:
        with io.BytesIO(p) as f:
            with wave.open(f, 'rb') as w:
                frames.append(w.readframes(w.getnframes()))

    # Ghi file WAV kết hợp
    output = io.BytesIO()
    with wave.open(output, 'wb') as w:
        w.setparams(params)
        for frame in frames:
            w.writeframes(frame)

    output.seek(0)
    return output.read()


# ── Endpoints ──────────────────────────────────────────────
@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Tổng hợp giọng nói từ text → WAV audio."""
    if not _tts:
        raise HTTPException(503, "TTS model not loaded")

    if not req.text or not req.text.strip():
        raise HTTPException(400, "Text is empty")

    start = time.time()

    try:
        sentences = _split_sentences(req.text)
        if not sentences:
            raise HTTPException(400, "No speakable text found after cleanup")

        audio_parts = []
        for sentence in sentences:
            if _default_voice:
                audio = _tts.infer(text=sentence, voice=_default_voice)
            else:
                audio = _tts.infer(text=sentence)
            wav_bytes = _audio_to_wav_bytes(audio)
            audio_parts.append(wav_bytes)

        result = _concat_wav_bytes(audio_parts)
        elapsed = time.time() - start

        logger.info(
            f"✅ Synthesized {len(sentences)} sentences "
            f"({len(req.text)} chars) in {elapsed:.2f}s → {len(result)} bytes"
        )

        return Response(
            content=result,
            media_type="audio/wav",
            headers={
                "X-TTS-Duration": f"{elapsed:.3f}",
                "X-TTS-Sentences": str(len(sentences)),
                "X-TTS-Voice": _voice_name,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Synthesis failed: {e}")
        raise HTTPException(500, f"Synthesis failed: {str(e)}")


@app.get("/voices", response_model=list[VoiceInfo])
async def list_voices():
    """Danh sách giọng nói preset."""
    if not _tts:
        raise HTTPException(503, "TTS model not loaded")
    return [VoiceInfo(name=d, id=v) for d, v in _tts.list_preset_voices()]


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "ok" if _tts else "loading",
        "model": "VieNeu-TTS-v2-GGUF-Q8",
        "voice": _voice_name,
        "ready": _tts is not None,
    }
