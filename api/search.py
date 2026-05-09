# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "bulletin": "..." }
returns: { "success": bool, "download_url": str, "filename": str, "error": str }

שינויים עיקריים:
 1. מביא תאריך עברי + פרשת השבוע אוטומטית (Hebcal API – חינמי, ללא key)
 2. ולידציה כפולה: שם בURL + הורדה חלקית לבדיקת magic bytes
 3. PDF נטען לזיכרון הזמני של Vercel ומוגש דרך /api/download?token=...
    → המשתמש לא מופנה לאתר חיצוני בשום שלב
"""
import io, json, os, re, hashlib, time, logging, urllib.parse, tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone

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

# ── זיכרון זמני בין-בקשתי (Vercel keeps the process warm for ~seconds) ──────
# dict: token -> {"data": bytes, "filename": str, "ts": float}
_PDF_CACHE: dict[str, dict] = {}
CACHE_TTL = 300  # 5 דקות

def _evict_old():
    now = time.time()
    for k in list(_PDF_CACHE.keys()):
        if now - _PDF_CACHE[k]["ts"] > CACHE_TTL:
            del _PDF_CACHE[k]

# ── 1. תאריך עברי + פרשת השבוע (Hebcal – חינמי) ─────────────────────────────
def get_hebrew_context() -> dict:
    """
    מחזיר:
      parasha      – שם הפרשה הנוכחית (עברית)
      parasha_en   – שם הפרשה (אנגלית)
      hebrew_date  – תאריך עברי מלא כטקסט
      greg_date    – תאריך לועזי yyyy-mm-dd
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ctx = {"parasha": "", "parasha_en": "", "hebrew_date": "", "greg_date": today}
    try:
        r = requests.get(
            "https://www.hebcal.com/hebcal",
            params={
                "v": "1", "cfg": "json",
                "maj": "on", "min": "off",
                "nx": "off", "year": "now", "month": "x",
                "ss": "off", "mf": "off", "c": "off",
                "geo": "none", "M": "on", "s": "on",
            },
            timeout=8,
        )
        data = r.json()
        for item in data.get("items", []):
            cat = item.get("category", "")
            if cat == "parashat":
                ctx["parasha_en"] = item.get("title_orig") or item.get("title", "")
                ctx["parasha"]    = item.get("hebrew", "") or ctx["parasha_en"]
                ctx["greg_date"]  = item.get("date", today)[:10]
                break
        # תאריך עברי מה-API
        r2 = requests.get(
            "https://www.hebcal.com/converter",
            params={"cfg": "json", "date": today, "g2h": "1"},
            timeout=6,
        )
        d2 = r2.json()
        ctx["hebrew_date"] = d2.get("hebrew", "")
    except Exception as e:
        log.warning("Hebcal error: %s", e)
    log.info("Hebrew context: %s", ctx)
    return ctx

# ── 2. Gemini: בניית שאילתות חיפוש ממוקדות ─────────────────────────────────
def build_queries(api_key: str, bulletin: str, hctx: dict) -> list[str]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.1-flash-lite")

    prompt = f"""אתה עוזר לחיפוש עלוני שבת עדכניים בפורמט PDF.

פרטי החיפוש:
- שם העלון: "{bulletin}"
- פרשת השבוע הנוכחית (לועזית): {hctx['parasha_en']}
- פרשת השבוע הנוכחית (עברית): {hctx['parasha']}
- תאריך עברי: {hctx['hebrew_date']}
- תאריך לועזי: {hctx['greg_date']}

משימתך: הפק בדיוק 7 שאילתות חיפוש Google/Bing שיוביל לקובץ PDF של העלון לשבוע הנוכחי.

כללים חשובים:
- כל שאילתה חייבת לכלול את שם הפרשה (עברית או לועזית) כדי להבטיח עדכניות.
- שלב את שם העלון עם שם הפרשה.
- אל תשכח להוסיף מילים כגון: עלון שבת, PDF, גיליון, {datetime.now().year}.
- הפק שאילתות מגוונות: חלק בעברית וחלק באנגלית.
- כל שאילתה בשורה נפרדת, ללא מספור, ללא נקודות, ללא הסברים.
"""
    resp  = model.generate_content(prompt)
    lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
    log.info("Gemini queries: %s", lines)
    return lines[:7]

