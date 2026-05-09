/* ═══════════════════════════════════════
   AlonBot – Frontend Logic
   API base: same origin (Vercel functions)
═══════════════════════════════════════ */

const API_BASE = "/api";
const HIST_KEY = "alonbot_history";
let   history  = [];

// ─── Init ─────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadKey();
  loadHist();
  renderHist();
});

// ─── Toggle collapsible card ──────────
function toggleCard(bodyId, chevronId) {
  const body    = document.getElementById(bodyId);
  const chevron = document.getElementById(chevronId);
  const hidden  = body.style.display === "none";
  body.style.display = hidden ? "" : "none";
  chevron.classList.toggle("open", hidden);
}

// ─── API Key ──────────────────────────
function loadKey() {
  const k = sessionStorage.getItem("alonbot_key");
  if (k) document.getElementById("apiKey").value = k;
}
function saveKey() {
  const k = document.getElementById("apiKey").value.trim();
  if (!k) { toast("⚠️ הזן מפתח תחילה"); return; }
  sessionStorage.setItem("alonbot_key", k);
  toast("✅ מפתח נשמר");
}
function toggleApiVis() {
  const inp = document.getElementById("apiKey");
  inp.type = inp.type === "password" ? "text" : "password";
}

// ─── Search ───────────────────────────
async function doSearch() {
  const apiKey   = document.getElementById("apiKey").value.trim();
  const bulletin = document.getElementById("bulletinName").value.trim();

  if (!apiKey)   { showStatus("error","⚠️","נא להזין Gemini API Key בקטע ההגדרות"); return; }
  if (!bulletin) { showStatus("error","⚠️","נא להזין שם עלון"); return; }

  setLoading(true);
  hideResult();
  showStatus("searching","⏳","מחפש עלון – אנא המתן...");

  try {
    const r = await fetch(API_BASE + "/search", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ api_key: apiKey, bulletin })
    });
    const data = await r.json();

    if (data.success) {
      sessionStorage.setItem("alonbot_key", apiKey);
      showStatus("found","✅", data.message || "נמצא!");
      showResult(data.pdf_url, data.filename, bulletin);
      addHist(bulletin, true, data.pdf_url, data.filename);
    } else {
      showStatus("error","❌", data.error || "לא נמצא");
      addHist(bulletin, false, null, null);
    }
  } catch (e) {
    showStatus("error","❌","שגיאת תקשורת עם השרת");
  } finally {
    setLoading(false);
    renderHist();
  }
}

function setLoading(on) {
  const btn = document.getElementById("searchBtn");
  document.getElementById("btnLabel").style.display  = on ? "none" : "";
  document.getElementById("btnSpinner").style.display = on ? "" : "none";
  btn.disabled = on;
}

// ─── Status ───────────────────────────
function showStatus(type, icon, msg) {
  const wrap = document.getElementById("statusWrap");
  const bar  = document.getElementById("statusBar");
  wrap.style.display = "";
  bar.className      = "status-bar " + type;
  document.getElementById("statusIcon").textContent = icon;
  document.getElementById("statusText").textContent = msg;
}

// ─── Result ───────────────────────────
function showResult(url, filename, bulletin) {
  const box  = document.getElementById("resultBox");
  box.style.display = "";
  document.getElementById("resName").textContent = bulletin || filename;
  const link = document.getElementById("downloadLink");
  link.href  = url;
  link.setAttribute("download", filename || "elon_shabbat.pdf");
}
function hideResult() {
  document.getElementById("resultBox").style.display = "none";
}
function trackDownload() {
  toast("⬇️ ההורדה החלה!");
}

// ─── History ──────────────────────────
function loadHist() {
  try { history = JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); }
  catch { history = []; }
}
function saveHistStorage() {
  localStorage.setItem(HIST_KEY, JSON.stringify(history.slice(0, 40)));
}
function addHist(bulletin, ok, url, filename) {
  history.unshift({
    id:       Date.now(),
    bulletin,
    ok,
    url:      url || null,
    filename: filename || null,
    date:     new Date().toLocaleString("he-IL")
  });
  saveHistStorage();
}
function clearHist() {
  if (!confirm("למחוק את כל ההיסטוריה?")) return;
  history = [];
  saveHistStorage();
  renderHist();
}

function renderHist() {
  const list  = document.getElementById("histList");
  const empty = document.getElementById("histEmpty");
  const badge = document.getElementById("histCount");
  const clearBtn = document.getElementById("clearHistBtn");

  badge.textContent = history.length;

  if (!history.length) {
    empty.style.display = "";
    list.innerHTML = "";
    clearBtn.style.display = "none";
    return;
  }

  empty.style.display = "none";
  clearBtn.style.display = "";

  list.innerHTML = history.map(h => `
    <div class="hist-row">
      <span class="hist-ic">${h.ok ? "📄" : "🔍"}</span>

      <div class="hist-info">
        <div class="hist-name">${esc(h.bulletin)}</div>
        <div class="hist-date">${h.date}</div>
      </div>

      <span class="pill ${h.ok ? "ok" : "err"}">
        ${h.ok ? "נמצא" : "לא נמצא"}
      </span>

      ${h.ok && h.url ? `
        <a class="hist-dl"
           href="${esc(h.url)}"
           download="${esc(h.filename || 'elon.pdf')}"
           target="_blank"
           rel="noopener">⬇️</a>
      ` : ""}
    </div>
  `).join("");
}

// ─── Utilities ────────────────────────
function esc(s) {
  return String(s).replace(/[&<>"']/g,
    m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
}

function toast(msg) {
  const t = document.createElement("div");
  t.textContent = msg;
  Object.assign(t.style, {
    position:"fixed", bottom:"28px", left:"50%",
    transform:"translateX(-50%)",
    background:"rgba(30,30,60,.95)", backdropFilter:"blur(12px)",
    color:"#f1f5f9", padding:"10px 22px",
    borderRadius:"10px", fontSize:".9rem",
    zIndex:"9999", boxShadow:"0 4px 20px rgba(0,0,0,.5)",
    border:"1px solid rgba(99,102,241,.4)",
    opacity:"0", transition:"opacity .3s"
  });
  document.body.appendChild(t);
  requestAnimationFrame(() => { t.style.opacity = "1"; });
  setTimeout(() => {
    t.style.opacity = "0";
    setTimeout(() => t.remove(), 400);
  }, 2600);
}