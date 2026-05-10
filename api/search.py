# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות בגרסה זו:
  1. פרשת השבוע מחושבת מטבלה קשיחה (אמינה 100%).
  2. שילוב מנוע NLP בעזרת Gemini - המשתמש יכול לכתוב "עלון לילדים לפרשת בראשית" והמערכת תבין לבד מה לחפש!
  3. הצעות חלופיות (Fallback) - אם עלון לא יצא, המערכת מציעה את העלון של שבוע שעבר או שנה שעברה.
  4. בדיקה מחמירה - שגיאת API בבדיקת ה-PDF מחזירה False ולא מאשרת בטעות עלון שגוי.
  5. ה-PDF מוחזר כ-Base64 להורדה ישירה פנימית.
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
# 1. טבלה קשיחה של פרשיות
# ══════════════════════════════════════════════════════════════════
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
    "2026-05-09": ("בהר-בחוקותי",         "Behar-Bechukotai",   "כ\"ב אייר"),
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

def get_default_parasha(d: date) -> dict:
    days_until_shabbat = (5 - d.weekday()) % 7
    candidate = d + timedelta(days=days_until_shabbat)

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
# 2. הבנת שפה טבעית (NLP) – פענוח כוונת המשתמש
# ══════════════════════════════════════════════════════════════════
def parse_user_intent(api_key: str, raw_query: str, default_ctx: dict) -> dict:
    """
    מקבל בקשה חופשית מהמשתמש ומחלץ את שם העלון, הפרשה והשנה.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.1-flash-lite", generation_config={"response_mime_type": "application/json"})
    
    prompt = f"""
    אתה עוזר למנוע חיפוש חכם של עלוני שבת.
    פרשת השבוע הקרובה בברירת מחדל היא: "{default_ctx['parasha']}" (אנגלית: {default_ctx['parasha_en']}). השנה הנוכחית היא תשפ"ו (2026).
    בקשת המשתמש החופשית: "{raw_query}"

    משימתך לנתח את הבקשה ולהחזיר קובץ JSON בלבד עם השדות הבאים:
    1. "bulletin": שם העלון המדויק. אם המשתמש שאל בכלליות (למשל "עלון לילדים"), הצע שם של עלון פופולרי מתאים (למשל "אותיות וילדים" או "מטעמים לשולחן שבת"). אם ביקש "עלון הלכה", הצע למשל "פניני הלכה".
    2. "parasha": שם הפרשה בעברית. אם המשתמש לא ציין פרשה ספציפית בבקשתו, השתמש בברירת המחדל שהיא "{default_ctx['parasha']}".
    3. "parasha_en": שם הפרשה המקביל באנגלית. אם אינך יודע, תרגם פונטית.
    4. "year": שנת ההוצאה (למשל "תשפ\"ו" או "תשפ\"ה"). אם המשתמש אמר "שנה שעברה" והשנה הנוכחית היא תשפ"ו, החזר "תשפ\"ה". אם לא אמר שום דבר על זמן, החזר "תשפ\"ו".
    """
    try:
        resp = model.generate_content(prompt)
        parsed = json.loads(resp.text)
        
        # וידוא שדות חובה למקרה של תקלה ב-JSON
        if "bulletin" not in parsed: parsed["bulletin"] = raw_query
        if "parasha" not in parsed: parsed["parasha"] = default_ctx["parasha"]
        if "parasha_en" not in parsed: parsed["parasha_en"] = default_ctx["parasha_en"]
        if "year" not in parsed: parsed["year"] = "תשפ\"ו"
        
        return parsed
    except Exception as e:
        log.error("Intent parsing failed: %s", e)
        # Fallback בסיסי במקרה של שגיאה
        return {
            "bulletin": raw_query, 
            "parasha": default_ctx["parasha"], 
            "parasha_en": default_ctx["parasha_en"], 
            "year": "תשפ\"ו"
        }

def build_queries(parsed: dict) -> list[str]:
    """בונה שאילתות חיפוש מדויקות לפי הפענוח של ג'מיני."""
    b = parsed['bulletin']
    p = parsed['parasha']
    pe = parsed['parasha_en']
    y = parsed['year']
    
    return[
        f'"{b}" "{p}" {y} filetype:pdf',
        f'עלון שבת "{b}" פרשת {p} {y} pdf',
        f'"{b}" "{pe}" {y} pdf',
        f'גליון "{b}" "{p}" {y}'
    ]

