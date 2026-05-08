const google = require('google-this');
const cheerio = require('cheerio');

async function secureFetch(url) {
    const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*;q=0.9',
        'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8',
    };
    return await fetch(url, { headers, redirect: 'follow' });
}

export default async function handler(req, res) {
    // הגדרות CORS פנימיות
    res.setHeader('Access-Control-Allow-Credentials', true);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'x-gemini-api-key, Content-Type');

    if (req.method === 'OPTIONS') return res.status(200).end();

    const userQuery = req.query.q;
    const userApiKey = req.headers['x-gemini-api-key'];

    if (!userQuery) return res.status(400).json({ error: 'חסר פרמטר חיפוש.' });
    if (!userApiKey || userApiKey.length < 20) {
        return res.status(401).json({ error: 'מפתח ה-API של Gemini חסר או שגוי.' });
    }

    try {
        console.log(`[Backend] Searching for: "${userQuery}"`);

        // 1. קריאה ל-Gemini עם המודל המבוקש בדיוק
        const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key=${userApiKey}`;
        const prompt = `
            המשתמש מחפש עלון שבת בשם: "${userQuery}".
            תקן שגיאות כתיב והחזר רק מחרוזת חיפוש במבנה: שם העלון המדויק + "pdf" + "עלון שבת".
            אל תחזיר אף מילה נוספת!
        `;

        const geminiRes = await fetch(geminiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] })
        });

        const geminiData = await geminiRes.json();
        if (geminiData.error) return res.status(401).json({ error: "חיבור ל-Gemini נכשל. ודא שהמפתח תקין." });
        
        const optimizedQuery = geminiData.candidates[0].content.parts[0].text.trim().replace(/"/g, '');
        
        // 2. חיפוש באינטרנט באמצעות הספריות בלבד
        let finalPdfUrl = null;
        try {
            const options = { page: 0, safe: false, additional_params: { hl: 'iw' } };
            const searchResponse = await google.search(`${optimizedQuery} ext:pdf`, options);
            for (const result of searchResponse.results) {
                if (result.url.toLowerCase().endsWith('.pdf') || result.title.toUpperCase().includes('PDF')) {
                    finalPdfUrl = result.url; break;
                }
            }
        } catch (e) {
            console.log("Google-this blocked, switching to Cheerio/DuckDuckGo...");
        }

        if (!finalPdfUrl) {
            const duckUrl = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(optimizedQuery + ' filetype:pdf')}`;
            const duckRes = await secureFetch(duckUrl);
            if (duckRes.ok) {
                const $ = cheerio.load(await duckRes.text());
                $('.result__url').each((i, elem) => {
                    const link = $(elem).attr('href');
                    if (link && link.toLowerCase().includes('.pdf')) {
                        finalPdfUrl = link.startsWith('//') ? 'https:' + link : link; return false;
                    }
                });
            }
        }

        if (!finalPdfUrl) throw new Error("לא נמצא קובץ PDF ברשת.");

        // 3. הורדה והעברה חזרה ללקוח (ללא הפניה החוצה)
        const pdfDownloadRes = await secureFetch(finalPdfUrl);
        if (!pdfDownloadRes.ok) throw new Error("השרת המאחסן סירב לאפשר את ההורדה.");

        const pdfBuffer = Buffer.from(await pdfDownloadRes.arrayBuffer());
        if (pdfBuffer.length < 5000) throw new Error("הקובץ שנמצא אינו PDF תקין.");

        res.setHeader('Content-Type', 'application/pdf');
        res.setHeader('Content-Disposition', `attachment; filename="Shabbat_Alon.pdf"`);
        return res.status(200).send(pdfBuffer);

    } catch (error) {
        console.error(error);
        return res.status(500).json({ error: error.message || "שגיאה בשרת." });
    }
}
