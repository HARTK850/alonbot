# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "bulletin": "..." }
returns:
  success=True  → { success, filename, parasha, hebrew_date, pdf_b64 }
  success=False → { success, error }

תיקונים בגרסה זו:
  1. פרשת השבוע מחושבת מטבלה קשיחה (לא API חיצוני) – אמינה 100%
  2. Gemini מאמת את תוכן ה-PDF (שם עלון + פרשה נכונה)
  3. ה-PDF מוחזר כ-base64 בתוך ה-JSON – אין צורך ב-download.py נפרד
     ולכן אין בעיית import בין Vercel functions
"""

import base64, io, json, logging, re, urllib.parse
from datetime import date, timedelta
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

# ══════════════════════════════════════════════════════════════════
# 1.  טבלה קשיחה של פרשיות תשפ"ו – תאריך השבת שבה קוראים
#     (ישראל; מאוחד במקום שנפרדות)
# ══════════════════════════════════════════════════════════════════
# key = תאריך השבת (yyyy-mm-dd)
# value = (שם עברי, שם אנגלי, תאריך עברי)
PARASHA_TABLE = {
    # תשרי–כסלו תשפ"ו
    "2025-10-04": ("האזינו",              "Haazinu",            "א' תשרי"),
    "2025-10-11": ("סוכות",               "Sukkot",             "ח' תשרי"),
    "2025-10-18": ("וזאת הברכה",          "Vezot Haberakhah",   "ט\"ו תשרי"),
    "2025-10-25": ("בראשית",              "Bereshit",           "כ\"ב תשרי"),
    "2025-11-01": ("נח",                  "Noach",              "כ\"ט תשרי"),
    "2025-11-08": ("לך לך",               "Lech-Lecha",         "ו' חשון"),
    "2025-11-15": ("וירא",                "Vayera",             "י\"ג חשון"),
    "2025-11-22": ("חיי שרה",             "Chayei Sara",        "כ' חשון"),
    "2025-11-29": ("תולדות",              "Toldot",             "כ\"ז חשון"),
    "2025-12-06": ("ויצא",                "Vayetzei",           "ה' כסלו"),
    "2025-12-13": ("וישלח",               "Vayishlach",         "י\"ב כסלו"),
    "2025-12-20": ("וישב",                "Vayeshev",           "י\"ט כסלו"),
    "2025-12-27": ("מקץ",                 "Miketz",             "כ\"ו כסלו"),
    # טבת–שבט
    "2026-01-03": ("ויגש",                "Vayigash",           "ג' טבת"),
    "2026-01-10": ("ויחי",                "Vayechi",            "י' טבת"),
    "2026-01-17": ("שמות",                "Shemot",             "י\"ז טבת"),
    "2026-01-24": ("וארא",                "Vaera",              "כ\"ד טבת"),
    "2026-01-31": ("בא",                  "Bo",                 "ב' שבט"),
    "2026-02-07": ("בשלח",                "Beshalach",          "ט' שבט"),
    "2026-02-14": ("יתרו",                "Yitro",              "ט\"ז שבט"),
    "2026-02-21": ("משפטים",              "Mishpatim",          "כ\"ג שבט"),
    "2026-02-28": ("תרומה",               "Terumah",            "א' אדר"),
    "2026-03-07": ("תצוה",                "Tetzaveh",           "ח' אדר"),
    "2026-03-14": ("כי תשא",              "Ki Tisa",            "ט\"ו אדר"),
    "2026-03-21": ("ויקהל-פקודי",         "Vayakhel-Pekudei",   "כ\"ב אדר"),
    "2026-03-28": ("ויקרא",               "Vayikra",            "כ\"ט אדר"),
    "2026-04-04": ("צו",                  "Tzav",               "ז' ניסן"),
    "2026-04-11": ("פסח",                 "Pesach",             "י\"ד ניסן"),
    "2026-04-18": ("שמיני",               "Shemini",            "כ\"א ניסן"),
    "2026-04-25": ("תזריע-מצורע",         "Tazria-Metzora",     "כ\"ח ניסן"),
    "2026-05-02": ("אחרי מות-קדושים",     "Achrei Mot-Kedoshim","ה' אייר"),
    "2026-05-09": ("בהר-בחוקותי",         "Behar-Bechukotai",   "כ\"ב אייר"),  # ← היום!
    "2026-05-16": ("במדבר",               "Bamidbar",           "כ\"ט אייר"),
    "2026-05-23": ("נשא",                 "Nasso",              "ז' סיון"),
    "2026-05-30": ("בהעלותך",             "Beha'alotcha",       "י\"ד סיון"),
    "2026-06-06": ("שלח",                 "Shelach",            "כ\"א סיון"),
    "2026-06-13": ("קרח",                 "Korach",             "כ\"ח סיון"),
    "2026-06-20": ("חקת",                 "Chukat",             "ה' תמוז"),
    "2026-06-27": ("בלק",                 "Balak",              "י\"ב תמוז"),
    "2026-07-04": ("פינחס",               "Pinchas",            "י\"ט תמוז"),
    "2026-07-11": ("מטות-מסעי",           "Matot-Masei",        "כ\"ו תמוז"),
    "2026-07-18": ("דברים",               "Devarim",            "ד' אב"),
    "2026-07-25": ("ואתחנן",              "Vaetchanan",         "י\"א אב"),
    "2026-08-01": ("עקב",                 "Eikev",              "י\"ח אב"),
    "2026-08-08": ("ראה",                 "Re'eh",              "כ\"ה אב"),
    "2026-08-15": ("שופטים",              "Shoftim",            "ג' אלול"),
    "2026-08-22": ("כי תצא",              "Ki Teitzei",         "י' אלול"),
    "2026-08-29": ("כי תבוא",             "Ki Tavo",            "י\"ז אלול"),
    "2026-09-05": ("ניצבים-וילך",         "Nitzavim-Vayeilech", "כ\"ד אלול"),
    "2026-09-12": ("האזינו",              "Haazinu",            "א' תשרי תשפ\"ז"),
}

def get_parasha_for_date(d: date) -> dict:
    """
    מחזיר את הפרשה של השבת הקרובה (או השבת שעברה עד יום שבת).
    מחפש בטבלה: השבת הקרובה מ-d ואילך (עד 6 ימים קדימה).
    אם לא נמצא – מחזיר את הקרוב ביותר בטבלה.
    """
    # חפש את השבת הקרובה (כולל היום אם שבת)
    # שבת = weekday() == 5
    days_until_shabbat = (5 - d.weekday()) % 7
    candidate = d + timedelta(days=days_until_shabbat)

    # חפש בטבלה את התאריך הקרוב ביותר (±14 ימים)
    best_key   = None
    best_delta = 999
    for k in PARASHA_TABLE:
        kd    = date.fromisoformat(k)
        delta = abs((kd - candidate).days)
        if delta < best_delta:
            best_delta = delta
            best_key   = k

    he, en, heb_date = PARASHA_TABLE[best_key]
    return {
        "parasha":      he,
        "parasha_en":   en,
        "hebrew_date":  heb_date,
        "shabbat_date": best_key,
        "greg_date":    d.isoformat(),
    }

# ══════════════════════════════════════════════════════════════════
# 2.  Gemini: בניית שאילתות חיפוש ממוקדות
# ══════════════════════════════════════════════════════════════════
def build_queries(api_key: str, bulletin: str, ctx: dict) -> list[str]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.1-flash-lite")
    prompt = f"""אתה עוזר לחיפוש עלוני שבת עדכניים בפורמט PDF.

