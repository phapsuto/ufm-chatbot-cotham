# 🎓 UFM Chatbot — Cô Giáo Thắm

> **Trợ lý AI tư vấn tuyển sinh Sau Đại học — Trường Đại học Tài chính - Marketing (UFM)**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📋 Mục lục

- [Tổng quan](#-tổng-quan)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Tính năng](#-tính-năng)
- [Cây thư mục](#-cây-thư-mục)
- [Cài đặt](#-cài-đặt)
- [Cấu hình](#-cấu-hình)
- [Chạy ứng dụng](#-chạy-ứng-dụng)
- [API Endpoints](#-api-endpoints)
- [Knowledge Base](#-knowledge-base)
- [Công nghệ](#-công-nghệ)

---

## 🌟 Tổng quan

**Cô Giáo Thắm** là chatbot AI mang nhân cách cô giáo miền Nam ấm áp, chuyên tư vấn tuyển sinh các chương trình **Thạc sĩ** và **Tiến sĩ** tại UFM. Hệ thống sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp:

- 🧠 **FPT Cloud Gemma-4** — LLM chính cho chat (ổn định, không rate limit)
- 🔍 **Gemini API + Google Search** — Tìm kiếm internet chất lượng cao
- 📚 **Hybrid RAG** — BM25 + Vector Search + BGE-M3 Reranker ONNX

---

## 🏗 Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (static/)                       │
│              index.html + app.js + app.css                  │
│              CRM Dashboard: crm/index.html                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ SSE Stream
┌──────────────────────▼──────────────────────────────────────┐
│                  FastAPI Backend (app/)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📨 CHAT PIPELINE (routes/chat.py)                          │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐  │
│  │ Pronoun  │→│ KB Search │→│ Reranker  │→│ LLM Stream │  │
│  │ Detect   │  │ BM25+Vec │  │ BGE-M3   │  │ Gemma-4    │  │
│  └─────────┘  └──────────┘  └───────────┘  └────────────┘  │
│                                                             │
│  🔍 SEARCH ENGINE                                           │
│     PRIMARY:  Gemini API + Google Search Grounding           │
│     FALLBACK: DuckDuckGo HTML API                           │
│                                                             │
│  🧠 CHAT LLM                                                │
│     FPT Cloud Gemma-4 (ổn định, không rate limit)           │
│                                                             │
│  📊 RERANKER                                                │
│     BGE-Reranker-v2-M3 ONNX INT8 (~500MB, CPU only)        │
│     Hybrid: 0.3×Keyword + 0.7×CrossEncoder                 │
│                                                             │
│  📄 PDF EXTRACTION (3-tier fallback)                        │
│     PyMuPDF → Jina Reader → Tesseract OCR                   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  📋 CRM (routes/crm.py) — Lead tracking & scoring          │
│  📝 Enrollment (routes/enrollment.py) — Đăng ký online     │
│  👋 Guest (routes/guest.py) — Xác định danh tính           │
│  🤝 Handoff (routes/handoff.py) — Chuyển giao nhân viên    │
│  ❤️ Health (routes/health.py) — Monitoring                  │
└─────────────────────────────────────────────────────────────┘
```

---

## ✨ Tính năng

### 💬 Chat AI thông minh
- **Nhân cách Cô Giáo Thắm**: Xưng hô tự nhiên theo vai vế (em/cô, anh-chị/em)
- **RAG chính xác**: Trả lời dựa trên dữ liệu thực từ 272 file knowledge base
- **Anti-hallucination**: Nguyên tắc vàng — không bịa số liệu, nói thẳng khi thiếu dữ liệu
- **Streaming response**: SSE real-time, phản hồi tức thì

### 🔍 Tìm kiếm đa tầng
- **Offline KB**: Hybrid Search (BM25 + ChromaDB Vector) → BGE-M3 Reranker
- **Online Search**: Gemini API + Google Search Grounding (fallback: DuckDuckGo)
- **PDF extraction**: 3 tầng fallback (PyMuPDF → Jina Reader → Tesseract OCR)

### 📊 CRM & Lead Management
- Dashboard quản lý lead với scoring engine
- Tự động phân loại: HOT / WARM / COLD / LOST
- Export CSV, timeline hoạt động, ghi chú

### 📝 Enrollment (Đăng ký online)
- Form đăng ký dự tuyển tích hợp
- Lưu trữ hồ sơ có cấu trúc

---

## 📁 Cây thư mục

```
chtabot DH Tai Chinh/
├── app/
│   ├── config.py                # Cấu hình từ .env
│   ├── main.py                  # FastAPI app + lifespan
│   ├── models.py                # Pydantic models
│   ├── knowledge_base/          # 272 file .md (3.6MB RAG data)
│   ├── routes/
│   │   ├── chat.py              # Chat pipeline chính
│   │   ├── crm.py               # CRM Dashboard API
│   │   ├── enrollment.py        # Đăng ký dự tuyển
│   │   ├── guest.py             # Xác định danh tính
│   │   ├── handoff.py           # Chuyển giao nhân viên
│   │   └── health.py            # Health check + OCR diagnostic
│   └── services/
│       ├── llm_service.py       # FPT Cloud Gemma-4 (chat LLM)
│       ├── kb_service.py        # Hybrid Search (BM25 + Vector)
│       ├── reranker_service.py  # BGE-M3 ONNX INT8 Reranker
│       ├── vector_service.py    # ChromaDB embedding
│       ├── crawler_service.py   # Gemini Search + web crawl
│       ├── context_service.py   # Gom context + source tracking
│       ├── memory_service.py    # Session memory (pronoun, history)
│       ├── cache_service.py     # HTML/PDF/QA cache
│       ├── pdf_service.py       # PDF extraction (3-tier)
│       ├── router_service.py    # Intent classification
│       ├── crm_service.py       # CRM data layer
│       ├── enrollment_service.py # Enrollment data
│       ├── handoff_service.py   # Handoff logic
│       ├── scoring_engine.py    # Lead scoring
│       └── suggestion_service.py # Gợi ý câu hỏi
├── static/
│   ├── index.html               # Chat UI
│   ├── app.js                   # Frontend logic
│   ├── app.css                  # Styles
│   └── crm/                     # CRM Dashboard UI
├── data/                        # Runtime data (gitignored)
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker image
├── docker-compose.yml           # Docker Compose
├── .env.example                 # Template biến môi trường
└── .gitignore
```

---

## 🚀 Cài đặt

### Yêu cầu
- Python 3.11+
- 4GB RAM (cho BGE-M3 ONNX Reranker)

### Bước 1 — Clone & setup

```bash
git clone https://github.com/phapsuto/ufm-chatbot-cotham.git
cd ufm-chatbot-cotham

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Bước 2 — Tải BGE-M3 Reranker (chỉ cần 1 lần)

```bash
# Tạo thư mục shared (dùng chung nhiều app)
mkdir -p ~/shared_models/bge-reranker-v2-m3-onnx-int8

# Tải model ONNX INT8 (~500MB)
python -c "
from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer

model_name = 'BAAI/bge-reranker-v2-m3'
save_path = '$HOME/shared_models/bge-reranker-v2-m3-onnx-int8'

# Export + Quantize sang INT8
model = ORTModelForSequenceClassification.from_pretrained(model_name, export=True)
tokenizer = AutoTokenizer.from_pretrained(model_name)

from optimum.onnxruntime import ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig
quantizer = ORTQuantizer.from_pretrained(model)
qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False)
quantizer.quantize(save_dir=save_path, quantization_config=qconfig)
tokenizer.save_pretrained(save_path)
print('✅ Model saved to', save_path)
"
```

### Bước 3 — Cấu hình .env

```bash
cp .env.example .env
# Sửa .env với API keys thực
```

---

## ⚙️ Cấu hình

| Biến | Mô tả | Mặc định |
|:---|:---|:---|
| `FPT_CLOUD_API_KEY` | API key FPT Cloud (chat LLM) | *required* |
| `FPT_CLOUD_DEFAULT_MODEL` | Model chat | `gemma-4-31B-it` |
| `GEMINI_API_KEY` | API key Gemini (search grounding) | *optional* |
| `GEMINI_DEFAULT_MODEL` | Model search | `gemini-flash-latest` |
| `LLM_MAX_TOKENS` | Token tối đa mỗi response | `4096` |
| `ALLOWED_DOMAIN` | Domain crawl cho phép | `daotaosdh.ufm.edu.vn` |
| `CRM_DASHBOARD_PASSWORD` | Mật khẩu CRM | `ufm_crm_2026` |

---

## 🏃 Chạy ứng dụng

### Development
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker
```bash
docker compose up -d
```

### Truy cập
- 💬 **Chat**: http://localhost:8000
- 📊 **CRM**: http://localhost:8000/crm
- ❤️ **Health**: http://localhost:8000/health

---

## 🔌 API Endpoints

### Chat
| Method | Path | Mô tả |
|:---|:---|:---|
| `POST` | `/api/chat` | Gửi tin nhắn (SSE stream) |
| `GET` | `/api/suggestions` | Gợi ý câu hỏi tiếp theo |

### Guest & Enrollment
| Method | Path | Mô tả |
|:---|:---|:---|
| `POST` | `/api/guest/identify` | Xác định danh tính |
| `POST` | `/api/enroll/submit` | Gửi đăng ký dự tuyển |

### CRM Dashboard
| Method | Path | Mô tả |
|:---|:---|:---|
| `GET` | `/api/crm/leads` | Danh sách leads |
| `GET` | `/api/crm/leads/{id}` | Chi tiết lead |
| `POST` | `/api/crm/leads/{id}/notes` | Ghi chú lead |
| `GET` | `/api/crm/export/csv` | Export CSV |
| `GET` | `/api/crm/stats` | Thống kê tổng hợp |

### Admin & Health
| Method | Path | Mô tả |
|:---|:---|:---|
| `GET` | `/health` | Health check |
| `GET` | `/health/detail` | Chi tiết cache & sessions |
| `POST` | `/admin/clear-cache` | Xoá cache (cần secret) |

---

## 📚 Knowledge Base

Dữ liệu RAG gồm **272 file Markdown** (~3.6MB), được crawl và chuẩn hoá từ website chính thức [daotaosdh.ufm.edu.vn](https://daotaosdh.ufm.edu.vn):

| Prefix | Nội dung | Số lượng |
|:---|:---|:---|
| `sdh_ts_*` | Chương trình Tiến sĩ | ~10 |
| `sdh_ths_*` | Chương trình Thạc sĩ (9 ngành) | ~30 |
| `sdh_*` | Quy chế, biểu mẫu, học phí SĐH | ~20 |
| `web_main_*` | Tin tức, hợp tác quốc tế, sự kiện | ~200 |
| `web_tu-van_*` | Tư vấn tuyển sinh | ~10 |

### Cập nhật Knowledge Base

Thêm file `.md` mới vào `app/knowledge_base/` → restart server → tự động index lại.

---

## 🛠 Công nghệ

| Thành phần | Công nghệ | Ghi chú |
|:---|:---|:---|
| **Backend** | FastAPI + Uvicorn | Async, SSE streaming |
| **Chat LLM** | FPT Cloud Gemma-4 31B | PRIMARY — ổn định |
| **Search** | Gemini API + Google Search | Grounding chất lượng cao |
| **Embedding** | `all-MiniLM-L6-v2` + ChromaDB | Vector search |
| **BM25** | `rank_bm25` (in-memory) | Keyword search |
| **Reranker** | BGE-M3 ONNX INT8 (~500MB) | 98% accuracy, CPU only |
| **PDF** | PyMuPDF + Jina + Tesseract | 3-tier fallback |
| **Frontend** | Vanilla HTML/CSS/JS | Lightweight, no framework |
| **Deploy** | Docker + Docker Compose | Single-container |

---

## 📝 Changelog

### v5.0.0 (2026-05-28) — Kiến trúc phân vai
- 🔄 **Phân vai LLM**: FPT Cloud Gemma-4 = chat, Gemini API = search grounding
- 🔍 **Nâng cấp search**: Gemini Google Search thay DuckDuckGo (fallback DDG)
- 🐛 **Fix double KB search**: context_service không còn gọi search_kb() lần 2
- 🎯 **Hạ ngưỡng reranker**: 0.6 → 0.35 (phù hợp hybrid BGE-M3)
- 🛡 **Anti-hallucination**: Thêm NGUYÊN TẮC VÀNG + thứ tự ưu tiên nguồn
- 🧹 **Code cleanup**: Xoá 8 unused imports, 5 unused dependencies, 22 temp scripts

### v4.0.0 (2026-05-28) — BGE-M3 ONNX Reranker
- ⚡ Reranker mới: BGE-M3 ONNX INT8 (98% accuracy, ~500MB, CPU)
- 🔗 Shared model architecture (`~/shared_models/`)
- 📄 PDF 3-tier fallback (PyMuPDF → Jina → Tesseract OCR)
- 📊 CRM Dashboard với lead scoring engine

### v3.0.0 — Hybrid Search + Vietnamese NLP
- 🔍 Hybrid Search: BM25 + Vector + Metadata Boosting
- 🇻🇳 Vietnamese tokenizer (underthesea)
- 💾 QA Cache cho câu hỏi lặp

---

## 📄 License

MIT License — xem [LICENSE](LICENSE)
