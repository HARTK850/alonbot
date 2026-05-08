// יש לעדכן את הכתובת הזו אחרי הפריסה ב-Vercel
const BACKEND_URL = 'https://YOUR-VERCEL-APP-NAME.vercel.app/api/search'; 

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const statusArea = document.getElementById('statusArea');
    const statusText = document.getElementById('statusText');
    const errorArea = document.getElementById('errorArea');
    const errorText = document.getElementById('errorText');
    const successArea = document.getElementById('successArea');

    // מאפשר חיפוש בלחיצה על Enter
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });

    searchBtn.addEventListener('click', performSearch);

    async function performSearch() {
        const query = searchInput.value.trim();
        if (!query) return;

        // איפוס ממשק
        hideAllMessages();
        searchBtn.disabled = true;
        statusArea.classList.remove('hidden');
        statusText.innerText = "מפענח את הבקשה בעזרת Gemini...";

        try {
            // שליחת בקשה לשרת Vercel שלנו
            const response = await fetch(`${BACKEND_URL}?q=${encodeURIComponent(query)}`);
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || "אירעה שגיאה בחיפוש הקובץ");
            }

            statusText.innerText = "מוריד את קובץ ה-PDF למכשיר שלך...";

            // קבלת הקובץ עצמו כ-Blob
            const blob = await response.blob();
            
            // יצירת מנגנון הורדה ישירה ללא פתיחת לשונית חדשה
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            
            // יצירת שם קובץ דינמי
            const fileName = `alon_${query.replace(/\s+/g, '_')}_${new Date().getTime()}.pdf`;
            a.download = fileName;
            
            document.body.appendChild(a);
            a.click(); // טריגר להורדה
            
            // ניקוי
            window.URL.revokeObjectURL(downloadUrl);
            document.body.removeChild(a);

            // הצגת הצלחה
            hideAllMessages();
            successArea.classList.remove('hidden');

        } catch (error) {
            hideAllMessages();
            errorArea.classList.remove('hidden');
            errorText.innerText = error.message;
        } finally {
            searchBtn.disabled = false;
        }
    }

    function hideAllMessages() {
        statusArea.classList.add('hidden');
        errorArea.classList.add('hidden');
        successArea.classList.add('hidden');
    }
});
