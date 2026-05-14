# 🎓 Cô giáo Thắm — UFM Chatbot v4

> Trợ lý AI tư vấn tuyển sinh Sau đại học, Trường Đại học Tài chính - Marketing (UFM).  
> Tích hợp CRM & AI Lead Scoring tự động.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Tính năng

### Chatbot AI
- 🧠 **Qwen3-32B** — LLM mạnh, streaming response realtime
- 🔍 **Web Crawling** — Crawl website UFM bằng Crawl4AI + BeautifulSoup
- 📄 **PDF Pipeline** — 3-tier extraction: PyMuPDF → Jina Reader → Tesseract OCR
- 💬 **Persona "Cô Thắm"** — Xưng hô thông minh theo ngữ cảnh (cô-em, tôi-anh/chị)
- 📝 **Onboarding Gate** — Bắt buộc đăng ký trước khi chat (tên, tuổi, học vấn, liên hệ)
- 🔗 **Smart Sources** — Dẫn chứng link chính xác, có relevance scoring

### CRM & Lead Scoring
- 📊 **AI Lead Scoring** — Tự động chấm điểm 0-100, phân grade A/B/C/D
- 🔥 **Behavior Tracking** — Ghi nhận hành vi chat realtime (hỏi học phí, điều kiện, hồ sơ...)
- 📈 **CRM Dashboard** — Giao diện quản lý lead cho nhân viên trường
- 📥 **Export CSV** — Xuất danh sách lead theo filter
- 🏷️ **Status Management** — Assign, ghi chú, follow-up tracking

## 🏗 Kiến trúc

```
Học viên → Onboarding → Chat Pipeline → CRM Tracking → Lead Scoring
              ↓              ↓                ↓              ↓
        Guest Profile    LLM (Qwen3)    Behavior DB    Score 0-100
              ↓              ↓                ↓              ↓
        Session Memory   Smart Sources   Activity Log   Grade A/B/C/D
                                                            ↓
                                                    CRM Dashboard
                                                  (KPIs, Charts, Export)
```

## 🚀 Cài đặt

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_USERNAME/ufm-chatbot-cotham.git
cd ufm-chatbot-cotham

python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
playwright install chromium
```

### 2. Cấu hình

```bash
cp .env.example .env
```

Mở `.env` và điền các giá trị:

| Biến | Mô tả | Bắt buộc |
|------|--------|----------|
| `FPT_CLOUD_API_KEY` | API key FPT Cloud AI | ✅ |
| `CRM_DASHBOARD_PASSWORD` | Mật khẩu CRM Dashboard | ✅ |
| `CRM_SESSION_SECRET` | Secret key cho session | ✅ |
| `LLM_TEMPERATURE` | Temperature LLM | Mặc định: 0.7 |
| `CACHE_TTL_HTML` | TTL cache HTML (giây) | Mặc định: 900 |

### 3. Chạy

```bash
uvicorn app.main:app --reload --port 8000
```

- **Chatbot**: http://localhost:8000
- **CRM Dashboard**: http://localhost:8000/crm/

### 4. OCR (tùy chọn)

Để đọc PDF scan dạng ảnh:

```bash
# macOS
brew install tesseract tesseract-lang poppler

# Ubuntu/Debian
apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils
```

## 📡 API Endpoints

### Chatbot

| Method | Path | Mô tả |
|--------|------|--------|
| `GET` | `/` | Frontend chatbot |
| `POST` | `/api/guest/register` | Đăng ký thông tin học viên |
| `POST` | `/api/chat` | Chat (streaming SSE) |
| `POST` | `/api/handoff` | Đăng ký tư vấn trực tiếp |
| `GET` | `/api/health` | Health check |

### CRM (yêu cầu `X-CRM-Token` header)

| Method | Path | Mô tả |
|--------|------|--------|
| `POST` | `/api/crm/login` | Đăng nhập CRM |
| `GET` | `/api/crm/dashboard/stats` | KPI tổng quan |
| `GET` | `/api/crm/leads` | Danh sách lead (filter + pagination) |
| `GET` | `/api/crm/leads/{id}` | Chi tiết lead + score breakdown |
| `PATCH` | `/api/crm/leads/{id}` | Cập nhật status/assign |
| `POST` | `/api/crm/leads/{id}/notes` | Thêm ghi chú |
| `GET` | `/api/crm/export/csv` | Xuất CSV |

## 📊 Lead Scoring Rubric

| Nhóm | Max | Tiêu chí |
|------|-----|----------|
| **Profile** | 25 | Trình độ (10), ngành liên quan (8), tuổi (4), kinh nghiệm (3) |
| **Engagement** | 40 | Hỏi học phí (15), điều kiện (10), liên hệ (10), lịch/hồ sơ (8), deadline (7)... |
| **Action** | 35 | Nộp hồ sơ (35), hoàn thành 80%+ (28), khẩn cấp (10), quay lại (8) |

| Grade | Score | Ý nghĩa |
|-------|-------|---------|
| 🔥 A | ≥75 | Hot Lead — liên hệ ngay |
| ⭐ B | ≥55 | Quan tâm — theo dõi tiếp |
| 💡 C | ≥35 | Cần follow-up |
| ❄️ D | <35 | Mới tiếp cận |

## 📁 Cấu trúc project

```
ufm-chatbot/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py             # Pydantic settings
│   ├── models.py             # Request/Response models
│   ├── routes/
│   │   ├── chat.py           # Chat pipeline
│   │   ├── crm.py            # CRM API endpoints
│   │   ├── guest.py          # Onboarding registration
│   │   ├── enrollment.py     # Enrollment forms
│   │   ├── handoff.py        # Tư vấn trực tiếp
│   │   └── health.py         # Health checks
│   └── services/
│       ├── llm_service.py    # LLM integration (Qwen3)
│       ├── crm_service.py    # CRM data layer
│       ├── scoring_engine.py # AI Lead Scoring
│       ├── crawler_service.py# Web crawling
│       ├── pdf_service.py    # PDF extraction (3-tier)
│       ├── memory_service.py # Session memory
│       ├── context_service.py# Context builder
│       └── ...
├── static/
│   ├── index.html            # Chatbot frontend
│   ├── app.js                # Chat UI logic
│   ├── style.css             # Chatbot styles
│   └── crm/
│       ├── index.html        # CRM Dashboard
│       ├── crm.css           # Dashboard styles
│       └── crm.js            # Dashboard logic
├── requirements.txt
├── .env.example
└── .gitignore
```

## 🔒 Bảo mật

- `.env` chứa API key — **KHÔNG** commit lên git
- CRM Dashboard được bảo vệ bằng password + SHA256 token
- Tất cả CRM API yêu cầu `X-CRM-Token` header

## 📄 License

MIT License — Phát triển bởi [Dr. Tô Nguyễn](https://github.com/YOUR_USERNAME) cho Trường ĐH Tài chính - Marketing.
