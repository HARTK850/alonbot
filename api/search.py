# -*- coding: utf-8 -*-
"""
================================================================================
AlonBot - Enterprise Smart Shabbat Bulletin Search API (Haredi Edition)
================================================================================
POST /api/search
body: { "api_key": "...", "query": "..." }

תכונות ליבה במערכת ה-Enterprise החדשה:
1. URL Unwrapping: פתרון קריטי לבעיית הקישורים של Yahoo ו-Bing! שולף את כתובת
   ה-PDF האמיתית מתוך ה-Redirect URL של מנועי החיפוש.
2. תכנות מונחה עצמים (OOP): הקוד בנוי ממחלקות (Classes) המטפלות בנפרד בהבנת שפה,
   סריקת רשת, ניהול תהליכים מקבילים (Threading) והורדת קבצים.
3. מאגרי מידע חרדיים בלבד: סריקה ממוקדת באתרים Ladaat.co, Beinenu.com, Dirshu.co.il.
4. NLP מחוזק עם מילון מובנה: מתרגם שמות רבנים לשמות העלונים הרשמיים שלהם.
5. מנגנון Fail-Safe: כל שלב עטוף ב-Try-Except למניעת קריסת Vercel.
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
import random

import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# ══════════════════════════════════════════════════════════════════
# Config & Logging - הגדרות מערכת מתקדמות
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger("AlonBotCore")

class AppConfig:
    """הגדרות סטטיות של המערכת, תצורת חיבור ומגבלות זיכרון"""
    
    # מגבלות קבצים כדי לא להקריס את השרת בפענוח
    MAX_FILE_SIZE_BYTES = 12 * 1024 * 1024  # 12 MB
    MIN_FILE_SIZE_BYTES = 5000              # 5 KB
    PDF_MAGIC = b"%PDF"
    
    # סבב של User Agents כדי להתחמק מחסימות בוטים (Anti-Bot evasion)
    USER_AGENTS =[
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ]

    @staticmethod
    def get_headers() -> dict:
        """מחזיר Headers רנדומליים לדפדפן כדי לדמות משתמש אמיתי"""
        return {
            "User-Agent": random.choice(AppConfig.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

# ══════════════════════════════════════════════════════════════════
# Calendar Engine - מנוע זמנים ופרשיות
# ══════════════════════════════════════════════════════════════════
class JewishCalendar:
    """מחלקה לניהול תאריכים, פרשיות השבוע והמרות זמנים"""
    
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

    @classmethod
    def get_context(cls, base_date: date) -> dict:
        """מחזיר הקשר זמן של השבוע ושבוע שעבר (הכרחי ל-Fallback)"""
        days_until_shabbat = (5 - base_date.weekday()) % 7
        current_shabbat = base_date + timedelta(days=days_until_shabbat)
        
        idx = 0
        best_delta = 9999
        
        for i, (k, _, _) in enumerate(cls.PARASHA_TABLE):
            kd = date.fromisoformat(k)
            delta = abs((kd - current_shabbat).days)
            if delta < best_delta:
                best_delta = delta
                idx = i

        curr = cls.PARASHA_TABLE[idx]
        prev = cls.PARASHA_TABLE[idx-1] if idx > 0 else curr
        
        return {
            "current_parasha": curr[1],
            "current_parasha_en": curr[2],
            "prev_parasha": prev[1],
            "prev_parasha_en": prev[2],
            "current_year": "תשפו",  # מוגש ללא גרשיים כדי למנוע קריסת JSON!
            "prev_year": "תשפה"
        }

# ══════════════════════════════════════════════════════════════════
# NLP Engine - פענוח שפה טבעית חרדית
# ══════════════════════════════════════════════════════════════════
class NaturalLanguageProcessor:
    """מחלקה שאחראית על תרגום בקשות חופשיות לשאילתות מדויקות"""
    
    @staticmethod
    def _clean_json_output(raw_text: str) -> str:
        """מנקה קוד עודף שג'מיני עלול להוסיף סביב ה-JSON"""
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
            
        if text.endswith("```"):
            text = text[:-3]
            
        return text.strip()

    @staticmethod
    def _call_gemini_with_fallback(api_key: str, prompt: str) -> str:
        """קורא למודל שפה, עם גיבוי למודל יציב יותר במקרה של קריסה"""
        genai.configure(api_key=api_key)
        try:
            model = genai.GenerativeModel("gemini-3.1-flash-lite")
            response = model.generate_content(prompt)
            return response.text
        except Exception as e1:
            log.warning("NLP Flash-Lite failed (%s). Retrying with Flash 2.5...", e1)
            try:
                fallback_model = genai.GenerativeModel("gemini-2.5-flash")
                response = fallback_model.generate_content(prompt)
                return response.text
            except Exception as e2:
                log.error("All NLP models failed. Reason: %s", e2)
                raise e2

    @classmethod
    def extract_intent(cls, api_key: str, raw_query: str, ctx: dict) -> dict:
        """הפונקציה המרכזית להבנת רצון המשתמש"""
        
        prompt = f"""
        אתה בוט חכם המיועד לציבור החרדי בישראל. תפקידך להבין מה המשתמש מקליד 
        ולהמיר זאת לחיפוש עלון שבת חרדי אותנטי.
        
        נתוני זמן נוכחיים:
        השבוע: פרשת {ctx['current_parasha']}, שנת {ctx['current_year']}.
        שבוע שעבר: פרשת {ctx['prev_parasha']}, שנת {ctx['prev_year']}.
        
        המשתמש הקליד: "{raw_query}"
        
        חוקי התרגום (מילון חרדי):
        - אם המשתמש מבקש עלון "לילדים", הצע את "נפלאות", "זרע שמשון לילדים", "הבאר" או "סיפורי צדיקים" (אל תציע בשום אופן "אותיות וילדים").
        - המרות שמות רבנים: 
          "קולדצקי" / "הרב קולדצקי" -> "דברי שיח".
          "בידרמן" / "רבי מיילך" -> "באר הפרשה".
          "פינקוס" -> "תפארת שמשון".
          "יצחק יוסף" -> "השיעור השבועי".
        - אם לא נדרשת המרה, השאר את השם שהקליד המשתמש, אך נקה אותו למילות חיפוש מדויקות.

        החזר אך ורק פורמט JSON חוקי וטהור בעל המבנה הבא:
        {{
            "bulletin": "שם העלון המדויק לחיפוש",
            "parasha": "שם הפרשה בעברית (ברירת מחדל: {ctx['current_parasha']})",
            "parasha_en": "שם הפרשה באנגלית (לפי המילון)",
            "year": "שנת ההוצאה המבוקשת ללא גרשיים! (למשל תשפו)"
        }}
        """
        
        try:
            raw_resp = cls._call_gemini_with_fallback(api_key, prompt)
            clean_text = cls._clean_json_output(raw_resp)
            parsed = json.loads(clean_text)
            
            # וידוא שכל השדות קיימים
            if "bulletin" not in parsed: parsed["bulletin"] = raw_query
            if "parasha" not in parsed: parsed["parasha"] = ctx["current_parasha"]
            if "parasha_en" not in parsed: parsed["parasha_en"] = ctx["current_parasha_en"]
            if "year" not in parsed: parsed["year"] = ctx["current_year"]
                
            log.info("NLP Intent Parsed Successfully: %s", parsed)
            return parsed
            
        except Exception as e:
            log.error("NLP Intent Extraction Failed: %s. Reverting to raw query.", e)
            return {
                "bulletin": raw_query, 
                "parasha": ctx["current_parasha"], 
                "parasha_en": ctx["current_parasha_en"], 
                "year": ctx["current_year"]
            }

