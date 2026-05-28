"""app/services/cache_service.py — Persistent Cache cho PDF & Memory Cache cho HTML + QA Cache"""
import os
import re
import json
import logging
import hashlib
from difflib import SequenceMatcher
from pathlib import Path
from cachetools import TTLCache
from underthesea import word_tokenize
from app.config import settings

logger = logging.getLogger("ufm-chatbot")

# Memory Cache cho HTML (chạy nhanh, không cần lưu disk)
_html_cache: TTLCache = TTLCache(maxsize=settings.CACHE_MAX_SIZE, ttl=settings.CACHE_TTL_HTML)

# Persistent Cache cho PDF (để không phải OCR lại khi restart)
PDF_CACHE_DIR = Path(__file__).resolve().parent.parent / "database" / "pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# QA Cache (Semantic Match)
QA_CACHE_FILE = Path(__file__).resolve().parent.parent / "database" / "qa_cache.json"
QA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

_qa_cache = []

def load_qa_cache():
    global _qa_cache
    if QA_CACHE_FILE.exists():
        try:
            with open(QA_CACHE_FILE, "r", encoding="utf-8") as f:
                _qa_cache = json.load(f)
            logger.info(f"[cache] Loaded {len(_qa_cache)} QA entries")
        except Exception as e:
            logger.error(f"[cache] QA load error: {e}")
            _qa_cache = []

load_qa_cache()

def save_qa_cache():
    try:
        with open(QA_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_qa_cache[-1000:], f, ensure_ascii=False, indent=2)  # Giữ tối đa 1000 câu
    except Exception as e:
        logger.error(f"[cache] QA save error: {e}")

# --- HTML CACHE ---
def get_html(url: str) -> str | None:
    hit = _html_cache.get(url)
    if hit:
        logger.info(f"[cache] HIT html url={url[:60]}")
    return hit

def set_html(url: str, content: str) -> None:
    _html_cache[url] = content
    logger.info(f"[cache] SET html url={url[:60]} chars={len(content)}")

# --- PDF CACHE (PERSISTENT) ---
def _get_pdf_hash(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest() + ".txt"

def get_pdf(url: str) -> str | None:
    file_path = PDF_CACHE_DIR / _get_pdf_hash(url)
    if file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8")
            logger.info(f"[cache] HIT pdf (disk) url={url[:60]}")
            return content
        except Exception:
            return None
    return None

def set_pdf(url: str, content: str) -> None:
    file_path = PDF_CACHE_DIR / _get_pdf_hash(url)
    try:
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"[cache] SET pdf (disk) url={url[:60]} chars={len(content)}")
    except Exception as e:
        logger.error(f"[cache] SET pdf error: {e}")

# --- QA SEMANTIC CACHE ---
def clean_query(q: str) -> str:
    # Xóa dấu câu và đưa về chữ thường, dùng underthesea để gộp từ tiếng Việt
    q = q.lower()
    q = re.sub(r'[^\w\s]', ' ', q)
    tokens = word_tokenize(q, format="text").split()
    return " ".join(tokens)

def get_cached_answer(query: str, similarity_threshold: float = 0.90) -> str | None:
    """Tìm câu trả lời đã lưu nếu câu hỏi giống trên 90%."""
    if not query or len(query) < 10:
        return None  # Câu quá ngắn không cache
        
    query_clean = clean_query(query)
    best_match = None
    best_ratio = 0.0
    
    for item in reversed(_qa_cache[-100:]):  # Chỉ scan 100 câu mới nhất để tránh O(n*m) quá lớn
        ratio = SequenceMatcher(None, query_clean, item["query_clean"]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = item["answer"]
            
    if best_ratio >= similarity_threshold and best_match:
        logger.info(f"[cache] QA HIT (ratio={best_ratio:.2f}) for query='{query[:40]}'")
        return best_match
        
    return None

def set_cached_answer(query: str, answer: str) -> None:
    """Lưu câu trả lời vào cache để dùng lại."""
    if not query or len(query) < 10 or not answer or len(answer) < 50:
        return
        
    query_clean = clean_query(query)
    
    # Kiểm tra xem đã có chưa
    for item in _qa_cache:
        if item["query_clean"] == query_clean:
            item["answer"] = answer  # Cập nhật answer mới
            save_qa_cache()
            return
            
    _qa_cache.append({
        "query": query,
        "query_clean": query_clean,
        "answer": answer
    })
    logger.info(f"[cache] QA SAVED for query='{query[:40]}'")
    save_qa_cache()

# --- UTILS ---
def clear_all() -> None:
    _html_cache.clear()
    _qa_cache.clear()
    save_qa_cache()
    # Disk cache cho PDF thì KHÔNG XÓA để tránh phải OCR lại, chỉ xóa HTML & QA
    logger.info("[cache] HTML and QA cleared")

def stats() -> dict:
    pdf_count = len(list(PDF_CACHE_DIR.glob("*.txt"))) if PDF_CACHE_DIR.exists() else 0
    return {"html_cached": len(_html_cache), "pdf_cached": pdf_count, "qa_cached": len(_qa_cache)}
