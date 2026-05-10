# -*- coding: utf-8 -*-
"""
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות המערכת:
1. הבנת שפה חופשית (NLP): ממיר משפטים כמו "משהו לילדים" ל-"אותיות וילדים".
2. אימות שנה חכם ונוקשה: מוודא שהעלון אכן מהשנה המבוקשת.
3. Fallback מקביל: מציע אלטרנטיבות חיות עם כפתורי הורדה.
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
# 2. NLP באמצעות Gemini (סופר חכם!)
# ══════════════════════════════════════════════════════════════════
def parse_user_intent(api_key: str, raw_query: str, ctx: dict) -> dict:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.1-flash-lite", generation_config={"response_mime_type": "application/json"})
    
    prompt = f"""
    אתה מנוע להבנת שפה טבעית עבור אפליקציית עלוני שבת.
    זמן נוכחי: הפרשה השבוע היא {ctx['current_parasha']} שנת {ctx['current_year']}. הפרשה בשבוע שעבר הייתה {ctx['prev_parasha']}.
    
    המשתמש הקליד במילים שלו: "{raw_query}"

    עליך לחלץ את הכוונה לקובץ JSON בלבד עם השדות הבאים:
    1. "bulletin": שים לב!! אם המשתמש כתב תיאור כמו "עלון מעניין לילדים", אסור לך להחזיר "עלון מעניין לילדים". עליך לחשוב על שם של עלון *אמיתי* שמתאים, למשל "אותיות וילדים", "מטעמים לשולחן שבת" וכדומה. אם הוא כתב "קולדצקי", החזר "דברי שיח" או "שיח יצחק". החזר תמיד שם של עלון יהודי מוכר!
    2. "parasha": שם הפרשה (ברירת מחדל: "{ctx['current_parasha']}". אם ביקש משבוע שעבר אז "{ctx['prev_parasha']}").
    3. "parasha_en": הפרשה באנגלית.
    4. "year": שנת ההוצאה (ברירת מחדל: "{ctx['current_year']}". אם אמר במפורש שנה שעברה, תן "{ctx['prev_year']}").
    """
    
    try:
        resp = model.generate_content(prompt)
        parsed = json.loads(resp.text)
        
        if "bulletin" not in parsed: parsed["bulletin"] = raw_query
        if "parasha" not in parsed: parsed["parasha"] = ctx["current_parasha"]
        if "parasha_en" not in parsed: parsed["parasha_en"] = ctx["current_parasha_en"]
        if "year" not in parsed: parsed["year"] = ctx["current_year"]
            
        return parsed
    except Exception as e:
        log.error("Intent parsing failed: %s", e)
        return {
            "bulletin": raw_query, 
            "parasha": ctx["current_parasha"], 
            "parasha_en": ctx["current_parasha_en"], 
            "year": ctx["current_year"]
        }

# ══════════════════════════════════════════════════════════════════
# 3. מנועי חיפוש ושליפת קבצים (מותאם לקישורים עבריים בעייתיים)
# ══════════════════════════════════════════════════════════════════
def build_queries(b: str, p: str, pe: str, y: str) -> list[str]:
    # מנקים גירשיים מהשנה עבור החיפוש ברשת, כדי שכתובות לא יישברו
    safe_y = y.replace('"', '').replace("'", "")
    return[
        f'"{b}" "{p}" {safe_y} filetype:pdf',
        f'עלון שבת "{b}" פרשת {p} {safe_y}',
        f'"{b}" "{pe}" {safe_y} pdf'
    ]

def ddg_search(query: str) -> list[str]:
    try:
        r = requests.get("https://html.duckduckgo.com/html/", params={"q": query}, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(r.text, "lxml")
        urls = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "uddg=" in href: 
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg",[""])[0]
            if href.lower().endswith(".pdf"): 
                urls.append(href)
        return urls[:4]
    except:
        return[]

def bing_search(query: str) -> list[str]:
    try:
        r = requests.get("https://www.bing.com/search", params={"q": query + " filetype:pdf"}, headers=HEADERS, timeout=8)
        urls = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        return list(dict.fromkeys(urls))[:4]
    except:
        return[]

def direct_site_search(b: str, pe: str) -> list[str]:
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
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:3])
        except:
            pass
    return urls[:4]

PDF_MAGIC = b"%PDF"

def fetch_pdf_bytes(url: str) -> bytes | None:
    try:
        head = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        if head.status_code != 200: return None
        
        ct = head.headers.get("Content-Type", "").lower()
        if "pdf" not in ct and not url.lower().endswith(".pdf"): return None
            
        r = requests.get(url, headers=HEADERS, timeout=12, stream=True)
        buf = io.BytesIO()
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > 12 * 1024 * 1024: return None
                
        data = buf.getvalue()
        if data.startswith(PDF_MAGIC) and len(data) > 5000: 
            return data
    except: pass
    return None

# ══════════════════════════════════════════════════════════════════
# 4. אימות קפדני וסמנטי על ידי ג'מיני
# ══════════════════════════════════════════════════════════════════
def gemini_validate_pdf(api_key: str, pdf_bytes: bytes, b: str, p: str, y: str) -> bool:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")
        b64 = base64.b64encode(pdf_bytes[:2 * 1024 * 1024]).decode()

        prompt = f"""
        ענה אך ורק מילה אחת: YES או NO.
        בדוק את קובץ ה-PDF וקבע האם הוא מקיים את *כל* 3 התנאים:
        1. האם העלון קשור או שייך לשם: "{b}"?
        2. האם הוא עוסק בפרשת: "{p}"?
        3. האם שנת ההוצאה הכתובה בעלון היא בפירוש: "{y}"? (אם ב-PDF כתובה שנה שונה מהשנה '{y}', למשל אם כתוב תשפ"ד או תשפ"ה ואתה צריך תשפ"ו, עליך לענות NO!).
        """
        resp = model.generate_content([{"mime_type": "application/pdf", "data": b64}, prompt])
        answer = resp.text.strip().upper()
        log.info("Validation for %s, Parasha %s, Year %s -> %s", b, p, y, answer)
        return answer.startswith("YES")
    except Exception as e:
        log.warning("Validation API error: %s", e)
        return False 

# ══════════════════════════════════════════════════════════════════
# 5. המנוע הראשי
# ══════════════════════════════════════════════════════════════════
def search_single_target(api_key: str, b: str, p: str, pe: str, y: str):
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
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    ctx = get_context_dates(today)
    
    parsed = parse_user_intent(api_key, raw_query, ctx)
    b, p, pe, y = parsed.get("bulletin"), parsed.get("parasha"), parsed.get("parasha_en"), parsed.get("year")
    
    log.info("NLP Result: %s | %s | %s", b, p, y)
    
    # חיפוש ראשוני
    pdf, filename = search_single_target(api_key, b, p, pe, y)
    if pdf:
        return {
            "success": True, 
            "pdf": pdf, 
            "filename": filename, 
            "msg": f"נמצא גליון '{b}' לפרשת {p} ({y})!"
        }
    
    # חיפוש Fallback
    options = []
    fallbacks =[
        ("שבוע שעבר", b, ctx['prev_parasha'], ctx['prev_parasha_en'], ctx['current_year']),
        ("שנה שעברה", b, p, pe, ctx['prev_year'])
    ]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(search_single_target, api_key, fb[1], fb[2], fb[3], fb[4]): fb for fb in fallbacks}
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
            except Exception:
                pass

    if len(options) > 0:
        return {
            "success": False, 
            "fallback": True, 
            "msg": f"העלון '{b}' לפרשת {p} השנה טרם הועלה. אבל מצאתי בארכיון אלטרנטיבות שמוכנות מיד להורדה:",
            "options": options
        }
    
    return {
        "success": False, 
        "error": f"מצטער, העלון '{b}' לפרשת {p} ({y}) לא נמצא ברשת, וגם לא מצאתי את העלון של שבוע שעבר או שנה שעברה."
    }

# ══════════════════════════════════════════════════════════════════
# 6. Vercel Handler
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
        try: body = json.loads(self.rfile.read(length))
        except: return self._json(400, {"success": False, "error": "JSON Error"})

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key: return self._json(400, {"success": False, "error": "חסר מפתח API בהגדרות"})
        if not query: return self._json(400, {"success": False, "error": "חסרה שורת שאילתה לחיפוש"})

        try:
            result = find_bulletin_logic(api_key, query)
        except Exception as e:
            log.exception("Server Error")
            return self._json(500, {"success": False, "error": f"Server crash: {e}"})

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
