# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות המערכת בגרסה זו:
1. NLP עמוק: המערכת מנתחת את שפת המשתמש באמצעות Gemini ומבינה לבד מהו שם העלון, איזו פרשה ואיזו שנה.
2. אימות שנה אכזרי: ג'מיני סורק את ה-PDF. אם המשתמש רוצה "תשפ"ו" וכתוב "תשפ"ה" - הוא פוסל מיד!
3. Fallback מקביל ואקטיבי: אם העלון של השבוע לא נמצא, המערכת מחפשת ברקע (בו זמנית) את שבוע שעבר ואת שנה שעברה, ומגישה למשתמש קבצים שמוכנים להורדה באותו רגע!
4. קוד מלא, מרווח, מפורט וקריא לחלוטין.
"""

import base64
import io
import json
import logging
import re
import urllib.parse
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
import concurrent.futures

import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# הגדרות לוגים
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# הגדרת דפדפן מדמה למנועי החיפוש
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

# ══════════════════════════════════════════════════════════════════
# 1. טבלה קשיחה של פרשיות – שורה לכל פרשה לשמירה על סדר וקריאות
# ══════════════════════════════════════════════════════════════════
PARASHA_TABLE =[
    ("2025-10-25", "בראשית", "Bereshit"),
    ("2025-11-01", "נח", "Noach"),
    ("2025-11-08", "לך לך", "Lech-Lecha"),
    ("2025-11-15", "וירא", "Vayera"),
    ("2025-11-22", "חיי שרה", "Chayei Sara"),
    ("2025-11-29", "תולדות", "Toldot"),
    ("2025-12-06", "ויצא", "Vayetzei"),
    ("2025-12-13", "וישלח", "Vayishlach"),
    ("2025-12-20", "וישב", "Vayeshev"),
    ("2025-12-27", "מקץ", "Miketz"),
    ("2026-01-03", "ויגש", "Vayigash"),
    ("2026-01-10", "ויחי", "Vayechi"),
    ("2026-01-17", "שמות", "Shemot"),
    ("2026-01-24", "וארא", "Vaera"),
    ("2026-01-31", "בא", "Bo"),
    ("2026-02-07", "בשלח", "Beshalach"),
    ("2026-02-14", "יתרו", "Yitro"),
    ("2026-02-21", "משפטים", "Mishpatim"),
    ("2026-02-28", "תרומה", "Terumah"),
    ("2026-03-07", "תצוה", "Tetzaveh"),
    ("2026-03-14", "כי תשא", "Ki Tisa"),
    ("2026-03-21", "ויקהל-פקודי", "Vayakhel-Pekudei"),
    ("2026-03-28", "ויקרא", "Vayikra"),
    ("2026-04-04", "צו", "Tzav"),
    ("2026-04-11", "פסח", "Pesach"),
    ("2026-04-18", "שמיני", "Shemini"),
    ("2026-04-25", "תזריע-מצורע", "Tazria-Metzora"),
    ("2026-05-02", "אחרי מות-קדושים", "Achrei Mot-Kedoshim"),
    ("2026-05-09", "בהר-בחוקותי", "Behar-Bechukotai"),
    ("2026-05-16", "במדבר", "Bamidbar"),
    ("2026-05-23", "נשא", "Nasso"),
    ("2026-05-30", "בהעלותך", "Beha'alotcha"),
    ("2026-06-06", "שלח", "Shelach"),
    ("2026-06-13", "קרח", "Korach"),
    ("2026-06-20", "חקת", "Chukat"),
    ("2026-06-27", "בלק", "Balak"),
    ("2026-07-04", "פינחס", "Pinchas"),
    ("2026-07-11", "מטות-מסעי", "Matot-Masei"),
    ("2026-07-18", "דברים", "Devarim"),
    ("2026-07-25", "ואתחנן", "Vaetchanan"),
    ("2026-08-01", "עקב", "Eikev"),
    ("2026-08-08", "ראה", "Re'eh"),
    ("2026-08-15", "שופטים", "Shoftim"),
    ("2026-08-22", "כי תצא", "Ki Teitzei"),
    ("2026-08-29", "כי תבוא", "Ki Tavo"),
    ("2026-09-05", "ניצבים-וילך", "Nitzavim-Vayeilech")
]

def get_context_dates(d: date) -> dict:
    """
    פונקציה זו מחשבת מהי הפרשה של השבוע הנוכחי, ומהי הפרשה של שבוע שעבר.
    זה משמש כדי להבין למה המשתמש מתכוון אם הוא כותב "משבוע שעבר".
    """
    days_until_shabbat = (5 - d.weekday()) % 7
    current_shabbat = d + timedelta(days=days_until_shabbat)
    
    idx = 0
    best_delta = 999
    
    for i, (k, _, _) in enumerate(PARASHA_TABLE):
        kd = date.fromisoformat(k)
        delta = abs((kd - current_shabbat).days)
        if delta < best_delta:
            best_delta = delta
            idx = i

    curr = PARASHA_TABLE[idx]
    prev = PARASHA_TABLE[idx-1] if idx > 0 else curr
    
    return {
        "current_parasha": curr[1],
        "current_parasha_en": curr[2],
        "prev_parasha": prev[1],
        "prev_parasha_en": prev[2],
        "current_year": "תשפ\"ו",
        "prev_year": "תשפ\"ה"
    }

# ══════════════════════════════════════════════════════════════════
# 2. הבנת שפה טבעית (NLP) באמצעות Gemini
# ══════════════════════════════════════════════════════════════════
def parse_user_intent(api_key: str, raw_query: str, ctx: dict) -> dict:
    """
    מנתח את הטקסט החופשי שהמשתמש הקליד, ומחלץ משם פרטים מדויקים.
    למשל אם הקליד "קולדצקי שבוע שעבר", המערכת תדע לחלץ את "קולדצקי" ואת שנת תשפ"ו ואת פרשת שבוע שעבר.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-3.1-flash-lite", 
        generation_config={"response_mime_type": "application/json"}
    )
    
    prompt = f"""
    אתה מנתח בקשות למנוע חיפוש.
    נתונים עדכניים נכון להיום:
    הפרשה של השבוע: {ctx['current_parasha']}. השנה הנוכחית: {ctx['current_year']}.
    הפרשה של שבוע שעבר: {ctx['prev_parasha']}. שנה שעברה: {ctx['prev_year']}.
    
    בקשת המשתמש החופשית: "{raw_query}"

    משימתך: חלץ את הנתונים והחזר אובייקט JSON בלבד, בעל המבנה הבא:
    - "bulletin": שם העלון בלבד (נקי, למשל "קולדצקי", "זרע שמשון"). אל תכניס פה את שם הפרשה! אם המשתמש שאל בכללי, תן שם מתאים.
    - "parasha": שם הפרשה בעברית. אם המשתמש ביקש משהו על "שבוע שעבר", שים את "{ctx['prev_parasha']}". אם "השבוע", שים "{ctx['current_parasha']}".
    - "parasha_en": הפרשה באנגלית.
    - "year": שנת ההוצאה המבוקשת. ("{ctx['current_year']}" אלא אם הוא אמר במפורש שנה שעברה, ואז שים "{ctx['prev_year']}").
    """
    
    try:
        resp = model.generate_content(prompt)
        parsed = json.loads(resp.text)
        
        # הבטחת קיום שדות
        if "bulletin" not in parsed: 
            parsed["bulletin"] = raw_query
        if "parasha" not in parsed:
            parsed["parasha"] = ctx["current_parasha"]
        if "parasha_en" not in parsed:
            parsed["parasha_en"] = ctx["current_parasha_en"]
        if "year" not in parsed:
            parsed["year"] = ctx["current_year"]
            
        return parsed
    except Exception as e:
        log.error("Intent parsing failed: %s", e)
        # ברירת מחדל במקרה שהעיבוד נכשל
        return {
            "bulletin": raw_query, 
            "parasha": ctx["current_parasha"], 
            "parasha_en": ctx["current_parasha_en"], 
            "year": ctx["current_year"]
        }

