"""app/services/kb_service.py — Offline Knowledge Base (BM25 Search)"""
import os
import re
import math
import logging
from pathlib import Path
from collections import Counter
from app.services import vector_service
from app.services import reranker_service

logger = logging.getLogger("ufm-chatbot")

KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"

class SimpleBM25:
    def __init__(self, corpus):
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / self.corpus_size if self.corpus_size else 0
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []
        
        nd = {}
        for doc in corpus:
            self.doc_len.append(len(doc))
            frequencies = Counter(doc)
            self.doc_freqs.append(frequencies)
            for word in frequencies:
                nd[word] = nd.get(word, 0) + 1
                
        for word, freq in nd.items():
            # BM25 IDF formulation
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query, k1=1.5, b=0.75):
        scores = []
        for i in range(self.corpus_size):
            score = 0.0
            doc_len = self.doc_len[i]
            frequencies = self.doc_freqs[i]
            for q in query:
                if q not in frequencies:
                    continue
                freq = frequencies[q]
                num = freq * (k1 + 1)
                den = freq + k1 * (1 - b + b * doc_len / self.avgdl)
                score += self.idf.get(q, 0) * (num / den)
            scores.append(score)
        return scores

_chunks = []
_chunk_ids = []
_bm25 = None

def _tokenize(text: str) -> list[str]:
    from underthesea import word_tokenize
    # Tách từ tiếng Việt thành các compound words (ví dụ: "sinh_viên")
    text = text.lower()
    tokens = word_tokenize(text, format="text").split()
    return [t for t in tokens if len(t) > 1]

def _load_kb():
    global _chunks, _bm25
    if not KB_DIR.exists():
        logger.warning(f"[kb] Directory not found: {KB_DIR}")
        return
        
    docs = []
    total_files = 0
    for file_path in KB_DIR.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            # Chia nhỏ file theo tiêu đề hoặc đoạn văn lớn
            paragraphs = re.split(r'\n#{1,3} |\n\n+', content)
            for p in paragraphs:
                p = p.strip()
                if len(p) > 100:  # Bỏ qua đoạn quá ngắn
                    chunk = f"Nguồn: {file_path.name}\nNội dung: {p}"
                    _chunks.append(chunk)
                    _chunk_ids.append(f"{file_path.name}_{len(_chunks)}")
                    docs.append(_tokenize(p))
            total_files += 1
        except Exception as e:
            logger.error(f"[kb] Failed to read {file_path.name}: {e}")
            
    if docs:
        _bm25 = SimpleBM25(docs)
        logger.info(f"[kb] Loaded {total_files} offline PDFs ({len(_chunks)} chunks)")
        vector_service.index_chunks(_chunks, _chunk_ids)

# Khởi tạo lúc start
_load_kb()

