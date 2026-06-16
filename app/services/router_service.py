"""app/services/router_service.py — Semantic Intent Router + URL mapping"""
import logging
import re
import numpy as np
from app.config import settings
from app.services import vector_service

logger = logging.getLogger("ufm-chatbot")

BASE = f"https://{settings.ALLOWED_DOMAIN}"

CATEGORY_PAGES = {
    "tuyen_sinh_thac_si": f"{BASE}/ChiTiet.aspx?LoaiTin=v1UjoAIA40d2Nl0tc5EwAA",
    "tuyen_sinh_tien_si": f"{BASE}/ChiTiet.aspx?LoaiTin=ffBwKFG43zUj-wnVkKHUNg",
    "ctdt_thac_si": f"{BASE}/ChiTiet.aspx?LoaiTin=8cr7n9Qk1GpeSBRepQ4wzA",
    "ctdt_tien_si": f"{BASE}/ChiTiet.aspx?LoaiTin=lquZmR-vGhvBxct6vgs8pg",
    "thoi_khoa_bieu": f"{BASE}/ChiTiet.aspx?LoaiTin=Bzgz-ukhgE3hS9Zo42laZQ",
    "quy_dinh": f"{BASE}/ChiTiet.aspx?LoaiTin=e-7LLNqh6SvXeFEhbKvEPg",
    "ke_hoach": f"{BASE}/ChiTiet.aspx?LoaiTin=0I0D1bv2Z33VwD8mL1xV5A",
    "quy_trinh": f"{BASE}/ChiTiet.aspx?LoaiTin=n-Mi4GQ07dn64iP-TVTz7w",
    "thong_bao": f"{BASE}/ChiTiet.aspx?LoaiTin=3nYAXkcB-_h9QVHaXbvg6g",
    "dieu_kien": f"{BASE}/DanhMucDieuKienXTDauVao.aspx",
    "bao_ve_luan_an": f"{BASE}/ChiTiet.aspx?LoaiTin=-K0-KOZzj-5-2_QOddP2YA",
    "bao_ve_luan_van": f"{BASE}/ChiTiet.aspx?LoaiTin=ifdVPsMrJ80B-dRMjA76Ow",
}

NGANH_TS = {
    "TCNH": f"{BASE}/ChiTietNganh.aspx?id=TCNH",
    "QTKD": f"{BASE}/ChiTietNganh.aspx?id=QTKD",
    "KT": f"{BASE}/ChiTietNganh.aspx?id=KT",
    "KTH": f"{BASE}/ChiTietNganh.aspx?id=KTH",
    "QLKT": f"{BASE}/ChiTietNganh.aspx?id=QLKT",
    "LKT": f"{BASE}/ChiTietNganh.aspx?id=LKT",
    "KDQT": f"{BASE}/ChiTietNganh.aspx?id=KDQT",
    "MKT": f"{BASE}/ChiTietNganh.aspx?id=MKT",
    "TKT": f"{BASE}/ChiTietNganh.aspx?id=TKT",
}

NGANH_TIENSI = {
    "TS_QTKD": f"{BASE}/ChiTietNganh.aspx?id=TS_QTKD",
    "TS_TCNH": f"{BASE}/ChiTietNganh.aspx?id=TS_TCNH",
    "TS_QLKT": f"{BASE}/ChiTietNganh.aspx?id=TS_QLKT",
}