# ══════════════════════════════════════════════════════════════════
# 3. מנועי חיפוש ושליפת קבצים
# ══════════════════════════════════════════════════════════════════
def build_queries(b: str, p: str, pe: str, y: str) -> list[str]:
    """בונה את השאילתות שיישלחו למנועי החיפוש"""
    return[
        f'"{b}" "{p}" {y} filetype:pdf',
        f'עלון שבת "{b}" פרשת {p} {y}',
        f'"{b}" "{pe}" {y} pdf'
    ]

def ddg_search(query: str) -> list[str]:
    """חיפוש ב-DuckDuckGo דרך HTML Scraping"""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/", 
            params={"q": query}, 
            headers=HEADERS, 
            timeout=8
        )
        soup = BeautifulSoup(r.text, "lxml")
        urls = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "uddg=" in href: 
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])[0]
            if href.lower().endswith(".pdf"): 
                urls.append(href)
        return urls[:3]
    except Exception as e:
        log.warning("DuckDuckGo error: %s", e)
        return []

def bing_search(query: str) -> list[str]:
    """חיפוש ב-Bing"""
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query + " filetype:pdf"},
            headers=HEADERS,
            timeout=8,
        )
        urls = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        return list(dict.fromkeys(urls))[:3]
    except Exception as e:
        log.warning("Bing error: %s", e)
        return []

