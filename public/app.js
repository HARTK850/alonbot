/* ═══════════════════════════════════════
   AlonBot – Frontend Logic
   ═══════════════════════════════════════ */

const API_BASE = "/api";
const HIST_KEY = "alonbot_history";
let history =[];

// ─── Init ─────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadKey();
  loadHist();
  renderHist();
});

// ─── Toggle collapsible card ──────────
function toggleCard(bodyId, chevronId) {
  const body = document.getElementById(bodyId);
  const chevron = document.getElementById(chevronId);
  const hidden = body.style.display === "none";
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
  if (!k) { toast("fa-solid fa-triangle-exclamation", "הזן מפתח תחילה"); return; }
  sessionStorage.setItem("alonbot_key", k);
  toast("fa-solid fa-check", "מפתח נשמר בהצלחה");
}
function toggleApiVis() {
  const inp = document.getElementById("apiKey");
  const icon = inp.nextElementSibling.querySelector('i');
  if (inp.type === "password") {
    inp.type = "text";
    icon.className = "fa-solid fa-eye-slash";
  } else {
    inp.type = "password";
    icon.className = "fa-solid fa-eye";
  }
}

// ─── Helper: Convert Base64 to Blob URL ───
// כך הקובץ יורד ישירות מתוך המידע שחזר, בלי צורך לחזור לשרת!
function base64ToBlobUrl(base64Data, contentType = 'application/pdf') {
  const byteCharacters = atob(base64Data);
  const byteArrays =[];
  for (let offset = 0; offset < byteCharacters.length; offset += 512) {
    const slice = byteCharacters.slice(offset, offset + 512);
    const byteNumbers = new Array(slice.length);
    for (let i = 0; i < slice.length; i++) {
      byteNumbers[i] = slice.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    byteArrays.push(byteArray);
  }
  const blob = new Blob(byteArrays, { type: contentType });
  return URL.createObjectURL(blob);
}

// ─── Search ───────────────────────────
async function doSearch() {
  const apiKey = document.getElementById("apiKey").value.trim();
  const bulletin = document.getElementById("bulletinName").value.trim();

  if (!apiKey) { showStatus("error", "fa-solid fa-triangle-exclamation", "נא להזין מפתח Gemini בחלק ההגדרות"); return; }
  if (!bulletin) { showStatus("error", "fa-solid fa-circle-exclamation", "נא להזין שם עלון לחיפוש"); return; }

  setLoading(true);
  hideResult();
  showStatus("searching", "fa-solid fa-spinner fa-spin", "מאתר פרשת שבוע וסורק מקורות לעלון...");

  try {
    const r = await fetch(API_BASE + "/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey, bulletin }),
    });
    const data = await r.json();

    if (data.success && data.pdf_b64) {
      sessionStorage.setItem("alonbot_key", apiKey);

      const parashaInfo = data.parasha ? ` | פרשת ${data.parasha}` : "";
      const hebrewInfo = data.hebrew_date ? ` | ${data.hebrew_date}` : "";
      
      // המרה ל-Blob מקומי
      const blobUrl = base64ToBlobUrl(data.pdf_b64);

      showStatus("found", "fa-solid fa-circle-check", (data.message || "נמצא בהצלחה!") + parashaInfo + hebrewInfo);
      showResult(blobUrl, data.filename, bulletin, data.parasha);
      addHist(bulletin, true, blobUrl, data.filename, data.parasha);
    } else {
      showStatus("error", "fa-solid fa-circle-xmark", data.error || "לא נמצא עלון שעונה על הדרישות המדויקות");
      addHist(bulletin, false, null, null, "");
    }
  } catch (e) {
    showStatus("error", "fa-solid fa-wifi", "שגיאת תקשורת בחיבור לשרת");
  } finally {
    setLoading(false);
    renderHist();
  }
}

function setLoading(on) {
  const btn = document.getElementById("searchBtn");
  document.getElementById("btnLabel").style.display = on ? "none" : "";
  document.getElementById("btnSpinner").style.display = on ? "" : "none";
  btn.disabled = on;
}

// ─── Status ───────────────────────────
function showStatus(type, iconClass, msg) {
  const wrap = document.getElementById("statusWrap");
  const bar = document.getElementById("statusBar");
  wrap.style.display = "";
  bar.className = "status-bar " + type;
  document.getElementById("statusIcon").innerHTML = `<i class="${iconClass}"></i>`;
  document.getElementById("statusText").textContent = msg;
}

// ─── Result ───────────────────────────
function showResult(downloadUrl, filename, bulletin, parasha) {
  const box = document.getElementById("resultBox");
  box.style.display = "";
  document.getElementById("resName").textContent = bulletin + (parasha ? ` – פרשת ${parasha}` : "");

  const link = document.getElementById("downloadLink");
  link.href = downloadUrl;
  link.setAttribute("download", filename || "alon_shabbat.pdf");
}

function hideResult() {
  document.getElementById("resultBox").style.display = "none";
}

function trackDownload() {
  toast("fa-solid fa-download", "הורדת הקובץ מתחילה...");
}

// ─── History ──────────────────────────
function loadHist() {
  try { history = JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); }
  catch { history =[]; }
}
function saveHistStorage() {
  // שומרים נתונים ללא URL ה-Blob מכיוון שהוא פג תוקף ברענון עמוד
  const toSave = history.map(h => ({ ...h, downloadUrl: null }));
  localStorage.setItem(HIST_KEY, JSON.stringify(toSave.slice(0, 30)));
}
function addHist(bulletin, ok, downloadUrl, filename, parasha) {
  history.unshift({
    id: Date.now(),
    bulletin, ok, downloadUrl, filename, parasha,
    date: new Date().toLocaleString("he-IL", {hour: '2-digit', minute:'2-digit', day:'2-digit', month:'2-digit'}),
  });
  saveHistStorage();
}
function clearHist() {
  if (!confirm("האם למחוק את כל ההיסטוריה?")) return;
  history =[];
  saveHistStorage();
  renderHist();
}

function renderHist() {
  const list = document.getElementById("histList");
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
    <div class="hist-row animate-fade-in">
      <span class="hist-ic"><i class="${h.ok ? 'fa-regular fa-file-pdf' : 'fa-solid fa-magnifying-glass'}"></i></span>
      <div class="hist-info">
        <div class="hist-name">${esc(h.bulletin)}${h.parasha ? ` – ${esc(h.parasha)}` : ""}</div>
        <div class="hist-date">${h.date}</div>
      </div>
      <span class="pill ${h.ok ? "ok" : "err"}">${h.ok ? "נמצא" : "לא נמצא"}</span>
      ${h.ok && h.downloadUrl ? `
        <a class="hist-dl" href="${esc(h.downloadUrl)}" download="${esc(h.filename || 'alon.pdf')}">
          <i class="fa-solid fa-download"></i> הורד
        </a>
      ` : ""}
    </div>
  `).join("");
}

// ─── Utilities ────────────────────────
function esc(s) {
  return String(s).replace(/[&<>"']/g,
    m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[m]));
}

function toast(iconClass, msg) {
  const t = document.createElement("div");
  t.className = "toast-msg";
  t.innerHTML = `<i class="${iconClass}"></i> <span>${msg}</span>`;
  document.body.appendChild(t);
  requestAnimationFrame(() => { t.style.opacity = "1"; });
  setTimeout(() => {
    t.style.opacity = "0";
    setTimeout(() => t.remove(), 400);
  }, 2600);
}