INTENT_MAP = {
    "chuong_trinh_thac_si": {
        "keywords": ["thạc sĩ", "master", "thac si", "cao học", "ngành thạc", "chương trình thạc"],
        "urls": [BASE, CATEGORY_PAGES["ctdt_thac_si"]],
        "need_pdf": True,
    },
    "chuong_trinh_tien_si": {
        "keywords": ["tiến sĩ", "phd", "tien si", "doctoral", "nghiên cứu sinh", "ncs"],
        "urls": [BASE, CATEGORY_PAGES["ctdt_tien_si"]],
        "need_pdf": True,
    },
    "hoc_phi": {
        "keywords": ["học phí", "hoc phi", "chi phí", "giá", "bao nhiêu tiền", "học bổng", "ưu đãi", "giảm giá"],
        "urls": [CATEGORY_PAGES["tuyen_sinh_thac_si"], CATEGORY_PAGES["thong_bao"]],
        "need_pdf": True,
    },
    "dieu_kien_dau_vao": {
        "keywords": ["điều kiện", "dieu kien", "đầu vào", "yêu cầu", "tiếng anh", "toeic", "ielts", "chứng chỉ", "bằng cấp"],
        "urls": [CATEGORY_PAGES["tuyen_sinh_thac_si"], CATEGORY_PAGES["dieu_kien"]],
        "need_pdf": True,
    },
    "ho_so_tuyen_sinh": {
        "keywords": ["hồ sơ", "ho so", "đăng ký", "dang ky", "nộp", "thủ tục", "giấy tờ", "cần gì"],
        "urls": [CATEGORY_PAGES["tuyen_sinh_thac_si"], CATEGORY_PAGES["tuyen_sinh_tien_si"]],
        "need_pdf": True,
    },
    "lich_hoc_su_kien": {
        "keywords": ["lịch học", "lich hoc", "khai giảng", "thời khóa biểu", "lịch thi", "sự kiện", "thông báo", "lịch tuyển sinh"],
        "urls": [CATEGORY_PAGES["thong_bao"], CATEGORY_PAGES["thoi_khoa_bieu"], CATEGORY_PAGES["ke_hoach"]],
        "need_pdf": False,
    },
    "luan_van_luan_an": {
        "keywords": ["luận văn", "luận án", "bảo vệ", "bao ve", "quy chế", "quy định"],
        "urls": [CATEGORY_PAGES["quy_dinh"], CATEGORY_PAGES["bao_ve_luan_van"]],
        "need_pdf": True,
    },
    "lam_ho_so_nhap_hoc": {
        "keywords": ["đăng ký nhập học", "nộp hồ sơ", "làm hồ sơ", "muốn đăng ký", "đăng ký học",
                     "nộp giấy tờ", "submit hồ sơ", "enrollment", "nhập học", "đăng ký tuyển sinh"],
        "urls": [CATEGORY_PAGES["tuyen_sinh_thac_si"], CATEGORY_PAGES["tuyen_sinh_tien_si"]],
        "need_pdf": False,
    },
    "thong_tin_truong": {
        "keywords": ["địa chỉ", "liên hệ", "lien he", "điện thoại", "email", "giới thiệu", "về trường"],
        "urls": [BASE],
        "need_pdf": False,
    },
}

NGANH_KW = {
    "tài chính": ["TCNH", "TS_TCNH"], "ngân hàng": ["TCNH", "TS_TCNH"],
    "quản trị kinh doanh": ["QTKD", "TS_QTKD"], "qtkd": ["QTKD", "TS_QTKD"],
    "mba": ["QTKD", "TS_QTKD"], "kế toán": ["KT"], "kinh tế học": ["KTH"],
    "quản lý kinh tế": ["QLKT", "TS_QLKT"], "luật": ["LKT"],
    "kinh doanh quốc tế": ["KDQT"], "marketing": ["MKT"], "toán kinh tế": ["TKT"],
}

# ══════════════════════════════════════════════════
# PROTOTYPES CHO SEMANTIC ROUTING
# ══════════════════════════════════════════════════

CHITCHAT_PROTOTYPES = [
    "chào cô giáo thắm", "chào bạn", "hello", "hi", "tán gẫu", "bạn là ai", 
    "cô là ai", "cô giáo thắm là ai", "hôm nay khoẻ không", "chúc một ngày tốt lành",
    "tên bạn là gì", "cô thắm xinh đẹp", "giúp mình nói chuyện phiếm"
]

OUT_OF_SCOPE_PROTOTYPES = [
    "viết code python", "bệnh tiểu đường triệu chứng", "thời tiết hôm nay", 
    "công thức nấu ăn", "luật giao thông đường bộ", "đăng kiểm xe ô tô", 
    "mua cổ phiếu nào tốt", "lịch sử việt nam", "cách làm bánh", "thuốc trị đau đầu",
    "dịch bài hát tiếng anh", "chơi game gì hay", "hướng dẫn cài windows"
]

# Lưu trữ vector nhúng của prototypes để tránh tính toán lại
_chitchat_vectors = None
_out_of_scope_vectors = None

