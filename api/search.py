# -*- coding: utf-8 -*-
"""
================================================================================
AlonBot - Smart Shabbat Bulletin Search API
================================================================================
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות המערכת בגרסה זו (גרסת NLP מתקדמת):
1. מנוע הבנת שפה חופשית (NLP): מפונח על ידי Gemini. יודע לתרגם בקשות כמו
   "עלון לילדים" לשם עלון אמיתי ("אותיות וילדים") או "קולדצקי" ל-"דברי שיח".
2. הגנת JSON קפדנית: פותר את בעיית ה- JSON Parsing Error על ידי הסרת גרשיים 
   פנימיים משנות הוצאה (למשל, שימוש ב-"תשפו" במקום "תשפ"ו").
3. אימות תוכן ה-PDF: מונע החזרת עלונים משנים קודמות בטעות.
4. מנגנון Fallback אקטיבי מרובה תהליכים: אם עלון לא נמצא השבוע, מחפש 
   בו-זמנית את השבוע שעבר ואת השנה שעברה!
5. קוד ארוך, מתועד, מסודר ומרווח להקלת תחזוקה והבנה.
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
# הגדרות לוגים מתקדמות כדי שתוכל לראות הכל בקונסול
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
# טבלת פרשיות קשיחה ומלאה לשנים תשפ"ה-תשפ"ו
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
    # כדי למנוע שגיאות JSON Parsing בהמשך התהליך מול מודל השפה.
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
    פונקציה קריטית: מנקה את התשובה של ג'מיני כדי למנוע שגיאות פענוח JSON.
    לפעמים ג'מיני מחזיר את ה-JSON בתוך בלוקים של קוד (```json ... ```)
    או מוסיף תווים לא רצויים.
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
# NLP Engine - הבנת שפה טבעית
# ══════════════════════════════════════════════════════════════════
def parse_user_intent(api_key: str, raw_query: str, ctx: dict) -> dict:
    """
    המוח מאחורי הבנת השפה הטבעית:
    מנתח טקסט חופשי (כמו "עלון לילדים לפרשת נח") ומחלץ ממנו
    במדויק את שם העלון האמיתי, שם הפרשה, והשנה!
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-3.1-flash-lite", 
        generation_config={"response_mime_type": "application/json"}
    )
    
    prompt = f"""
    אתה מנוע להבנת שפה טבעית עבור מערכת חיפוש עלוני שבת יהודיים.
    המטרה שלך היא לתרגם את הבקשה החופשית של המשתמש לשאילתת חיפוש מדויקת.
    
    נתונים עדכניים:
    - הפרשה של השבוע: {ctx['current_parasha']}. השנה הנוכחית: {ctx['current_year']}.
    - הפרשה של שבוע שעבר: {ctx['prev_parasha']}. השנה שעברה: {ctx['prev_year']}.
    
    המשתמש הקליד במילים שלו: "{raw_query}"

    עליך להחזיר אובייקט JSON חוקי ותקין עם השדות הבאים בדיוק:
    1. "bulletin": שים לב!! אם המשתמש כתב מונח כללי כמו "עלון מעניין לילדים", "משהו לילדים" או "לילדים", אסור לך להחזיר "עלון מעניין לילדים"! חובה עליך להמיר זאת לשם של עלון ילדים אמיתי ומוכר כגון "אותיות וילדים", "מטעמים לשולחן שבת", או "ילדים תורניים".
       אם הוא אמר "קולדצקי" או "הרב קולדצקי", המר זאת לעלון: "דברי שיח".
       אם הוא אמר "עלון הלכה", המר זאת ל-"פניני הלכה" או "הלכה למעשה".
       החזר תמיד רק את שם העלון המדויק!
    2. "parasha": שם הפרשה בעברית. (ברירת מחדל: "{ctx['current_parasha']}". אם ביקש במפורש על שבוע שעבר, החזר "{ctx['prev_parasha']}").
    3. "parasha_en": הפרשה באנגלית.
    4. "year": שנת ההוצאה ללא גרשיים (ברירת מחדל: "{ctx['current_year']}". אם אמר שנה שעברה תן "{ctx['prev_year']}").
    
    החזר אך ורק פורמט JSON ללא שום טקסט נוסף לפני או אחרי!
    """
    
    try:
        resp = model.generate_content(prompt)
        clean_text = clean_json_text(resp.text)
        parsed = json.loads(clean_text)
        
        # השלמת חוסרים במקרה שהמודל "שכח" משהו
        if "bulletin" not in parsed: parsed["bulletin"] = raw_query
        if "parasha" not in parsed: parsed["parasha"] = ctx["current_parasha"]
        if "parasha_en" not in parsed: parsed["parasha_en"] = ctx["current_parasha_en"]
        if "year" not in parsed: parsed["year"] = ctx["current_year"]
            
        log.info("NLP Successfully Parsed: %s", parsed)
        return parsed
        
    except Exception as e:
        log.error("NLP Intent Parsing Failed: %s. Using raw query.", e)
        # Fallback בטוח: אם יש קריסה כלשהי בעיבוד השפה, נחזיר את הנתונים כפי שהם
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
    יוצר וריאציות של שאילתות כדי למקסם את הסיכוי למצוא את הקובץ במנועי החיפוש.
    """
    # אם השנה היא "תשפו" נחפש גם תשפ"ו
    y_with_quotes = y
    if y == "תשפו": y_with_quotes = 'תשפ"ו'
    elif y == "תשפה": y_with_quotes = 'תשפ"ה'
    
    return[
        f'"{b}" "{p}" {y_with_quotes} filetype:pdf',
        f'עלון שבת "{b}" פרשת {p} {y_with_quotes}',
        f'"{b}" "{pe}" {y_with_quotes} pdf'
    ]

def search_duckduckgo(query: str) -> list[str]:
    """מבצע חיפוש עומק ב-DuckDuckGo דרך ממשק ה-HTML הנסתר שלהם"""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/", 
            params={"q": query}, 
            headers=HEADERS, 
            timeout=10
        )
        soup = BeautifulSoup(r.text, "lxml")
        urls = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "uddg=" in href: 
                # פריסת הקישור המוצפן של DuckDuckGo
                parsed_url = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                href = query_params.get("uddg", [""])[0]
                
            if href.lower().endswith(".pdf"): 
                urls.append(href)
                
        return urls[:4]
    except Exception as e:
        log.warning("DuckDuckGo fetch failed: %s", e)
        return []

def search_bing(query: str) -> list[str]:
    """מבצע חיפוש מהיר ב-Bing לאיתור קבצי PDF נסתרים"""
    try:
        r = requests.get(
            "https://www.bing.com/search", 
            params={"q": query + " filetype:pdf"}, 
            headers=HEADERS, 
            timeout=8
        )
        # שימוש בביטוי רגולרי לשליפת כל הקישורים שמסתיימים ב-pdf
        urls = re.findall(r'"(https?://[^"]+\.pdf)"', r.text)
        # סינון כפילויות
        unique_urls = list(dict.fromkeys(urls))
        return unique_urls[:4]
    except Exception as e:
        log.warning("Bing fetch failed: %s", e)
        return[]

def search_direct_sites(b: str, pe: str) -> list[str]:
    """
    חיפוש ישיר בתוך הפורטלים היהודיים הגדולים בישראל:
    Yeshiva.org.il ו-Toraland.
    """
    safe_parasha = urllib.parse.quote(pe)
    safe_bulletin = urllib.parse.quote(b)
    
    sites =[
        f"https://www.yeshiva.org.il/search?q={safe_bulletin}+{safe_parasha}&type=pdf",
        f"https://www.toraland.org.il/search?s={safe_bulletin}+{safe_parasha}"
    ]
    
    urls =[]
    for site in sites:
        try:
            r = requests.get(site, headers=HEADERS, timeout=8)
            urls.extend(re.findall(r'"(https?://[^"]+\.pdf)"', r.text)[:3])
        except Exception:
            continue
            
    return urls[:4]

# ══════════════════════════════════════════════════════════════════
# הורדה ואימות של ה-PDF
# ══════════════════════════════════════════════════════════════════
def download_pdf_bytes(url: str) -> bytes | None:
    """
    מוריד את ה-PDF מהאינטרנט. מגן מפני קבצים ענקיים או קבצים שבורים.
    מחזיר Bytes של הקובץ או None במקרה של כישלון.
    """
    try:
        # בדיקה מוקדמת של הכותרות (Headers) כדי למנוע הורדת קבצי ענק
        head = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)
        if head.status_code != 200: 
            return None
        
        content_type = head.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type and not url.lower().endswith(".pdf"): 
            return None
            
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        buf = io.BytesIO()
        
        # הורדה בחלקים (Chunks) עם עצירת חירום
        for chunk in r.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > MAX_FILE_SIZE: 
                log.warning("File too large, aborted: %s", url)
                return None
                
        data = buf.getvalue()
        
        # בדיקת חתימת PDF (Magic Bytes) וגודל מינימלי
        if data.startswith(PDF_MAGIC_BYTES) and len(data) > MIN_FILE_SIZE: 
            return data
            
    except Exception as e:
        log.warning("Download failed for %s: %s", url, e)
        
    return None

def gemini_validate_pdf(api_key: str, pdf_bytes: bytes, b: str, p: str, y: str) -> bool:
    """
    אימות קפדני ונוקשה!
    קורא את ה-PDF ומוודא שהוא לא זבל מלפני שנתיים, אלא בדיוק השנה והפרשה המבוקשת.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite")
        
        # לוקחים רק את 2 המגה-בייט הראשונים (העמודים הראשונים) כדי לחסוך טוקנים
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
        3. האם שנת ההוצאה הכתובה בעלון היא בפירוש שנת {display_year}? 
           (אזהרה חמורה: אם ב-PDF כתובה שנה ישנה כמו תשפ"ד או תשפ"ג - עליך לענות NO מיד!).
        
        אם אתה מסופק אפילו באחד מהסעיפים - ענה NO.
        """
        
        resp = model.generate_content([
            {"mime_type": "application/pdf", "data": b64_data}, 
            prompt
        ])
        
        answer = resp.text.strip().upper()
        log.info("PDF Validation result for [%s | %s | %s] -> %s", b, p, y, answer)
        return answer.startswith("YES")
        
    except Exception as e:
        log.warning("Validation API error: %s. Rejecting file for safety.", e)
        # במקרה של שגיאת התחברות - נפסול את הקובץ כדי לא להגיש למשתמש זבל
        return False 


# ══════════════════════════════════════════════════════════════════
# ליבת החיפוש וה-Fallback
# ══════════════════════════════════════════════════════════════════
def search_single_target(api_key: str, b: str, p: str, pe: str, y: str):
    """
    הפונקציה מבצעת את מעגל החיפוש השלם (שאילתות -> מנועי חיפוש -> הורדה -> אימות)
    עבור יעד אחד ספציפי.
    """
    queries = build_search_queries(b, p, pe, y)
    candidates =[]
    
    for q in queries: 
        candidates += search_duckduckgo(q)
        candidates += search_bing(q)
        
    candidates += search_direct_sites(b, pe)
    
    # ניקוי כפילויות תוך שמירה על הסדר המקורי (רלוונטיות)
    unique_urls = list(dict.fromkeys(candidates))
    log.info("Found %d unique URL candidates for %s %s", len(unique_urls), b, p)

    for url in unique_urls:
        pdf_data = download_pdf_bytes(url)
        if pdf_data and gemini_validate_pdf(api_key, pdf_data, b, p, y):
            # יצירת שם קובץ בטוח (Safe Filename)
            safe_name = f"{b}_{pe}_{y}.pdf".replace('"', "").replace(' ', '_')
            return pdf_data, safe_name
            
    return None, None

def find_bulletin_logic(api_key: str, raw_query: str):
    """
    מנוע החיפוש המרכזי.
    שלב א: מנתח את בקשת המשתמש.
    שלב ב: מחפש את העלון הספציפי.
    שלב ג: אם העלון לא יצא השבוע - מפעיל חיפוש ברקע לעלוני עבר (Fallback).
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
    
    # שלב 2: ניסיון חיפוש ראשוני (מה שהמשתמש באמת ביקש)
    pdf, filename = search_single_target(api_key, b, p, pe, y)
    if pdf:
        return {
            "success": True, 
            "pdf": pdf, 
            "filename": filename, 
            "msg": f"מעולה! נמצא הגליון '{b}' לפרשת {p} ({y})."
        }
    
    # שלב 3: חיפוש אקטיבי של אלטרנטיבות (Fallback) במקביל!
    log.info("Primary search failed. Initiating concurrent fallbacks for '%s'...", b)
    options =[]
    
    # הגדרת היעדים החלופיים: שבוע שעבר, וגם שנה שעברה.
    fallbacks = [
        ("משבוע שעבר", b, ctx['prev_parasha'], ctx['prev_parasha_en'], ctx['current_year']),
        ("משנה שעברה", b, p, pe, ctx['prev_year'])
    ]
    
    # הרצת היעדים החלופיים במקביל כדי לחסוך זמן למשתמש (Multi-threading)
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
                    # מצאנו עלון חלופי! נצרף אותו להצעות המוכנות להורדה.
                    options.append({
                        "title": f"פרשת {fb_info[2]} {fb_info[0]}",
                        "filename": res_fn,
                        "pdf_b64": base64.b64encode(res_pdf).decode()
                    })
            except Exception as e:
                log.error("Error during fallback search for %s: %s", fb_info[0], e)

    # אם מצאנו אלטרנטיבות חלופיות
    if len(options) > 0:
        return {
            "success": False, 
            "fallback": True, 
            "msg": f"מצטער, העלון '{b}' לפרשת {p} השנה עדיין לא פורסם. אבל אל דאגה! חיפשתי עמוק בארכיון והבאתי לך אלטרנטיבות שמוכנות מיד להורדה:",
            "options": options
        }
    
    # לא מצאנו כלום, גם לא בארכיון
    return {
        "success": False, 
        "error": f"מצטער, העלון '{b}' לפרשת {p} לא נמצא בשום מקום ברשת, וגם לא בארכיון השנים הקודמות. נסה לחפש עלון אחר."
    }