def search_kb(query: str, top_k: int = 3, level: str = None, major: str = None) -> list[dict]:
    """Tìm kiếm nội dung offline dựa vào câu hỏi, sử dụng Hybrid Search (BM25 + Vector) và metadata boost."""
    if not _bm25 or not _chunks:
        return []
        
    query_lower = query.lower()
    
    # 1. Tự động phát hiện và ghi đè Level dựa trên câu hỏi thực tế
    if any(k in query_lower for k in ["tiến sĩ", "tiến sỹ", "tien si", "tien sy", "nghiên cứu sinh", "ncs", "luận án"]):
        level = "tien_si"
    elif any(k in query_lower for k in ["thạc sĩ", "thạc sỹ", "thac si", "thac sy", "cao học", "cao hoc", "luận văn"]):
        level = "thac_si"
        
    # 2. Tự động phát hiện và ghi đè Major dựa trên câu hỏi thực tế
    if any(k in query_lower for k in ["quản trị kinh doanh", "qtkd"]):
        major = "quản trị kinh doanh"
    elif any(k in query_lower for k in ["tài chính", "ngân hàng", "tcnh"]):
        major = "tài chính ngân hàng"
    elif any(k in query_lower for k in ["kế toán", "kt"]):
        major = "kế toán"
    elif any(k in query_lower for k in ["marketing", "mkt"]):
        major = "marketing"
    elif any(k in query_lower for k in ["quản lý kinh tế", "qlkt"]):
        major = "quản lý kinh tế"
    elif any(k in query_lower for k in ["luật kinh tế", "luật", "lkt"]):
        major = "luật kinh tế"
    elif any(k in query_lower for k in ["kinh doanh quốc tế", "kdqt"]):
        major = "kinh doanh quốc tế"
    elif any(k in query_lower for k in ["toán kinh tế", "tkt"]):
        major = "toán kinh tế"

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
        
    # 1. BM25 Search
    bm25_scores = _bm25.get_scores(query_tokens)
    bm25_ranked = sorted(range(len(_chunks)), key=lambda i: bm25_scores[i], reverse=True)
    bm25_ranks = {idx: rank for rank, idx in enumerate(bm25_ranked)}
    
    # 2. Vector Search
    vector_results = vector_service.semantic_search(query, top_k=top_k*3)
    vector_score_map = {res["content"]: res["vector_score"] for res in vector_results}
    
    vector_scores_list = [vector_score_map.get(chunk, 0.0) for chunk in _chunks]
    vector_ranked = sorted(range(len(_chunks)), key=lambda i: vector_scores_list[i], reverse=True)
    vector_ranks = {idx: rank for rank, idx in enumerate(vector_ranked)}
    
    # 3. Kết hợp bằng Reciprocal Rank Fusion (RRF)
    k = 60
    scores = []
    for i, chunk in enumerate(_chunks):
        # Tính điểm RRF
        if bm25_scores[i] > 0 or vector_scores_list[i] > 0:
            rrf_score = 1.0 / (k + bm25_ranks[i]) + 1.0 / (k + vector_ranks[i])
        else:
            rrf_score = 0.0
            
        score = rrf_score
        
        # Áp dụng Metadata Boosting nếu có ngữ cảnh level hoặc major
        if score > 0 and (level or major):
            first_line = chunk.splitlines()[0]
            filename = first_line.replace("Nguồn: ", "").strip().lower()
            
            # 1. Khớp Level (Bậc đào tạo)
            level_match = False
            if level == "tien_si":
                if any(k in filename for k in ["tiến sĩ", "tien si", "ts"]):
                    level_match = True
            elif level == "thac_si":
                if any(k in filename for k in ["thạc sĩ", "thac si", "ths", "cao học", "cao hoc"]):
                    level_match = True
                    
            # 2. Khớp Major (Ngành học)
            major_match = False
            if major:
                major_clean = major.lower()
                major_keywords = [major_clean]
                if "quản trị kinh doanh" in major_clean:
                    major_keywords.extend(["qtkd", "quản trị kinh doanh", "quan tri kinh doanh"])
                elif "tài chính" in major_clean or "ngân hàng" in major_clean:
                    major_keywords.extend(["tcnh", "tài chính", "ngân hàng", "tai chinh", "ngan hang"])
                elif "kế toán" in major_clean:
                    major_keywords.extend(["kế toán", "ke toan", "kt"])
                elif "marketing" in major_clean:
                    major_keywords.extend(["marketing", "mkt"])
                elif "quản lý kinh tế" in major_clean:
                    major_keywords.extend(["qlkt", "quản lý kinh tế", "quan ly kinh te"])
                elif "luật kinh tế" in major_clean or "luật" in major_clean:
                    major_keywords.extend(["lkt", "luật", "luat"])
                elif "kinh doanh quốc tế" in major_clean:
                    major_keywords.extend(["kdqt", "kinh doanh quốc tế", "kinh doanh quoc te"])
                elif "toán kinh tế" in major_clean:
                    major_keywords.extend(["tkt", "toán kinh tế", "toan kinh te"])
                    
                if any(k in filename for k in major_keywords):
                    major_match = True
                    
            # Áp dụng hệ số nhân boost
            if level_match and major_match:
                score *= 3.0  # Ưu tiên tuyệt đối
            elif level_match or major_match:
                score *= 1.5
                
        scores.append(score)
    
    # Lấy top_k * 3 chunks có điểm cao nhất từ Hybrid Search để Rerank
    top_hybrid_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 3]
    
    hybrid_results = []
    for i in top_hybrid_indices:
        if scores[i] > 0.0:  # Đã có điểm RRF
            hybrid_results.append(_chunks[i])
            
    if not hybrid_results:
        return []
        
    # 4. Reranking bằng CrossEncoder (BGE-M3)
    rerank_scores = reranker_service.rerank(query, hybrid_results)
    
    # Kết hợp lại với content và sort theo điểm Rerank
    final_results = []
    for i, content in enumerate(hybrid_results):
        final_results.append({
            "content": content,
            "score": rerank_scores[i]
        })
        
    # Trả về top_k kết quả sau khi đã Rerank
    final_results = sorted(final_results, key=lambda x: x["score"], reverse=True)[:top_k]
    
    return final_results
