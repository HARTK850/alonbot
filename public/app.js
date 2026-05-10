const API_BASE = "/api";
const HIST_KEY = "alonbot_history";
let history =[];

document.addEventListener("DOMContentLoaded", () => {
    initParticles();
    loadKey();
    loadHist();
    renderHist();
    
    // Setup Modal
    const modal = document.getElementById('settingsModal');
    document.getElementById('openSettingsBtn').onclick = () => modal.classList.remove('hidden');
    document.getElementById('closeModalBtn').onclick = () => modal.classList.add('hidden');
    document.getElementById('togglePasswordBtn').onclick = togglePassword;
    document.getElementById('saveApiKeyBtn').onclick = saveKey;
});

// --- UI Actions ---
function setInput(text) {
    document.getElementById("botInput").value = text;
    doSearch();
}

function showToast(msg) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<i class="fas fa-check-circle"></i> ${msg}`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function togglePassword() {
    const input = document.getElementById('apiKeyInput');
    const icon = document.querySelector('#togglePasswordBtn i');
    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'fas fa-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'fas fa-eye';
    }
}

// --- API Key ---
function loadKey() {
    const k = sessionStorage.getItem("alonbot_key");
    if (k) document.getElementById("apiKeyInput").value = k;
}
function saveKey() {
    const k = document.getElementById("apiKeyInput").value.trim();
    if (!k) { alert("יש להזין מפתח תחילה"); return; }
    sessionStorage.setItem("alonbot_key", k);
    document.getElementById('settingsModal').classList.add('hidden');
    showToast("המפתח נשמר בהצלחה!");
}

// --- Search Logic ---
function base64ToBlobUrl(base64Data, contentType = 'application/pdf') {
    const byteCharacters = atob(base64Data);
    const byteArrays =[];
    for (let offset = 0; offset < byteCharacters.length; offset += 512) {
        const slice = byteCharacters.slice(offset, offset + 512);
        const byteNumbers = new Array(slice.length);
        for (let i = 0; i < slice.length; i++) { byteNumbers[i] = slice.charCodeAt(i); }
        byteArrays.push(new Uint8Array(byteNumbers));
    }
    return URL.createObjectURL(new Blob(byteArrays, { type: contentType }));
}

async function doSearch() {
    const apiKey = document.getElementById("apiKeyInput").value.trim();
    const query = document.getElementById("botInput").value.trim();

    if (!apiKey) {
        document.getElementById('settingsModal').classList.remove('hidden');
        return;
    }
    if (!query) return;

    setStatus('loading', 'מנתח את בקשתך ומחפש במאגרי העלונים...');
    const btn = document.getElementById('actionBtn');
    btn.disabled = true;

    try {
        const r = await fetch(API_BASE + "/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: apiKey, query: query })
        });
        const data = await r.json();

        if (data.success && data.pdf_b64) {
            sessionStorage.setItem("alonbot_key", apiKey);
            const blobUrl = base64ToBlobUrl(data.pdf_b64);
            
            // אוטומטית פותח את ההורדה
            const link = document.createElement('a');
            link.href = blobUrl;
            link.download = data.filename || "alon.pdf";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            setStatus('success', data.message || "העלון נמצא בהצלחה וההורדה מתחילה!");
            addHist(data.filename, blobUrl);
            showToast("ההורדה החלה!");
        } else {
            // טיפול חכם בשגיאות עם הצעות חלופיות!
            setStatus('error', data.error || "לא מצאנו את העלון המבוקש.");
            if (data.suggestions && data.suggestions.length > 0) {
                showSuggestions(data.suggestions);
            }
        }
    } catch (e) {
        setStatus('error', "שגיאת תקשורת. בדוק את חיבור האינטרנט שלך.");
    } finally {
        btn.disabled = false;
    }
}

function setStatus(type, msg) {
    const box = document.getElementById('botStatusArea');
    const icon = document.getElementById('botIcon');
    const spinner = document.getElementById('loadingSpinner');
    const text = document.getElementById('botMessage');
    const suggestions = document.getElementById('suggestionsArea');
    
    box.classList.remove('hidden', 'error', 'success');
    suggestions.classList.add('hidden');
    suggestions.innerHTML = '';
    
    if (type === 'loading') {
        icon.classList.add('hidden');
        spinner.classList.remove('hidden');
    } else {
        spinner.classList.add('hidden');
        icon.classList.remove('hidden');
        box.classList.add(type);
        if (type === 'error') icon.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
        if (type === 'success') icon.innerHTML = '<i class="fas fa-check-circle"></i>';
    }
    text.textContent = msg;
}

function showSuggestions(suggestionsArray) {
    const container = document.getElementById('suggestionsArea');
    container.innerHTML = '<span style="width:100%; font-size:0.85rem; color:var(--text-muted);">אולי התכוונת ל:</span>';
    
    suggestionsArray.forEach(sug => {
        const span = document.createElement('span');
        span.className = 'tag suggestion-tag';
        span.textContent = sug;
        span.onclick = () => setInput(sug);
        container.appendChild(span);
    });
    container.classList.remove('hidden');
}

// --- History ---
function loadHist() {
    try { history = JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); } catch { history =[]; }
}
function addHist(filename, url) {
    history.unshift({ name: filename, url: url, date: new Date().toLocaleDateString('he-IL') });
    localStorage.setItem(HIST_KEY, JSON.stringify(history.slice(0, 20).map(h=>({...h, url:null}))));
    renderHist();
}
function clearHist() {
    history =[];
    localStorage.removeItem(HIST_KEY);
    renderHist();
}
function renderHist() {
    const list = document.getElementById("historyList");
    const clearBtn = document.getElementById("clearHistoryBtn");
    list.innerHTML = "";
    
    if (!history.length) {
        list.innerHTML = '<div class="empty-history">אין היסטוריית הורדות</div>';
        clearBtn.classList.add('hidden');
        return;
    }
    
    clearBtn.classList.remove('hidden');
    history.forEach(h => {
        const item = document.createElement('div');
        item.className = 'history-item';
        item.innerHTML = `<div><i class="fas fa-file-pdf"></i> ${h.name.replace('.pdf','')}</div> 
                          <span style="font-size:0.75rem; color:#888;">${h.date}</span>`;
        // מאפשר הורדה חוזרת במידה וה-URL עדיין פעיל בסשן הנוכחי
        if (h.url) {
            item.onclick = () => {
                const a = document.createElement('a'); a.href = h.url; a.download = h.name; a.click();
            };
        }
        list.appendChild(item);
    });
}

// --- Particles Background Animation ---
function initParticles() {
    const canvas = document.getElementById('particleCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    
    let particles =[];
    for(let i=0; i<80; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            vx: (Math.random() - 0.5) * 0.5,
            vy: (Math.random() - 0.5) * 0.5,
            radius: Math.random() * 2 + 1
        });
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy;
            if(p.x < 0 || p.x > canvas.width) p.vx *= -1;
            if(p.y < 0 || p.y > canvas.height) p.vy *= -1;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0, 206, 201, 0.3)';
            ctx.fill();
        });
        requestAnimationFrame(animate);
    }
    animate();
    
    window.addEventListener('resize', () => {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    });
}
