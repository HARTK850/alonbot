# -*- coding: utf-8 -*-
"""
================================================================================
AlonBot - Smart Shabbat Bulletin Search API
================================================================================
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות המערכת בגרסה זו (חסינה לשגיאות):
1. תיקון שגיאות 404 ו-501: השרת תמיד יחזיר סטטוס 200, ויש לו מענה לבקשות GET.
2. מנוע הבנת שפה (NLP) מוגן קריסות: גם אם ג'מיני מתבלבל במבנה, הקוד יודע לתקן אותו.
   אם מודל ה-Lite נכשל, הוא עובר מיד למודל ה-Flash היציב כדי לא לאבד את בקשת המשתמש!
3. אימות תוכן ה-PDF: מונע החזרת עלונים משנים קודמות.
4. חיפוש באתרי יהדות נוספים שהוחזרו למערכת להגדלת מאגר העלונים.
5. מנגנון Fallback אקטיבי מרובה תהליכים (מציאת אלטרנטיבות בזמן אמת).
================================================================================
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

# ══════════════════════════════════════════════════════════════════
# הגדרות לוגים מתקדמות לבקרה על השרת
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# קבועים (Constants) - הגדרות חיפוש ותקשורת
# ══════════════════════════════════════════════════════════════════
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

MAX_FILE_SIZE = 12 * 1024 * 1024  # 12 MB - מגבלת גודל לקובץ PDF
MIN_FILE_SIZE = 5000              # 5 KB - קובץ קטן מזה הוא כנראה שגיאה או דף ריק
PDF_MAGIC_BYTES = b"%PDF"         # החתימה הדיגיטלית של כל קובץ PDF חוקי

# ══════════════════════════════════════════════════════════════════
# טבלת פרשיות קשיחה ומלאה
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
    מחשב את הפרשה של השבוע הנוכחי ואת הפרשה של שבוע שעבר.
    כך המערכת יכולה להבין כשהמשתמש כותב לה "משבוע שעבר".
    """
    days_until_shabbat = (5 - d.weekday()) % 7
    current_shabbat = d + timedelta(days=days_until_shabbat)
    
    idx = 0
    best_delta = 9999
    
    for i, (k, _, _) in enumerate(PARASHA_TABLE):
        kd = date.fromisoformat(k)
        delta = abs((kd - current_shabbat).days)
        if delta < best_delta:
            best_delta = delta
            idx = i

    curr = PARASHA_TABLE[idx]
    prev = PARASHA_TABLE[idx-1] if idx > 0 else curr
    
    # שימו לב: השנים מוחזרות ללא גרשיים (תשפו במקום תשפ"ו)
    # כדי למנוע שגיאות JSON Parsing שעלולות לקרוס בגלל גרשיים כפולים.
    return {
        "current_parasha": curr[1],
        "current_parasha_en": curr[2],
        "prev_parasha": prev[1],
        "prev_parasha_en": prev[2],
        "current_year": "תשפו",
        "prev_year": "תשפה"
    }


def clean_json_text(raw_text: str) -> str:
    """
    פונקציית הגנה קריטית: מנקה את התשובה של ג'מיני כדי למנוע שגיאות.
    מוריד שאריות קוד (כמו ```json) שאותן מודלי בינה מלאכותית נוטים להוסיף.
    """
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
        
    if text.endswith("```"):
        text = text[:-3]
        
    return text.strip()


# ══════════════════════════════════════════════════════════════════
# NLP Engine - הבנת שפה טבעית חסינה משגיאות
# ══════════════════════════════════════════════════════════════════
def call_gemini_nlp(api_key: str, prompt: str) -> str:
    """
    קורא לג'מיני. מנסה קודם את המודל הקל, ואם הוא לא זמין או קורס, 
    עובר מיד למודל ה-2.5-flash היציב כדי לא לאבד את בקשת המשתמש!
    (זה פותר את הקריסה שראית בלוגים).
    """
    genai.configure(api_key=api_key)
    try:
        # מנסים ללא mime_type מגביל
        model = genai.GenerativeModel("gemini-3.1-flash-lite")
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as e1:
        log.warning("Primary NLP model failed (%s). Falling back to gemini-2.5-flash...", e1)
        try:
            fallback_model = genai.GenerativeModel("gemini-2.5-flash")
            resp = fallback_model.generate_content(prompt)
            return resp.text
        except Exception as e2:
            log.error("Both NLP models failed! %s", e2)
            raise e2


