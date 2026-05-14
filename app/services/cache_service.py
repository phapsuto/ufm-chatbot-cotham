"""app/services/cache_service.py — TTL Cache cho HTML và PDF"""
import logging
from cachetools import TTLCache
from app.config import settings

logger = logging.getLogger("ufm-chatbot")

_html_cache: TTLCache = TTLCache(maxsize=settings.CACHE_MAX_SIZE, ttl=settings.CACHE_TTL_HTML)
_pdf_cache: TTLCache = TTLCache(maxsize=settings.CACHE_MAX_SIZE, ttl=settings.CACHE_TTL_PDF)

def get_html(url: str) -> str | None:
    hit = _html_cache.get(url)
    if hit:
        logger.info(f"[cache] HIT html url={url[:60]}")
    return hit

def set_html(url: str, content: str) -> None:
    _html_cache[url] = content
    logger.info(f"[cache] SET html url={url[:60]} chars={len(content)}")

def get_pdf(url: str) -> str | None:
    hit = _pdf_cache.get(url)
    if hit:
        logger.info(f"[cache] HIT pdf url={url[:60]}")
    return hit

def set_pdf(url: str, content: str) -> None:
    _pdf_cache[url] = content

def clear_all() -> None:
    _html_cache.clear()
    _pdf_cache.clear()
    logger.info("[cache] ALL cleared")

def stats() -> dict:
    return {"html_cached": len(_html_cache), "pdf_cached": len(_pdf_cache)}