# ── 3. מנועי חיפוש (חינמיים, ללא API key) ──────────────────────────────────
def ddg_search(query: str) -> list[str]:
    urls = []
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12,
        )
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "uddg=" in href:
                href = urllib.parse.parse_qs(
                    urllib.parse.urlparse(href).query
                ).get("uddg", [""])[0]
            if href.lower().endswith(".pdf"):
                urls.append(href)
    except Exception as e:
        log.warning("DDG error: %s", e)
    return list(dict.fromkeys(urls))[:5]

def bing_search(query: str) -> list[str]:
    urls = []
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12,
        )
        found = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        urls  = list(dict.fromkeys(found))[:5]
    except Exception as e:
        log.warning("Bing error: %s", e)
    return urls

def direct_site_search(bulletin: str, hctx: dict) -> list[str]:
    """חיפוש ישיר בכמה אתרי עלוני שבת ידועים, עם שם הפרשה."""
    parasha = urllib.parse.quote(hctx["parasha_en"] or hctx["parasha"])
    bl      = urllib.parse.quote(bulletin)
    urls    = []
    sites   = [
        f"https://www.yeshiva.org.il/search?q={bl}+{parasha}&type=pdf",
        f"https://www.toraland.org.il/search?s={bl}+{parasha}",
        f"https://www.kipa.co.il/?s={bl}+{parasha}+pdf",
        f"https://www.mizrachi.org/hamizrachi/?s={parasha}",
    ]
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=10)
            found = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
            urls.extend(found[:3])
        except Exception:
            pass
    return list(dict.fromkeys(urls))[:6]

# ── 4. ולידציה קפדנית ──────────────────────────────────────────────────────
PDF_MAGIC = b"%PDF"

def _url_matches_bulletin(url: str, bulletin: str) -> bool:
    """
    בדיקה ראשונית: האם שם הפרשה / שם העלון מופיעים ב-URL או בשם הקובץ?
    מספיקה התאמה חלקית (fuzzy).
    """
    url_lower = urllib.parse.unquote(url).lower()
    # נרמול: הסר ניקוד, רווחים → _
    words = re.sub(r"[^\w\u0590-\u05ff]", " ", bulletin.lower()).split()
    return any(w in url_lower for w in words if len(w) > 2)

def validate_and_fetch_pdf(url: str, bulletin: str, hctx: dict) -> bytes | None:
    """
    1. HEAD – וודא שהתגובה היא PDF וגודלה סביר (>10KB).
    2. בדיקת שם: URL או Content-Disposition חייב להכיל מילת מפתח.
    3. GET חלקי (512 bytes) – בדוק magic bytes %PDF.
    4. GET מלא – החזר bytes.
    """
    try:
        # HEAD
        head = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
        ct   = head.headers.get("Content-Type", "").lower()
        cl   = int(head.headers.get("Content-Length", 0) or 0)
        if head.status_code != 200:
            return None
        if "pdf" not in ct and not url.lower().endswith(".pdf"):
            return None
        if cl and cl < 10_000:  # פחות מ-10KB – בוודאות לא עלון שלם
            return None

        # בדיקת שם (URL + Content-Disposition)
        cd       = head.headers.get("Content-Disposition", "")
        combined = (url + " " + cd).lower()
        parasha_words = re.sub(
            r"[^\w\u0590-\u05ff]", " ",
            (hctx["parasha_en"] + " " + hctx["parasha"]).lower()
        ).split()
        bulletin_words = re.sub(r"[^\w\u0590-\u05ff]", " ", bulletin.lower()).split()
        all_kw = [w for w in (parasha_words + bulletin_words) if len(w) > 2]
        match_score = sum(1 for w in all_kw if w in urllib.parse.unquote(combined))
        if match_score == 0:
            log.info("Name mismatch, skipping: %s", url)
            return None

        # GET חלקי לבדיקת magic bytes
        partial = requests.get(
            url, headers={**HEADERS, "Range": "bytes=0-511"},
            timeout=10, stream=True,
        )
        first_bytes = b""
        for chunk in partial.iter_content(512):
            first_bytes += chunk
            break
        if not first_bytes.startswith(PDF_MAGIC):
            log.info("Not a real PDF (bad magic): %s", url)
            return None

        # GET מלא
        full = requests.get(url, headers=HEADERS, timeout=25, stream=True)
        buf  = io.BytesIO()
        for chunk in full.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > 20_000_000:  # max 20MB
                log.warning("PDF too large, skipping: %s", url)
                return None
        data = buf.getvalue()
        if len(data) < 10_000:
            return None
        return data

    except Exception as e:
        log.warning("validate_and_fetch failed %s: %s", url, e)
        return None