def parse_user_intent(api_key: str, raw_query: str, ctx: dict) -> dict:
    """
    המוח מאחורי הבנת השפה הטבעית:
    מנתח טקסט חופשי (כמו "עלון לילדים לפרשת נח") ומחלץ ממנו
    במדויק את שם העלון האמיתי, שם הפרשה, והשנה!
    """
    prompt = f"""
    אתה מנוע להבנת שפה טבעית עבור מערכת חיפוש עלוני שבת יהודיים.
    המטרה שלך היא לתרגם את הבקשה החופשית של המשתמש לשאילתת חיפוש מדויקת.
    
    נתונים עדכניים:
    - הפרשה של השבוע: {ctx['current_parasha']}. השנה הנוכחית: {ctx['current_year']}.
    - הפרשה של שבוע שעבר: {ctx['prev_parasha']}. השנה שעברה: {ctx['prev_year']}.
    
    המשתמש הקליד במילים שלו: "{raw_query}"

    עליך להחזיר אך ורק אובייקט JSON חוקי ותקין עם השדות הבאים בדיוק:
    1. "bulletin": שים לב!! אם המשתמש כתב מונח כללי כמו "עלון מעניין לילדים", "משהו לילדים" או "לילדים", אסור לך להחזיר "עלון מעניין לילדים"! חובה עליך להמיר זאת לשם של עלון ילדים אמיתי ומוכר כגון "אותיות וילדים", "מטעמים לשולחן שבת", או "ילדים תורניים".
       אם הוא אמר "קולדצקי" או "הרב קולדצקי", המר זאת לעלון: "דברי שיח".
       אם הוא אמר "עלון הלכה", המר זאת ל-"פניני הלכה" או "הלכה למעשה".
       החזר תמיד רק את שם העלון המדויק!
    2. "parasha": שם הפרשה בעברית. (ברירת מחדל: "{ctx['current_parasha']}". אם ביקש במפורש על שבוע שעבר, החזר "{ctx['prev_parasha']}").
    3. "parasha_en": הפרשה באנגלית. (ברירת מחדל: "{ctx['current_parasha_en']}").
    4. "year": שנת ההוצאה ללא גרשיים כלל! (למשל: תשפו ולא תשפ"ו). 
    
    החזר אך ורק פורמט JSON.
    """
    
    try:
        raw_resp = call_gemini_nlp(api_key, prompt)
        clean_text = clean_json_text(raw_resp)
        parsed = json.loads(clean_text)
        
        # השלמת חוסרים במקרה שהמודל "שכח" משהו
        if "bulletin" not in parsed: parsed["bulletin"] = raw_query
        if "parasha" not in parsed: parsed["parasha"] = ctx["current_parasha"]
        if "parasha_en" not in parsed: parsed["parasha_en"] = ctx["current_parasha_en"]
        if "year" not in parsed: parsed["year"] = ctx["current_year"]
            
        log.info("NLP Successfully Parsed: %s", parsed)
        return parsed
        
    except Exception as e:
        log.error("NLP Intent Parsing Failed completely: %s. Using raw query as fallback.", e)
        # Fallback בטוח: אם יש קריסה כלשהי, נחזיר את הנתונים כפי שהם כדי לא למנוע חיפוש
        return {
            "bulletin": raw_query, 
            "parasha": ctx["current_parasha"], 
            "parasha_en": ctx["current_parasha_en"], 
            "year": ctx["current_year"]
        }


# ══════════════════════════════════════════════════════════════════
# מנועי חיפוש מקוונים (Scraping)
# ══════════════════════════════════════════════════════════════════
def build_search_queries(b: str, p: str, pe: str, y: str) -> list[str]:
    """
    יוצר וריאציות של שאילתות כדי למקסם את הסיכוי למצוא את הקובץ.
    מסיר את הגרשיים מהשנה כדי שקישורים לא יישברו במנועי חיפוש מסוימים.
    """
    safe_y = y.replace('"', '').replace("'", "")
    
    return[
        f'"{b}" "{p}" {safe_y} filetype:pdf',
        f'עלון שבת "{b}" פרשת {p} {safe_y}',
        f'"{b}" "{pe}" {safe_y} pdf'
    ]

