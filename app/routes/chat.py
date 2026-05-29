"""app/routes/chat.py — Chat pipeline v3 (xưng hô + contextual suggestions + smart sources)"""
import json
import uuid
import time
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response

from app.models import ChatRequest
from app.services import (
    router_service, crawler_service, pdf_service,
    context_service, memory_service, suggestion_service,
    llm_service, crm_service, cache_service, kb_service
)

logger = logging.getLogger("ufm-chatbot")
router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        return {"error": "Vui lòng nhập câu hỏi"}

    session_id = req.session_id or str(uuid.uuid4())
    t0 = time.time()

    # 1. Session + Pronoun detection (TRƯỚC TIÊN)
    memory_service.get_or_create_session(session_id)
    memory_service.update_pronoun_early(session_id, message)

    # Lưu giới tính từ frontend (nếu có)
    if req.gender:
        sess = memory_service.get_or_create_session(session_id)
        sess["context"]["user_gender"] = req.gender  # "nam" hoặc "nu"

    # 2. Check QA Semantic Cache (Tăng tốc độ trả lời)
    cached_answer = cache_service.get_cached_answer(message)
    if cached_answer:
        logger.info(f"[pipeline] Using QA Cache for '{message[:20]}'")
        
        def generate_cached():
            # Giả lập stream cực nhanh
            chunk_size = max(5, len(cached_answer) // 20)
            for i in range(0, len(cached_answer), chunk_size):
                chunk_data = json.dumps({"content": cached_answer[i:i+chunk_size], "session_id": session_id})
                yield f"data: {chunk_data}\n\n"
                
            ctx = memory_service.get_or_create_session(session_id)["context"]
            suggestions = suggestion_service.get_suggestions("general", ctx.get("asked_about", []))
            
            meta = json.dumps({
                "done": True,
                "session_id": session_id,
                "sources": [{"title": "Cached Database", "url": "#", "type": "cache"}],
                "suggestions": suggestions,
                "requires_handoff": False,
            })
            yield f"data: {meta}\n\n"
            yield "data: [DONE]\n\n"
            
            # Cập nhật lịch sử
            memory_service.add_message(session_id, "user", message)
            memory_service.add_message(session_id, "assistant", cached_answer)
            try:
                crm_service.update_chat_behavior(session_id, message, "general")
            except Exception:
                pass

        return StreamingResponse(
            generate_cached(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # 3. Tra cứu Offline KB trước (BM25 siêu tốc)
    # Mở rộng câu hỏi dựa vào ngữ cảnh bộ nhớ để tránh mất context khi hỏi tiếp (follow-up)
    search_keywords = memory_service.get_search_expansion_keywords(session_id, message)
    search_query = message
    if search_keywords:
        # Lọc các từ khóa chưa có trong câu hỏi hiện tại để tránh lặp từ vô ích
        missing_keywords = [kw for kw in search_keywords.split() if kw.lower() not in message.lower()]
        if missing_keywords:
            search_query = f"{message} {' '.join(missing_keywords)}"
            logger.info(f"[pipeline] Expanded query from '{message}' to '{search_query}'")

    ctx = memory_service.get_or_create_session(session_id)["context"]
    level = ctx.get("interested_level")
    major = ctx.get("interested_major")

    kb_chunks = kb_service.search_kb(search_query, top_k=5, level=level, major=major)
    highest_score = max(chunk["score"] for chunk in kb_chunks) if kb_chunks else 0.0
    # Ngưỡng khớp mạnh từ Hybrid Reranker (0.3*keyword + 0.7*BGE-M3)
    # BGE-M3 sigmoid score 0.3+ đã là match tốt, nhân 0.7 ≈ 0.21, cộng keyword ≈ 0.35
    kb_has_strong_match = highest_score >= 0.35
    logger.info(f"[pipeline] Offline KB: query='{search_query[:40]}' matches={len(kb_chunks)} best_score={highest_score:.3f} (strong={kb_has_strong_match})")
    
    # 4. Crawl HTML hoặc Tìm kiếm tự do trên Internet nếu là câu hỏi ngoài lề
    html_contents = {}
    pdf_contents = {}
    voice_mode = req.voice_mode

    # Helper: kiểm tra câu hỏi UFM
    def is_ufm_related(text: str) -> bool:
        keywords = ["ufm", "tài chính - marketing", "tài chính marketing", "tai chinh marketing", "cô thắm", "co tham", "sau đại học", "sau dai hoc", "trường mình", "truong minh", "khoa mình", "khoa minh", "chương trình mình", "chuong trinh minh"]
        return any(kw in text.lower() for kw in keywords)

    # ══ VOICE FAST PATH: skip crawling cho tốc độ ══
    if voice_mode:
        routing = router_service.detect_intent(search_query)
        intent = routing["intents"][0] if routing["intents"] else "general"
        is_general = not kb_has_strong_match and not is_ufm_related(message)
        if is_general and not kb_has_strong_match:
            # Chỉ search web nếu KB hoàn toàn trống (score < 0.1)
            if highest_score < 0.1:
                logger.info(f"[voice-fast] No KB match, quick Gemini search")
                search_results = await crawler_service.web_search_gemini(message)
                if search_results:
                    html_contents["internet_search"] = search_results
        logger.info(f"[voice-fast] Skipped crawling, KB={len(kb_chunks)} score={highest_score:.3f}")
    else:
        # ══ TEXT MODE: pipeline đầy đủ ══
        routing = router_service.detect_intent(search_query)
        intent = routing["intents"][0] if routing["intents"] else "general"

        is_general = False
        if not kb_has_strong_match:
            if highest_score < 0.15 or (intent == "general" and not is_ufm_related(message)):
                logger.info(f"[pipeline] Unrelated/General question (score={highest_score:.4f}, intent={intent}). Triggering Gemini Google Search for: '{message}'")
                search_results = await crawler_service.web_search_gemini(message)
                if search_results:
                    html_contents["internet_search"] = search_results
                is_general = True
            elif routing.get("urls"):
                logger.info("[pipeline] KB match low but UFM-related. Falling back to Web Crawler...")
                html_contents = await crawler_service.crawl_multiple(routing["urls"], max_urls=4)
                if html_contents:
                    all_html = "\n".join(html_contents.values())
                    pdf_links = pdf_service.extract_pdf_links(all_html)
                    if pdf_links:
                        max_pdfs = 2 if routing.get("need_pdf") else 1
                        pdf_contents = await pdf_service.read_pdfs(pdf_links, max_pdfs=max_pdfs)
        else:
            logger.info("[pipeline] Strong KB match found, skipping Web Crawler!")

    # 5. Build context + context summary (có pronoun_role)
    mem_summary = memory_service.get_context_summary(session_id)
    context, sources_used = context_service.build_context(html_contents, pdf_contents, mem_summary, message, kb_chunks=kb_chunks)

    # 6. Pre-compute metadata
    # Nếu có kb_chunks với điểm cao, độ tự tin tự động đạt mức cao (1.0)
    if kb_has_strong_match:
        confidence = 1.0
    else:
        confidence = context_service.estimate_confidence(html_contents, pdf_contents)
        
    requires_handoff = confidence < 0.4 or suggestion_service.check_handoff_trigger(message)
    history = memory_service.get_conversation_history(session_id)
    
    elapsed = time.time() - t0
    logger.info(f"[pipeline] prep={elapsed:.1f}s html={len(html_contents)} pdf={len(pdf_contents)} kb={len(kb_chunks)} voice={voice_mode}")

    # 7. Stream LLM response — pass context_summary for xưng hô + is_general + voice_mode
    def generate():
        full_response = ""
        for chunk in llm_service.get_response_stream(context, message, history, session_id, context_summary=mem_summary, is_general=is_general, voice_mode=voice_mode):
            if chunk.startswith("__FULL__"):
                full_response = chunk[8:]
                continue
            yield f"data: {chunk}\n\n"

        # --- Post-stream: generate contextual suggestions ---
        ctx = memory_service.get_or_create_session(session_id)["context"]
        asked_about = ctx.get("asked_about", [])

        # Voice mode: skip LLM suggestions (tốn 2-3s), dùng static suggestions
        if voice_mode:
            suggestions = suggestion_service.get_suggestions(intent, asked_about)
        elif full_response:
            suggestions = suggestion_service.generate_contextual_suggestions(
                answer=full_response,
                query=message,
                intent=intent,
                asked_about=asked_about,
            )
        else:
            suggestions = suggestion_service.get_suggestions(intent, asked_about)

        # Filter relevant sources
        filtered_sources = context_service.filter_relevant_sources(full_response, sources_used)
        # Format sources for JSON
        sources_json = [
            {"url": s["url"], "title": s["title"], "type": s["type"]}
            for s in filtered_sources
        ]

        # Send metadata (kèm thông tin xưng hô để frontend hiển thị typing message đúng)
        pronoun_ctx = memory_service.get_or_create_session(session_id)["context"].get("pronoun_role") or {}
        meta = json.dumps({
            "done": True,
            "session_id": session_id,
            "sources": sources_json,
            "suggestions": suggestions,
            "requires_handoff": requires_handoff,
            "co_tham_xung": pronoun_ctx.get("co_tham_xung", "em"),
        })
        yield f"data: {meta}\n\n"
        yield "data: [DONE]\n\n"

        # Save memory
        memory_service.add_message(session_id, "user", message)
        memory_service.add_message(session_id, "assistant", full_response)
        memory_service.update_context(session_id, intent, message)
        
        # Save to QA Cache for future identical/similar questions
        cache_service.set_cached_answer(message, full_response)

        # CRM: track behavior + re-score
        try:
            crm_service.update_chat_behavior(session_id, message, intent)
        except Exception as e:
            logger.warning(f"[crm] tracking error: {e}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ── TTS (Text-to-Speech) Endpoints ─────────────────────────
from pydantic import BaseModel

class TTSRequest(BaseModel):
    text: str


@router.post("/api/tts/speak")
async def tts_speak(req: TTSRequest):
    """Tổng hợp giọng nói từ text → WAV audio (gọi TTS sidecar)."""
    from app.services import tts_service

    audio = await tts_service.synthesize(req.text)
    if audio:
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"Content-Disposition": "inline; filename=co_tham.wav"},
        )
    raise HTTPException(status_code=503, detail="TTS service không khả dụng — vui lòng thử lại")


@router.get("/api/tts/health")
async def tts_health():
    """Kiểm tra TTS sidecar status."""
    from app.services import tts_service

    available = await tts_service.is_available()
    return {"tts_available": available}