def direct_site_search(b: str, pe: str) -> list[str]:
    """חיפוש בתוך אתרי יהדות ישראליים מוכרים"""
    p = urllib.parse.quote(pe)
    bl = urllib.parse.quote(b)
    sites =[
        f"https://www.yeshiva.org.il/search?q={bl}+{p}&type=pdf",
        f"https://www.toraland.org.il/search?s={bl}+{p}"
    ]
    urls =[]
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=8)
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:2])
        except Exception:
            pass
    return urls[:3]

PDF_MAGIC = b"%PDF"

def fetch_pdf_bytes(url: str) -> bytes | None:
    """
    מוריד את ה-PDF מהלינק.
    מוודא שמדובר בקובץ מתחת ל-10 מגה ושזה אכן PDF חוקי.
    """
    try:
        head = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        if head.status_code != 200:
            return None
        
        content_type = head.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type and not url.lower().endswith(".pdf"): 
            return None
            
        r = requests.get(url, headers=HEADERS, timeout=10, stream=True)
        buf = io.BytesIO()
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > 10 * 1024 * 1024:  # חסימת קבצים כבדים מדי
                return None
                
        data = buf.getvalue()
        if data.startswith(PDF_MAGIC) and len(data) > 5000: 
            return data
    except Exception as e:
        log.warning("fetch_pdf_bytes failed: %s", e)
        
    return None