# ══════════════════════════════════════════════════════════════════
# Search Utilities - שולפי קישורים ומפענחי Redirects
# ══════════════════════════════════════════════════════════════════
class UrlExtractor:
    """מחלקה קריטית לפענוח הקישורים המוסווים של יאהו ובינג"""
    
    @staticmethod
    def extract_real_url(raw_url: str) -> str:
        """
        מוציא את ה-URL האמיתי מתוך ה-Redirect של מנוע החיפוש.
        זה הפתרון לשגיאה שראינו בלוגים (https://r.search.yahoo.com/...).
        """
        try:
            if "r.search.yahoo.com" in raw_url and "RU=" in raw_url:
                # הכתובת האמיתית נמצאת אחרי הפרמטר RU=
                parts = raw_url.split("RU=")
                if len(parts) > 1:
                    # הקישור מסתיים בדרך כלל בפרמטר הבא או בסוף המחרוזת
                    encoded_url = parts[1].split("/RK=")[0]
                    decoded_url = urllib.parse.unquote(encoded_url)
                    log.info("Decoded Yahoo URL -> %s", decoded_url)
                    return decoded_url
                    
            if "duckduckgo.com" in raw_url and "uddg=" in raw_url:
                parsed_url = urllib.parse.urlparse(raw_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                decoded_url = query_params.get("uddg", [raw_url])[0]
                return decoded_url
                
            return raw_url
        except Exception as e:
            log.warning("Failed to extract real URL from %s: %s", raw_url, e)
            return raw_url

# ══════════════════════════════════════════════════════════════════
# Web Scraper - מנוע סריקת האינטרנט
# ══════════════════════════════════════════════════════════════════
class WebScraper:
    """סריקת האינטרנט ואיתור קישורי PDF של עלונים"""
    
    @staticmethod
    def get_query_variations(b: str, p: str, pe: str, y: str) -> list[str]:
        """מייצר וריאציות של חיפוש. מסיר גרשיים מהשנה למניעת שבירת כתובות"""
        safe_y = y.replace('"', '').replace("'", "")
        return [
            f'"{b}" "{p}" {safe_y} filetype:pdf',
            f'עלון שבת "{b}" פרשת {p} {safe_y} pdf',
            f'"{b}" "{pe}" {safe_y} pdf'
        ]

    @staticmethod
    def search_yahoo(query: str) -> list[str]:
        """מנוע מצוין וסלחני לחיפושי PDF ממוכנים"""
        try:
            headers = AppConfig.get_headers()
            r = requests.get(
                "https://search.yahoo.com/search", 
                params={"p": query + " filetype:pdf"}, 
                headers=headers, 
                timeout=10
            )
            urls = re.findall(r'(https?://[^\s"<>\'()]+?\.pdf)', r.text)
            
            # חילוץ הקישורים האמיתיים
            real_urls = [UrlExtractor.extract_real_url(u) for u in urls]
            return list(dict.fromkeys(real_urls))[:4]
        except Exception as e:
            log.warning("Yahoo Scraper failed: %s", e)
            return[]

    @staticmethod
    def search_duckduckgo(query: str) -> list[str]:
        """חיפוש דרך גרסת ה-HTML של DDG כדי למנוע חסימות"""
        try:
            headers = AppConfig.get_headers()
            r = requests.post(
                "https://lite.duckduckgo.com/lite/", 
                data={"q": query}, 
                headers=headers, 
                timeout=10
            )
            urls = re.findall(r'(https?://[^\s"<>\'()]+?\.pdf)', r.text)
            real_urls = [UrlExtractor.extract_real_url(u) for u in urls]
            return list(dict.fromkeys(real_urls))[:4]
        except Exception as e:
            log.warning("DDG Scraper failed: %s", e)
            return[]

    @staticmethod
    def search_haredi_archives(b: str, p: str) -> list[str]:
        """
        חיפוש ממוקד בתוך אתרים חרדיים בולטים:
        לדעת (ladaat.co), בינינו (beinenu.com), ודרשו (dirshu.co.il).
        אלו הם האתרים המרכזיים שמכילים קבצי PDF נקיים!
        """
        safe_bulletin = urllib.parse.quote(b)
        safe_parasha = urllib.parse.quote(p)
        
        # אנחנו משתמשים ב-Yahoo כדי לבצע site-search בתוך ארכיונים אלו
        queries = [
            f'"{b}" "{p}" site:ladaat.co filetype:pdf',
            f'"{b}" "{p}" site:beinenu.com filetype:pdf',
            f'"{b}" "{p}" site:dirshu.co.il filetype:pdf'
        ]
        
        urls =[]
        for q in queries:
            urls.extend(WebScraper.search_yahoo(q))
            
        return list(dict.fromkeys(urls))[:5]

# ══════════════════════════════════════════════════════════════════
# File Handler - הורדה ואימות קבצים
# ══════════════════════════════════════════════════════════════════
class PdfHandler:
    """אחראי על הורדת ה-PDF ואימות התוכן שלו בעזרת ראייה ממוחשבת"""
    
    @staticmethod
    def download_pdf(url: str) -> bytes | None:
        """
        מוריד קובץ בצורה בטוחה (Chunking) כדי למנוע קריסת זיכרון.
        מוודא שהקובץ הוא PDF אותנטי באמצעות Magic Bytes.
        """
        try:
            headers = AppConfig.get_headers()
            head = requests.head(url, headers=headers, timeout=6, allow_redirects=True)
            if head.status_code not in (200, 301, 302):
                return None
            
            content_type = head.headers.get("Content-Type", "").lower()
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                return None
                
            r = requests.get(url, headers=headers, timeout=15, stream=True)
            buf = io.BytesIO()
            
            for chunk in r.iter_content(chunk_size=8192):
                buf.write(chunk)
                if buf.tell() > AppConfig.MAX_FILE_SIZE_BYTES:
                    log.warning("Download aborted. File %s exceeds max size.", url)
                    return None
                    
            data = buf.getvalue()
            
            if data.startswith(AppConfig.PDF_MAGIC) and len(data) > AppConfig.MIN_FILE_SIZE_BYTES:
                return data
                
        except Exception as e:
            log.warning("Download failed for URL %s | Error: %s", url, e)
            
        return None

    @staticmethod
    def validate_content(api_key: str, pdf_bytes: bytes, b: str, p: str, y: str) -> bool:
        """
        השומר בכניסה! (Gatekeeper).
        ג'מיני קורא את ה-PDF כדי לוודא בוודאות מוחלטת שזה העלון הנכון מהשנה הנכונה.
        """
        try:
            genai.configure(api_key=api_key)
            # מודל ה-Flash מומלץ יותר לקריאת מסמכים (OCR) מה-Lite.
            model = genai.GenerativeModel("gemini-2.5-flash")
            
            # לוקחים רק את 1.5MB הראשונים של הקובץ (מספיק לעמוד הראשון והשני)
            sample_bytes = pdf_bytes[:int(1.5 * 1024 * 1024)]
            b64_data = base64.b64encode(sample_bytes).decode()

            # פירוק השנה לוריאציות אפשריות כדי לאפשר קריאה קלה יותר
            display_year = y
            if y == "תשפו": display_year = "תשפ\"ו או תשפו"
            if y == "תשפה": display_year = "תשפ\"ה או תשפה"

            prompt = f"""
            ענה אך ורק במילה אחת בלבד: YES או NO.
            לפניך העמוד הראשון של קובץ PDF. עליך לבדוק האם הקובץ מקיים את *כל* 3 התנאים הבאים:
            
            1. האם העלון משתייך באופן ברור לסדרה, לשם או למחבר: "{b}"?
            2. האם הוא מיועד לפרשת: "{p}"?
            3. חמור מאוד: האם שנת ההוצאה המודפסת בו היא {display_year}? 
               (אם כתוב במפורש שנה ישנה יותר כמו תשפ"ד או תשפ"ג - עליך לענות NO).
            
            אם התנאים מתקיימים - ענה YES. אחרת - ענה NO.
            """
            
            resp = model.generate_content([
                {"mime_type": "application/pdf", "data": b64_data}, 
                prompt
            ])
            
            answer = resp.text.strip().upper()
            log.info("Validation Result for [%s | %s | %s] -> %s", b, p, y, answer)
            
            return answer.startswith("YES")
            
        except Exception as e:
            log.error("Validation API error: %s. Rejecting file to ensure quality.", e)
            # עדיף לדחות קובץ מאשר להחזיר למשתמש עלון לא רלוונטי במקרה של שגיאת API.
            return False 

# ══════════════════════════════════════════════════════════════════
# Search Orchestrator - מנהל החיפוש וה-Concurrency
# ══════════════════════════════════════════════════════════════════
class SearchOrchestrator:
    """המנצח על התזמורת: מנהל את כל תהליכי החיפוש במקביל ובטור"""
    
    @staticmethod
    def search_single_bulletin(api_key: str, b: str, p: str, pe: str, y: str):
        """תהליך חיפוש ליעד אחד (עלון X לפרשה Y בשנה Z)"""
        queries = WebScraper.get_query_variations(b, p, pe, y)
        candidates =[]
        
        for q in queries: 
            candidates += WebScraper.search_yahoo(q)
            candidates += WebScraper.search_duckduckgo(q)
            
        # הוספת חיפוש יעודי בארכיונים החרדיים
        candidates += WebScraper.search_haredi_archives(b, p)
        
        unique_urls = list(dict.fromkeys(candidates))
        log.info("Collected %d unique URLs for target: %s, %s, %s", len(unique_urls), b, p, y)

        for url in unique_urls:
            log.info("Attempting download: %s", url)
            pdf_data = PdfHandler.download_pdf(url)
            
            if pdf_data and PdfHandler.validate_content(api_key, pdf_data, b, p, y):
                # יצירת שם קובץ תקני למערכות הפעלה
                safe_name = f"{b}_{pe}_{y}.pdf"
                safe_name = re.sub(r'[\\/*?:"<>|]', "", safe_name).replace(' ', '_')
                log.info("Successfully found and validated: %s", safe_name)
                return pdf_data, safe_name
                
        return None, None

    @classmethod
    def execute_full_search(cls, api_key: str, raw_query: str) -> dict:
        """הלוגיקה המרכזית: מנתח, מחפש ראשית, ואם נכשל עובר ל-Fallback במקביל"""
        
        today = date.today()
        ctx = JewishCalendar.get_context(today)
        
        # 1. פענוח שפה חופשית
        parsed = NaturalLanguageProcessor.extract_intent(api_key, raw_query, ctx)
        b = parsed.get("bulletin")
        p = parsed.get("parasha")
        pe = parsed.get("parasha_en")
        y = parsed.get("year")
        
        # 2. ניסיון מציאה של יעד המקור (מה שהמשתמש באמת ביקש)
        pdf, filename = cls.search_single_bulletin(api_key, b, p, pe, y)
        
        if pdf:
            return {
                "success": True, 
                "pdf": pdf, 
                "filename": filename, 
                "msg": f"בשורות טובות! מצאתי את הגליון '{b}' לפרשת {p}."
            }
            
        log.info("Primary search failed. Triggering Concurrent Fallback mode.")
        
        # 3. מנגנון Fallback אקטיבי (רב תהליכי)
        options =[]
        fallbacks = [
            # תצורה: (כותרת כפתור, שם עלון, פרשה, פרשה אנגלית, שנה)
            ("משבוע שעבר", b, ctx['prev_parasha'], ctx['prev_parasha_en'], ctx['current_year']),
            ("משנה שעברה", b, p, pe, ctx['prev_year'])
        ]
        
        # הפעלת ThreadPoolExecutor מאפשרת לנו לחפש את שני היעדים החלופיים בו-זמנית!
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(cls.search_single_bulletin, api_key, fb[1], fb[2], fb[3], fb[4]): fb 
                for fb in fallbacks
            }
            
            for future in concurrent.futures.as_completed(futures):
                fb_info = futures[future]
                try:
                    res_pdf, res_fn = future.result()
                    if res_pdf:
                        # אם מצאנו עלון חלופי, נמיר אותו ל-Base64 ונצרף לאופציות!
                        options.append({
                            "title": f"פרשת {fb_info[2]} {fb_info[0]}",
                            "filename": res_fn,
                            "pdf_b64": base64.b64encode(res_pdf).decode()
                        })
                except Exception as e:
                    log.error("Concurrent Fallback Thread Error for %s: %s", fb_info[0], e)

        if len(options) > 0:
            return {
                "success": False, 
                "fallback": True, 
                "msg": f"העלון '{b}' לפרשת {p} השנה עדיין לא הועלה. אבל חיפשתי עמוק בארכיון והבאתי לך אלטרנטיבות חלופיות שמוכנות מיד להורדה:",
                "options": options
            }
            
        return {
            "success": False, 
            "error": f"מצטער, העלון '{b}' לפרשת {p} לא נמצא בשום מקום ברשת. גם חיפוש בארכיוני שבוע שעבר ושנה שעברה לא העלה תוצאות."
        }