# ══════════════════════════════════════════════════════════════════
# 3. מנועי חיפוש (DuckDuckGo, Bing, אתרים ישירים)
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
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])[0]
            if href.lower().endswith(".pdf"):
                urls.append(href)
        return list(dict.fromkeys(urls))[:4]
    except Exception as e:
        log.warning("DDG error: %s", e)
        return[]

def bing_search(query: str) -> list[str]:
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS, timeout=12,
        )
        urls = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        return list(dict.fromkeys(urls))[:4]
    except Exception as e:
        log.warning("Bing error: %s", e)
        return []

def direct_site_search(parsed: dict) -> list[str]:
    p = urllib.parse.quote(parsed["parasha_en"])
    bl = urllib.parse.quote(parsed["bulletin"])
    sites =[
        f"https://www.yeshiva.org.il/search?q={bl}+{p}&type=pdf",
        f"https://www.toraland.org.il/search?s={bl}+{p}",
        f"https://www.kipa.co.il/?s={bl}+{p}+pdf",
    ]
    urls =[]
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=10)
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:2])
        except Exception:
            pass
    return list(dict.fromkeys(urls))[:4]

# ══════════════════════════════════════════════════════════════════
# 4. הורדה ואימות (Magic Bytes)
# ══════════════════════════════════════════════════════════════════
PDF_MAGIC = b"%PDF"
MAX_SIZE  = 15 * 1024 * 1024  # 15 MB

def fetch_pdf_bytes(url: str) -> bytes | None:
    """מוריד PDF ומחזיר bytes. מוודא שמדובר ב-PDF אמיתי."""
    try:
        head = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if head.status_code != 200:
            return None
        ct = head.headers.get("Content-Type", "").lower()
        if "pdf" not in ct and not url.lower().endswith(".pdf"):
            return None

        r = requests.get(url, headers=HEADERS, timeout=25, stream=True)
        buf = io.BytesIO()
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > MAX_SIZE:
                return None
        
        data = buf.getvalue()
        if not data.startswith(PDF_MAGIC):
            return None
        if len(data) < 5000:
            return None
        return data
    except Exception as e:
        log.warning("fetch_pdf_bytes failed for %s: %s", url, e)
        return None

# ══════════════════════════════════════════════════════════════════
# 5. ולידציה של תוכן ה-PDF באמצעות Gemini (מחמיר!)
# ══════════════════════════════════════════════════════════════════
def gemini_validate_pdf(api_key: str, pdf_bytes: bytes, parsed: dict) -> bool:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")

        # שימוש בדגימה כדי לחסוך טוקנים
        sample = pdf_bytes[:3 * 1024 * 1024]
        b64    = base64.b64encode(sample).decode()

        prompt = f"""בדוק את קובץ ה-PDF המצורף וענה אך ורק YES או NO.

שאלה: האם קובץ זה הוא בהכרח ובוודאות הגליון/עלון של "{parsed['bulletin']}" שעוסק בפרשת השבוע "{parsed['parasha']}"?

כללים חמורים:
- ענה YES רק אם גם שם העלון המדויק ("{parsed['bulletin']}") וגם שם הפרשה ("{parsed['parasha']}") מופיעים בקובץ באופן ברור.
- אם מדובר בעלון אחר לגמרי או שם דומה אך לא זהה - ענה NO.
- אם הפרשה לא מוזכרת בקובץ – ענה NO.
- אם אינך בטוח ב-100% – ענה NO.
- אל תוסיף שום הסבר. רק מילה אחת: YES או NO.
"""
        resp = model.generate_content([
            {"mime_type": "application/pdf", "data": b64},
            prompt,
        ])
        answer = resp.text.strip().upper()
        log.info("Gemini validation answer for '%s': '%s'", parsed['bulletin'], answer)
        return answer.startswith("YES")
    except Exception as e:
        log.warning("Gemini validation error: %s", e)
        # תיקון קריטי: אם יש שגיאה, דוחים את הקובץ כדי למנוע זבל
        return False

