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
    llm_service, crm_service,
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

    # 2. Detect intent
    routing = router_service.detect_intent(message)

    # 3. Crawl HTML
    html_contents = await crawler_service.crawl_multiple(routing["urls"], max_urls=4)

    # 4. Extract & read PDFs (always scan for PDF links in HTML)
    pdf_contents = {}
    if html_contents:
        all_html = "\n".join(html_contents.values())
        pdf_links = pdf_service.extract_pdf_links(all_html)
        if pdf_links:
            max_pdfs = 2 if routing["need_pdf"] else 1
            pdf_contents = await pdf_service.read_pdfs(pdf_links, max_pdfs=max_pdfs)

    # 5. Build context + context summary (có pronoun_role)
    mem_summary = memory_service.get_context_summary(session_id)
    context, sources_used = context_service.build_context(html_contents, pdf_contents, mem_summary, message)

    # 6. Pre-compute metadata
    confidence = context_service.estimate_confidence(html_contents, pdf_contents)
    requires_handoff = confidence < 0.4 or suggestion_service.check_handoff_trigger(message)
    history = memory_service.get_conversation_history(session_id)
    intent = routing["intents"][0] if routing["intents"] else "general"

    elapsed = time.time() - t0
    logger.info(f"[pipeline] prep={elapsed:.1f}s html={len(html_contents)} pdf={len(pdf_contents)}")

    # 7. Stream LLM response — pass context_summary for xưng hô
    def generate():
        full_response = ""
        for chunk in llm_service.get_response_stream(context, message, history, session_id, context_summary=mem_summary):
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