def search_duckduckgo(query: str) -> list[str]:
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=10
        )

        log.info("DDG STATUS: %s", r.status_code)
        log.info("DDG LENGTH: %d", len(r.text))

        soup = BeautifulSoup(r.text, "lxml")

        urls = []

        for a in soup.select("a[href]"):
            href = a.get("href", "")

            if "uddg=" in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                href = qs.get("uddg", [""])[0]

            if ".pdf" in href.lower():
                urls.append(href)

        log.info("DDG PDF RESULTS: %d", len(urls))

        return list(dict.fromkeys(urls))[:8]

    except Exception as e:
        log.warning("DDG failed: %s", e)
        return []

def search_bing(query: str) -> list[str]:
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers=HEADERS,
            timeout=10
        )

        log.info("BING STATUS: %s", r.status_code)
        log.info("BING LENGTH: %d", len(r.text))

        urls = re.findall(r'https?://[^\s"\']+', r.text)

        pdfs = [u for u in urls if ".pdf" in u.lower()]

        log.info("BING PDF RESULTS: %d", len(pdfs))

        return list(dict.fromkeys(pdfs))[:8]

    except Exception as e:
        log.warning("BING failed: %s", e)
        return []

def search_direct_sites(b: str, pe: str) -> list[str]:
    """
    חיפוש ישיר בתוך הפורטלים היהודיים הגדולים בישראל:
    החזרנו לכאן גם את kipa.co.il כפי שהיה במקור!
    """
    safe_parasha = urllib.parse.quote(pe)
    safe_bulletin = urllib.parse.quote(b)
    
    sites =[
        f"https://www.yeshiva.org.il/search?q={safe_bulletin}+{safe_parasha}&type=pdf",
        f"https://www.toraland.org.il/search?s={safe_bulletin}+{safe_parasha}",
        f"https://www.kipa.co.il/?s={safe_bulletin}+{safe_parasha}+pdf"
    ]
    
    urls =[]
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=8)
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:3])
        except Exception:
            continue
            
    return urls[:5]

# ══════════════════════════════════════════════════════════════════
# הורדה ואימות של ה-PDF
# ══════════════════════════════════════════════════════════════════
def download_pdf_bytes(url: str) -> bytes | None:
    """
    מוריד את ה-PDF מהאינטרנט. מגן מפני קבצים ענקיים או קבצים שבורים.
    מחזיר Bytes של הקובץ או None במקרה של כישלון.
    """
    try:
        head = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        if head.status_code != 200: 
            return None
        
        content_type = head.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type and not url.lower().endswith(".pdf"): 
            return None
            
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        buf = io.BytesIO()
        
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > MAX_FILE_SIZE: 
                log.warning("File too large, aborted: %s", url)
                return None
                
        data = buf.getvalue()
        
        if data.startswith(PDF_MAGIC_BYTES) and len(data) > MIN_FILE_SIZE: 
            return data
            
    except Exception as e:
        log.warning("Download failed for %s: %s", url, e)
        
    return None

