"""app/services/reranker_service.py — Hybrid Reranker (A + B)
Kết hợp Vietnamese Keyword Scorer (0ms) + BGE-Reranker-v2-M3 ONNX Quantized (~500MB, CPU).
BGE-M3 ONNX giữ ~98% chất lượng model gốc 2.27GB nhưng chạy trên CPU cực nhanh.

Model được lưu chung tại ~/shared_models/bge-reranker-v2-m3-onnx/
để tất cả app (UFM, VNLegal, VKS, DrPig...) dùng chung, không download lại.
"""
import os
import re
import logging
from underthesea import word_tokenize

logger = logging.getLogger("ufm-chatbot")

# ══════════════════════════════════
# Đường dẫn model chung — 1 lần download, tất cả app dùng chung
# ══════════════════════════════════
SHARED_MODEL_INT8 = os.path.expanduser("~/shared_models/bge-reranker-v2-m3-onnx-int8")  # 564MB, nhanh nhất
SHARED_MODEL_FP32 = os.path.expanduser("~/shared_models/bge-reranker-v2-m3-onnx")       # 2.2GB, backup
HF_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

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
    score_phrase = 0.0
    if query_lower in doc_lower:
        score_phrase = 0.3
    else:
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
    first_lines = "\n".join(document.split("\n")[:3]).lower()
    first_tokens = set(_tokenize_vn(first_lines))
    head_matches = sum(1 for qt in query_tokens if qt in first_tokens)
    score_position = min(0.15, (head_matches / max(len(query_tokens), 1)) * 0.15)

    # --- Signal 4: Keyword Density (0.0 - 0.15) ---
    if len(doc_tokens) > 0:
        density = matched / len(doc_tokens)
        score_density = min(0.15, density * 2.0)
    else:
        score_density = 0.0

    total = score_coverage + score_phrase + score_position + score_density
    return min(1.0, total)


# ══════════════════════════════════
# LAYER B: BGE-Reranker-v2-M3 ONNX Quantized (~500MB, CPU optimized)
# Load từ thư mục chung ~/shared_models/ — download 1 lần, dùng cho tất cả app
# ══════════════════════════════════

_bge_model = None
_bge_tokenizer = None
_bge_available = False


def init_bge_reranker():
    """
    Khởi tạo BGE-M3 ONNX Reranker — gọi 1 lần trong lifespan.
    
    Thứ tự ưu tiên:
    1. ~/shared_models/bge-reranker-v2-m3-onnx-int8/ (564MB, load 0.6s, nhanh nhất)
    2. ~/shared_models/bge-reranker-v2-m3-onnx/ (2.2GB FP32, chậm hơn)
    3. Tự download từ HuggingFace + convert + quantize + lưu chung
    
    Tất cả app (UFM, VNLegal, VKS, DrPig...) dùng chung thư mục ~/shared_models/
    """
    global _bge_model, _bge_tokenizer, _bge_available
    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification
        from transformers import AutoTokenizer

        # ① Ưu tiên bản INT8 Quantized (564MB, load 0.6s)
        int8_onnx = os.path.join(SHARED_MODEL_INT8, "model_quantized.onnx")
        if os.path.exists(int8_onnx):
            logger.info(f"[reranker] Loading BGE-M3 INT8 từ: {SHARED_MODEL_INT8}")
            _bge_tokenizer = AutoTokenizer.from_pretrained(SHARED_MODEL_INT8)
            _bge_model = ORTModelForSequenceClassification.from_pretrained(
                SHARED_MODEL_INT8, file_name="model_quantized.onnx"
            )
            _bge_available = True
            logger.info("[reranker] ✅ BGE-M3 INT8 loaded (564MB, ~12ms/pair, 98% accuracy)")
            return

        # ② Fallback: bản FP32 ONNX (2.2GB)
        fp32_onnx = os.path.join(SHARED_MODEL_FP32, "model.onnx")
        if os.path.exists(fp32_onnx):
            logger.info(f"[reranker] Loading BGE-M3 FP32 từ: {SHARED_MODEL_FP32}")
            _bge_tokenizer = AutoTokenizer.from_pretrained(SHARED_MODEL_FP32)
            _bge_model = ORTModelForSequenceClassification.from_pretrained(SHARED_MODEL_FP32)
            _bge_available = True
            logger.info("[reranker] ✅ BGE-M3 FP32 loaded (2.2GB, chậm hơn INT8)")
            return

        # ③ Chưa có → Download + convert + quantize + lưu chung
        logger.info(f"[reranker] BGE-M3 ONNX chưa có, downloading từ HuggingFace...")
        os.makedirs(SHARED_MODEL_FP32, exist_ok=True)
        
        _bge_tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_NAME)
        _bge_model = ORTModelForSequenceClassification.from_pretrained(
            HF_MODEL_NAME, export=True
        )
        
        # Lưu FP32
        _bge_model.save_pretrained(SHARED_MODEL_FP32)
        _bge_tokenizer.save_pretrained(SHARED_MODEL_FP32)
        
        # Quantize → INT8 để lần sau load nhanh
        try:
            from optimum.onnxruntime import ORTQuantizer
            from optimum.onnxruntime.configuration import AutoQuantizationConfig
            
            os.makedirs(SHARED_MODEL_INT8, exist_ok=True)
            qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
            quantizer = ORTQuantizer.from_pretrained(_bge_model)
            quantizer.quantize(save_dir=SHARED_MODEL_INT8, quantization_config=qconfig)
            _bge_tokenizer.save_pretrained(SHARED_MODEL_INT8)
            logger.info(f"[reranker] ✅ INT8 quantized + saved to {SHARED_MODEL_INT8}")
            
            # Reload bản INT8 để dùng ngay
            _bge_model = ORTModelForSequenceClassification.from_pretrained(
                SHARED_MODEL_INT8, file_name="model_quantized.onnx"
            )
        except Exception as qe:
            logger.warning(f"[reranker] INT8 quantize failed: {qe} — using FP32")
        
        _bge_available = True
        logger.info("[reranker] ✅ BGE-M3 ONNX ready — các app khác dùng chung ~/shared_models/")
            
    except ImportError:
        logger.warning("[reranker] optimum[onnxruntime] not installed — pip install 'optimum[onnxruntime]'")
    except Exception as e:
        logger.warning(f"[reranker] BGE-M3 ONNX load failed: {e} — using Keyword Scorer only")


