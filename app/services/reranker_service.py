"""app/services/reranker_service.py — Semantic Reranker using CrossEncoder"""
import logging

logger = logging.getLogger("ufm-chatbot")

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None
    logger.warning("[reranker] sentence_transformers not installed.")

# Khởi tạo mô hình Reranker BGE-M3
reranker = None
if CrossEncoder:
    try:
        logger.info("[reranker] Loading BAAI/bge-reranker-v2-m3... This may take a moment.")
        # Dùng phiên bản m3 (đa ngôn ngữ) rất tốt cho tiếng Việt
        reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
    except Exception as e:
        logger.error(f"[reranker] Failed to load reranker model: {e}")

def rerank(query: str, documents: list[str]) -> list[float]:
    """
    Chấm điểm lại độ tương đồng giữa câu hỏi và danh sách tài liệu.
    Trả về danh sách điểm tương ứng với từng document. Điểm càng cao càng tốt.
    """
    if not reranker or not documents:
        # Nếu model lỗi, trả về điểm 0 hết để fallback về thứ tự mặc định
        return [0.0] * len(documents)
        
    try:
        # CrossEncoder yêu cầu input là danh sách các cặp (query, document)
        pairs = [[query, doc] for doc in documents]
        scores = reranker.predict(pairs)
        return scores.tolist()
    except Exception as e:
        logger.error(f"[reranker] Reranking error: {e}")
        return [0.0] * len(documents)
