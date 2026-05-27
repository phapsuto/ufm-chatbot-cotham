"""app/services/crawler_service.py — FAST: httpx+BS4 chính, Crawl4AI fallback"""
import asyncio
import logging
import warnings
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services import cache_service

warnings.filterwarnings("ignore")
logger = logging.getLogger("ufm-chatbot")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

# Shared async client — connection pooling, reuse TCP connections
_http_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0),
            verify=False,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers=HEADERS,
        )
    return _http_client


def is_allowed_domain(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return host.endswith(settings.ALLOWED_DOMAIN)


async def _fast_bs4(url: str) -> Optional[str]:
    """Layer chính: async httpx + BS4 — nhanh 5-10x so với Crawl4AI."""
    try:
        client = await _get_client()
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        html = resp.text
        soup = BeautifulSoup(html, "lxml")
        
        # Extract PDF links BEFORE decomposing tags
        pdf_urls = []
        from urllib.parse import urljoin
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.lower().endswith('.pdf') or 'filetype=pdf' in href.lower():
                full_url = urljoin(url, href)
                if full_url not in pdf_urls:
                    pdf_urls.append(full_url)
                    
        for tag in soup(["script", "style", "nav", "iframe", "footer", "noscript"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.find(class_="content") or soup.find("body")
        if not main:
            return None
        text = main.get_text(separator="\n", strip=True)
        
        # Append found PDF URLs so the regex in pdf_service can pick them up
        if pdf_urls:
            text += "\n\n[PDF LINKS]:\n" + "\n".join(pdf_urls)
            
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
        clean = "\n".join(lines)[:8000]
        if clean and len(clean) > 50:
            logger.info(f"[fast] bs4 url={url.split('?')[0][-30:]} chars={len(clean)} pdfs={len(pdf_urls)}")
            return clean
        return None
    except httpx.TimeoutException:
        logger.warning(f"[fast] TIMEOUT url={url[:50]}")
        return None
    except Exception as e:
        logger.error(f"[fast] ERROR url={url[:50]}: {e}")
        return None


async def _crawl4ai_fallback(url: str) -> Optional[str]:
    """Fallback: Crawl4AI chỉ khi BS4 thất bại (JS-rendered pages)."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            word_count_threshold=10,
            remove_overlay_elements=True,
            exclude_external_links=True,
        )
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=run_cfg), timeout=12
            )
            if result and result.success and result.markdown:
                md = result.markdown[:8000]
                logger.info(f"[crawl4ai] fallback ok url={url[:50]} chars={len(md)}")
                return md
        return None
    except Exception as e:
        logger.warning(f"[crawl4ai] fallback failed: {e}")
        return None


async def crawl(url: str) -> str:
    """Crawl 1 URL: cache → fast BS4 → Crawl4AI fallback."""
    if not is_allowed_domain(url):
        return ""
    # Cache hit = instant
    cached = cache_service.get_html(url)
    if cached:
        return cached
    # Fast path first
    content = await _fast_bs4(url)
    # Crawl4AI only if BS4 totally fails
    if not content:
        content = await _crawl4ai_fallback(url)
    if content:
        cache_service.set_html(url, content)
        return content
    return ""


async def crawl_multiple(urls: list[str], max_urls: int = 4) -> dict[str, str]:
    """Crawl nhiều URL concurrent, giới hạn max_urls."""
    urls = urls[:max_urls]
    results = {}
    gathered = await asyncio.gather(*[crawl(u) for u in urls], return_exceptions=True)
    for url, result in zip(urls, gathered):
        if isinstance(result, str) and result:
            results[url] = result
    return results


def web_search_ddg(query: str) -> str:
    """Tra cứu thông tin tự do trên Internet qua DuckDuckGo HTML API (Miễn phí 100% & Không cần API Key)"""
    try:
        import requests
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        # Gửi yêu cầu tìm kiếm dạng POST lên DuckDuckGo
        resp = requests.post(url, data={"q": query}, headers=headers, timeout=8, verify=False)
        if resp.status_code != 200:
            logger.warning(f"[web-search] DuckDuckGo search returned status {resp.status_code}")
            return ""
            
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        
        # Duyệt qua tối đa 4 kết quả tìm kiếm đầu tiên
        snippets = soup.find_all("a", class_="result__snippet")[:4]
        for a in snippets:
            text = a.get_text(strip=True)
            parent = a.find_parent("div", class_="result__body")
            title_tag = parent.find("a", class_="result__url") if parent else None
            title = title_tag.get_text(strip=True) if title_tag else "Kết quả tìm kiếm Internet"
            href = title_tag["href"] if title_tag and "href" in title_tag.attrs else "#"
            
            # Giải mã link chuyển hướng của DuckDuckGo nếu có
            if href.startswith("//duckduckgo.com/l/?uddg="):
                from urllib.parse import unquote
                href = unquote(href.split("uddg=")[1].split("&")[0])
                
            results.append(f"📖 TIÊU ĐỀ: {title}\n🔗 NGUỒN: {href}\n📝 NỘI DUNG TÓM TẮT: {text}")
            
        if results:
            clean_search = "\n\n---\n\n".join(results)
            logger.info(f"[web-search] DuckDuckGo search successful for '{query[:30]}' results={len(results)}")
            return clean_search
        return ""
    except Exception as e:
        logger.error(f"[web-search] DuckDuckGo search error: {e}")
        return ""