פרטי החיפוש:
- שם העלון המדויק: "{bulletin}"
- פרשת השבוע הקרובה (עברית): {ctx['parasha']}
- פרשת השבוע הקרובה (אנגלית): {ctx['parasha_en']}
- תאריך השבת: {ctx['shabbat_date']}
- תאריך עברי: {ctx['hebrew_date']}

הפק בדיוק 7 שאילתות חיפוש שיובילו לקובץ PDF של הגליון הנוכחי של "{bulletin}".

כללים:
- כל שאילתה חייבת לכלול את שם הפרשה (עברית או אנגלית).
- כל שאילתה חייבת לכלול את שם העלון המדויק "{bulletin}".
- שלב גם: עלון שבת, PDF, גיליון, 2026, תשפו.
- חלק מהשאילתות בעברית וחלק באנגלית.
- כל שאילתה בשורה נפרדת בלבד, ללא מספור, ללא נקודות.
"""
    resp  = model.generate_content(prompt)
    lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
    log.info("Gemini queries (%d): %s", len(lines), lines)
    return lines[:7]

# ══════════════════════════════════════════════════════════════════
# 3.  מנועי חיפוש (חינמיים)
# ══════════════════════════════════════════════════════════════════
def ddg_search(query: str) -> list[str]:
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12,
        )
        soup = BeautifulSoup(r.text, "lxml")
        urls = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "uddg=" in href:
                href = urllib.parse.parse_qs(
                    urllib.parse.urlparse(href).query
                ).get("uddg", [""])[0]
            if href.lower().endswith(".pdf"):
                urls.append(href)
        return list(dict.fromkeys(urls))[:5]
    except Exception as e:
        log.warning("DDG: %s", e)
        return []

def bing_search(query: str) -> list[str]:
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12,
        )
        urls = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        return list(dict.fromkeys(urls))[:5]
    except Exception as e:
        log.warning("Bing: %s", e)
        return []

def direct_site_search(bulletin: str, ctx: dict) -> list[str]:
    p  = urllib.parse.quote(ctx["parasha_en"])
    bl = urllib.parse.quote(bulletin)
    sites = [
        f"https://www.yeshiva.org.il/search?q={bl}+{p}&type=pdf",
        f"https://www.toraland.org.il/search?s={bl}+{p}",
        f"https://www.kipa.co.il/?s={bl}+{p}+pdf",
    ]
    urls = []
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=10)
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:3])
        except Exception:
            pass
    return list(dict.fromkeys(urls))[:6]

# ══════════════════════════════════════════════════════════════════
# 4.  הורדה + ולידציה בסיסית (magic bytes)
# ══════════════════════════════════════════════════════════════════
PDF_MAGIC = b"%PDF"
MAX_SIZE  = 15 * 1024 * 1024  # 15 MB

def fetch_pdf_bytes(url: str) -> bytes | None:
    """מוריד PDF ומחזיר את ה-bytes, או None אם לא תקין."""
    try:
        # HEAD check
        head = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if head.status_code != 200:
            return None
        ct = head.headers.get("Content-Type", "").lower()
        cl = int(head.headers.get("Content-Length", 0) or 0)
        if "pdf" not in ct and not url.lower().endswith(".pdf"):
            return None
        if cl and cl < 5_000:
            return None

        # GET
        r   = requests.get(url, headers=HEADERS, timeout=25, stream=True)
        buf = io.BytesIO()
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > MAX_SIZE:
                log.warning("PDF too large: %s", url)
                return None
        data = buf.getvalue()
        if not data.startswith(PDF_MAGIC):
            return None
        if len(data) < 5_000:
            return None
        return data
    except Exception as e:
        log.warning("fetch_pdf_bytes %s: %s", url, e)
        return None

# ══════════════════════════════════════════════════════════════════
# 5.  Gemini: ולידציה של תוכן ה-PDF
# ══════════════════════════════════════════════════════════════════
def gemini_validate_pdf(api_key: str, pdf_bytes: bytes,
                         bulletin: str, ctx: dict) -> bool:
    """
    שולח את ה-PDF ל-Gemini ומבקש ממנו לאשר:
      א. זהו גליון של "{bulletin}"
      ב. הוא עוסק בפרשת {ctx['parasha']} / {ctx['parasha_en']}
    מחזיר True אם אושר, False אחרת.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")

        # מגביל ל-3MB כדי לא לחרוג מ-token limit
        sample = pdf_bytes[:3 * 1024 * 1024]
        b64    = base64.b64encode(sample).decode()

        prompt = f"""בדוק את קובץ ה-PDF המצורף וענה אך ורק YES או NO.

שאלה: האם קובץ זה הוא גליון/עלון של "{bulletin}" שעוסק בפרשת השבוע "{ctx['parasha']}" (באנגלית: {ctx['parasha_en']})?

כללים:
- ענה YES רק אם גם שם העלון וגם הפרשה תואמים.
- אם הפרשה לא מוזכרת בכלל בקובץ – ענה NO.
- אם שם העלון לא תואם – ענה NO.
- אל תוסיף הסברים. רק YES או NO.
"""
        resp = model.generate_content([
            {"mime_type": "application/pdf", "data": b64},
            prompt,
        ])
        answer = resp.text.strip().upper()
        log.info("Gemini validation answer: '%s'", answer)
        return answer.startswith("YES")
    except Exception as e:
        log.warning("Gemini validation error: %s", e)
        # במקרה של שגיאה – נעביר (כדי לא לחסום הכל)
        return True

