"""
app/services/pdf_service.py — PDF extraction với 3 tầng fallback:
  Tầng 1: PyMuPDF text layer (nhanh, đọc PDF text layer)
  Tầng 2: Jina Reader fallback (cloud OCR)
  Tầng 3: pdf2image + Tesseract OCR (local OCR cho PDF scan/ảnh)
"""
import io
import os
import re
import json
import logging
import asyncio
import hashlib
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import fitz  # PyMuPDF

from app.config import settings
from app.services import cache_service

logger = logging.getLogger("ufm-chatbot")

# ── OCR availability check ────────────────────────────────
_TESSERACT_AVAILABLE = False
_POPPLER_AVAILABLE = False

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True
    logger.info("[pdf] Tesseract OCR: AVAILABLE")
except Exception:
    logger.warning("[pdf] Tesseract OCR: NOT AVAILABLE (install tesseract-ocr for scanned PDF support)")

try:
    from pdf2image import convert_from_bytes
    from pdf2image.exceptions import PDFInfoNotInstalledError
    # Quick check if poppler is available
    _POPPLER_AVAILABLE = True
    logger.info("[pdf] pdf2image (Poppler): AVAILABLE")
except ImportError:
    logger.warning("[pdf] pdf2image: NOT INSTALLED")
except Exception:
    logger.warning("[pdf] pdf2image: AVAILABLE but Poppler may be missing")

try:
    import cv2
    import numpy as np
    from PIL import Image
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("[pdf] OpenCV/Pillow: NOT AVAILABLE (image preprocessing disabled)")

# ── Constants from settings ───────────────────────────────
TESSERACT_LANG = getattr(settings, 'TESSERACT_LANG', 'vie+eng')
OCR_DPI = getattr(settings, 'OCR_DPI', 300)
MIN_TEXT_LENGTH = getattr(settings, 'OCR_MIN_TEXT_LENGTH', 100)
MAX_PDF_SIZE_MB = getattr(settings, 'MAX_PDF_SIZE_MB', 25)
PDF_TIMEOUT = 30

# Set TESSDATA_PREFIX if configured
tessdata = getattr(settings, 'TESSDATA_PREFIX', '')
if tessdata:
    os.environ.setdefault("TESSDATA_PREFIX", tessdata)

# ── Extraction log ────────────────────────────────────────
_LOG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "pdf_extraction_log.jsonl"


def _log_extraction(entry: dict):
    """Append extraction result to JSONL log file."""
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # Non-critical


# ── Image preprocessing pipeline ─────────────────────────
def preprocess_image_for_ocr(pil_image):
    """
    Tiền xử lý ảnh để tăng độ chính xác Tesseract OCR:
    1. Grayscale
    2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
    3. Denoise
    4. Adaptive thresholding
    5. Deskew
    """
    if not _CV2_AVAILABLE:
        return pil_image

    img_array = np.array(pil_image)

    # Grayscale
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Light denoise
    denoised = cv2.GaussianBlur(enhanced, (1, 1), 0)

    # Adaptive threshold
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Deskew
    coords = np.column_stack(np.where(thresh < 128))
    if len(coords) > 10:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if 0.5 < abs(angle) < 15:
            h, w = thresh.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(
                thresh, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )

    return Image.fromarray(thresh)


# ── Tầng 1: PyMuPDF text layer ───────────────────────────
def extract_text_pymupdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract text layer from PDF using PyMuPDF. Returns (text, num_pages)."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_pages = len(doc)
        texts = []
        for page_num in range(num_pages):
            page = doc[page_num]
            text = page.get_text("text")
            if text.strip():
                texts.append(f"[Trang {page_num + 1}]\n{text.strip()}")
        doc.close()
        return "\n\n".join(texts), num_pages
    except Exception as e:
        logger.warning(f"[pdf] PyMuPDF failed: {e}")
        return "", 0