# ══════════════════════════════════════════════════════════════════
# 4. אימות קפדני (Strict Validation) של ה-PDF על ידי ג'מיני
# ══════════════════════════════════════════════════════════════════
def gemini_validate_pdf(api_key: str, pdf_bytes: bytes, b: str, p: str, y: str) -> bool:
    """
    מנגנון מחמיר שקורא את תוכן ה-PDF.
    אם המשתמש מחפש תשפ"ו ויש שם תשפ"ה - פוסל!
    אם המשתמש מחפש עלון א' ויש עלון ב' - פוסל!
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")
        b64 = base64.b64encode(pdf_bytes[:2 * 1024 * 1024]).decode()

        prompt = f"""
        ענה אך ורק מילה אחת: YES או NO.
        בדוק את קובץ ה-PDF המצורף וקבע האם הוא מקיים את **כל** 3 התנאים הבאים:
        1. שייך במדויק לעלון בשם: "{b}"
        2. עוסק בפרשת: "{p}"
        3. הודפס בשנת ההוצאה: "{y}" (שים לב!! אם ב-PDF כתובה שנה שונה מהשנה '{y}', למשל אם כתוב תשפ"ד או תשפ"ה, עליך לענות NO!).
        
        אם אחד מהתנאים לא מתקיים או שאתה לא בטוח, ענה NO.
        """
        resp = model.generate_content([
            {"mime_type": "application/pdf", "data": b64}, 
            prompt
        ])
        answer = resp.text.strip().upper()
        log.info("Validation for %s, Parasha %s, Year %s -> %s", b, p, y, answer)
        return answer.startswith("YES")
    except Exception as e:
        log.warning("Validation API error: %s", e)
        return False  # במקרה של שגיאת אינטרנט/API - אנחנו פוסלים את העלון כדי לא להביא זבל.

# ══════════════════════════════════════════════════════════════════
# 5. המנוע הראשי: חיפוש רגיל או Fallback מקביל מרובה תהליכים
# ══════════════════════════════════════════════════════════════════
def search_single_target(api_key: str, b: str, p: str, pe: str, y: str):
    """
    פונקציית מעטפת שמבצעת חיפוש, הורדה ואימות עבור עלון ספציפי.
    """
    queries = build_queries(b, p, pe, y)
    candidates =[]
    
    for q in queries: 
        candidates += ddg_search(q)
        candidates += bing_search(q)
        
    candidates += direct_site_search(b, pe)
    unique = list(dict.fromkeys(candidates))

    for url in unique:
        pdf = fetch_pdf_bytes(url)
        if pdf and gemini_validate_pdf(api_key, pdf, b, p, y):
            safe_name = f"{b}_{pe}_{y}.pdf".replace('"', "").replace(' ', '_')
            return pdf, safe_name
            
    return None, None

def find_bulletin_logic(api_key: str, raw_query: str):
    """
    לוגיקת העל של המערכת:
    1. פענוח.
    2. ניסיון מציאה של העלון המדויק.
    3. אם נכשל -> חיפוש ברקע של שבוע שעבר + שנה שעברה בו זמנית!
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    ctx = get_context_dates(today)
    
    parsed = parse_user_intent(api_key, raw_query, ctx)
    b = parsed.get("bulletin")
    p = parsed.get("parasha")
    pe = parsed.get("parasha_en")
    y = parsed.get("year")
    
    log.info("Starting target search: %s | %s | %s", b, p, y)
    
    # ניסיון 1: חיפוש ראשוני לפי בקשת המשתמש בדיוק
    pdf, filename = search_single_target(api_key, b, p, pe, y)
    if pdf:
        return {
            "success": True, 
            "pdf": pdf, 
            "filename": filename, 
            "msg": f"נמצא גליון '{b}' לפרשת {p} ({y})!"
        }
    
    # ניסיון 2: חיפוש אקטיבי של אלטרנטיבות (Fallback) במקביל!
    # נריץ חיפוש גם על שבוע שעבר וגם על שנה שעברה בו זמנית.
    log.info("Primary target failed. Initiating concurrent fallbacks...")
    options = []
    
    fallbacks =[
        ("שבוע שעבר", b, ctx['prev_parasha'], ctx['prev_parasha_en'], ctx['current_year']),
        ("שנה שעברה", b, p, pe, ctx['prev_year'])
    ]
    
    # מפעילים ThreadPoolExecutor כדי להריץ אותם במקביל ולא לבזבז למשתמש זמן
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(search_single_target, api_key, fb[1], fb[2], fb[3], fb[4]): fb 
            for fb in fallbacks
        }
        
        for future in concurrent.futures.as_completed(futures):
            fb_info = futures[future]
            try:
                res_pdf, res_fn = future.result()
                if res_pdf:
                    options.append({
                        "title": f"פרשת {fb_info[2]} ({fb_info[0]})",
                        "filename": res_fn,
                        "pdf_b64": base64.b64encode(res_pdf).decode()
                    })
            except Exception as e:
                log.warning("Fallback exception for %s: %s", fb_info[0], e)

    if len(options) > 0:
        return {
            "success": False, 
            "fallback": True, 
            "msg": f"העלון '{b}' לפרשת {p} השנה עדיין לא יצא או טרם הועלה. אבל חיפשתי בארכיון והבאתי לך אלטרנטיבות חלופיות שמוכנות מיד להורדה:",
            "options": options
        }
    
    return {
        "success": False, 
        "error": f"מצטער, העלון '{b}' לפרשת {p} ({y}) לא נמצא בשום מקום ברשת, וגם לא מצאתי את העלון של שבוע שעבר או שנה שעברה."
    }

# ══════════════════════════════════════════════════════════════════
# 6. Vercel Handler - טיפול בבקשות HTTP
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            return self._json(400, {"success": False, "error": "JSON Error"})

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key:
            return self._json(400, {"success": False, "error": "חסר מפתח API בהגדרות"})
        if not query:
            return self._json(400, {"success": False, "error": "חסרה שורת שאילתה לחיפוש"})

        try:
            result = find_bulletin_logic(api_key, query)
        except Exception as e:
            log.exception("Server Error in find_bulletin_logic")
            return self._json(500, {"success": False, "error": f"Server crash: {e}"})

        # ניתוב התשובה למשתמש לפי התוצאה: רגיל, Fallback, או כישלון
        if result.get("success"):
            self._json(200, {
                "success": True,
                "message": result["msg"],
                "filename": result["filename"],
                "pdf_b64": base64.b64encode(result["pdf"]).decode()
            })
        elif result.get("fallback"):
            self._json(200, {
                "success": False,
                "fallback": True,
                "message": result["msg"],
                "options": result["options"]
            })
        else:
            self._json(404, {"success": False, "error": result["error"]})

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# --- סוף הקובץ ---