def gemini_validate_pdf(api_key: str, pdf_bytes: bytes, b: str, p: str, y: str) -> bool:
    """
    אימות קפדני! קורא את ה-PDF ומוודא שזה בדיוק השנה והפרשה המבוקשת.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash") # משתמשים במודל היציב לבדיקות ה-PDF
        
        sample_bytes = pdf_bytes[:2 * 1024 * 1024]
        b64_data = base64.b64encode(sample_bytes).decode()

        # אם השנה היא "תשפו" נבקש לחפש גם תשפ"ו
        display_year = y
        if y == "תשפו": display_year = "תשפ\"ו או תשפו"
        if y == "תשפה": display_year = "תשפ\"ה או תשפה"

        prompt = f"""
        ענה אך ורק מילה אחת: YES או NO.
        אנא קרא את העמוד הראשון של קובץ ה-PDF המצורף וקבע האם הוא מקיים את *כל* 3 התנאים:
        1. האם העלון שייך באופן ברור לסדרה/שם: "{b}"?
        2. האם הוא עוסק בפרשת: "{p}"?
        3. האם שנת ההוצאה הכתובה בעלון תואמת לשנת: {display_year}? 
           (אזהרה: אם ב-PDF כתובה שנה ישנה אחרת - עליך לענות NO!).
        
        אם אתה מסופק אפילו באחד מהסעיפים - ענה NO.
        """
        
        resp = model.generate_content([
            {"mime_type": "application/pdf", "data": b64_data}, 
            prompt
        ])
        
        answer = resp.text.strip().upper()
        log.info("PDF Validation result for[%s | %s | %s] -> %s", b, p, y, answer)
        return answer.startswith("YES")
        
    except Exception as e:
        log.warning("Validation API error: %s. Rejecting file for safety.", e)
        return False 


# ══════════════════════════════════════════════════════════════════
# ליבת החיפוש וה-Fallback
# ══════════════════════════════════════════════════════════════════
def search_single_target(api_key: str, b: str, p: str, pe: str, y: str):
    """
    חיפוש דו-שלבי חכם:
    1. חיפוש רגיל
    2. אם לא נמצא - משתמש במה שכן נמצא כדי לנסח חיפוש טוב יותר
    """

    # =========================
    # שלב ראשון - רגיל
    # =========================
    queries = build_search_queries(b, p, pe, y)
    candidates = []

    for q in queries:
        candidates += search_duckduckgo(q)
        candidates += search_bing(q)

    candidates += search_direct_sites(b, pe)

    unique_urls = list(dict.fromkeys(candidates))
    log.info("First search found %d candidates for %s %s", len(unique_urls), b, p)

    # ניסיון הורדה
    for url in unique_urls:
        pdf_data = download_pdf_bytes(url)
        if pdf_data and gemini_validate_pdf(api_key, pdf_data, b, p, y):
            safe_name = f"{b}_{pe}_{y}.pdf".replace('"', "").replace(" ", "_")
            return pdf_data, safe_name

    # =========================
    # שלב שני - חיפוש חכם
    # =========================
    log.info("Primary search failed. Starting smart retry...")

    smart_queries = build_smart_retry_queries(b, p, pe, y, unique_urls)

    second_candidates = []

    for q in smart_queries:
        second_candidates += search_duckduckgo(q)
        second_candidates += search_bing(q)

    second_urls = list(dict.fromkeys(second_candidates))
    log.info("Smart retry found %d candidates", len(second_urls))

    for url in second_urls:
        pdf_data = download_pdf_bytes(url)
        if pdf_data and gemini_validate_pdf(api_key, pdf_data, b, p, y):
            safe_name = f"{b}_{pe}_{y}.pdf".replace('"', "").replace(" ", "_")
            return pdf_data, safe_name

    return None, None

def build_smart_retry_queries(b: str, p: str, pe: str, y: str, found_urls: list[str]) -> list[str]:
    """
    אם חיפוש ראשון נכשל -
    משתמש במה שמצא כדי לייצר חיפוש חכם יותר
    """

    words = set()

    for url in found_urls:
        parts = re.split(r'[/_\-.?=&]+', url)

        for part in parts:
            part = part.strip()

            if len(part) >= 3:
                words.add(part)

    extra = " ".join(list(words)[:6])

    queries = [
        f'"{b}" pdf',
        f'"{b}" "{p}" pdf',
        f'"{b}" "{pe}" pdf',
        f'{b} {p} filetype:pdf',
        f'{b} {extra} pdf',
        f'"{b}" עלון שבת pdf',
        f'"{b}" פרשת {p}',
    ]

    return list(dict.fromkeys(queries))

def find_bulletin_logic(api_key: str, raw_query: str):
    """
    מנוע החיפוש המרכזי.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    ctx = get_context_dates(today)
    
    # שלב 1: הבנת כוונת המשתמש
    parsed = parse_user_intent(api_key, raw_query, ctx)
    b = parsed.get("bulletin")
    p = parsed.get("parasha")
    pe = parsed.get("parasha_en")
    y = parsed.get("year")
    
    log.info("NLP Extracted Intent: Bulletin='%s', Parasha='%s', Year='%s'", b, p, y)
    
    # שלב 2: ניסיון חיפוש ראשוני
    pdf, filename = search_single_target(api_key, b, p, pe, y)
    if pdf:
        return {
            "success": True, 
            "pdf": pdf, 
            "filename": filename, 
            "msg": f"מעולה! נמצא הגליון '{b}' לפרשת {p}."
        }
    
    # שלב 3: חיפוש אקטיבי של אלטרנטיבות (Fallback) במקביל!
    log.info("Primary search failed. Initiating concurrent fallbacks for '%s'...", b)
    options =[]
    
    fallbacks = [
        ("משבוע שעבר", b, ctx['prev_parasha'], ctx['prev_parasha_en'], ctx['current_year']),
        ("משנה שעברה", b, p, pe, ctx['prev_year'])
    ]
    
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
                        "title": f"פרשת {fb_info[2]} {fb_info[0]}",
                        "filename": res_fn,
                        "pdf_b64": base64.b64encode(res_pdf).decode()
                    })
            except Exception as e:
                log.error("Error during fallback search for %s: %s", fb_info[0], e)

    if len(options) > 0:
        return {
            "success": False, 
            "fallback": True, 
            "msg": f"מצטער, העלון '{b}' לפרשת {p} טרם פורסם. חיפשתי עמוק בארכיון והבאתי לך אלטרנטיבות שמוכנות מיד להורדה:",
            "options": options
        }
    
    return {
        "success": False, 
        "error": f"מצטער, העלון '{b}' לפרשת {p} לא נמצא בשום מקום ברשת, וגם לא בארכיון השנים הקודמות."
    }

