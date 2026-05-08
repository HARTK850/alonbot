const google = require('google-this');
const cheerio = require('cheerio');

// פונקציית העזר לביצוע פניות HTTP מתקדמות לדפדפן כדי לא להיחסם
async function secureFetch(url) {
    const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7',
    };
    return await fetch(url, { headers, redirect: 'follow' });
}

export default async function handler(req, res) {
    if (req.method === 'OPTIONS') return res.status(200).end();

    const userQuery = req.query.q;
    if (!userQuery) return res.status(400).json({ error: 'לא הוזן שם של עלון לחיפוש.' });

    try {
        console.log(`[ALON-BOT] מתחיל טיפול בבקשה: "${userQuery}"`);

        // ==========================================
        // 1. שימוש במודל Gemini בדיוק לפי הדרישה: gemini-3.1-flash-lite-preview
        // ==========================================
        const geminiApiKey = process.env.GEMINI_API_KEY;
        if (!geminiApiKey) throw new Error("מפתח Gemini API חסר בשרת Vercel.");

        const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key=${geminiApiKey}`;
        
        const prompt = `
            המשתמש מחפש עלון שבת: "${userQuery}".
            תפקידך להבין לאיזה עלון בדיוק הוא התכוון, לתקן שגיאות כתיב, ולהחזיר אך ורק את המחרוזת המדויקת הבאה:
            שם העלון המדויק + "pdf" + "עלון שבת".
            לדוגמה, אם הקליד "שיחת השבו", תחזיר: "שיחת השבוע pdf עלון שבת".
            אל תחזיר אף מילה נוספת מעבר לשורת החיפוש!
        `;

        const geminiRes = await fetch(geminiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
        });

        const geminiData = await geminiRes.json();
        if (!geminiData.candidates) throw new Error("Gemini לא הצליח לפענח את הבקשה.");
        
        const optimizedQuery = geminiData.candidates[0].content.parts[0].text.trim().replace(/"/g, '');
        console.log(`[ALON-BOT] שאילתה חכמה לאחר עיבוד: "${optimizedQuery}"`);

        // ==========================================
        // 2. חיפוש ברשת באמצעות חבילות NPM בלבד (ללא מפתחות של גוגל!)
        // מנגנון כפול להבטחת אמינות: קודם Google-This ואז DuckDuckGo Scraper
        // ==========================================
        let finalPdfUrl = null;

        try {
            // מנגנון א': חיפוש דרך חבילת google-this
            const options = { page: 0, safe: false, parse_ads: false, additional_params: { hl: 'iw' } };
            const searchResponse = await google.search(`${optimizedQuery} ext:pdf`, options);
            
            for (const result of searchResponse.results) {
                if (result.url.toLowerCase().endsWith('.pdf') || result.title.includes('PDF')) {
                    finalPdfUrl = result.url;
                    break;
                }
            }
        } catch (e) {
            console.log(`[ALON-BOT] ספריית גוגל נחסמה, עובר לסריקת גיבוי (DuckDuckGo)...`);
        }

        // מנגנון ב': גיבוי Scraper עצמאי לחלוטין מול DuckDuckGo
        if (!finalPdfUrl) {
            const duckUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(optimizedQuery + ' filetype:pdf')}`;
            const duckRes = await secureFetch(duckUrl);
            
            if (duckRes.ok) {
                const html = await duckRes.text();
                const $ = cheerio.load(html);
                
                $('.result__url').each((i, elem) => {
                    const link = $(elem).attr('href');
                    if (link && link.includes('.pdf')) {
                        finalPdfUrl = link.startsWith('//') ? 'https:' + link : link;
                        return false; // עוצר את הלולאה
                    }
                });
            }
        }

        if (!finalPdfUrl) {
            throw new Error(`סליחה, הבוט סרק את הרשת אך לא מצא קובץ PDF עדכני עבור "${userQuery}".`);
        }

        console.log(`[ALON-BOT] בינגו! נמצא קישור לקובץ: ${finalPdfUrl}`);

        // ==========================================
        // 3. הורדת ה-PDF בפועל אל השרת והחזרתו כקובץ ללקוח
        // (אסור לתת למשתמש קישור לאתר חיצוני!)
        // ==========================================
        
        let pdfBuffer;
        try {
            const pdfDownloadRes = await secureFetch(finalPdfUrl);
            if (!pdfDownloadRes.ok) throw new Error("השרת המאחסן את העלון דחה את ההורדה.");
            
            // בדיקת תקינות התוכן (לוודא שזה באמת PDF ולא דף חסימה)
            const contentType = pdfDownloadRes.headers.get('content-type');
            if (contentType && !contentType.includes('pdf') && !contentType.includes('application/octet-stream')) {
                throw new Error("הקובץ שנמצא אינו בפורמט PDF תקין.");
            }

            const arrayBuffer = await pdfDownloadRes.arrayBuffer();
            pdfBuffer = Buffer.from(arrayBuffer);
            
            if (pdfBuffer.length < 1000) throw new Error("קובץ ה-PDF שהורד ריק או פגום.");

        } catch (downloadErr) {
            console.error(downloadErr);
            throw new Error("הבוט מצא את העלון, אך השרת החיצוני סירב להעביר את הקובץ.");
        }

        console.log(`[ALON-BOT] ה-PDF נטען בהצלחה לשרת. גודל: ${(pdfBuffer.length / 1024 / 1024).toFixed(2)} MB. שולח למשתמש...`);

        // החזרת הקובץ ישירות כהורדה מאובטחת מהשרת שלנו
        res.setHeader('Content-Type', 'application/pdf');
        res.setHeader('Content-Disposition', `attachment; filename="AlonBot_Shabbat.pdf"`);
        res.setHeader('Cache-Control', 's-maxage=3600'); 

        return res.status(200).send(pdfBuffer);

    } catch (error) {
        console.error("[ALON-BOT] שגיאה:", error.message);
        return res.status(500).json({ error: error.message || "אירעה תקלה פנימית במנועי הבוט." });
    }
}