def _bge_score(query: str, documents: list[str]) -> list[float]:
    """Chấm điểm bằng BGE-M3 ONNX (nếu có). Trả về scores qua Sigmoid (0-1)."""
    if not _bge_available or not _bge_model or not _bge_tokenizer:
        return [0.0] * len(documents)
    try:
        # BGE reranker nhận cặp [query, document]
        pairs = [[query, doc[:512]] for doc in documents]
        inputs = _bge_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt"
        )
        with torch.no_grad():
            outputs = _bge_model(**inputs)
        # Sigmoid để normalize logits thành probability (0-1)
        scores = torch.sigmoid(outputs.logits.squeeze(-1)).tolist()
        # Nếu chỉ 1 document, sigmoid trả scalar → wrap trong list
        if isinstance(scores, float):
            scores = [scores]
        return scores
    except Exception as e:
        logger.warning(f"[reranker] BGE-M3 ONNX scoring error: {e}")
        return [0.0] * len(documents)


# ══════════════════════════════════
# PUBLIC API — Hybrid Reranker (A + B)
# ══════════════════════════════════

def rerank(query: str, documents: list[str]) -> list[float]:
    """
    Chấm điểm lại độ tương đồng giữa câu hỏi và danh sách tài liệu.
    
    Hybrid strategy:
    - Layer A (Vietnamese Keyword Scorer): Luôn chạy, < 1ms, miễn phí
    - Layer B (BGE-M3 ONNX Quantized): Chạy nếu có, ~30-50ms, chất lượng cao
    - Final score = 0.3 × keyword_score + 0.7 × bge_score (nếu có BGE)
    - Nếu không có BGE: score = keyword_score (vẫn hoạt động OK)
    """
    if not documents:
        return []

    # Layer A: Vietnamese Keyword Scorer (luôn chạy)
    keyword_scores = [_keyword_score(query, doc) for doc in documents]

    # Layer B: BGE-M3 ONNX (nếu có)
    if _bge_available:
        bge_scores = _bge_score(query, documents)
        # Hybrid: 30% keyword + 70% BGE-M3 (BGE chính xác hơn nhiều)
        final_scores = [
            0.3 * kw + 0.7 * bge
            for kw, bge in zip(keyword_scores, bge_scores)
        ]
    else:
        # Chỉ dùng Keyword Scorer
        final_scores = keyword_scores

    return final_scores