# ══════════════════════════════════════════════════════════════════
# Vercel Server Handler - טיפול בתקשורת שרת-לקוח
# ══════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):
    """מטפל בבקשות HTTP (מותאם לסביבת Vercel Serverless)"""
    
    def _apply_cors(self):
        """מאפשר תקשורת פתוחה ובטוחה מול הדפדפן"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """בקשת Preflight של הדפדפן. חייבים להשיב בסטטוס 200."""
        self.send_response(200)
        self._apply_cors()
        self.end_headers()
        
    def do_GET(self):
        """
        פותר את השגיאה של Error 501 (Method Not Allowed).
        מספק תשובה ידידותית במקרה שמשתמש מנסה לפתוח את הקישור ישירות בדפדפן.
        """
        self._send_json_response(200, {
            "success": True, 
            "message": "AlonBot Enterprise API is actively running. Please use POST method to submit a search query."
        })

    def do_POST(self):
        """קולט את בקשת החיפוש, מפעיל את מנוע ה-Orchestrator ומחזיר תוצאות"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            body = json.loads(raw_body)
        except Exception as e:
            log.error("Failed to parse incoming JSON request: %s", e)
            return self._send_json_response(200, {
                "success": False, 
                "error": "מבנה הבקשה שגוי (JSON Parse Error)."
            })

        api_key = (body.get("api_key") or "").strip()
        query = (body.get("query") or "").strip()

        if not api_key:
            return self._send_json_response(200, {"success": False, "error": "מפתח API חסר. אנא הוסף בהגדרות החשבון."})
        if not query:
            return self._send_json_response(200, {"success": False, "error": "נא להקליד מילת חיפוש או שם עלון."})

        try:
            # הפעלת שרשרת החיפוש הראשית
            result = SearchOrchestrator.execute_full_search(api_key, query)
        except Exception as e:
            log.exception("Critical unexpected error in Orchestrator")
            return self._send_json_response(200, {"success": False, "error": f"שגיאת מערכת פנימית: {e}"})

        # בניית התשובה הסופית.
        # אנו תמיד מחזירים 200 OK ברמת פרוטוקול HTTP, כדי למנוע את שגיאת ה-404 האדומה שצצה בקונסול!
        # הסטטוס הלוגי מנוהל בתוך האובייקט המוחזר (success = true/false).
        
        if result.get("success"):
            self._send_json_response(200, {
                "success": True,
                "message": result["msg"],
                "filename": result["filename"],
                "pdf_b64": base64.b64encode(result["pdf"]).decode()
            })
        elif result.get("fallback"):
            self._send_json_response(200, {
                "success": False,
                "fallback": True,
                "message": result["msg"],
                "options": result["options"]
            })
        else:
            self._send_json_response(200, {
                "success": False, 
                "error": result["error"]
            })

    def _send_json_response(self, status_code: int, response_dict: dict):
        """אורז את התשובה לפורמט JSON תקני ומשגר אותה בחזרה ללקוח"""
        response_bytes = json.dumps(response_dict, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._apply_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)
