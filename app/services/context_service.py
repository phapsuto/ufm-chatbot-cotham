"""app/services/context_service.py — Gom context + smart source tracking (v3 enhanced)"""
import logging
from urllib.parse import urlparse, parse_qs
from app.services import kb_service

logger = logging.getLogger("ufm-chatbot")

MAX_CONTEXT_CHARS = 8000

# ══════════════════════════════════
# URL → Friendly Name Mapping (PHẦN 4)
# ══════════════════════════════════

URL_FRIENDLY_MAP = {
    "v1UjoAIA40d2Nl0tc5EwAA": "Tuyển sinh Thạc sĩ",
    "ffBwKFG43zUj-wnVkKHUNg": "Tuyển sinh Tiến sĩ",
    "8cr7n9Qk1GpeSBRepQ4wzA": "Chương trình Thạc sĩ",
    "lquZmR-vGhvBxct6vgs8pg": "Chương trình Tiến sĩ",
    "Bzgz-ukhgE3hS9Zo42laZQ": "Thời khóa biểu",
    "e-7LLNqh6SvXeFEhbKvEPg": "Quy định đào tạo",
    "0I0D1bv2Z33VwD8mL1xV5A": "Kế hoạch đào tạo",
    "n-Mi4GQ07dn64iP-TVTz7w": "Quy trình",
    "3nYAXkcB-_h9QVHaXbvg6g": "Thông báo & Sự kiện",
    "-K0-KOZzj-5-2_QOddP2YA": "Bảo vệ luận án",
    "ifdVPsMrJ80B-dRMjA76Ow": "Bảo vệ luận văn",
}

NGANH_ID_MAP = {
    "TCNH": "Ngành Tài chính - Ngân hàng",
    "QTKD": "Ngành Quản trị kinh doanh",
    "KT": "Ngành Kế toán",
    "KTH": "Ngành Kinh tế học",
    "QLKT": "Ngành Quản lý kinh tế",
    "LKT": "Ngành Luật kinh tế",
    "KDQT": "Ngành Kinh doanh quốc tế",
    "MKT": "Ngành Marketing",
    "TKT": "Ngành Toán kinh tế",
    "TS_QTKD": "Tiến sĩ Quản trị kinh doanh",
    "TS_TCNH": "Tiến sĩ Tài chính - Ngân hàng",
    "TS_QLKT": "Tiến sĩ Quản lý kinh tế",
}

# Keyword-based URL mapping for more accurate naming
URL_KEYWORD_MAP = {
    "tuyen-sinh": "Thông tin Tuyển sinh",
    "hoc-phi": "Thông tin Học phí",
    "thong-bao": "Thông báo & Sự kiện",
    "lien-he": "Liên hệ UFM",
    "TCNH": "Thạc sĩ Tài chính - Ngân hàng",
    "QTKD": "Thạc sĩ Quản trị Kinh doanh",
    "KeToan": "Thạc sĩ Kế toán",
    "KinhTe": "Thạc sĩ Kinh tế học",
    "QLKT": "Thạc sĩ Quản lý Kinh tế",
    "LuatKT": "Thạc sĩ Luật Kinh tế",
    "KDQT": "Thạc sĩ Kinh doanh Quốc tế",
    "Marketing": "Thạc sĩ Marketing",
    "ToanKT": "Thạc sĩ Toán Kinh tế",
    "TS_QTKD": "Tiến sĩ Quản trị Kinh doanh",
    "TS_TCNH": "Tiến sĩ Tài chính - Ngân hàng",
    "TS_QLKT": "Tiến sĩ Quản lý Kinh tế",
    "tien-si": "Chương trình Tiến sĩ",
    "thac-si": "Chương trình Thạc sĩ",
    "quychedt": "📄 Quy chế Đào tạo",
    "chuongtrinh": "📄 Chương trình Đào tạo",
    "hocphi": "📄 Bảng Học phí",
    "thongbao": "📄 Thông báo Tuyển sinh",
    "dieukien": "📄 Điều kiện Tuyển sinh",
}


def url_to_friendly_name(url: str) -> str:
    """Convert URL thành tên dễ đọc."""
    parsed = urlparse(url)
    path = parsed.path or ""
    qs = parse_qs(parsed.query)

    # Trang chủ
    if path in ("/", "") and not qs:
        return "Trang chủ Sau đại học UFM"

    # DanhMucDieuKienXTDauVao
    if "DanhMucDieuKien" in path:
        return "Điều kiện xét tuyển đầu vào"

    # ChiTietNganh.aspx?id=XXX
    if "ChiTietNganh" in path:
        nganh_id = qs.get("id", [""])[0]
        return NGANH_ID_MAP.get(nganh_id, f"Chi tiết ngành {nganh_id}")

    # ChiTiet.aspx?LoaiTin=XXX
    if "ChiTiet" in path:
        loai_tin = qs.get("LoaiTin", [""])[0]
        return URL_FRIENDLY_MAP.get(loai_tin, "Thông tin Sau đại học UFM")

    # Keyword-based matching for other URLs
    url_str = url.lower()
    for key, name in URL_KEYWORD_MAP.items():
        if key.lower() in url_str:
            return name

    # Fallback: parse path cuối URL
    path_end = url.split("/")[-1].split("?")[0]
    if path_end:
        return f"Website UFM — {path_end[:40]}"
    return "Website Sau đại học UFM"