# ── 5. לוגיקה ראשית ─────────────────────────────────────────────────────────
def find_and_cache_pdf(api_key: str, bulletin: str):
    """
    מחזיר (token, filename) אם נמצא PDF תקין, אחרת (None, None).
    ה-PDF נשמר ב-_PDF_CACHE לפי token.
    """
    _evict_old()
    hctx    = get_hebrew_context()
    queries = build_queries(api_key, bulletin, hctx)

    candidate_urls: list[str] = []
    for q in queries:
        candidate_urls += ddg_search(q)
        candidate_urls += bing_search(q)
    candidate_urls += direct_site_search(bulletin, hctx)

    # ביטול כפילויות
    seen, unique = set(), []
    for u in candidate_urls:
        if u not in seen:
            seen.add(u); unique.append(u)

    log.info("Total candidates: %d", len(unique))

    for url in unique:
        pdf_data = validate_and_fetch_pdf(url, bulletin, hctx)
        if pdf_data:
            # שם קובץ נקי
            raw  = url.split("/")[-1].split("?")[0]
            raw  = urllib.parse.unquote(raw)
            safe = re.sub(r"[^\w\u0590-\u05ff._-]", "_", raw)
            if not safe.lower().endswith(".pdf"):
                safe = f"{bulletin}_{hctx['parasha_en']}.pdf"
            safe = safe[:80]

            token = hashlib.sha256(os.urandom(16)).hexdigest()[:24]
            _PDF_CACHE[token] = {
                "data":     pdf_data,
                "filename": safe,
                "ts":       time.time(),
            }
            log.info("Cached PDF %s (%d bytes), token=%s", safe, len(pdf_data), token)
            return token, safe, hctx

    return None, None, hctx

# ── 6. Vercel handler ────────────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            return self._json(400, {"success": False, "error": "JSON לא תקין"})

        api_key  = (data.get("api_key")  or "").strip()
        bulletin = (data.get("bulletin") or "").strip()

        if not api_key:
            return self._json(400, {"success": False, "error": "נא להזין Gemini API Key"})
        if not bulletin:
            return self._json(400, {"success": False, "error": "נא להזין שם עלון"})

        try:
            token, filename, hctx = find_and_cache_pdf(api_key, bulletin)
        except Exception as e:
            log.exception("find_and_cache_pdf failed")
            return self._json(500, {"success": False, "error": f"שגיאת שרת: {e}"})

        if not token:
            return self._json(404, {
                "success": False,
                "error": (
                    f"לא נמצא עלון '{bulletin}' לפרשת {hctx.get('parasha','השבוע')}. "
                    "נסה שם מדויק יותר."
                ),
            })

        self._json(200, {
            "success":      True,
            "download_url": f"/api/download?token={token}",
            "filename":     filename,
            "parasha":      hctx.get("parasha", ""),
            "hebrew_date":  hctx.get("hebrew_date", ""),
            "message":      f"נמצא עלון לפרשת {hctx.get('parasha','')}!",
        })

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)
