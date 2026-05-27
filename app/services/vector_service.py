"""app/services/vector_service.py — Vector Search với ChromaDB và SentenceTransformers"""
import os
import logging
from pathlib import Path

# Setup logging
logger = logging.getLogger("ufm-chatbot")

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError:
    chromadb = None
    SentenceTransformer = None
    logger.warning("[vector] chromadb or sentence_transformers not installed.")

# Khởi tạo mô hình Embedding tiếng Việt
embedder = None
if SentenceTransformer:
    try:
        logger.info("[vector] Loading Vietnamese Embedding Model (local files only)...")
        # local_files_only=True chặn hoàn toàn việc kiểm tra update online
        embedder = SentenceTransformer("dangvantuan/vietnamese-embedding", local_files_only=True)
    except Exception as e:
        logger.warning(f"[vector] Offline loading failed, trying online fallback... Error: {e}")
        try:
            embedder = SentenceTransformer("dangvantuan/vietnamese-embedding")
        except Exception as ex:
            logger.error(f"[vector] Failed to load embedding model online: {ex}")


# Thiết lập thư mục lưu trữ Vector DB
DB_DIR = Path(__file__).resolve().parent.parent / "database" / "chroma_db"
DB_DIR.mkdir(parents=True, exist_ok=True)

collection = None
if chromadb:
    try:
        chroma_client = chromadb.PersistentClient(path=str(DB_DIR))
        collection = chroma_client.get_or_create_collection(
            name="ufm_kb_collection",
            metadata={"hnsw:space": "cosine"} # Sử dụng cosine similarity
        )
    except Exception as e:
        logger.error(f"[vector] Failed to initialize ChromaDB: {e}")

def generate_embedding(text: str) -> list[float]:
    """Tạo vector nhúng từ văn bản."""
    if embedder is None:
        return []
    # sentence-transformers trả về numpy array, cần chuyển sang list cho ChromaDB
    return embedder.encode(text).tolist()

def index_chunks(chunks: list[str], ids: list[str]) -> None:
    """Thêm dữ liệu văn bản vào ChromaDB collection."""
    if not collection or not chunks or len(chunks) != len(ids):
        return
        
    try:
        # Kiểm tra dữ liệu hiện có để tránh nạp trùng
        existing_count = collection.count()
        if existing_count >= len(chunks):
            logger.info(f"[vector] ChromaDB already has {existing_count} chunks. Skipping indexing.")
            return
            
        logger.info(f"[vector] Generating embeddings for {len(chunks)} chunks... This may take a moment.")
        embeddings = [generate_embedding(c) for c in chunks]
        
        # Nạp dữ liệu vào DB
        collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=ids
        )
        logger.info(f"[vector] Successfully indexed {len(chunks)} chunks into ChromaDB.")
    except Exception as e:
        logger.error(f"[vector] Error indexing chunks: {e}")

def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    """Tìm kiếm ngữ nghĩa bằng vector, trả về danh sách dict {content, score}."""
    if not collection or not embedder:
        return []
        
    try:
        query_embedding = generate_embedding(query)
        # Truy vấn ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        output = []
        if results and 'documents' in results and results['documents']:
            docs = results['documents'][0]
            distances = results['distances'][0]
            for i, doc in enumerate(docs):
                # Cosine distance: 0 là giống hệt, 1 là không giống. 
                # Chuyển đổi thành điểm score từ 0 đến 1 (càng cao càng giống)
                similarity_score = 1.0 - distances[i]
                output.append({
                    "content": doc,
                    "vector_score": similarity_score
                })
        return output
    except Exception as e:
        logger.error(f"[vector] Search error: {e}")
        return []