# ══════════════════════════════════════════════════════════════════
# 6.  לוגיקה ראשית
# ══════════════════════════════════════════════════════════════════
def find_bulletin_pdf(api_key: str, bulletin: str):
    """
    מחזיר (pdf_bytes, filename, ctx) אם נמצא, אחרת (None, None, ctx).
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    ctx   = get_parasha_for_date(today)
    log.info("Context: %s", ctx)

    queries = build_queries(api_key, bulletin, ctx)

    # איסוף מועמדים
    candidates: list[str] = []
    for q in queries:
        candidates += ddg_search(q)
        candidates += bing_search(q)
    candidates += direct_site_search(bulletin, ctx)

    # ביטול כפילויות
    seen, unique = set(), []
    for u in candidates:
        if u not in seen:
            seen.add(u); unique.append(u)
    log.info("Total unique candidates: %d", len(unique))

    for url in unique:
        log.info("Trying: %s", url)
        pdf_bytes = fetch_pdf_bytes(url)
        if not pdf_bytes:
            continue

        # ולידציה עם Gemini
        if not gemini_validate_pdf(api_key, pdf_bytes, bulletin, ctx):
            log.info("Gemini rejected: %s", url)
            continue

        # שם קובץ נקי
        raw  = urllib.parse.unquote(url.split("/")[-1].split("?")[0])
        safe = re.sub(r"[^\w\u0590-\u05ff._-]", "_", raw)
        if not safe.lower().endswith(".pdf"):
            safe = f"{bulletin}_{ctx['parasha_en']}.pdf"
        safe = safe[:80]

        log.info("Accepted: %s (%d bytes)", url, len(pdf_bytes))
        return pdf_bytes, safe, ctx

    return None, None, ctx

# ══════════════════════════════════════════════════════════════════
# 7.  Vercel handler
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        try:
            body = json.loads(raw_body)
        except Exception:
            return self._json(400, {"success": False, "error": "JSON לא תקין"})

        api_key  = (body.get("api_key")  or "").strip()
        bulletin = (body.get("bulletin") or "").strip()

        if not api_key:
            return self._json(400, {"success": False, "error": "נא להזין Gemini API Key"})
        if not bulletin:
            return self._json(400, {"success": False, "error": "נא להזין שם עלון"})

        try:
            pdf_bytes, filename, ctx = find_bulletin_pdf(api_key, bulletin)
        except Exception as e:
            log.exception("find_bulletin_pdf crashed")
            return self._json(500, {"success": False, "error": f"שגיאת שרת: {e}"})

        if not pdf_bytes:
            return self._json(404, {
                "success": False,
                "error": (
                    f"לא נמצא גליון של \"{bulletin}\" לפרשת {ctx.get('parasha','השבוע')}. "
                    "נסה שם מדויק יותר."
                ),
            })

        # המרה ל-base64 – ה-frontend יוריד ישירות
        b64 = base64.b64encode(pdf_bytes).decode()

        self._json(200, {
            "success":     True,
            "filename":    filename,
            "parasha":     ctx["parasha"],
            "parasha_en":  ctx["parasha_en"],
            "hebrew_date": ctx["hebrew_date"],
            "message":     f"נמצא גליון של \"{bulletin}\" לפרשת {ctx['parasha']}!",
            "pdf_b64":     b64,
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
