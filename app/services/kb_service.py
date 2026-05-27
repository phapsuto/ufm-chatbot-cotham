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

def _smart_chunk_file(file_path: Path) -> list[str]:
    """Chia nhỏ file Markdown một cách thông minh, gộp các dòng ngắn và giữ ngữ cảnh tiêu đề."""
    content = file_path.read_text(encoding="utf-8")
    
    # Dọn dẹp tên file để làm chủ đề mặc định nếu không có tiêu đề
    file_title = file_path.stem
    if file_title.startswith("web_main_"):
        file_title = file_title.replace("web_main_", "Cổng thông tin UFM - ")
    elif file_title.startswith("web_"):
        file_title = file_title.replace("web_", "Tuyển sinh Sau đại học UFM - ")
    file_title = file_title.replace("-", " ").replace("_", " ").strip().title()
    
    current_h1 = ""
    current_h2 = ""
    current_h3 = ""
    
    chunks = []
    current_lines = []
    current_len = 0
    
    # Đọc từng dòng
    lines = content.splitlines()
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # Nhận diện tiêu đề Markdown
        h1_match = re.match(r'^#\s+(.+)$', line_strip)
        h2_match = re.match(r'^##\s+(.+)$', line_strip)
        h3_match = re.match(r'^###\s+(.+)$', line_strip)
        
        is_header = False
        if h1_match:
            if current_lines:
                chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
                current_lines = []
                current_len = 0
            current_h1 = h1_match.group(1).strip()
            current_h2 = ""
            current_h3 = ""
            is_header = True
        elif h2_match:
            if current_lines:
                chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
                current_lines = []
                current_len = 0
            current_h2 = h2_match.group(1).strip()
            current_h3 = ""
            is_header = True
        elif h3_match:
            if current_lines:
                chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
                current_lines = []
                current_len = 0
            current_h3 = h3_match.group(1).strip()
            is_header = True
            
        if is_header:
            continue
            
        # Nhận diện ngắt trang hoặc phân tách ngang
        if line_strip == "---" or line_strip.startswith("<!-- Trang"):
            if current_lines:
                chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
                current_lines = []
                current_len = 0
            continue
            
        # Thêm dòng vào chunk hiện tại
        current_lines.append(line_strip)
        current_len += len(line_strip)
        
        # Flush nếu chunk đạt quá 800 ký tự
        if current_len > 800:
            chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
            current_lines = []
            current_len = 0
            
    # Flush phần còn lại
    if current_lines:
        chunks.append((current_h1, current_h2, current_h3, "\n".join(current_lines)))
        
    # Định dạng các chunk với đầy đủ ngữ cảnh
    formatted_chunks = []
    for h1, h2, h3, text in chunks:
        hierarchy = []
        if h1: hierarchy.append(h1)
        if h2: hierarchy.append(h2)
        if h3: hierarchy.append(h3)
        
        topic = " > ".join(hierarchy) if hierarchy else file_title
        
        # Lọc bỏ các chunk quá rác (dưới 20 ký tự thực tế)
        if len(text.strip()) > 20:
            formatted = f"Nguồn: {file_path.name}\nChủ đề: {topic}\nNội dung:\n{text}"
            formatted_chunks.append(formatted)
        
    return formatted_chunks

def _load_kb():
    global _chunks, _bm25
    if not KB_DIR.exists():
        logger.warning(f"[kb] Directory not found: {KB_DIR}")
        return
        
    docs = []
    total_files = 0
    for file_path in KB_DIR.glob("*.md"):
        try:
            # Sử dụng bộ chunker thông minh thay vì split thô
            file_chunks = _smart_chunk_file(file_path)
            for chunk in file_chunks:
                _chunks.append(chunk)
                _chunk_ids.append(f"{file_path.name}_{len(_chunks)}")
                
                # Trích xuất phần nội dung thực tế để token hóa cho BM25
                content_part = chunk.split("Nội dung:\n", 1)[-1]
                docs.append(_tokenize(content_part))
            total_files += 1
        except Exception as e:
            logger.error(f"[kb] Failed to read {file_path.name}: {e}")
            
    if docs:
        _bm25 = SimpleBM25(docs)
        logger.info(f"[kb] Loaded {total_files} offline files ({len(_chunks)} chunks)")
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
        
    # 1. Thu thập ứng cử viên từ BM25 (lấy top 20 Chunks)
    bm25_scores = _bm25.get_scores(query_tokens)
    top_bm25_indices = sorted(range(len(_chunks)), key=lambda i: bm25_scores[i], reverse=True)[:20]
    
    candidate_chunks = {}
    for idx in top_bm25_indices:
        if bm25_scores[idx] > 0.0:
            candidate_chunks[idx] = _chunks[idx]
            
    # 2. Thu thập ứng cử viên từ Vector Search (lấy top 20 Chunks)
    vector_results = vector_service.semantic_search(query, top_k=20)
    # Ánh xạ từ content về index trong _chunks
    chunk_index_map = {chunk: i for i, chunk in enumerate(_chunks)}
    for res in vector_results:
        content = res["content"]
        if content in chunk_index_map:
            idx = chunk_index_map[content]
            candidate_chunks[idx] = content

    if not candidate_chunks:
        return []
        
    # Chuyển đổi thành danh sách các index và các chunk ứng cử viên thực tế
    candidate_indices = list(candidate_chunks.keys())
    candidate_texts = list(candidate_chunks.values())
    
    # 3. Reranking tất cả ứng cử viên bằng CrossEncoder (BGE-M3)
    rerank_scores = reranker_service.rerank(query, candidate_texts)
    
    # 4. Áp dụng Metadata Boosting lên kết quả Rerank
    final_results = []
    for i, idx in enumerate(candidate_indices):
        score = rerank_scores[i]
        chunk = candidate_texts[i]
        
        # Áp dụng Metadata Boosting nếu có ngữ cảnh level hoặc major
        if level or major:
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
                score = min(1.0, score * 1.5)  # Ưu tiên cao nhất
            elif level_match or major_match:
                score = min(1.0, score * 1.2)
                
        final_results.append({
            "content": chunk,
            "score": score
        })
        
    # Trả về top_k kết quả sau khi đã Rerank và Boost
    final_results = sorted(final_results, key=lambda x: x["score"], reverse=True)[:top_k]
    
    return final_results
