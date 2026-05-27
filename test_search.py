import logging
logging.basicConfig(level=logging.INFO)
from app.services.kb_service import search_kb

def main():
    print("Đang khởi động cỗ máy tìm kiếm...")
    res = search_kb("Điều kiện ngoại ngữ đầu vào", top_k=3)
    print("\n====== KẾT QUẢ TỪ BGE-M3 RERANKER ======")
    for i, r in enumerate(res):
        score = r.get("score", 0)
        content = r.get("content", "")
        print(f"\n[Top {i+1}] Độ tin cậy: {score:.4f}")
        print("-" * 40)
        print(content)

if __name__ == "__main__":
    main()
