const google = require('google-this');
const cheerio = require('cheerio');

// פונקציית עזר להורדה מאובטחת של הקובץ (Scxxxxxx/xxxxx)
async function secureFetch(url) {
    const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*;q=0.9',
        'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7',
    };
    return await fetch(url, { headers, redirect: 'follow' });
}

export default async function handler(req, res) {
    // מניעת בעיות CORS
    if (req.method === 'OPTIONS') return res.status(200).end();

    const userQuery = req.query.q;
    // שליפת המפתח שנשלח מהדפדפן של המשתמש!
    const userApiKey = req.headers['x-gemini-api-key'];

    if (!userQuery) return res.status(400).json({ error: 'חסר פרמטר חיפוש.' });
    if (!userApiKey || userApiKey.length < 20) {
        return res.status(401).json({ error: 'מפתח ה-API של Gemini חסר או שגוי. אנא עדכן בהגדרות.' });
    }

    try {
        console.log(`[ALON-BOT API] מתחיל חיפוש עבור: "${userQuery}"`);

        // ==========================================
        // שלב 1: אינטראקציה עם Gemini באמצעות המפתח של המשתמש
        // מודל מוקפד: gemini-3.1-flash-lite-preview
        // ==========================================
        const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key=${userApiKey}`;
        
        const prompt = `
            המשתמש מחפש עלון שבת בשם: "${userQuery}".
            תפקידך לתקן שגיאות כתיב אם ישנן, ולהחזיר אך ורק את מחרוזת החיפוש המדויקת למנוע חיפוש, 
            במבנה הזה: שם העלון המדויק + "pdf" + "עלון שבת".
            לדוגמה: "שיחת השבוע pdf עלון שבת".
            אל תחזיר אף טקסט אחר מלבד שורת החיפוש!
        `;

        const geminiRes = await fetch(geminiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
        });

        const geminiData = await geminiRes.json();
        
        // בדיקת שגיאות מה-API (כמו מפתח לא תקין או חריגה ממכסה)
        if (geminiData.error) {
            console.error("[Gemini Error]", geminiData.error);
            return res.status(401).json({ error: "החיבור ל-Gemini נכשל. ודא שהמפתח שלך תקין ויש לו הרשאות." });
        }
        if (!geminiData.candidates || !geminiData.candidates[0].content) {
            throw new Error("מבנה תשובה לא צפוי מ-Gemini.");
        }
        
        const optimizedQuery = geminiData.candidates[0].content.parts[0].text.trim().replace(/"/g, '');
        console.log(`[ALON-BOT API] שאילתה חכמה לאחר Gemini: "${optimizedQuery}"`);

        // ==========================================
        // שלב 2: סריקת הרשת בעזרת ספריות קוד פתוח מקומיות בלבד
        // (ללא מפתחות של Google Search API!)
        // ==========================================
        let finalPdfUrl = null;

        try {
            // ניסיון ראשי: חבילת google-this
            const options = { page: 0, safe: false, additional_params: { hl: 'iw' } };
            const searchResponse = await google.search(`${optimizedQuery} ext:pdf`, options);
            
            for (const result of searchResponse.results) {
                if (result.url.toLowerCase().endsWith('.pdf') || result.title.toUpperCase().includes('PDF')) {
                    finalPdfUrl = result.url;
                    break;
                }
            }
        } catch (e) {
            console.log(`[ALON-BOT API] אזהרה: google-this נחסם, עובר לסריקת גיבוי (DuckDuckGo/Cheerio)...`);
        }

        // ניסיון גיבוי: Web Scraping פשוט מול DuckDuckGo
        if (!finalPdfUrl) {
            const duckUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(optimizedQuery + ' filetype:pdf')}`;
            const duckRes = await secureFetch(duckUrl);
            
            if (duckRes.ok) {
                const html = await duckRes.text();
                const $ = cheerio.load(html);
                
                $('.result__url').each((i, elem) => {
                    const link = $(elem).attr('href');
                    if (link && link.toLowerCase().includes('.pdf')) {
                        finalPdfUrl = link.startsWith('//') ? 'https:' + link : link;
                        return false; // Break loop
                    }
                });
            }
        }

        if (!finalPdfUrl) {
            throw new Error(`לצערי לא מצאתי קובץ PDF זמין ברשת עבור "${userQuery}". נסה שם מדויק יותר.`);
        }

        console.log(`[ALON-BOT API] הקישור אותר: ${finalPdfUrl}`);

        // ==========================================
        // שלב 3: הורדת הקובץ לשרת והזרמתו בחזרה למשתמש
        // דרישת חובה: ללא העברת המשתמש לאתרים חיצוניים!
        // ==========================================
        let pdfBuffer;
        try {
            const pdfDownloadRes = await secureFetch(finalPdfUrl);
            if (!pdfDownloadRes.ok) throw new Error(`השרת המאחסן השיב בשגיאה ${pdfDownloadRes.status}.`);
            
            // וידוא שאנחנו לא מורידים בטעות דף HTML עם הודעת חסימה
            const contentType = pdfDownloadRes.headers.get('content-type') || '';
            if (!contentType.includes('pdf') && !contentType.includes('octet-stream')) {
                // לפעמים שרתים מסתירים את התוכן, ננסה לבדוק גודל
                const buffer = Buffer.from(await pdfDownloadRes.arrayBuffer());
                if (buffer.length < 5000) throw new Error("הקובץ קטן מדי ואינו PDF תקין.");
                pdfBuffer = buffer;
            } else {
                pdfBuffer = Buffer.from(await pdfDownloadRes.arrayBuffer());
            }

        } catch (downloadErr) {
            console.error("[Download Error]", downloadErr);
            throw new Error("הקובץ אותר ברשת, אך השרת החיצוני סירב לאפשר לבוט להוריד אותו (חסימת אבטחה).");
        }

        console.log(`[ALON-BOT API] הצלחה! הקובץ מוכן להורדה. גודל: ${(pdfBuffer.length / 1024 / 1024).toFixed(2)} MB`);

        // שליחת ה-Buffer כקובץ אמיתי למשתמש
        res.setHeader('Content-Type', 'application/pdf');
        res.setHeader('Content-Disposition', `attachment; filename="Shabbat_Alon.pdf"`);
        res.setHeader('Cache-Control', 'no-store'); // מניעת מטמון מכיוון שהקובץ תלוי במפתח הלקוח

        return res.status(200).send(pdfBuffer);

    } catch (error) {
        console.error("[ALON-BOT API Fatal Error]", error.message);
        return res.status(500).json({ error: error.message || "אירעה שגיאה לא ידועה בשרת." });
    }
}
