# 🎓 Cô giáo Thắm UFM Chatbot (v4.0.0)

Hệ thống Chatbot AI Tuyển sinh Thông minh dành riêng cho **Viện Đào tạo Sau đại học - Trường Đại học Tài chính - Marketing (UFM)**.
Phiên bản v4.0.0 đánh dấu sự lột xác toàn diện từ một chatbot hỏi-đáp thông thường thành **Hệ thống CRM Tư vấn Tuyển sinh Tự động (AI Recruitment CRM)**.

## 🌟 Tính năng Nổi bật (Core Features)

### 1. 🎯 Tự động Phân tích Tiềm năng Học viên (AI Lead Scoring)
- **CRM Dashboard:** Giao diện quản lý thời gian thực tại `/crm/` dành cho chuyên viên tuyển sinh.
- **Tự động chấm điểm (Lead Scoring 100 điểm):** Hệ thống âm thầm đánh giá mức độ quan tâm của học viên dựa trên hành vi chat.
  - *Profile (25đ):* Thu thập Tên, Tuổi, Bằng cấp qua cổng Onboarding bắt buộc.
  - *Engagement (40đ):* Tính điểm dựa trên số lượng câu hỏi và độ dài cuộc hội thoại.
  - *Action/Intent (35đ):* Nhận diện ý định quan trọng (Hỏi học phí, Cách đăng ký, Thời gian nộp hồ sơ).

### 2. ⚡ Hybrid RAG & Knowledge Base (Bộ não Tri thức Lai)
Hệ thống kết hợp hoàn hảo giữa dữ liệu Offline và Online:
- **Offline BM25 Engine:** Nạp toàn bộ kho tài liệu `.md` (Chương trình đào tạo, Quy chế) vào RAM. Truy xuất siêu tốc (0.01s) bằng thuật toán BM25.
- **Live Web Crawler:** Tự động cào dữ liệu từ website `daotaosdh.ufm.edu.vn` làm dự phòng nếu offline không có.

### 3. 👁️‍🗨️ AI Vision PDF Reader
Khắc phục hoàn toàn điểm yếu của các chatbot truyền thống khi gặp file PDF dạng ảnh scan (có mộc đỏ, chữ ký).
- Tự động bắt link PDF trên website UFM.
- Nếu là ảnh scan, chatbot cắt trang và gửi cho siêu mô hình thị giác **Qwen2.5-VL-7B-Instruct** (FPT Cloud) để bóc tách text chính xác 100%.

### 4. 🧠 Siêu Bộ Nhớ (Semantic QA Cache & Persistent PDF)
- **Semantic QA Cache:** Tự động lưu trữ CÂU HỎI + CÂU TRẢ LỜI. Nếu học viên sau hỏi một câu giống >90%, AI phản hồi tức thì trong 0 giây, không tốn API.
- **Persistent PDF Cache:** Kết quả OCR bóc tách từ PDF được lưu vĩnh viễn xuống ổ cứng. Chỉ tốn thời gian đọc ở người hỏi đầu tiên.

### 5. 🗣️ Xưng hô Cảm Xúc & Gợi ý Thông minh
- Nhận diện tuổi từ Onboarding để chọn đại từ xưng hô phù hợp (`Cô - em` cho người trẻ, `Tôi - anh/chị` cho người lớn tuổi).
- **Contextual Suggestions:** Các nút bấm gợi ý câu hỏi tiếp theo được AI sinh ra (Generate) dựa trên đúng mạch câu chuyện đang nói.

---

## 🛠️ Cài đặt & Vận hành

### Yêu cầu hệ thống
- Python 3.10+
- Môi trường Mac/Linux/Windows
- Tài khoản API FPT Cloud (Model Qwen3-32B và Qwen2.5-VL-7B)

### Khởi động dự án
1. **Cài đặt thư viện:**
   ```bash
   pip install -r requirements.txt
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
- `app/routes/`: Các API endpoints (chat, handoff, crm).
- `app/services/`: Logic nghiệp vụ lõi:
  - `kb_service.py`: Xử lý Offline RAG BM25.
  - `pdf_service.py`: Xử lý OCR và AI Vision.
  - `crm_service.py`: Chấm điểm Lead Scoring & Lưu trữ JSON.
  - `cache_service.py`: Semantic QA Cache.
- `CTDT_THACSI VA TIENSI/`: Kho dữ liệu Markdown Offline.
- `static/`: Giao diện Web Client & Dashboard CRM.

---
*Phát triển chuyên biệt cho Viện Đào tạo Sau đại học UFM.*
