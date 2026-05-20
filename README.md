# 🎓 Cô giáo Thắm UFM Chatbot (v4.2.0)

Hệ thống Chatbot AI Tuyển sinh Thông minh dành riêng cho **Viện Đào tạo Sau đại học - Trường Đại học Tài chính - Marketing (UFM)**.
Phiên bản v4.2.0 hoàn thiện hóa khả năng triển khai với cấu trúc **Docker hóa toàn diện (Fully Dockerized)**, đóng gói trực tiếp 13 Quyết định chương trình đào tạo (.md) đi kèm ứng dụng và hỗ trợ bộ lưu trữ Database vĩnh viễn trên máy chủ.

## 🌟 Tính năng Nổi bật (Core Features)

### 1. 🐳 Đóng gói Docker Tự chứa (Fully Dockerized & Self-Contained)
- **Đóng gói mã nguồn & dữ liệu gốc:** Thư mục tri thức khóa học `app/knowledge_base/` chứa 13 quyết định và khung chương trình học được sao chép trực tiếp vào bên trong Docker Image, đảm bảo ứng dụng luôn có đủ tri thức gốc mà không lo thất lạc thư mục khi tải về máy khác.
- **Poppler & Tesseract tích hợp:** Dockerfile tự động cài đặt sẵn `poppler-utils` (phục vụ việc chuyển PDF sang ảnh cho AI Vision đọc) và `tesseract-ocr` (hỗ trợ OCR dự phòng).
- **Bộ nhớ vĩnh viễn (Host-mounted Volumes):** Toàn bộ QA Cache và lịch sử học viên được đồng bộ trực tiếp ra thư mục `./app/database/` trên máy chủ vật lý, đảm bảo dữ liệu không bao giờ bị mất khi khởi động lại hay cập nhật container.

### 2. 🇻🇳 Lõi Xử lý Ngôn ngữ Tự nhiên Tiếng Việt (Underthesea NLP)
Hệ thống được tích hợp bộ công cụ NLP `underthesea` chuyên biệt cho tiếng Việt:
- **Tách từ thông minh (Word Tokenize):** Thay vì tách từng chữ (như "sinh", "viên"), AI hiểu được các cụm từ ghép ("sinh_viên", "tài_chính") để tính toán BM25 và độ tương đồng ngữ nghĩa chính xác 100%.
- Giúp chatbot hiểu đúng văn cảnh tiếng Việt phức tạp hơn, tra cứu Knowledge Base và Semantic Cache mượt mà hơn.

### 3. ⚡ Hybrid RAG & Knowledge Base (Bộ não Tri thức Lai)
Hệ thống kết hợp hoàn hảo giữa dữ liệu Offline và Online:
- **Ưu tiên tuyệt đối Offline KB:** Toàn bộ kho tài liệu `.md` (Chương trình đào tạo, Quy chế) được nạp trực tiếp vào RAM từ thư mục tích hợp `app/knowledge_base/`. Khi có câu hỏi, chatbot **bắt buộc lục tìm trong KB trước**. 
- Nếu tìm thấy dữ liệu chuẩn với điểm tự tin cao, nó sẽ **bỏ qua bước tìm kiếm web** để tiết kiệm thời gian (thời gian phản hồi < 1s).
- **Live Web Crawler:** Tự động cào dữ liệu từ website `daotaosdh.ufm.edu.vn` làm dự phòng nếu offline không có dữ liệu.

### 4. 🧠 Siêu Bộ Nhớ Vĩnh Viễn (Persistent Cache Database)
Tất cả bộ nhớ đã được đưa vào thư mục nội bộ `app/database/` để đảm bảo lưu trữ vĩnh viễn và sống chung với vòng đời của ứng dụng:
- **Semantic QA Cache (`qa_cache.json`):** Tự động lưu trữ CÂU HỎI + CÂU TRẢ LỜI. Nhờ Underthesea NLP, các câu hỏi tương tự được nhận diện cực kì chuẩn. Học viên hỏi trùng ý, AI phản hồi tức thì trong 0 giây.
- **Persistent PDF Cache (`pdfs/`):** Kết quả AI Vision OCR bóc tách từ PDF được lưu vĩnh viễn xuống ổ cứng nội bộ.

### 5. 🎯 Tự động Phân tích Tiềm năng Học viên (AI Lead Scoring)
- **CRM Dashboard:** Giao diện quản lý thời gian thực tại `/crm/` dành cho chuyên viên tuyển sinh.
- **Tự động chấm điểm (Lead Scoring 100 điểm):** Hệ thống âm thầm đánh giá mức độ quan tâm của học viên dựa trên hành vi chat.

---

## 🛠️ Cài đặt & Vận hành

### Yêu cầu hệ thống
- Đã cài đặt **Docker** và **Docker Compose**.
- Tài khoản API FPT Cloud (Model Qwen3-32B và Qwen2.5-VL-7B) cấu hình trong file `.env`.

---

### Cách 1: Triển khai nhanh bằng Docker (Khuyên Dùng)

1. **Chuẩn bị file `.env` ở thư mục gốc chứa các khóa API:**
   ```env
   FPT_CLOUD_API_KEY="Mã API của bạn"
   CRM_DASHBOARD_PASSWORD="ufm_crm_2026"
   ```

2. **Khởi chạy ứng dụng:**
   Chỉ cần chạy duy nhất một lệnh sau:
   ```bash
   docker compose up --build -d
   ```

   *Lệnh này sẽ tự động tải các thư viện hệ thống (poppler, tesseract), đóng gói ứng dụng kèm theo 13 file tri thức `.md`, khởi tạo cổng 8001 và chạy ngầm ứng dụng một cách an toàn.*

3. **Quản lý container:**
   - Xem logs hoạt động: `docker compose logs -f`
   - Dừng ứng dụng: `docker compose down`

---

### Cách 2: Triển khai thủ công (Không dùng Docker)

1. **Cài đặt thư viện Python:**
   ```bash
   pip3 install -r requirements.txt
   ```
2. **Cài đặt thư viện hệ thống bắt buộc (đặc biệt là Poppler):**
   - **macOS:** `brew install poppler tesseract`
   - **Ubuntu/Debian:** `sudo apt-get install -y poppler-utils tesseract-ocr`
3. **Cấu hình môi trường (.env):**
   Tạo file `.env` và điền `FPT_CLOUD_API_KEY` của bạn.
4. **Chạy Server:**
   ```bash
   uvicorn app.main:app --port 8001 --reload
   ```

---

## 🏗️ Cấu trúc thư mục cốt lõi
- `app/knowledge_base/`: Kho dữ liệu Markdown Offline tích hợp trực tiếp bên trong Docker (Bắt buộc truy xuất trước tiên).
- `app/database/`: Nơi lưu trữ bộ nhớ dài hạn, QA Cache và PDF Cache (Được mount ra máy chủ vật lý).
- `app/routes/`: Các API endpoints (chat, handoff, crm).
- `app/services/`: Logic nghiệp vụ lõi:
  - `kb_service.py`: Xử lý Offline RAG BM25 siêu tốc với *underthesea*.
  - `pdf_service.py`: Xử lý OCR và AI Vision.
  - `crm_service.py`: Chấm điểm Lead Scoring & Lưu trữ JSON.
  - `cache_service.py`: Semantic QA Cache.
- `static/`: Giao diện Web Client & Dashboard CRM.

---
*Phát triển chuyên biệt cho Viện Đào tạo Sau đại học UFM.*