# ══════════════════════════════════════════════════════════════════
# Vercel Handler - ניהול בקשות ותגובות מול הדפדפן
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    
    def _handle_cors(self):
        """מאפשר גישה ממקורות שונים (CORS)"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """תגובה חלקה לבקשות OPTIONS מהדפדפן"""
        self.send_response(200)
        self._handle_cors()
        self.end_headers()

    def do_POST(self):
        """מקבל את בקשת החיפוש, מנתח, מחפש ומחזיר JSON"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            body = json.loads(raw_body)
        except Exception:
            return self._send_json(400, {"success": False, "error": "פורמט בקשה לא תקין (JSON Error)."})

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key:
            return self._send_json(400, {"success": False, "error": "חסר מפתח API. נא להזין בהגדרות."})
        if not query:
            return self._send_json(400, {"success": False, "error": "אנא הקלד את שם העלון שברצונך לחפש."})

        try:
            # הפעלת ליבת המערכת
            result = find_bulletin_logic(api_key, query)
        except Exception as e:
            log.exception("Critical server crash in find_bulletin_logic")
            return self._send_json(500, {"success": False, "error": f"שגיאת שרת פנימית: {e}"})

        # מענה למשתמש בהתאם לסטטוס התוצאה
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
            self._send_json(404, {"success": False, "error": result["error"]})

    def _send_json(self, status_code: int, data_obj: dict):
        """פונקציית עזר לאריזת ושליחת תשובת JSON מסודרת לדפדפן"""
        response_body = json.dumps(data_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._handle_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

# --- סוף הקובץ ---