# ── Tầng 2: FPT Cloud Qwen-VL (Vision OCR) ────────────────
async def extract_text_fpt_vision(pdf_bytes: bytes) -> tuple[str, str]:
    """Sử dụng Qwen2.5-VL-7B-Instruct trên FPT Cloud để đọc PDF dạng ảnh."""
    import base64
    from app.config import settings
    
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_pages = min(len(doc), 5)  # Giới hạn 5 trang đầu để tránh quá tải/chi phí
        texts = []
        
        headers = {
            "Authorization": f"Bearer {settings.FPT_CLOUD_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=45.0) as client:
            for page_num in range(num_pages):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("jpeg")
                b64_img = base64.b64encode(img_bytes).decode('utf-8')
                
                payload = {
                    "model": "Qwen2.5-VL-7B-Instruct",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Trích xuất toàn bộ văn bản trong hình ảnh này. Chỉ trả về văn bản, không bình luận thêm."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                            ]
                        }
                    ]
                }
                
                response = await client.post(
                    settings.FPT_CLOUD_BASE_URL + "/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    page_text = response.json()['choices'][0]['message']['content']
                    texts.append(f"[Trang {page_num + 1}]\n{page_text.strip()}")
                else:
                    logger.warning(f"[pdf] Qwen-VL page {page_num+1} failed: {response.text}")
                    
        doc.close()
        full_text = "\n\n".join(texts)
        if full_text:
            return full_text, "qwen_vl_ocr"
        return "", "ocr_failed"
        
    except Exception as e:
        logger.error(f"[pdf] Qwen-VL OCR failed: {e}")
        return "", "ocr_failed"


# ── Text cleaning ────────────────────────────────────────
def clean_extracted_text(text: str) -> str:
    """Clean extracted text: remove garbage chars, normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^[.\-_=~*]{5,}$', '', text, flags=re.MULTILINE)
    lines = [re.sub(r'[ \t]{2,}', ' ', line).rstrip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


# ── PDF link extraction from HTML ─────────────────────────
def extract_pdf_links(html_content: str) -> list[str]:
    """Find PDF links in HTML content, only keep allowed domain."""
    links = re.findall(r'https?://[^\s\)\"\>\'\]]+\.pdf', html_content, re.IGNORECASE)
    seen, unique = set(), []
    for link in links:
        parsed = urlparse(link)
        if link not in seen and (parsed.hostname or "").endswith(settings.ALLOWED_DOMAIN):
            seen.add(link)
            unique.append(link)
    return unique


def is_pdf_url(url: str) -> bool:
    """Check if URL is a PDF."""
    url_lower = url.lower()
    return url_lower.endswith('.pdf') or '/pdf/' in url_lower or 'filetype=pdf' in url_lower


def extract_pdf_links_from_html(html_content: str, base_url: str) -> list[str]:
    """Find all PDF links from crawled HTML, return full URLs."""
    from urllib.parse import urljoin
    pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', re.IGNORECASE)
    matches = pdf_pattern.findall(html_content)
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    pdf_urls = set()
    for match in matches:
        if match.startswith('http'):
            full_url = match
        elif match.startswith('/'):
            full_url = base_domain + match
        else:
            full_url = urljoin(base_url, match)
        if settings.ALLOWED_DOMAIN in full_url:
            pdf_urls.add(full_url)
    return list(pdf_urls)


# ══════════════════════════════════════════════════════════
# MAIN: Smart PDF extraction with 3-tier fallback
# ══════════════════════════════════════════════════════════
async def read_pdf(pdf_url: str) -> Optional[str]:
    """
    Download + extract PDF text with 3-tier fallback:
      1. PyMuPDF text layer (fast, no OCR needed)
      2. Jina Reader (cloud OCR)
      3. Tesseract OCR (local, for scanned PDFs)
    Returns extracted text or None.
    """
    t0 = time.time()

    # Cache check
    cached = cache_service.get_pdf(pdf_url)
    if cached:
        _log_extraction({"url": pdf_url, "method": "cache_hit", "time_ms": 0,
                         "chars": len(cached), "timestamp": time.time()})
        return cached

    try:
        # Download PDF
        async with httpx.AsyncClient(timeout=PDF_TIMEOUT, follow_redirects=True, verify=False) as client:
            response = await client.get(pdf_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; UFMBot/1.0)",
                "Accept": "application/pdf,*/*",
            })
            response.raise_for_status()

        pdf_bytes = response.content
        size_mb = len(pdf_bytes) / (1024 * 1024)

        if size_mb > MAX_PDF_SIZE_MB:
            logger.warning(f"[pdf] TOO LARGE {size_mb:.1f}MB: {pdf_url}")
            return None

        logger.info(f"[pdf] Downloaded {pdf_url.split('/')[-1]} ({size_mb:.1f}MB)")

        method = "none"
        text = ""
        num_pages = 0

        # ── Tầng 1: PyMuPDF text layer ──
        pymupdf_text, num_pages = extract_text_pymupdf(pdf_bytes)
        if len(pymupdf_text.strip()) >= MIN_TEXT_LENGTH:
            text = clean_extracted_text(pymupdf_text)
            method = "pymupdf_text_layer"
            logger.info(f"[pdf] Tầng 1 (PyMuPDF text): {len(text)} chars")
        else:
            logger.info(f"[pdf] Text layer too short ({len(pymupdf_text.strip())} chars), fallback to Vision OCR...")

            # ── Tầng 2: FPT Cloud Vision OCR ──
            vl_text, vl_method = await extract_text_fpt_vision(pdf_bytes)
            if len(vl_text.strip()) >= 50:
                text = clean_extracted_text(vl_text)
                method = "qwen_vl_ocr"
                num_pages = max(num_pages, vl_text.count("[Trang "))
                logger.info(f"[pdf] Tầng 2 (Qwen-VL OCR): {len(text)} chars")
            else:
                logger.error(f"[pdf] ALL METHODS FAILED: {pdf_url}")

        # Truncate for context window
        if text:
            text = text[:4000]
            cache_service.set_pdf(pdf_url, text)

        elapsed_ms = int((time.time() - t0) * 1000)
        _log_extraction({
            "url": pdf_url, "size_mb": round(size_mb, 2), "method": method,
            "pages": num_pages, "chars": len(text), "time_ms": elapsed_ms,
            "success": bool(text), "timestamp": time.time(),
        })
        logger.info(f"[PDF] {pdf_url.split('/')[-1]} | {size_mb:.1f}MB | {method} | "
                     f"Pages:{num_pages} | Chars:{len(text)} | {elapsed_ms}ms")

        return text if text else None

    except httpx.TimeoutException:
        logger.error(f"[pdf] TIMEOUT: {pdf_url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"[pdf] HTTP {e.response.status_code}: {pdf_url}")
        return None
    except Exception as e:
        logger.error(f"[pdf] ERROR: {e} — {pdf_url}")
        return None


async def read_pdfs(pdf_urls: list[str], max_pdfs: int = 3) -> dict[str, str]:
    """Read multiple PDFs concurrently with limit."""
    urls = pdf_urls[:max_pdfs]
    results = {}
    gathered = await asyncio.gather(*[read_pdf(u) for u in urls], return_exceptions=True)
    for url, result in zip(urls, gathered):
        if isinstance(result, str) and result:
            results[url] = result
    return results


def get_ocr_health() -> dict:
    """Return OCR system health info for diagnostic endpoint."""
    info = {
        "tesseract_available": _TESSERACT_AVAILABLE,
        "poppler_available": _POPPLER_AVAILABLE,
        "cv2_available": _CV2_AVAILABLE,
        "tessdata_prefix": os.environ.get("TESSDATA_PREFIX", "not set"),
        "tesseract_lang": TESSERACT_LANG,
        "ocr_dpi": OCR_DPI,
    }
    if _TESSERACT_AVAILABLE:
        try:
            info["tesseract_version"] = str(pytesseract.get_tesseract_version())
            info["installed_languages"] = pytesseract.get_languages(config='')
            info["vietnamese_available"] = "vie" in info["installed_languages"]
        except Exception as e:
            info["tesseract_error"] = str(e)
    return info
