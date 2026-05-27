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

def _calculate_chunks_hash(chunks: list[str]) -> str:
    """Tính toán mã băm SHA-256 của danh sách chunk để phát hiện thay đổi nội dung."""
    import hashlib
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk.encode('utf-8'))
    return hasher.hexdigest()

def index_chunks(chunks: list[str], ids: list[str]) -> None:
    """Thêm dữ liệu văn bản vào ChromaDB collection với kiểm tra hash chống nạp lại trùng."""
    if not collection or not chunks or len(chunks) != len(ids):
        return
        
    try:
        current_hash = _calculate_chunks_hash(chunks)
        # Lấy metadata hiện có từ collection
        coll_metadata = collection.metadata or {}
        saved_hash = coll_metadata.get("chunks_hash")
        existing_count = collection.count()
        
        # Nếu hash khớp và số lượng chunks khớp, bỏ qua re-indexing cực kỳ an toàn và nhanh chóng
        if saved_hash == current_hash and existing_count == len(chunks):
            logger.info(f"[vector] ChromaDB is up-to-date with {existing_count} chunks (hash: {saved_hash[:8]}). Skipping indexing.")
            return
            
        logger.info(f"[vector] Re-indexing ChromaDB with {len(chunks)} chunks (old count: {existing_count}, old hash: {str(saved_hash)[:8]})...")
        
        # Xóa sạch các tài liệu cũ để tránh trùng lặp
        if existing_count > 0:
            try:
                all_docs = collection.get()
                if all_docs and 'ids' in all_docs and all_docs['ids']:
                    collection.delete(ids=all_docs['ids'])
                    logger.info("[vector] Cleared existing ChromaDB chunks to avoid duplicates.")
            except Exception as del_err:
                logger.warning(f"[vector] Failed to clear collection before indexing: {del_err}")
        
        # Thêm theo từng batch nhỏ để tránh vượt quá giới hạn tối đa của ChromaDB (5461 items)
        batch_size = 500
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            
            # Sử dụng batch encoding cực nhanh thay vì lặp từng phần tử trên CPU
            if embedder is not None:
                batch_embeddings = embedder.encode(batch_chunks, batch_size=128, show_progress_bar=False).tolist()
            else:
                batch_embeddings = [[] for _ in batch_chunks]
            
            collection.add(
                documents=batch_chunks,
                embeddings=batch_embeddings,
                ids=batch_ids
            )
            logger.info(f"[vector] Indexed batch {i//batch_size + 1}/{-(-len(chunks)//batch_size)}")
            
        # Cập nhật hash mới vào metadata của collection
        new_metadata = {k: v for k, v in coll_metadata.items() if not k.startswith("hnsw:")}
        new_metadata["chunks_hash"] = current_hash
        collection.modify(metadata=new_metadata)
        logger.info(f"[vector] Successfully indexed all {len(chunks)} chunks into ChromaDB (new hash: {current_hash[:8]}).")
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
