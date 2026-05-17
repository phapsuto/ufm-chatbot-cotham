# 🎓 Cô giáo Thắm UFM Chatbot (v4.1.0)

Hệ thống Chatbot AI Tuyển sinh Thông minh dành riêng cho **Viện Đào tạo Sau đại học - Trường Đại học Tài chính - Marketing (UFM)**.
Phiên bản v4.1.0 đánh dấu sự hoàn thiện toàn diện với bộ não Tiếng Việt NLP và lưu trữ Data tích hợp chặt chẽ vào mã nguồn.

## 🌟 Tính năng Nổi bật (Core Features)

### 1. 🇻🇳 Lõi Xử lý Ngôn ngữ Tự nhiên Tiếng Việt (Underthesea NLP)
Hệ thống được tích hợp bộ công cụ NLP `underthesea` chuyên biệt cho tiếng Việt:
- **Tách từ thông minh (Word Tokenize):** Thay vì tách từng chữ (như "sinh", "viên"), AI hiểu được các cụm từ ghép ("sinh_viên", "tài_chính") để tính toán BM25 và độ tương đồng ngữ nghĩa chính xác 100%.
- Giúp chatbot hiểu đúng văn cảnh tiếng Việt phức tạp hơn, tra cứu Knowledge Base và Semantic Cache mượt mà hơn.

### 2. ⚡ Hybrid RAG & Knowledge Base (Bộ não Tri thức Lai)
Hệ thống kết hợp hoàn hảo giữa dữ liệu Offline và Online:
- **Ưu tiên tuyệt đối Offline KB:** Toàn bộ kho tài liệu `.md` (Chương trình đào tạo, Quy chế) được nạp trực tiếp vào RAM từ thư mục tích hợp `app/knowledge_base/`. Khi có câu hỏi, chatbot **bắt buộc lục tìm trong KB trước**. 
- Nếu tìm thấy dữ liệu chuẩn với điểm tự tin cao, nó sẽ **bỏ qua bước tìm kiếm web** để tiết kiệm thời gian (thời gian phản hồi < 1s).
- **Live Web Crawler:** Tự động cào dữ liệu từ website `daotaosdh.ufm.edu.vn` làm dự phòng nếu offline không có dữ liệu.

### 3. 🧠 Siêu Bộ Nhớ Vĩnh Viễn (Persistent Cache Database)
Tất cả bộ nhớ đã được đưa vào thư mục nội bộ `app/database/` để đảm bảo lưu trữ vĩnh viễn và sống chung với vòng đời của ứng dụng:
- **Semantic QA Cache (`qa_cache.json`):** Tự động lưu trữ CÂU HỎI + CÂU TRẢ LỜI. Nhờ Underthesea NLP, các câu hỏi tương tự được nhận diện cực kì chuẩn. Học viên hỏi trùng ý, AI phản hồi tức thì trong 0 giây.
- **Persistent PDF Cache (`pdfs/`):** Kết quả AI Vision OCR bóc tách từ PDF được lưu vĩnh viễn xuống ổ cứng nội bộ.

### 4. 🎯 Tự động Phân tích Tiềm năng Học viên (AI Lead Scoring)
- **CRM Dashboard:** Giao diện quản lý thời gian thực tại `/crm/` dành cho chuyên viên tuyển sinh.
- **Tự động chấm điểm (Lead Scoring 100 điểm):** Hệ thống âm thầm đánh giá mức độ quan tâm của học viên dựa trên hành vi chat.

### 5. 👁️‍🗨️ AI Vision PDF Reader
Khắc phục hoàn toàn điểm yếu của các chatbot truyền thống khi gặp file PDF dạng ảnh scan (có mộc đỏ, chữ ký).
- Gửi ảnh trang PDF cho siêu mô hình thị giác **Qwen2.5-VL-7B-Instruct** (FPT Cloud) để bóc tách text.

---

## 🛠️ Cài đặt & Vận hành

### Yêu cầu hệ thống
- Python 3.10+
- `underthesea>=6.8.0`
- Tài khoản API FPT Cloud (Model Qwen3-32B và Qwen2.5-VL-7B)

### Khởi động dự án
1. **Cài đặt thư viện:**
   ```bash
   pip3 install -r requirements.txt
   ```
2. **Cấu hình môi trường (.env):**
   ```env
   FPT_CLOUD_API_KEY="Mã API của bạn"
   CRM_DASHBOARD_PASSWORD="ufm_crm_2026"
   ```
3. **Chạy Server:**
   ```bash
   uvicorn app.main:app --port 8001 --reload
   ```

### Truy cập
- **Chat Interface:** [http://localhost:8001](http://localhost:8001)
- **CRM Dashboard:** [http://localhost:8001/crm/](http://localhost:8001/crm/)

---

## 🏗️ Cấu trúc thư mục cốt lõi
- `app/knowledge_base/`: Kho dữ liệu Markdown Offline tích hợp (Bắt buộc truy xuất trước tiên).
- `app/database/`: Nơi lưu trữ bộ nhớ dài hạn, QA Cache và PDF Cache.
- `app/routes/`: Các API endpoints (chat, handoff, crm).
- `app/services/`: Logic nghiệp vụ lõi:
  - `kb_service.py`: Xử lý Offline RAG BM25 siêu tốc với *underthesea*.
  - `pdf_service.py`: Xử lý OCR và AI Vision.
  - `crm_service.py`: Chấm điểm Lead Scoring & Lưu trữ JSON.
  - `cache_service.py`: Semantic QA Cache.
- `static/`: Giao diện Web Client & Dashboard CRM.

---
*Phát triển chuyên biệt cho Viện Đào tạo Sau đại học UFM.*
