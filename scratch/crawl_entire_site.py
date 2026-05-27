import os
import re
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# Tắt cảnh báo SSL không an toàn vì một số trang web của trường có thể cấu hình SSL cũ
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

START_URL = "https://daotaosdh.ufm.edu.vn/"
ALLOWED_DOMAIN = "daotaosdh.ufm.edu.vn"

# Lưu trực tiếp vào thư mục tri thức offline của ứng dụng
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.dirname(CURRENT_DIR), "app", "knowledge_base")

# Giới hạn an toàn để tránh quá tải máy chủ trường hoặc lặp vô tận
MAX_PAGES = 250
DELAY_SECONDS = 0.5  # Nghỉ 0.5s giữa các yêu cầu để tránh bị chặn IP

visited = set()
queue = [START_URL]
saved_count = 0

def clean_filename(url):
    """Chuyển đổi URL thành tên file .md an toàn, dễ đọc"""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    query = parsed.query
    
    if not path and not query:
        return "web_homepage.md"
        
    name = path.replace("/", "_").replace(".aspx", "").replace(".html", "").replace(".php", "")
    if query:
        # Làm sạch query string
        q_clean = query.replace("=", "_").replace("&", "_").replace("?", "_")
        name += "_" + q_clean
        
    # Loại bỏ ký tự đặc biệt
    name = re.sub(r'[^\w\-_]', '', name)
    return f"web_{name[:80]}.md"

def clean_html_to_markdown(html, url):
    """Phân tích HTML, lọc nhiễu, chiết xuất links con và trả về Markdown sạch"""
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Phát hiện link PDF tuyển sinh đính kèm
    pdf_urls = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.lower().endswith('.pdf') or 'filetype=pdf' in href.lower():
            full_url = urljoin(url, href)
            if full_url not in pdf_urls:
                pdf_urls.append(full_url)
                
    # 2. Loại bỏ các thẻ nhiễu không chứa nội dung đọc
    for tag in soup(["script", "style", "nav", "iframe", "footer", "noscript", "header", "aside"]):
        tag.decompose()
        
    # 3. Định vị khu vực nội dung chính
    main = (
        soup.find("main") 
        or soup.find("article") 
        or soup.find(class_="content") 
        or soup.find(id="content") 
        or soup.find(id="main-content")
        or soup.find("body")
    )
    if not main:
        return None, []
        
    # 4. Tìm các liên kết nội bộ UFM để bò tiếp
    next_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urljoin(url, href).split("#")[0] # Bỏ fragment neo trang (#...)
        parsed_full = urlparse(full_url)
        
        # Chỉ đi tiếp nếu cùng domain chính thức và không phải file tĩnh
        if parsed_full.netloc == ALLOWED_DOMAIN:
            # Bỏ qua các file tĩnh không phải HTML
            if not any(full_url.lower().endswith(ext) for ext in [
                '.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.pdf', 
                '.docx', '.xlsx', '.zip', '.rar', '.mp3', '.mp4'
            ]):
                next_links.append(full_url)
                
    # 5. Làm sạch chữ viết chính
    text = main.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
    clean_text = "\n".join(lines)
    
    title = soup.title.string if soup.title else "Website Sau đại học UFM"
    title_clean = title.replace("\r", "").replace("\n", "").strip()
    
    # 6. Đóng gói dạng Markdown
    md_content = f"# {title_clean}\n\n"
    md_content += f"**Nguồn URL:** {url}\n"
    md_content += f"**Thời gian cào:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    md_content += f"---\n\n{clean_text}\n"
    
    if pdf_urls:
        md_content += "\n\n### 📄 Tài liệu PDF đính kèm phát hiện trên trang:\n"
        md_content += "\n".join(f"- [{u.split('/')[-1]}]({u})" for u in pdf_urls)
        
    return md_content, next_links

# Khởi tạo thư mục
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("=" * 60)
print(f"🚀 KHỞI ĐỘNG HỆ THỐNG BÒ MẠNG ĐỆ QUY SAU ĐẠI HỌC UFM")
print(f"📍 Trang bắt đầu: {START_URL}")
print(f"📂 Thư mục lưu tri thức: {OUTPUT_DIR}")
print(f"⚙️ Giới hạn: {MAX_PAGES} trang, trễ an toàn {DELAY_SECONDS}s/trang")
print("=" * 60)

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"
}

try:
    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)
        
        # Bỏ qua nếu đã đi qua
        if url in visited:
            continue
            
        visited.add(url)
        print(f"🔗 [{len(visited)}/{MAX_PAGES}] Đang cào: {url}")
        
        try:
            resp = requests.get(url, headers=headers, timeout=10, verify=False)
            
            # Chỉ cào trang HTML
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                continue
                
            md_content, next_links = clean_html_to_markdown(resp.text, url)
            
            # Lưu file nếu trang có chữ nghĩa
            if md_content and len(md_content.strip()) > 150:
                filename = clean_filename(url)
                file_path = os.path.join(OUTPUT_DIR, filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                saved_count += 1
                
            # Đưa các đường link con vào hàng đợi
            for link in next_links:
                if link not in visited and link not in queue:
                    queue.append(link)
                    
            # Trễ an toàn để tránh block IP
            time.sleep(DELAY_SECONDS)
            
        except Exception as e:
            print(f"❌ Lỗi khi cào URL {url}: {e}")
            
except KeyboardInterrupt:
    print("\n🛑 Tiến trình bị dừng bởi người dùng.")

print("=" * 60)
print(f"🎉 HOÀN THÀNH TIẾN TRÌNH CÀO SẠCH DỮ LIỆU WEBSITE!")
print(f"✅ Tổng số trang web đã duyệt: {len(visited)}")
print(f"💾 Tổng số file tri thức offline đã tạo: {saved_count} file .md")
print("=" * 60)