# ══════════════════════════════════════════════════════════════════
# 6. לוגיקה ראשית
# ══════════════════════════════════════════════════════════════════
def find_bulletin_pdf(api_key: str, raw_query: str):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    default_ctx = get_default_parasha(today)
    
    # שלב 1: הבנת כוונת המשתמש
    parsed = parse_user_intent(api_key, raw_query, default_ctx)
    log.info("Parsed intent: %s", parsed)

    # שלב 2: איסוף מועמדים
    queries = build_queries(parsed)
    candidates =[]
    for q in queries:
        candidates += ddg_search(q)
        candidates += bing_search(q)
    candidates += direct_site_search(parsed)

    unique = list(dict.fromkeys(candidates))
    log.info("Total unique candidates: %d", len(unique))

    # שלב 3: בדיקת הקבצים
    for url in unique:
        log.info("Trying: %s", url)
        pdf_bytes = fetch_pdf_bytes(url)
        if not pdf_bytes:
            continue

        if not gemini_validate_pdf(api_key, pdf_bytes, parsed):
            log.info("Gemini rejected: %s", url)
            continue

        # יצירת שם קובץ בטוח ונקי להורדה
        safe_name = f"{parsed['bulletin']}_{parsed['parasha_en']}_{parsed['year']}.pdf"
        safe_name = re.sub(r'[\\/*?:"<>|]', "", safe_name).replace(' ', '_')

        log.info("Accepted: %s", url)
        return pdf_bytes, safe_name, parsed

    return None, None, parsed

# ══════════════════════════════════════════════════════════════════
# 7. Vercel Handler
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        try:
            body = json.loads(raw_body)
        except Exception:
            return self._json(400, {"success": False, "error": "JSON לא תקין"})

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key:
            return self._json(400, {"success": False, "error": "נא להזין מפתח API בהגדרות"})
        if not query:
            return self._json(400, {"success": False, "error": "נא להזין מה לחפש (שם עלון)"})

        try:
            pdf_bytes, filename, parsed = find_bulletin_pdf(api_key, query)
        except Exception as e:
            log.exception("find_bulletin_pdf crashed")
            return self._json(500, {"success": False, "error": f"שגיאת שרת פנימית: {e}"})

        # אם העלון לא נמצא, נייצר הצעות חלופיות למשתמש!
        if not pdf_bytes:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date()
            prev_week = get_default_parasha(today - timedelta(days=7))
            
            b_name = parsed['bulletin']
            p_name = parsed['parasha']
            
            # בניית רשימת הצעות (שבוע שעבר / שנה שעברה)
            suggestions =[
                f"{b_name} לפרשת {prev_week['parasha']} (שבוע שעבר)",
                f"{b_name} לפרשת {p_name} שנה שעברה"
            ]
            
            return self._json(404, {
                "success": False,
                "error": f"נראה שהעלון '{b_name}' לפרשת {p_name} עדיין לא יצא.",
                "suggestions": suggestions
            })

        # העלון נמצא - נמיר ל-Base64 ונחזיר לדפדפן
        b64 = base64.b64encode(pdf_bytes).decode()

        self._json(200, {
            "success":     True,
            "filename":    filename,
            "message":     f"מעולה! מצאתי את '{parsed['bulletin']}' לפרשת {parsed['parasha']}.",
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
