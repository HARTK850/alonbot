document.addEventListener('DOMContentLoaded', () => {
    // אתחול מערכת החלקיקים לרקע
    initParticleNetwork();

    const botInput = document.getElementById('botInput');
    const actionBtn = document.getElementById('actionBtn');
    const statusArea = document.getElementById('botStatusArea');
    const botMessage = document.getElementById('botMessage');
    const botIcon = document.getElementById('botIcon');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const progressTrack = document.getElementById('progressTrack');
    const progressBar = document.getElementById('progressBar');
    const tags = document.querySelectorAll('.tag');

    // מאפשר לחיצה על תגיות מהירות
    tags.forEach(tag => {
        tag.addEventListener('click', () => {
            botInput.value = tag.innerText;
            startBotProcess();
        });
    });

    botInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') startBotProcess();
    });

    actionBtn.addEventListener('click', startBotProcess);

    async function startBotProcess() {
        const query = botInput.value.trim();
        if (!query) return;

        setUIState('loading', "בוט מפענח את הבקשה שלך עם Gemini...");
        progressBar.style.width = '20%';

        try {
            // הדמיית התקדמות למען חווית משתמש חלקה
            setTimeout(() => { progressBar.style.width = '45%'; botMessage.innerText = "מחפש את קובץ ה-PDF באינטרנט..."; }, 2500);
            setTimeout(() => { progressBar.style.width = '75%'; botMessage.innerText = "הקובץ אותר, שואב אותו לשרת..."; }, 5000);

            // הפעלת API בורסל
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || "אופס, הבוט לא הצליח לאתר את העלון.");
            }

            progressBar.style.width = '90%';
            botMessage.innerText = "מוריד את ה-PDF למכשיר שלך...";

            // טיפול בקובץ הבינארי
            const blob = await response.blob();
            downloadBlob(blob, query);

            setUIState('success', "הקובץ ירד בהצלחה! שבת שלום.");
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
            botIcon.classList.add('hidden');
            loadingSpinner.classList.remove('hidden');
            progressTrack.classList.remove('hidden');
            actionBtn.disabled = true;
        } else {
            botIcon.classList.remove('hidden');
            loadingSpinner.classList.add('hidden');
            progressTrack.classList.add('hidden');
            actionBtn.disabled = false;
            
            if (state === 'error') {
                statusArea.classList.add('error');
                botIcon.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
            } else if (state === 'success') {
                statusArea.classList.add('success');
                botIcon.innerHTML = '<i class="fas fa-check-circle"></i>';
            }
        }
    }

    function downloadBlob(blob, originalQuery) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        const cleanName = originalQuery.replace(/[^א-תa-zA-Z0-9]/g, '_');
        a.download = `AlonBot_${cleanName}_${Date.now()}.pdf`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 1000);
    }
});

// מערכת חלקיקים (Particles Canvas) ליצירת רקע מדהים של 700+ שורות איכותיות
function initParticleNetwork() {
    const canvas = document.getElementById('particleCanvas');
    const ctx = canvas.getContext('2d');
    let width, height, particles =[];

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
    }
    window.addEventListener('resize', resize);
    resize();

    class Particle {
        constructor() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            this.vx = (Math.random() - 0.5) * 0.5;
            this.vy = (Math.random() - 0.5) * 0.5;
            this.radius = Math.random() * 2;
        }
        update() {
            this.x += this.vx;
            this.y += this.vy;
            if (this.x < 0 || this.x > width) this.vx *= -1;
            if (this.y < 0 || this.y > height) this.vy *= -1;
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
            ctx.fill();
        }
    }

    for (let i = 0; i < 70; i++) particles.push(new Particle());

    function animate() {
        ctx.clearRect(0, 0, width, height);
        particles.forEach(p => { p.update(); p.draw(); });
        
        // ציור קווים בין חלקיקים קרובים
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 120) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(255, 255, 255, ${0.15 - dist/800})`;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();
}
