"""app/services/flare_service.py — Tier 5 (FLARE Active RAG) and active search logic"""
import re
import json
import logging
import asyncio
import nest_asyncio
from typing import Generator
from app.services import (
    kb_service, crawler_service, pdf_service,
    context_service, router_service, memory_service,
    llm_service
)

logger = logging.getLogger("ufm-chatbot")

FLARE_DRAFT_SYSTEM_PROMPT = """Bạn là Cô giáo Thắm — trợ lý tư vấn tuyển sinh Sau Đại học tại UFM.

QUY TẮC ĐẶC BIỆT KHI SOẠN THẢO NHÁP (FLARE DRAFT MODE):
1. Dựa trên [NỘI DUNG TỪ WEBSITE UFM] hiện có để nháp câu trả lời.
2. Khi trích dẫn thông tin học vụ, quy chế, hoặc điều kiện xét tuyển, bạn bắt buộc phải chỉ rõ nguồn bằng cách thêm thẻ neo tương ứng ở cuối câu (ví dụ: "[C1]", "[C2]",...).
3. Nếu câu trả lời cần nhắc tới một số liệu học phí, ngày tuyển sinh, hoặc quy chế cụ thể mà tài liệu hiện tại CHƯA cung cấp:
   -> Hãy chèn thẻ placeholder dạng `[SEARCH: <từ khóa tuyển sinh cụ thể cần tìm>]` ngay tại vị trí cần thông tin đó.
   -> Ví dụ: "Học phí thạc sĩ năm nay là [SEARCH: học phí thạc sĩ ufm 2026] và nộp theo đợt [C1]."
4. Sau placeholder, tiếp tục viết phần còn lại của câu trả lời nháp bình thường.
5. Tuyệt đối không tự bịa thông tin nếu thiếu, bắt buộc phải dùng thẻ [SEARCH: ...] để yêu cầu hệ thống tra cứu.
"""

FLARE_FINAL_SYSTEM_PROMPT = """Bạn là Cô giáo Thắm — trợ lý tư vấn tuyển sinh Sau Đại học tại UFM.

QUY TẮC TUYỆT ĐỐI (Citation & Groundedness):
1. Hãy viết câu trả lời hoàn chỉnh dựa trên các tài liệu tuyển sinh bổ sung dưới đây. Tuyệt đối không tự nhắc đến các từ kỹ thuật như "ngữ cảnh", "context", "tài liệu bổ sung" trong câu trả lời. Hãy trả lời một cách tự nhiên (ví dụ: "Theo quy định..." hoặc "Hiện tại trường chưa công bố...").
2. Khi trích dẫn thông tin, bắt buộc phải kèm theo ký hiệu neo trích dẫn ở cuối câu: "Điều kiện xét tuyển là X [C1]".
3. Tuyệt đối KHÔNG sử dụng thẻ placeholder `[SEARCH: ...]` trong câu trả lời này nữa.
4. Nếu vẫn thiếu thông tin, hãy nói rõ không tìm thấy trên website trường và hướng dẫn liên hệ phòng Sau đại học. Không bịa đặt thông tin.
"""

async def retrieve_context_for_query(
    query: str,
    session_id: str,
    mem_summary: str,
    voice_mode: bool = False,
) -> tuple[str, list[dict]]:
    sess = memory_service.get_or_create_session(session_id)
    ctx = sess["context"]
    level = ctx.get("interested_level")
    major = ctx.get("interested_major")
    
    kb_chunks = kb_service.search_kb(query, top_k=3, level=level, major=major)
    highest_score = max(chunk["score"] for chunk in kb_chunks) if kb_chunks else 0.0
    kb_has_strong_match = highest_score >= 0.35
    
    html_contents = {}
    pdf_contents = {}
    
    def is_ufm_related(text: str) -> bool:
        keywords = ["ufm", "tài chính - marketing", "tài chính marketing", "tai chinh marketing", "cô thắm", "co tham", "sau đại học", "sau dai hoc", "trường mình", "truong minh", "khoa mình", "khoa minh", "chương trình mình", "chuong trinh minh"]
        return any(kw in text.lower() for kw in keywords)
        
    is_general = not kb_has_strong_match and not is_ufm_related(query)
    
    if voice_mode:
        if is_general and not kb_has_strong_match and highest_score < 0.1:
            search_results = await crawler_service.web_search_gemini(query)
            if search_results:
                html_contents["internet_search"] = search_results
    else:
        routing = router_service.detect_intent(query)
        intent = routing["intents"][0] if routing["intents"] else "general"
        if not kb_has_strong_match:
            if highest_score < 0.15 or (intent == "general" and not is_ufm_related(query)):
                search_results = await crawler_service.web_search_gemini(query)
                if search_results:
                    html_contents["internet_search"] = search_results
            elif routing.get("urls"):
                html_contents = await crawler_service.crawl_multiple(routing["urls"], max_urls=3)
                if html_contents:
                    all_html = "\n".join(html_contents.values())
                    pdf_links = pdf_service.extract_pdf_links(all_html)
                    if pdf_links:
                        max_pdfs = 2 if routing.get("need_pdf") else 1
                        pdf_contents = await pdf_service.read_pdfs(pdf_links, max_pdfs=max_pdfs)
                        
    context, sources_used = context_service.build_context(
        html_contents, pdf_contents, mem_summary, query, kb_chunks=kb_chunks
    )
    return context, sources_used

