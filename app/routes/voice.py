"""
app/routes/voice.py — Cổng kết nối giọng nói thời gian thực qua WebSocket (/ws/voice).
Điều phối luồng: Nhận PCM 16kHz ➔ ASR ➔ RAG ➔ DeepSeek-V4-Flash Stream ➔ TTS Stream ➔ Trả âm thanh.
"""
import json
import logging
import asyncio
import re
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services import (
    asr_service, tts_service, kb_service, context_service,
    memory_service, flare_service
)
from app.routes.chat import clean_context_artifacts

logger = logging.getLogger("ufm-chatbot")
router = APIRouter()


def split_into_sentences(text: str) -> list[str]:
    """Tách đoạn văn bản thành các câu ngắn dựa trên dấu chấm câu tiếng Việt."""
    # Tách theo các dấu kết thúc câu phổ biến
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


@router.websocket("/ws/voice")
async def voice_websocket(
    websocket: WebSocket,
    session_id: str = "voice_default",
    gender: str = "nam",
    level: str = "sau_dai_hoc",
    major: str = "marketing"
):
    await websocket.accept()
    logger.info(f"[ws-voice] ✅ Client connected: session={session_id} gender={gender} level={level} major={major}")

    # Đảm bảo session được khởi tạo
    memory_service.get_or_create_session(session_id)
    sess = memory_service.get_or_create_session(session_id)
    sess["context"]["user_gender"] = gender
    sess["context"]["interested_level"] = level
    sess["context"]["interested_major"] = major

    audio_buffer = bytearray()
    speech_ready_event = asyncio.Event()
    abort_event = asyncio.Event()

    async def receive_messages():
        nonlocal audio_buffer
        try:
            while True:
                msg = await websocket.receive()
                if "bytes" in msg:
                    # Nhận dữ liệu PCM thô từ Client
                    audio_buffer.extend(msg["bytes"])
                elif "text" in msg:
                    data = json.loads(msg["text"])
                    msg_type = data.get("type")
                    
                    if msg_type == "speech_start":
                        logger.info("[ws-voice] 🎙️ Khách bắt đầu nói. Abort phản hồi hiện tại.")
                        abort_event.set()
                        audio_buffer.clear()
                        # Gửi tin hiệu dừng phát âm thanh ngay lập tức (Barge-in)
                        await websocket.send_json({"type": "stop_audio"})
                    
                    elif msg_type == "speech_end":
                        logger.info(f"[ws-voice] 🔇 Khách dừng nói. Kích hoạt ASR cho {len(audio_buffer)} bytes.")
                        abort_event.clear()
                        speech_ready_event.set()
                    
                    elif msg_type == "abort":
                        logger.info("[ws-voice] ⏹️ Nhận lệnh dừng (Abort).")
                        abort_event.set()
                        audio_buffer.clear()
                        await websocket.send_json({"type": "stop_audio"})
                        
        except WebSocketDisconnect:
            logger.info("[ws-voice] Client disconnected.")
        except Exception as e:
            logger.error(f"[ws-voice] Lỗi trong luồng nhận tin nhắn: {e}")

    # Chạy luồng nhận tin nhắn ngầm
    receive_task = asyncio.create_task(receive_messages())

    try:
        while True:
            # Chờ sự kiện có âm thanh sẵn sàng để dịch
            await speech_ready_event.wait()
            speech_ready_event.clear()

            if abort_event.is_set():
                continue

            # Lấy toàn bộ âm thanh trong buffer ra xử lý
            raw_audio = bytes(audio_buffer)
            audio_buffer.clear()

            # Trạng thái: Đang dịch ASR
            await websocket.send_json({"type": "status", "status": "processing_asr"})

            # 1. Chuyển đổi âm thanh sang văn bản (STT/ASR)
            transcribed_text = await asr_service.transcribe(raw_audio)
            
            if abort_event.is_set():
                continue

            if not transcribed_text or len(transcribed_text.strip()) < 2:
                logger.warning("[ws-voice] Không nhận dạng được giọng nói hoặc âm thanh quá ngắn.")
                await websocket.send_json({
                    "type": "error", 
                    "message": "Dạ, cô chưa nghe rõ lắm, em nói lại giúp cô nha! 😊"
                })
                await websocket.send_json({"type": "status", "status": "idle"})
                continue

            # Gửi text đã nhận dạng được về cho Client hiển thị
            await websocket.send_json({"type": "transcript", "text": transcribed_text})

            # Trạng thái: Đang chuẩn bị câu trả lời RAG
            await websocket.send_json({"type": "status", "status": "thinking"})

            # 2. Xử lý RAG + LLM giống như pipeline của chat thường
            search_keywords = memory_service.get_search_expansion_keywords(session_id, transcribed_text)
            search_query = transcribed_text
            if search_keywords:
                missing_keywords = [kw for kw in search_keywords.split() if kw.lower() not in transcribed_text.lower()]
                if missing_keywords:
                    search_query = f"{transcribed_text} {' '.join(missing_keywords)}"

            # Tra cứu KB
            kb_chunks = kb_service.search_kb(search_query, top_k=3, level=level, major=major)
            mem_summary = memory_service.get_context_summary(session_id)
            
            # Xây dựng context RAG (chế độ voice_mode bỏ qua cào web sâu để tối ưu tốc độ)
            context, sources_used = context_service.build_context(
                html_contents={}, pdf_contents={}, mem_summary=mem_summary, 
                message=transcribed_text, kb_chunks=kb_chunks
            )

            # Lịch sử hội thoại
            history = memory_service.get_conversation_history(session_id)

            # 3. Stream phản hồi từ DeepSeek-V4-Flash và tổng hợp TTS theo câu
            sentence_buffer = ""
            full_response = ""
            
            # Trạng thái: Bắt đầu trả lời
            await websocket.send_json({"type": "status", "status": "answering"})

            # Chạy FLARE stream
            loop = asyncio.get_event_loop()
            for chunk in flare_service.flare_generate_stream(
                transcribed_text, context, sources_used, mem_summary, history, session_id,
                is_general=False, voice_mode=True
            ):
                if abort_event.is_set():
                    logger.info("[ws-voice] Hủy sinh phản hồi do có tín hiệu ngắt lời.")
                    break

                if chunk.startswith("__FULL__"):
                    full_response = clean_context_artifacts(chunk[8:])
                    continue
                if chunk.startswith("__SOURCES__"):
                    continue

                try:
                    data = json.loads(chunk)
                    token = data.get("content", "")
                except Exception:
                    token = chunk

                # Gửi token về Web UI để hiển thị chữ chạy
                await websocket.send_json({"type": "bot_token", "text": token})
                
                sentence_buffer += token

                # Khi có một câu tương đối hoàn chỉnh (kết thúc bằng dấu câu)
                if any(p in token for p in [".", "?", "!", "\n"]) and len(sentence_buffer.strip()) > 8:
                    clean_sentence = clean_context_artifacts(sentence_buffer.strip())
                    sentence_buffer = ""

                    if clean_sentence:
                        # 4. Gửi câu sang TTS để tổng hợp WAV
                        logger.info(f"[ws-voice] TTS start for sentence: '{clean_sentence}'")
                        audio_bytes = await tts_service.synthesize(clean_sentence)
                        
                        if abort_event.is_set():
                            break

                        if audio_bytes:
                            # Stream binary bytes âm thanh trực tiếp về client qua WebSocket
                            await websocket.send_bytes(audio_bytes)
                            logger.info(f"[ws-voice] Sent {len(audio_bytes)} bytes audio to client.")
            
            # Xử lý phần text còn dư lại ở cuối (nếu có)
            if not abort_event.is_set() and sentence_buffer.strip():
                clean_sentence = clean_context_artifacts(sentence_buffer.strip())
                if clean_sentence:
                    audio_bytes = await tts_service.synthesize(clean_sentence)
                    if audio_bytes and not abort_event.is_set():
                        await websocket.send_bytes(audio_bytes)

            # Kết thúc lượt
            if not abort_event.is_set() and full_response:
                # Lưu lịch sử chat
                memory_service.add_message(session_id, "user", transcribed_text)
                memory_service.add_message(session_id, "assistant", full_response)
                
            await websocket.send_json({"type": "done"})
            await websocket.send_json({"type": "status", "status": "idle"})

    except Exception as e:
        logger.error(f"[ws-voice] Lỗi kết nối WebSocket: {e}")
    finally:
        receive_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("[ws-voice] Connection cleaned up.")
