"""app/services/cache_service.py — Persistent Cache cho PDF & HTML + FAISS Vector Semantic Cache"""
import os
import re
import json
import sqlite3
import logging
import hashlib
from pathlib import Path
from difflib import SequenceMatcher
from cachetools import TTLCache
from underthesea import word_tokenize
import numpy as np
import faiss

from app.config import settings
from app.services import vector_service

logger = logging.getLogger("ufm-chatbot")

# Memory Cache cho HTML
_html_cache: TTLCache = TTLCache(maxsize=settings.CACHE_MAX_SIZE, ttl=settings.CACHE_TTL_HTML)

# Persistent Cache cho PDF
PDF_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# SQLite DB Path cho Semantic Cache
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "semantic_cache.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════
# FAISS VECTOR CACHE CLASS
# ══════════════════════════════════════════════════

class FAISSSemanticCache:
    def __init__(self, db_path: str = str(DB_PATH), threshold: float = 0.92):
        self.db_path = db_path
        self.threshold = threshold
        self.dim = 768  # dangvantuan/vietnamese-embedding dimension
        self.faiss_index = None
        self.cache_map = []
        self._init_db()
        self._build_index()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT UNIQUE,
                query_clean TEXT,
                response TEXT,
                sources TEXT,
                suggestions TEXT,
                query_vector BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _build_index(self):
        self.faiss_index = faiss.IndexFlatIP(self.dim)
        self.cache_map = []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, query, query_clean, response, sources, suggestions, query_vector FROM semantic_cache")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            logger.info("[cache] Semantic Cache database is empty.")
            return
            
        vectors = []
        for row in rows:
            rec_id, query, query_clean, response, sources_json, sugg_json, vec_blob = row
            vec = np.frombuffer(vec_blob, dtype=np.float32)
            if len(vec) == self.dim:
                vectors.append(vec)
                self.cache_map.append({
                    "id": rec_id,
                    "query": query,
                    "query_clean": query_clean,
                    "response": response,
                    "sources": json.loads(sources_json) if sources_json else [],
                    "suggestions": json.loads(sugg_json) if sugg_json else []
                })
                
        if vectors:
            vectors_np = np.vstack(vectors).astype(np.float32)
            faiss.normalize_L2(vectors_np)
            self.faiss_index.add(vectors_np)
            logger.info(f"[cache] Loaded {len(self.cache_map)} entries into FAISS Cache Index.")

    def clean_query(self, query: str) -> str:
        q = query.strip().lower()
        q = re.sub(r'[?.\!]+$', '', q)
        q = re.sub(r'[^\w\s]', ' ', q)
        # Sử dụng underthesea để tokenize từ tiếng Việt
        tokens = word_tokenize(q, format="text").split()
        return " ".join(tokens)

    def lookup(self, query: str, threshold: float = 0.92) -> tuple[bool, str | None, list | None, list | None]:
        # Tránh cache các câu hỏi có mã quyết định/quy chế hoặc mã số cụ thể để tránh collision
        if re.search(r'\d+/\w+-\w+', query) or re.search(r'\b\d{3,}\b', query):
            return False, None, None, None

        q_clean = self.clean_query(query)
        if not q_clean or self.faiss_index is None or self.faiss_index.ntotal == 0:
            return False, None, None, None
            
        try:
            # Sinh vector nhúng
            vec = np.array(vector_service.generate_embedding(query), dtype=np.float32).reshape(1, -1)
            if vec.shape[1] != self.dim:
                return False, None, None, None
                
            faiss.normalize_L2(vec)
            distances, indices = self.faiss_index.search(vec, 1)
            
            score = float(distances[0][0])
            idx = int(indices[0][0])
            
            if idx != -1 and score >= threshold:
                record = self.cache_map[idx]
                logger.info(f"[cache] FAISS QA HIT! score={score:.4f} query='{query[:40]}'")
                return True, record["response"], record["sources"], record["suggestions"]
                
            logger.info(f"[cache] FAISS QA MISS. score={score:.4f} query='{query[:40]}'")
            return False, None, None, None
        except Exception as e:
            logger.error(f"[cache] Lookup error: {e}")
            return False, None, None, None

    def update(self, query: str, response: str, sources: list = None, suggestions: list = None):
        q_clean = self.clean_query(query)
        if not q_clean or not response:
            return
            
        try:
            vec = np.array(vector_service.generate_embedding(query), dtype=np.float32).reshape(1, -1)
            if vec.shape[1] != self.dim:
                return
                
            faiss.normalize_L2(vec)
            vec_blob = vec.tobytes()
            
            sources_str = json.dumps(sources or [], ensure_ascii=False)
            sugg_str = json.dumps(suggestions or [], ensure_ascii=False)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO semantic_cache (query, query_clean, response, sources, suggestions, query_vector) VALUES (?, ?, ?, ?, ?, ?)",
                    (query, q_clean, response, sources_str, sugg_str, vec_blob)
                )
                conn.commit()
                rec_id = cursor.lastrowid
                
                # Thêm vào index FAISS và map bộ nhớ
                self.faiss_index.add(vec)
                self.cache_map.append({
                    "id": rec_id,
                    "query": query,
                    "query_clean": q_clean,
                    "response": response,
                    "sources": sources or [],
                    "suggestions": suggestions or []
                })
                logger.info(f"[cache] FAISS QA SAVED id={rec_id} query='{query[:40]}'")
            except sqlite3.IntegrityError:
                # Đã tồn tại, bỏ qua
                pass
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[cache] Update error: {e}")

# Khởi tạo singleton cache
_faiss_cache = None

def get_faiss_cache() -> FAISSSemanticCache:
    global _faiss_cache
    if _faiss_cache is None:
        _faiss_cache = FAISSSemanticCache()
    return _faiss_cache

# --- Tương thích ngược với các hàm cũ ---

def get_cached_answer(query: str, similarity_threshold: float = 0.92) -> str | None:
    cache = get_faiss_cache()
    is_hit, answer, _, _ = cache.lookup(query, threshold=similarity_threshold)
    return answer if is_hit else None

def set_cached_answer(query: str, answer: str) -> None:
    cache = get_faiss_cache()
    cache.update(query, answer, [], [])

def lookup_cache_detail(query: str, threshold: float = 0.92) -> tuple[bool, str | None, list | None, list | None]:
    cache = get_faiss_cache()
    return cache.lookup(query, threshold=threshold)

def update_cache_detail(query: str, answer: str, sources: list = None, suggestions: list = None):
    cache = get_faiss_cache()
    cache.update(query, answer, sources, suggestions)

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

# --- UTILS ---
def clear_all() -> None:
    _html_cache.clear()
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM semantic_cache")
    conn.commit()
    conn.close()
    
    # Rebuild index rỗng
    cache = get_faiss_cache()
    cache._build_index()
    logger.info("[cache] HTML and FAISS QA cleared")

def stats() -> dict:
    pdf_count = len(list(PDF_CACHE_DIR.glob("*.txt"))) if PDF_CACHE_DIR.exists() else 0
    cache = get_faiss_cache()
    return {
        "html_cached": len(_html_cache),
        "pdf_cached": pdf_count,
        "qa_cached": len(cache.cache_map)
    }
