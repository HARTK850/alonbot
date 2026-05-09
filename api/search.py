# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "bulletin": "..." }
returns: { "success": bool, "pdf_url": str, "filename": str, "error": str }
"""
import json, re, time, logging, urllib.parse
from http.server import BaseHTTPRequestHandler

import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

# ─── Gemini: build search queries ────────────────────────────
def build_queries(api_key: str, bulletin: str) -> list:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.1-flash-lite")
    prompt = f"""אתה עוזר לחיפוש עלוני שבת בפורמט PDF.
שם העלון שהמשתמש חיפש: "{bulletin}"

הפק בדיוק 6 שאילתות חיפוש (מגוונות, בעברית ובאנגלית) שיוביל לקובץ PDF של העלון.
כל שאילתה בשורה נפרדת בלבד. ללא מספור, ללא נקודות, ללא הסברים.
שלב מילים כגון: אלון שבת, עלון שבת, PDF, parasha, שבועון.
"""
    resp = model.generate_content(prompt)
    lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
    log.info("Gemini produced %d queries", len(lines))
    return lines[:6]

# ─── Search engines (free, no API key) ───────────────────────
def ddg_search(query: str) -> list:
    """DuckDuckGo HTML scraping."""
    urls = []
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12
        )
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a.result__url, a[href]"):
            href = a.get("href", "")
            # DDG wraps URLs
            if "uddg=" in href:
                parsed = urllib.parse.parse_qs(
                    urllib.parse.urlparse(href).query
                )
                href = parsed.get("uddg", [""])[0]
            if href.lower().endswith(".pdf"):
                urls.append(href)
        log.info("DDG: %d pdf links for '%s'", len(urls), query)
    except Exception as e:
        log.warning("DDG error: %s", e)
    return urls[:5]

def bing_search(query: str) -> list:
    """Bing HTML scraping."""
    urls = []
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12
        )
        urls = re.findall(r'href=\\"(https?://[^\\"]+\\.pdf)\\"', r.text)
        if not urls:
            urls = re.findall(r'"(https?://[^"]+\\.pdf)"', r.text)
        urls = list(dict.fromkeys(urls))[:5]
        log.info("Bing: %d pdf links", len(urls))
    except Exception as e:
        log.warning("Bing error: %s", e)
    return urls

def moreshethisrael_search(bulletin: str) -> list:
    """חיפוש ישיר באתרי עלוני שבת ידועים."""
    sites = [
        f"https://www.yeshiva.org.il/search?q={urllib.parse.quote(bulletin)}&type=pdf",
        f"https://www.toraland.org.il/search?s={urllib.parse.quote(bulletin)}",
        f"https://www.kipa.co.il/?s={urllib.parse.quote(bulletin)}+pdf",
    ]
    urls = []
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=10)
            found = re.findall(r'"(https?://[^"]+\\.pdf)"', r.text)
            urls.extend(found[:2])
        except Exception:
            pass
    return list(dict.fromkeys(urls))[:4]

# ─── Validate PDF URL ─────────────────────────────────────────
def validate_pdf_url(url: str) -> bool:
    """HEAD request to confirm URL is a real PDF."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=8,
                          allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        cl = int(r.headers.get("Content-Length", 0))
        return r.status_code == 200 and ("pdf" in ct.lower() or
               url.lower().endswith(".pdf")) and cl > 2000
    except Exception:
        return False

# ─── Main logic ───────────────────────────────────────────────
def find_pdf(api_key: str, bulletin: str):
    queries = build_queries(api_key, bulletin)

    candidate_urls = []
    for q in queries:
        candidate_urls += ddg_search(q)
        candidate_urls += bing_search(q)
    candidate_urls += moreshethisrael_search(bulletin)

    # de-duplicate
    seen = set()
    unique = []
    for u in candidate_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    for url in unique:
        if validate_pdf_url(url):
            # derive a clean filename
            raw = url.split("/")[-1].split("?")[0]
            raw = urllib.parse.unquote(raw)
            safe = re.sub(r"[^\\w\\u0590-\\u05ff._-]", "_", raw)
            if not safe.lower().endswith(".pdf"):
                safe += ".pdf"
            return url, safe[:80]

    return None, None

# ─── Vercel handler ───────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def _cors(self):
        """מגדיר כותרות שמאפשרות לכל אתר (כולל GitHub) לגשת לשרת הזה"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """טיפול בבקשת 'בדיקה' שהדפדפן שולח לפני ה-POST"""
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._json(400, {"success": False, "error": "JSON לא תקין"})
            return

        api_key  = (data.get("api_key") or "").strip()
        bulletin = (data.get("bulletin") or "").strip()

        if not api_key:
            self._json(400, {"success": False, "error": "נא להזין Gemini API Key"})
            return
        if not bulletin:
            self._json(400, {"success": False, "error": "נא להזין שם עלון"})
            return

        try:
            pdf_url, filename = find_pdf(api_key, bulletin)
        except Exception as e:
            log.exception("find_pdf failed")
            self._json(500, {"success": False, "error": f"שגיאת שרת: {e}"})
            return

        if not pdf_url:
            self._json(404, {
                "success": False,
                "error": "לא נמצא קובץ PDF עבור העלון המבוקש. נסה שם אחר."
            })
            return

        self._json(200, {
            "success":  True,
            "pdf_url":  pdf_url,
            "filename": filename,
            "message":  "העלון נמצא בהצלחה!"
        })

    def _json(self, code, obj):
        """שליחת תשובה בפורמט JSON עם כותרות CORS"""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors() # שורה קריטית - מוסיפה את אישור הגישה לתשובה
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)