def _lazy_init_vectors():
    global _chitchat_vectors, _out_of_scope_vectors
    if _chitchat_vectors is None:
        if vector_service.embedder is not None:
            try:
                _chitchat_vectors = vector_service.embedder.encode(CHITCHAT_PROTOTYPES)
                _out_of_scope_vectors = vector_service.embedder.encode(OUT_OF_SCOPE_PROTOTYPES)
                # Normalize for cosine similarity
                _chitchat_vectors = _chitchat_vectors / np.linalg.norm(_chitchat_vectors, axis=1, keepdims=True)
                _out_of_scope_vectors = _out_of_scope_vectors / np.linalg.norm(_out_of_scope_vectors, axis=1, keepdims=True)
                logger.info("[router] Semantic Router prototypes embedded successfully.")
            except Exception as e:
                logger.error(f"[router] Failed to embed prototypes: {e}")
        else:
            logger.warning("[router] Vector service embedder not loaded. Semantic routing fallback to keyword mode.")

def classify_intent_semantic(query: str) -> str:
    """Định tuyến câu hỏi dựa trên độ tương đồng vector Cosine với các prototype."""
    _lazy_init_vectors()
    if _chitchat_vectors is None or vector_service.embedder is None:
        # Fallback dùng keyword regex thô sơ nếu không có vector
        q = query.lower().strip()
        if q in ["hi", "hello", "chào", "chào cô", "chào bạn", "cô thắm", "cô là ai"]:
            return "chitchat"
        if any(w in q for w in ["viết code", "python", "javascript", "nấu ăn", "thuốc trị", "bệnh án", "đóng tàu"]):
            return "out_of_scope"
        return "ufm_legal"

    try:
        q_vec = np.array(vector_service.generate_embedding(query), dtype=np.float32)
        q_vec = q_vec / np.linalg.norm(q_vec)
        
        # Tính cosine similarity với chitchat
        chitchat_sims = np.dot(_chitchat_vectors, q_vec)
        best_chitchat_score = float(np.max(chitchat_sims))
        
        # Tính cosine similarity với out_of_scope
        oos_sims = np.dot(_out_of_scope_vectors, q_vec)
        best_oos_score = float(np.max(oos_sims))
        
        logger.debug(f"[router] Semantic Routing: chitchat_score={best_chitchat_score:.4f}, oos_score={best_oos_score:.4f}")
        
        # Ngưỡng khớp tương đồng ngữ nghĩa
        if best_chitchat_score >= 0.70:
            return "chitchat"
        elif best_oos_score >= 0.70:
            return "out_of_scope"
            
        return "ufm_legal"
    except Exception as e:
        logger.error(f"[router] Semantic routing classification error: {e}")
        return "ufm_legal"

# ══════════════════════════════════════════════════
# MAIN DETECT INTENT
# ══════════════════════════════════════════════════

def detect_intent(query: str) -> dict:
    """Phân tích câu hỏi → intent + URLs + need_pdf + routing_class."""
    msg = query.lower()
    urls = set()
    need_pdf = False
    matched_intents = []

    # 1. Phân loại ngữ nghĩa (Tầng 1 Semantic Router)
    routing_class = classify_intent_semantic(query)
    
    # 2. Xử lý map keyword thông thường cho URLs
    for intent_name, cfg in INTENT_MAP.items():
        if any(kw in msg for kw in cfg["keywords"]):
            matched_intents.append(intent_name)
            for u in cfg["urls"]:
                urls.add(u)
            if cfg["need_pdf"]:
                need_pdf = True

    for kw, ids in NGANH_KW.items():
        if kw in msg:
            for nid in ids:
                if nid in NGANH_TS:
                    urls.add(NGANH_TS[nid])
                if nid in NGANH_TIENSI:
                    urls.add(NGANH_TIENSI[nid])

    if not matched_intents:
        matched_intents = ["general"]
        urls.add(BASE)
        urls.add(CATEGORY_PAGES["ctdt_thac_si"])

    urls.add(BASE)

    intent = matched_intents[0] if len(matched_intents) == 1 else "multi"
    final_urls = list(urls)[:4]
    
    logger.info(f"[router] class={routing_class} intent={intent} urls={len(final_urls)} need_pdf={need_pdf}")
    return {
        "intent": intent,
        "intents": matched_intents,
        "urls": final_urls,
        "need_pdf": need_pdf,
        "routing_class": routing_class
    }
