// שים פה את הכתובת של השרת שלך מ-Vercel:
const VERCEL_BACKEND_URL = 'https://alonbotapi.vercel.app/api/search';

document.addEventListener('DOMContentLoaded', () => {
    initParticleNetwork();

    const botInput = document.getElementById('botInput');
    const actionBtn = document.getElementById('actionBtn');
    const statusArea = document.getElementById('botStatusArea');
    const botMessage = document.getElementById('botMessage');
    const botIcon = document.getElementById('botIcon');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const progressBar = document.getElementById('progressBar');
    
    const settingsModal = document.getElementById('settingsModal');
    const openSettingsBtn = document.getElementById('openSettingsBtn');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const saveApiKeyBtn = document.getElementById('saveApiKeyBtn');
    const apiKeyInput = document.getElementById('apiKeyInput');
    const togglePasswordBtn = document.getElementById('togglePasswordBtn');

    const historyList = document.getElementById('historyList');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');

    function showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast`;
        toast.style.borderRightColor = type === 'error' ? 'var(--error)' : 'var(--primary)';
        toast.innerHTML = `<i class="fas ${type === 'error' ? 'fa-exclamation-circle' : 'fa-check-circle'}"></i> ${message}`;
        container.appendChild(toast);
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, 4000);
    }

    let currentUserApiKey = localStorage.getItem('geminiApiKey') || '';

    function checkApiKey() {
        if (!currentUserApiKey) {
            settingsModal.classList.remove('hidden');
            showToast("נא להזין מפתח API", 'error');
            return false;
        }
        return true;
    }

    openSettingsBtn.addEventListener('click', () => { apiKeyInput.value = currentUserApiKey; settingsModal.classList.remove('hidden'); });
    closeModalBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));

    togglePasswordBtn.addEventListener('click', () => {
        apiKeyInput.type = apiKeyInput.type === 'password' ? 'text' : 'password';
        togglePasswordBtn.innerHTML = apiKeyInput.type === 'password' ? '<i class="fas fa-eye"></i>' : '<i class="fas fa-eye-slash"></i>';
    });

    saveApiKeyBtn.addEventListener('click', () => {
        const key = apiKeyInput.value.trim();
        if (key.length < 20) return showToast("המפתח לא תקין", 'error');
        currentUserApiKey = key;
        localStorage.setItem('geminiApiKey', key);
        settingsModal.classList.add('hidden');
        showToast("מפתח נשמר!");
    });

    function loadHistory() {
        const history = JSON.parse(localStorage.getItem('alonBotHistory') || '[]');
        historyList.innerHTML = '';
        if (history.length === 0) {
            historyList.innerHTML = '<div class="empty-history">אין היסטוריה.</div>';
            clearHistoryBtn.classList.add('hidden'); return;
        }
        clearHistoryBtn.classList.remove('hidden');
        history.forEach(item => {
            const div = document.createElement('div'); div.className = 'history-item';
            div.innerHTML = `<span>${item.name}</span> <i class="fas fa-file-pdf"></i>`;
            div.addEventListener('click', () => { botInput.value = item.name; startBotProcess(); });
            historyList.appendChild(div);
        });
    }

    function saveToHistory(name) {
        let history = JSON.parse(localStorage.getItem('alonBotHistory') || '[]');
        history = history.filter(item => item.name !== name);
        history.unshift({ name, date: new Date().toISOString() });
        if (history.length > 8) history.pop();
        localStorage.setItem('alonBotHistory', JSON.stringify(history));
        loadHistory();
    }

    clearHistoryBtn.addEventListener('click', () => { localStorage.removeItem('alonBotHistory'); loadHistory(); });
    loadHistory();

    document.querySelectorAll('.tag').forEach(tag => {
        tag.addEventListener('click', () => { botInput.value = tag.innerText; startBotProcess(); });
    });

    botInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') startBotProcess(); });
    actionBtn.addEventListener('click', startBotProcess);

    async function startBotProcess() {
        if (!checkApiKey()) return;
        const query = botInput.value.trim();
        if (!query) return;

        setUIState('loading', "מתחבר לשרת...");
        progressBar.style.width = '20%';

        try {
            setTimeout(() => { progressBar.style.width = '60%'; botMessage.innerText = "מפענח עם Gemini ומחפש PDF..."; }, 2000);

            // === קריאה לשרת ב-Vercel מהאתר בגיטהאב ===
            const response = await fetch(`${VERCEL_BACKEND_URL}?q=${encodeURIComponent(query)}`, {
                method: 'GET',
                headers: { 'x-gemini-api-key': currentUserApiKey }
            });
            
            if (!response.ok) {
                const errData = await response.json();
                if (response.status === 401) { localStorage.removeItem('geminiApiKey'); currentUserApiKey = ''; }
                throw new Error(errData.error || "שגיאה בחיפוש.");
            }

            progressBar.style.width = '85%';
            botMessage.innerText = "הקובץ יורד עכשיו...";

            const blob = await response.blob();
            downloadBlob(blob, query);
            saveToHistory(query);

            setUIState('success', "הורדה הושלמה!");
            progressBar.style.width = '100%';

        } catch (error) {
            setUIState('error', error.message);
            progressBar.style.width = '0%';
        }
    }

    function setUIState(state, message) {
        statusArea.classList.remove('hidden', 'error', 'success');
        botMessage.innerText = message;
        if (state === 'loading') {
            botIcon.classList.add('hidden'); loadingSpinner.classList.remove('hidden');
            document.getElementById('progressTrack').classList.remove('hidden'); actionBtn.disabled = true;
        } else {
            botIcon.classList.remove('hidden'); loadingSpinner.classList.add('hidden');
            document.getElementById('progressTrack').classList.add('hidden'); actionBtn.disabled = false;
            if (state === 'error') { statusArea.classList.add('error'); botIcon.innerHTML = '<i class="fas fa-exclamation-triangle"></i>'; }
            else if (state === 'success') { statusArea.classList.add('success'); botIcon.innerHTML = '<i class="fas fa-check-circle"></i>'; }
        }
    }

    function downloadBlob(blob, query) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none'; a.href = url;
        a.download = `AlonBot_${query.replace(/\s+/g, '_')}.pdf`;
        document.body.appendChild(a); a.click();
        setTimeout(() => { window.URL.revokeObjectURL(url); document.body.removeChild(a); }, 1000);
    }
});

// רקע חלקיקים (אפקט ויזואלי)
function initParticleNetwork() {
    const canvas = document.getElementById('particleCanvas');
    const ctx = canvas.getContext('2d');
    let width, height, particles =[];
    function resize() { width = canvas.width = window.innerWidth; height = canvas.height = window.innerHeight; }
    window.addEventListener('resize', resize); resize();
    class Particle {
        constructor() {
            this.x = Math.random() * width; this.y = Math.random() * height;
            this.vx = (Math.random() - 0.5) * 0.4; this.vy = (Math.random() - 0.5) * 0.4;
            this.radius = Math.random() * 2;
        }
        update() {
            this.x += this.vx; this.y += this.vy;
            if (this.x < 0 || this.x > width) this.vx *= -1;
            if (this.y < 0 || this.y > height) this.vy *= -1;
        }
        draw() {
            ctx.beginPath(); ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0, 206, 201, 0.3)'; ctx.fill();
        }
    }
    for (let i = 0; i < 60; i++) particles.push(new Particle());
    function animate() {
        ctx.clearRect(0, 0, width, height);
        particles.forEach(p => { p.update(); p.draw(); });
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x, dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 100) {
                    ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y); ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(0, 206, 201, ${0.15 - dist/666})`; ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();
}