# ══════════════════════════════════════════════════════════════════
# Vercel Handler - טיפול בבקשות מהדפדפן עם מניעת שגיאות ה-404 ו-501
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    
    def _handle_cors(self):
        """מאפשר גישה חלקה לדפדפן"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """תגובה חלקה לבקשות מקדימות"""
        self.send_response(200)
        self._handle_cors()
        self.end_headers()
        
    def do_GET(self):
        """
        תיקון קריטי לשגיאת ה-501!
        כעת אם משתמש ייכנס לקישור דרך הדפדפן (שמפעיל GET), 
        הוא יקבל הודעה יפה במקום שגיאת שרת מפחידה.
        """
        self._send_json(200, {
            "success": True, 
            "message": "AlonBot API is running successfully. Please send a POST request to use the search engine."
        })

    def do_POST(self):
        """הפונקציה המרכזית המקבלת את בקשת החיפוש"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            body = json.loads(raw_body)
        except Exception:
            # במקום להחזיר 400 שיוצר שגיאה בדפדפן, מחזירים תמיד 200 עם success=False
            return self._send_json(200, {"success": False, "error": "פורמט בקשה לא תקין (JSON Error)."})

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key:
            return self._send_json(200, {"success": False, "error": "חסר מפתח API. נא להזין בהגדרות."})
        if not query:
            return self._send_json(200, {"success": False, "error": "אנא הקלד את שם העלון שברצונך לחפש."})

        try:
            result = find_bulletin_logic(api_key, query)
        except Exception as e:
            log.exception("Critical server crash in find_bulletin_logic")
            return self._send_json(200, {"success": False, "error": f"שגיאת שרת פנימית: {e}"})

        # שים לב: אנחנו מחזירים *תמיד* סטטוס 200, כדי לא ליצור שגיאת 404 (Not Found) אדומה בדפדפן!
        # הלוגיקה של ההצלחה או הכישלון מנוהלת בתוך ה-JSON עצמו.
        
        if result.get("success"):
            self._send_json(200, {
                "success": True,
                "message": result["msg"],
                "filename": result["filename"],
                "pdf_b64": base64.b64encode(result["pdf"]).decode()
            })
        elif result.get("fallback"):
            self._send_json(200, {
                "success": False,
                "fallback": True,
                "message": result["msg"],
                "options": result["options"]
            })
        else:
            self._send_json(200, {
                "success": False, 
                "error": result["error"]
            })

    def _send_json(self, status_code: int, data_obj: dict):
        """פונקציית עזר לשליחת ה-JSON חזרה לדפדפן בצורה תקנית"""
        response_body = json.dumps(data_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._handle_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)
