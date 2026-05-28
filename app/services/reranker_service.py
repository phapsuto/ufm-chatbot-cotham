"""app/services/reranker_service.py — Lightweight Hybrid Reranker (A+B)
Kết hợp Vietnamese Keyword Scorer (0ms, chạy luôn) + FlashRank ONNX (5ms, fallback nếu có).
Thay thế BGE-Reranker-v2-M3 (~1.2GB RAM → ~4MB + 0MB)
"""
import re
import math
import logging
from underthesea import word_tokenize

logger = logging.getLogger("ufm-chatbot")

# ══════════════════════════════════
# LAYER A: Vietnamese Keyword Scorer (Thuần Python, 0 model, < 1ms)
# ══════════════════════════════════

# Vietnamese stopwords — không mang ý nghĩa tìm kiếm
_STOPWORDS = {
    "và", "của", "là", "có", "được", "cho", "các", "trong", "này", "đó",
    "với", "không", "để", "từ", "một", "về", "theo", "tại", "đã", "khi",
    "hay", "hoặc", "nếu", "thì", "mà", "cũng", "ra", "vào", "lên", "bị",
    "ở", "sẽ", "do", "hơn", "rồi", "rất", "nào", "ai", "gì", "bao",
    "nhiêu", "bao_nhiêu", "thế_nào", "như_thế_nào", "dạ", "ạ", "nha",
    "nhé", "vậy", "thế", "ơi", "em", "anh", "chị", "cô", "thầy",
}


def _tokenize_vn(text: str) -> list[str]:
    """Tách từ tiếng Việt, loại stopwords, trả về danh sách từ có nghĩa."""
    text = text.lower().strip()
    tokens = word_tokenize(text, format="text").split()
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _keyword_score(query: str, document: str) -> float:
    """
    Chấm điểm dựa trên keyword overlap giữa query và document.
    Kết hợp nhiều tín hiệu:
    1. Query term coverage — bao nhiêu từ trong query xuất hiện trong doc
    2. Exact phrase matching — cụm từ nguyên vẹn khớp (bonus lớn)
    3. Position bonus — từ xuất hiện ở đầu doc (title/header) được ưu tiên
    4. Density — tỷ lệ từ khớp trên tổng từ doc (tránh doc quá dài chứa hết)
    """
    query_tokens = _tokenize_vn(query)
    doc_tokens = _tokenize_vn(document)

    if not query_tokens or not doc_tokens:
        return 0.0

    doc_lower = document.lower()
    query_lower = query.lower()

    # --- Signal 1: Query Term Coverage (0.0 - 0.4) ---
    doc_token_set = set(doc_tokens)
    matched = sum(1 for qt in query_tokens if qt in doc_token_set)
    coverage = matched / len(query_tokens)
    score_coverage = coverage * 0.4

    # --- Signal 2: Exact Phrase Matching (0.0 - 0.3) ---
    # Kiểm tra cụm từ nguyên vẹn từ query có trong doc không
    score_phrase = 0.0
    # 2a. Full query match
    if query_lower in doc_lower:
        score_phrase = 0.3
    else:
        # 2b. Ngram matching (2-3 gram)
        q_words = query_lower.split()
        ngram_matches = 0
        ngram_total = 0
        for n in range(min(3, len(q_words)), 1, -1):
            for i in range(len(q_words) - n + 1):
                ngram = " ".join(q_words[i:i+n])
                ngram_total += 1
                if ngram in doc_lower:
                    ngram_matches += 1
        if ngram_total > 0:
            score_phrase = (ngram_matches / ngram_total) * 0.25

    # --- Signal 3: Position Bonus (0.0 - 0.15) ---
    # Từ khớp ở đầu doc (dòng 1-3 = title/header) quan trọng hơn
    first_lines = "\n".join(document.split("\n")[:3]).lower()
    first_tokens = set(_tokenize_vn(first_lines))
    head_matches = sum(1 for qt in query_tokens if qt in first_tokens)
    score_position = min(0.15, (head_matches / max(len(query_tokens), 1)) * 0.15)

    # --- Signal 4: Keyword Density (0.0 - 0.15) ---
    # Tránh doc dài chứa mọi thứ nhưng không tập trung
    if len(doc_tokens) > 0:
        density = matched / len(doc_tokens)
        # Normalize: density 0.1 → OK, density 0.01 → quá loãng
        score_density = min(0.15, density * 2.0)
    else:
        score_density = 0.0

    total = score_coverage + score_phrase + score_position + score_density
    return min(1.0, total)


# ══════════════════════════════════
# LAYER B: FlashRank ONNX (Siêu nhẹ, ~4MB, ~5-10ms)
# ══════════════════════════════════

_flashrank_ranker = None
_flashrank_available = False

try:
    from flashrank import Ranker, RerankRequest
    # Model siêu nhẹ: ms-marco-TinyBERT-L-2-v2 chỉ ~4MB, chạy ONNX trên CPU cực nhanh
    _flashrank_ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir="data/models")
    _flashrank_available = True
    logger.info("[reranker] FlashRank ONNX loaded (ms-marco-MiniLM-L-2, ~4MB) ✅")
except ImportError:
    logger.info("[reranker] FlashRank not installed — using Vietnamese Keyword Scorer only")
except Exception as e:
    logger.warning(f"[reranker] FlashRank load failed: {e} — using Keyword Scorer only")


def _flashrank_score(query: str, documents: list[str]) -> list[float]:
    """Chấm điểm bằng FlashRank ONNX (nếu có)."""
    if not _flashrank_available or not _flashrank_ranker:
        return [0.0] * len(documents)
    try:
        passages = [{"id": i, "text": doc[:512]} for i, doc in enumerate(documents)]
        request = RerankRequest(query=query, passages=passages)
        results = _flashrank_ranker.rerank(request)
        # FlashRank trả về sorted — cần map lại theo thứ tự gốc
        score_map = {r["id"]: r["score"] for r in results}
        return [score_map.get(i, 0.0) for i in range(len(documents))]
    except Exception as e:
        logger.warning(f"[reranker] FlashRank error: {e}")
        return [0.0] * len(documents)


# ══════════════════════════════════
# PUBLIC API — Hybrid Reranker (A + B)
# ══════════════════════════════════

def rerank(query: str, documents: list[str]) -> list[float]:
    """
    Chấm điểm lại độ tương đồng giữa câu hỏi và danh sách tài liệu.
    
    Hybrid strategy:
    - Layer A (Vietnamese Keyword Scorer): Luôn chạy, < 1ms, miễn phí
    - Layer B (FlashRank ONNX): Chạy nếu có, ~5ms, chất lượng cao hơn
    - Final score = 0.4 × keyword_score + 0.6 × flashrank_score (nếu có FlashRank)
    - Nếu không có FlashRank: score = keyword_score (vẫn hoạt động tốt)
    """
    if not documents:
        return []

    # Layer A: Vietnamese Keyword Scorer (luôn chạy)
    keyword_scores = [_keyword_score(query, doc) for doc in documents]

    # Layer B: FlashRank ONNX (nếu có)
    if _flashrank_available:
        flash_scores = _flashrank_score(query, documents)
        # Normalize FlashRank scores to 0-1 range
        max_flash = max(flash_scores) if flash_scores else 1.0
        if max_flash > 0:
            flash_scores = [s / max_flash for s in flash_scores]
        # Hybrid: 40% keyword + 60% FlashRank
        final_scores = [
            0.4 * kw + 0.6 * fr
            for kw, fr in zip(keyword_scores, flash_scores)
        ]
    else:
        # Chỉ dùng Keyword Scorer
        final_scores = keyword_scores

    return final_scores
