export default async function handler(req, res) {
    // טיפול בבקשות preflight של CORS
    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    const userQuery = req.query.q;

    if (!userQuery) {
        return res.status(400).json({ error: 'חסר פרמטר חיפוש' });
    }

    try {
        console.log(`[1] מתחיל עיבוד עבור: "${userQuery}"`);

        // ==========================================
        // שלב 1: שימוש ב-Gemini להבנת הבקשה ויצירת שאילתת חיפוש מדויקת
        // דרישה חובה: שימוש במודל gemini-3.1-flash-lite-preview
        // ==========================================
        const geminiApiKey = process.env.GEMINI_API_KEY;
        if (!geminiApiKey) throw new Error("חסר מפתח API של Gemini בשרת");

        const prompt = `
            המשתמש מחפש עלון שבת (Jewish Sabbath Newsletter) ורוצה להוריד קובץ PDF שלו.
            הבקשה של המשתמש: "${userQuery}"
            
            תפקידך:
            1. זהה שגיאות כתיב אם ישנן ותקן אותן (למשל: "שיחת השבו" -> "שיחת השבוע").
            2. אם המשתמש ביקש בקשה כללית (למשל "עלון לילדים"), בחר את העלון המוכר ביותר שעונה להגדרה (למשל "זרע שמשון לילדים" או "אותיות").
            3. החזר *אך ורק* מחרוזת טקסט אחת שהיא שאילתת החיפוש הטובה ביותר לגוגל שתמצא את העלון של השבת האחרונה בפורמט PDF.
            הוסף לשאילתה את המילה "עלון" ואת "filetype:pdf".
            
            אל תחזיר שום טקסט אחר, רק את שורת החיפוש.
        `;

        const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key=${geminiApiKey}`;
        
        const geminiResponse = await fetch(geminiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{ parts: [{ text: prompt }] }]
            })
        });

        const geminiData = await geminiResponse.json();
        if (!geminiData.candidates || !geminiData.candidates[0].content) {
            throw new Error("שגיאה בפענוח הבקשה מול Gemini");
        }

        const exactSearchQuery = geminiData.candidates[0].content.parts[0].text.trim();
        console.log(`[2] שאילתת חיפוש שנוצרה ע"י מודל 3.1-flash-lite-preview: "${exactSearchQuery}"`);

        // ==========================================
        // שלב 2: חיפוש בגוגל מציאת ה-PDF (Google Custom Search API)
        // ==========================================
        const googleApiKey = process.env.GOOGLE_SEARCH_API_KEY;
        const googleCx = process.env.GOOGLE_CX_ID;
        
        if (!googleApiKey || !googleCx) throw new Error("חסרים מפתחות חיפוש של גוגל בשרת");

        const searchApiUrl = `https://www.googleapis.com/customsearch/v1?key=${googleApiKey}&cx=${googleCx}&q=${encodeURIComponent(exactSearchQuery)}&num=3`;
        
        const searchRes = await fetch(searchApiUrl);
        const searchData = await searchRes.json();

        if (!searchData.items || searchData.items.length === 0) {
            throw new Error("לא נמצא קובץ PDF מתאים לעלון המבוקש.");
        }

        // חילוץ הקישור הראשון שהוא אכן PDF
        let pdfUrl = null;
        for (const item of searchData.items) {
            if (item.link.toLowerCase().endsWith('.pdf') || (item.mime && item.mime === 'application/pdf')) {
                pdfUrl = item.link;
                break;
            }
        }

        if (!pdfUrl) {
            // Fallback לתוצאה הראשונה גם אם גוגל לא זיהה בוודאות שזה PDF לפי הסיומת
            pdfUrl = searchData.items[0].link; 
        }

        console.log(`[3] נמצא קובץ: ${pdfUrl}`);

        // ==========================================
        // שלב 3: הורדת ה-PDF לשרת (Vercel) והחזרתו ל-Frontend
        // חובה: אסור להחזיר קישור! מחזירים את הקובץ עצמו כ-Stream/Buffer
        // ==========================================
        
        const pdfResponse = await fetch(pdfUrl, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } // מניעת חסימות בוטים
        });

        if (!pdfResponse.ok) {
            throw new Error("נמצא קובץ אך השרת המאחסן סירב להורדה.");
        }

        const pdfBuffer = await pdfResponse.arrayBuffer();

        console.log(`[4] הקובץ הורד בהצלחה לשרת, שולח לקליינט. גודל: ${pdfBuffer.byteLength} bytes`);

        // הגדרת Headers להחזרת קובץ בינארי
        res.setHeader('Content-Type', 'application/pdf');
        res.setHeader('Content-Disposition', `attachment; filename="shabbat_newsletter.pdf"`);
        res.setHeader('Cache-Control', 's-maxage=86400'); // קאש בשרת Vercel ל-24 שעות

        // שליחת הקובץ עצמו למשתמש!
        return res.status(200).send(Buffer.from(pdfBuffer));

    } catch (error) {
        console.error("Error:", error);
        return res.status(500).json({ error: error.message || "אירעה שגיאה פנימית בשרת" });
    }
}
