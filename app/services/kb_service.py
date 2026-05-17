"""app/services/kb_service.py — Offline Knowledge Base (BM25 Search)"""
import os
import re
import math
import logging
from pathlib import Path
from collections import Counter

logger = logging.getLogger("ufm-chatbot")

KB_DIR = Path("app/knowledge_base")

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
                    docs.append(_tokenize(p))
            total_files += 1
        except Exception as e:
            logger.error(f"[kb] Failed to read {file_path.name}: {e}")
            
    if docs:
        _bm25 = SimpleBM25(docs)
        logger.info(f"[kb] Loaded {total_files} offline PDFs ({len(_chunks)} chunks)")

# Khởi tạo lúc start
_load_kb()

def search_kb(query: str, top_k: int = 3) -> list[dict]:
    """Tìm kiếm nội dung offline dựa vào câu hỏi, trả về list dict chứa content và score."""
    if not _bm25 or not _chunks:
        return []
        
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
        
    scores = _bm25.get_scores(query_tokens)
    
    # Lấy top_k chunks có điểm cao nhất
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    
    results = []
    for i in top_indices:
        if scores[i] > 0.5:  # Ngưỡng tối thiểu
            results.append({
                "content": _chunks[i],
                "score": scores[i]
            })
            
    return results