def flare_generate_stream(
    query: str,
    initial_context: str,
    sources_used: list[dict],
    mem_summary: str,
    history: list[dict],
    session_id: str,
    is_general: bool = False,
    voice_mode: bool = False,
) -> Generator:
    """
    Yields streaming chunks for the FLARE process.
    - Pass 1: Generates draft. If [SEARCH: ...] placeholders exist, triggers active retrieval.
    - Pass 2: Merges new context and streams the final answer tokens back to the user.
    """
    word_count = len(query.split())
    is_simple = word_count < 15 or voice_mode or is_general
    
    if is_simple:
        logger.info("[flare] Simple query or voice mode. Skipping active draft phase.")
        for chunk in llm_service.get_response_stream(
            initial_context, query, history, session_id,
            context_summary=mem_summary, is_general=is_general, voice_mode=voice_mode
        ):
            yield chunk
        return
        
    logger.info("[flare] Generating draft answer...")
    
    # ── FIRST PASS: DRAFT GENERATION ──
    draft_text = ""
    for chunk in llm_service.get_response_stream(
        initial_context, query, history, session_id,
        context_summary=mem_summary, is_general=False, voice_mode=False,
        system_prompt_override=FLARE_DRAFT_SYSTEM_PROMPT
    ):
        if chunk.startswith("__FULL__"):
            draft_text = chunk[8:]
            
    if not draft_text:
        logger.warning("[flare] Draft generation failed or empty. Falling back to direct stream.")
        for chunk in llm_service.get_response_stream(
            initial_context, query, history, session_id,
            context_summary=mem_summary, is_general=is_general, voice_mode=voice_mode
        ):
            yield chunk
        return
        
    # Parse [SEARCH: ...] placeholders
    placeholders = re.findall(r'\[SEARCH:\s*(.*?)\]', draft_text)
    
    if not placeholders:
        logger.info("[flare] No placeholders found in draft. Yielding draft directly.")
        chunk_size = max(5, len(draft_text) // 20)
        for i in range(0, len(draft_text), chunk_size):
            yield json.dumps({"content": draft_text[i:i+chunk_size], "session_id": session_id})
        yield "__FULL__" + draft_text
        return
        
    # ── ACTIVE RETRIEVAL PHASE ──
    logger.info(f"[flare] Found placeholders: {placeholders}. Triggering active search...")
    
    context_pool = [initial_context]
    final_sources = list(sources_used)
    
    # Get current event loop or create one
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    for keyword in placeholders[:2]:
        keyword = keyword.strip()
        if not keyword:
            continue
        logger.info(f"[flare] Active Search: '{keyword}'...")
        try:
            if loop.is_running():
                nest_asyncio.apply()
            new_context, new_sources = loop.run_until_complete(
                retrieve_context_for_query(keyword, session_id, mem_summary, voice_mode)
            )
            if new_context and "Không thể truy cập website UFM" not in new_context:
                context_pool.append(new_context)
                for src in new_sources:
                    if src["url"] not in [fs["url"] for fs in final_sources]:
                        final_sources.append(src)
        except Exception as e:
            logger.error(f"[flare] Active search error for '{keyword}': {e}")
            
    # ── SECOND PASS: FINAL GENERATION ──
    merged_context = "\n\n====================\n\n".join(context_pool)
    logger.info("[flare] Generating final grounded answer...")
    
    for chunk in llm_service.get_response_stream(
        merged_context, query, history, session_id,
        context_summary=mem_summary, is_general=is_general, voice_mode=voice_mode,
        system_prompt_override=FLARE_FINAL_SYSTEM_PROMPT
    ):
        yield chunk
        
    yield "__SOURCES__" + json.dumps(final_sources)