def extract_pdf_name(pdf_url: str) -> str:
    """Lấy tên file PDF đẹp."""
    filename = pdf_url.split("/")[-1]
    name = filename.replace(".pdf", "").replace("-", " ").replace("_", " ").strip()
    # Check keyword mapping for PDF names
    for key, label in URL_KEYWORD_MAP.items():
        if key.lower() in name.lower():
            return label
    return f"📄 {name[:50]}" if name else "📄 Tài liệu PDF"


# ══════════════════════════════════
# Relevance scoring (PHẦN 4)
# ══════════════════════════════════

def _relevance_score(content: str, query: str) -> float:
    """Tính relevance score giữa content và query."""
    query_words = set(w for w in query.lower().split() if len(w) > 2)
    content_lower = content.lower()
    if not query_words:
        return 0.0
    matches = sum(1 for w in query_words if w in content_lower)
    return matches / len(query_words)


def build_context(
    html_contents: dict[str, str],
    pdf_contents: dict[str, str],
    memory_summary: str,
    query: str,
) -> tuple[str, list[dict]]:
    """Gom context với relevance scoring, trả về (context_string, sources_list)."""
    sources_with_score = []

    # Score HTML sources
    for url, content in html_contents.items():
        score = _relevance_score(content, query)
        if len(content) > 80:
            title = url_to_friendly_name(url)
            sources_with_score.append({
                "url": url,
                "title": title,
                "type": "webpage",
                "chars_used": len(content),
                "relevance": score,
            })

    # Score PDF sources
    for url, content in pdf_contents.items():
        score = _relevance_score(content, query)
        if len(content) > 80:
            sources_with_score.append({
                "url": url,
                "title": extract_pdf_name(url),
                "type": "pdf",
                "chars_used": len(content),
                "relevance": score,
            })

    # Tra cứu Offline Knowledge Base (ưu tiên cao)
    kb_chunks = kb_service.search_kb(query, top_k=3)
    if kb_chunks:
        kb_content = "\n\n---\n\n".join(kb_chunks)
        sources_with_score.append({
            "url": "offline_kb",
            "title": "Kho dữ liệu Đào tạo UFM",
            "type": "database",
            "chars_used": len(kb_content),
            "relevance": 0.9,  # High priority cho matched data offline
            "content": kb_content
        })

    # Sort by relevance + size, keep top sources
    sources_with_score.sort(key=lambda x: (x["relevance"], x["chars_used"]), reverse=True)
    top_sources = sources_with_score[:3]

    # Build context string prioritizing relevant sources
    parts = []
    for s in top_sources:
        if s["type"] == "webpage":
            content = html_contents.get(s["url"], "")
        elif s["type"] == "pdf":
            content = pdf_contents.get(s["url"], "")
        else:
            content = s.get("content", "")
        parts.append(f"[NGUỒN: {s['title']}]\n{content[:4000]}")

    # Add remaining sources with lower priority
    for s in sources_with_score[3:]:
        if s["type"] == "webpage":
            content = html_contents.get(s["url"], "")
        elif s["type"] == "pdf":
            content = pdf_contents.get(s["url"], "")
        else:
            content = s.get("content", "")
        parts.append(f"[NGUỒN: {s['title']}]\n{content[:2000]}")

    if memory_summary:
        parts.append(f"[NGỮ CẢNH HỘI THOẠI]\n{memory_summary}")

    header = "Dữ liệu được lấy trực tiếp từ website https://daotaosdh.ufm.edu.vn/\n"
    full = header + "\n\n---\n\n".join(parts)

    if len(full) > MAX_CONTEXT_CHARS:
        full = full[:MAX_CONTEXT_CHARS] + "\n... (rút gọn)"

    if not html_contents and not pdf_contents and not kb_chunks:
        full = "[CẢNH BÁO] Không thể truy cập website UFM lúc này và không có dữ liệu offline phù hợp."

    return full, top_sources


def filter_relevant_sources(answer: str, sources_used: list[dict]) -> list[dict]:
    """Post-processing: chỉ giữ sources thật sự liên quan đến answer."""
    if not sources_used:
        return []

    answer_lower = answer.lower()
    verified = []

    for source in sources_used:
        # Check title keywords match in answer
        title_keywords = [w for w in source["title"].lower().split() if len(w) > 3]
        answer_matches = sum(1 for w in title_keywords if w in answer_lower)

        # Keep source if:
        # - keywords match in answer, OR
        # - relevance score high, OR
        # - large content (likely used)
        relevance = source.get("relevance", 0)
        if answer_matches > 0 or relevance > 0.3 or source.get("chars_used", 0) > 800:
            verified.append(source)

    # Always keep at least 1 source (trang chủ fallback)
    if not verified and sources_used:
        verified = [sources_used[0]]

    return verified[:2]  # Tối đa 2


def estimate_confidence(html_contents: dict, pdf_contents: dict) -> float:
    total = sum(len(v) for v in html_contents.values()) + sum(len(v) for v in pdf_contents.values())
    if total > 1000:
        return 0.9
    if total > 200:
        return 0.6
    return 0.3
