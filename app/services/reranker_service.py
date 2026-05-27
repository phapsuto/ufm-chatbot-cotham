"""app/services/reranker_service.py — Semantic Reranker using native Transformers"""
import logging
import torch

logger = logging.getLogger("ufm-chatbot")

class CustomCrossEncoder:
    def __init__(self, model_name: str):
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            logger.info(f"[reranker] Loading {model_name} with native Transformers...")
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # Sử dụng GPU Apple Silicon (MPS) nếu có trên Mac, nếu không dùng CPU
            if torch.backends.mps.is_available():
                self.device = torch.device("mps")
                logger.info("[reranker] MPS hardware acceleration enabled on Mac GPU!")
            elif torch.cuda.is_available():
                self.device = torch.device("cuda")
                logger.info("[reranker] CUDA hardware acceleration enabled!")
            else:
                self.device = torch.device("cpu")
                logger.info("[reranker] Using CPU for inference.")
                
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
            self.model.eval()
            self.loaded = True
        except Exception as e:
            logger.error(f"[reranker] Failed to load model {model_name}: {e}")
            self.loaded = False

    def predict(self, pairs: list[list[str]]) -> list[float]:
        if not self.loaded:
            return [0.0] * len(pairs)
        try:
            from transformers import AutoModelForSequenceClassification
            with torch.no_grad():
                # Tokenize các cặp (query, document)
                inputs = self.tokenizer(
                    [p[0] for p in pairs],
                    [p[1] for p in pairs],
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt"
                ).to(self.device)
                
                outputs = self.model(**inputs)
                # Lấy logits (điểm số thô) và đưa về CPU dạng numpy array
                scores = outputs.logits.view(-1)
                
                # BGE-Reranker chấm điểm bằng sigmoid để chuyển sang thang điểm 0-1
                probs = torch.sigmoid(scores)
                return probs.cpu().numpy().tolist()
        except Exception as e:
            logger.error(f"[reranker] Reranking execution error: {e}")
            return [0.0] * len(pairs)

# Khởi tạo mô hình Reranker BGE-M3
reranker = None
try:
    # Dùng phiên bản m3 (đa ngôn ngữ) rất tốt cho tiếng Việt
    reranker = CustomCrossEncoder("BAAI/bge-reranker-v2-m3")
except Exception as e:
    logger.error(f"[reranker] Failed to instantiate CustomCrossEncoder: {e}")

def rerank(query: str, documents: list[str]) -> list[float]:
    """
    Chấm điểm lại độ tương đồng giữa câu hỏi và danh sách tài liệu.
    Trả về danh sách điểm tương ứng với từng document. Điểm càng cao càng tốt.
    """
    if not reranker or not documents:
        # Nếu model lỗi hoặc không có tài liệu, trả về điểm 0 hết để fallback về mặc định
        return [0.0] * len(documents)
        
    # CrossEncoder yêu cầu input là danh sách các cặp (query, document)
    pairs = [[query, doc] for doc in documents]
    return reranker.predict(pairs)

