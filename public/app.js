const API_BASE = "/api";
const HIST_KEY = "alonbot_history";
let history =[];

document.addEventListener("DOMContentLoaded", () => {
    initParticles();
    loadKey();
    loadHist();
    renderHist();
    
    const modal = document.getElementById('settingsModal');
    document.getElementById('openSettingsBtn').onclick = () => modal.classList.remove('hidden');
    document.getElementById('closeModalBtn').onclick = () => modal.classList.add('hidden');
    document.getElementById('togglePasswordBtn').onclick = togglePassword;
    document.getElementById('saveApiKeyBtn').onclick = saveKey;
});

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

function triggerDownload(blobUrl, filename) {
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename || "alon.pdf";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast("ההורדה החלה!");
    addHist(filename, blobUrl);
}

async function doSearch() {
    const apiKey = document.getElementById("apiKeyInput").value.trim();
    const query = document.getElementById("botInput").value.trim();

    if (!apiKey) {
        document.getElementById('settingsModal').classList.remove('hidden');
        return;
    }
    if (!query) return;

    setStatus('loading', 'מנתח את בקשתך, מחפש ומוודא תקינות (עלול לקחת כמה שניות)...');
    const btn = document.getElementById('actionBtn');
    btn.disabled = true;

    try {
        const r = await fetch(API_BASE + "/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: apiKey, query: query })
        });
        const data = await r.json();

        sessionStorage.setItem("alonbot_key", apiKey);

        if (data.success && data.pdf_b64) {
            const blobUrl = base64ToBlobUrl(data.pdf_b64);
            triggerDownload(blobUrl, data.filename);
            setStatus('success', data.message || "העלון נמצא בהצלחה וההורדה מתחילה!");
            
        } else if (data.fallback && data.options && data.options.length > 0) {
            setStatus('error', data.message);
            showFallbackOptions(data.options);
        } else {
            setStatus('error', data.error || "לא מצאנו את העלון, וגם לא בארכיון.");
        }
    } catch (e) {
        setStatus('error', "שגיאת תקשורת. השרת עמוס או שיש בעיית אינטרנט.");
    } finally {
        btn.disabled = false;
    }
}

function setStatus(type, msg) {
    const box = document.getElementById('botStatusArea');
    const icon = document.getElementById('botIcon');
    const spinner = document.getElementById('loadingSpinner');
    const text = document.getElementById('botMessage');
    const fallbackArea = document.getElementById('fallbackArea');
    
    box.classList.remove('hidden', 'error', 'success');
    fallbackArea.classList.add('hidden');
    document.getElementById('fallbackButtons').innerHTML = '';
    
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

function showFallbackOptions(options) {
    const area = document.getElementById('fallbackArea');
    const container = document.getElementById('fallbackButtons');
    
    options.forEach(opt => {
        const btn = document.createElement('button');
        btn.className = 'primary-btn';
        btn.style.fontSize = '0.9rem';
        btn.style.padding = '10px 20px';
        btn.innerHTML = `<i class="fas fa-download"></i> ${opt.title}`;
        
        btn.onclick = () => {
            const blobUrl = base64ToBlobUrl(opt.pdf_b64);
            triggerDownload(blobUrl, opt.filename);
        };
        container.appendChild(btn);
    });
    
    area.classList.remove('hidden');
}

// --- History (FIXED CRASH BUG) ---
function loadHist() {
    try { 
        history = JSON.parse(localStorage.getItem(HIST_KEY) || "[]");
        // תיקון אוטומטי למקרה של היסטוריה פגומה מגרסאות קודמות
        history = history.filter(h => h && (h.name || h.filename || h.bulletin));
    } catch { 
        history =[]; 
    }
}

function addHist(filename, url) {
    if (!filename) filename = "alon.pdf";
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
    
    if (!history || !history.length) {
        list.innerHTML = '<div class="empty-history">אין היסטוריית הורדות</div>';
        clearBtn.classList.add('hidden');
        return;
    }
    
    clearBtn.classList.remove('hidden');
    history.forEach(h => {
        // משיג את שם העלון באופן בטוח, מתאים גם להיסטוריה מגרסה ישנה
        const rawTitle = h.name || h.filename || h.bulletin || 'עלון';
        const displayTitle = String(rawTitle).replace('.pdf', '').replace(/_/g, ' ');

        const item = document.createElement('div');
        item.className = 'history-item';
        item.innerHTML = `<div><i class="fas fa-file-pdf"></i> ${displayTitle}</div> 
                          <span style="font-size:0.75rem; color:#888;">${h.date || ''}</span>`;
        if (h.url) {
            item.onclick = () => {
                const a = document.createElement('a'); a.href = h.url; a.download = rawTitle; a.click();
            };
        }
        list.appendChild(item);
    });
}

function initParticles() {
    const canvas = document.getElementById('particleCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    let particles =[];
    for(let i=0; i<60; i++) {
        particles.push({
            x: Math.random() * canvas.width, y: Math.random() * canvas.height,
            vx: (Math.random() - 0.5) * 0.5, vy: (Math.random() - 0.5) * 0.5,
            radius: Math.random() * 2 + 1
        });
    }
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy;
            if(p.x < 0 || p.x > canvas.width) p.vx *= -1;
            if(p.y < 0 || p.y > canvas.height) p.vy *= -1;
            ctx.beginPath(); ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0, 206, 201, 0.3)'; ctx.fill();
        });
        requestAnimationFrame(animate);
    }
    animate();
    window.addEventListener('resize', () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight; });
}
