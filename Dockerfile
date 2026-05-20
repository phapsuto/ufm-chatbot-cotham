# Sử dụng Python 3.10-slim làm base image để tối ưu hóa dung lượng
FROM python:3.10-slim

# Thiết lập thư mục làm việc trong container
WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết
# - poppler-utils: Bắt buộc phải có để convert PDF thành ảnh (pdf2image)
# - tesseract-ocr & tesseract-ocr-vie: Hỗ trợ OCR Tiếng Việt cục bộ dự phòng
# - gcc, g++, python3-dev, libffi-dev: Cần thiết để biên dịch một số thư viện Python (như crawl4ai, lxml, underthesea)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    libffi-dev \
    libssl-dev \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-vie \
    tesseract-ocr-eng \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập biến môi trường tránh sinh file .pyc và log buffer
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Sao chép requirements.txt trước để tận dụng Docker Cache
COPY requirements.txt .

# Nâng cấp pip và cài đặt toàn bộ thư viện Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Cài đặt Playwright Chromium (Dự phòng cho crawl4ai nếu trang web cần JS)
# Chạy với || true để nếu gặp lỗi mạng thì tiến trình build vẫn tiếp tục và sử dụng crawler tiêu chuẩn (fast_bs4)
RUN playwright install chromium --with-deps || echo "Playwright install skipped/failed. Fallback to standard crawl mode active."

# Sao chép toàn bộ mã nguồn dự án vào container (bao gồm cả thư mục app/knowledge_base chứa toàn bộ file .md)
COPY . .

# Tạo các thư mục lưu trữ dữ liệu vĩnh viễn
RUN mkdir -p app/database data/cache app/knowledge_base

# Mở cổng 8001 (FastAPI chạy trên cổng này)
EXPOSE 8001

# Lệnh khởi động server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
