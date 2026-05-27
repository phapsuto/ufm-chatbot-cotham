"""app/routes/chat.py — Chat pipeline v3 (xưng hô + contextual suggestions + smart sources)"""
import json
import uuid
import time
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import ChatRequest
from app.services import (
    router_service, crawler_service, pdf_service,
    context_service, memory_service, suggestion_service,
    llm_service, crm_service, cache_service
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

    # 2. Check QA Semantic Cache (Tăng tốc độ trả lời)
    cached_answer = cache_service.get_cached_answer(message)
    if cached_answer:
        logger.info(f"[pipeline] Using QA Cache for '{message[:20]}'")
        
        def generate_cached():
            import asyncio
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
    from app.services import kb_service
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
    # Ngưỡng khớp mạnh từ Reranker BGE-M3 (xác suất 0.0 đến 1.0) thường từ >= 0.6
    kb_has_strong_match = highest_score >= 0.6
    logger.info(f"[pipeline] Offline KB check: search_query='{search_query[:40]}' matches={len(kb_chunks)} highest_score={highest_score:.2f} (strong_match={kb_has_strong_match})")
    
    # 4. Crawl HTML hoặc Tìm kiếm tự do trên Internet nếu là câu hỏi ngoài lề
    html_contents = {}
    pdf_contents = {}
    routing = router_service.detect_intent(search_query)  # Dùng search_query để detect chính xác hơn
    intent = routing["intents"][0] if routing["intents"] else "general"

    # Định nghĩa hàm kiểm tra xem câu hỏi có chứa từ khóa đặc thù UFM không
    def is_ufm_related(text: str) -> bool:
        keywords = ["ufm", "tài chính - marketing", "tài chính marketing", "tai chinh marketing", "cô thắm", "co tham", "sau đại học", "sau dai hoc", "trường mình", "truong minh", "khoa mình", "khoa minh", "chương trình mình", "chuong trinh minh"]
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    is_general = False
    if not kb_has_strong_match:
        # Nếu điểm số khớp offline rất thấp, hoặc là câu hỏi chung/tào lao không liên quan trực tiếp đến UFM
        if highest_score < 0.45 or intent == "general" or not is_ufm_related(message):
            logger.info(f"[pipeline] Unrelated/General/Tào lao question detected (score={highest_score:.4f}, intent={intent}). Triggering DuckDuckGo Internet Search for: '{message}'")
            ddg_results = crawler_service.web_search_ddg(message)
            if ddg_results:
                html_contents["internet_search"] = ddg_results
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
    context, sources_used = context_service.build_context(html_contents, pdf_contents, mem_summary, message, search_query=search_query, level=level, major=major)

    # 6. Pre-compute metadata
    # Nếu có kb_chunks với điểm cao, độ tự tin tự động đạt mức cao (1.0)
    if kb_has_strong_match:
        confidence = 1.0
    else:
        confidence = context_service.estimate_confidence(html_contents, pdf_contents)
        
    requires_handoff = confidence < 0.4 or suggestion_service.check_handoff_trigger(message)
    history = memory_service.get_conversation_history(session_id)
    
    elapsed = time.time() - t0
    logger.info(f"[pipeline] prep={elapsed:.1f}s html={len(html_contents)} pdf={len(pdf_contents)} kb={len(kb_chunks)}")

    # 7. Stream LLM response — pass context_summary for xưng hô + is_general
    def generate():
        full_response = ""
        for chunk in llm_service.get_response_stream(context, message, history, session_id, context_summary=mem_summary, is_general=is_general):
            if chunk.startswith("__FULL__"):
                full_response = chunk[8:]
                continue
            yield f"data: {chunk}\n\n"

        # --- Post-stream: generate contextual suggestions ---
        ctx = memory_service.get_or_create_session(session_id)["context"]
        asked_about = ctx.get("asked_about", [])

        # Try LLM-generated suggestions (nếu có answer)
        if full_response:
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

        # Send metadata
        meta = json.dumps({
            "done": True,
            "session_id": session_id,
            "sources": sources_json,
            "suggestions": suggestions,
            "requires_handoff": requires_handoff,
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
