let jwt = "", role = "", patientId = "";
const $ = (id) => document.getElementById(id);

const loginCard = $("loginCard"),
      appSection = $("appSection"),
      chatWrap = $("chatWrap"),
      adminCard = $("adminCard"),
      messages = $("messages");

const setCriticalError = (msg) => {
  const el = $("error");
  if (!msg) { el.classList.add("hidden"); el.textContent = ""; return; }
  el.textContent = " " + msg; el.classList.remove("hidden");
};
const uiRefresh = () => $("pid").textContent = patientId || "—";
const showApp = (show) => {
  loginCard.classList.toggle("hidden", show);
  appSection.classList.toggle("hidden", !show);
  $("logoutBtn").classList.toggle("hidden", !show);
};

let popupTimer = null;
const showPopup = (msg, isError = false) => {
  const el = $("popup");
  const iconWrap = $("popup-icon-container");
  const msgEl = $("popup-message");

  // Set message
  msgEl.textContent = msg;

  // Set icon
  if (isError) {
    iconWrap.innerHTML = `
      <svg class="popup-icon-error h-6 w-6 text-rose-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>`;
  } else {
    iconWrap.innerHTML = `
      <svg class="popup-icon-success h-6 w-6 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>`;
  }

  // Show
  el.classList.add("show");

  // Hide after 3 seconds
  if (popupTimer) clearTimeout(popupTimer);
  popupTimer = setTimeout(() => {
    el.classList.remove("show");
  }, 3000);
};


$("logoutBtn").onclick = () => {
  jwt = role = patientId = "";
  messages.innerHTML = "";
  chatWrap.classList.remove("hidden");
  adminCard.classList.add("hidden");
  showApp(false); uiRefresh();
};

// ---- login ----
$("loginBtn").onclick = async () => {
  const btn = $("loginBtn");
  try {
    setCriticalError(""); // Clear critical error
    btn.disabled = true; 
    // Add spinner
    btn.innerHTML = `
      <span class="spinner-dark"></span>
      <span class="ml-2">Signing in…</span>
    `;
    btn.classList.add('inline-flex', 'items-center', 'justify-center');

    const tryLogin = async (path) => {
      const res = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ user_id: $("userId").value, password: $("password").value })
      });
      const raw = await res.text();
      let data = null;
      try { data = JSON.parse(raw); } catch {
        const m = /```(?:json)?\s*([\sS]*?)\s*```/i.exec(raw);
        if (m) { try { data = JSON.parse(m[1]); } catch {} }
      }
      if (!res.ok) {
        const detail = data?.detail || data?.message || raw || `HTTP ${res.status}`;
        throw new Error(detail);
      }
      return data;
    };

    let data;
    try { data = await tryLogin("/auth/login"); }
    catch (_) { data = await tryLogin("/login"); }

    if (!data?.access_token) throw new Error("No token returned from server.");
    jwt = data.access_token;
    role = data.role || "patient";
    patientId = data.patient_id || "";

    showApp(true); uiRefresh();

    if (role === "doctor") {
      chatWrap.classList.add("hidden");
      adminCard.classList.remove("hidden");
    } else {
      chatWrap.classList.remove("hidden");
      adminCard.classList.add("hidden");
    }
    showPopup(`Welcome, ${data.name || role}!`);

  } catch (err) {
    showPopup("Login failed: " + (err.message || String(err)), true);
  } finally {
    btn.disabled = false; 
    btn.innerHTML = "Sign in";
    btn.classList.remove('inline-flex', 'items-center', 'justify-center');
  }
};

// ---- chat ----
$("chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (role !== "patient") return;

  const input = $("chatInput");
  const btn = e.target.querySelector('button'); // Get the submit button
  const text = (input.value || "").trim();
  if (!text) return;

  input.disabled = true;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>`; // Show spinner
  btn.classList.add('inline-flex', 'items-center', 'justify-center');

  input.value = "";
  pushMsg("user", text);
  setLoading(true);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(jwt ? { Authorization: `Bearer ${jwt}` } : {})
      },
      body: JSON.stringify({ message: text })
    });

    let data, raw;
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/json")) {
      data = await res.json();
    } else {
      raw = await res.text();
      data = safeParseAny(raw) || { assistant: cleanAssistantText(raw) };
    }
    if (!res.ok) {
      throw new Error(data?.detail || data?.message || raw || `Chat failed (${res.status})`);
    }
    const inner = typeof data.assistant === "string" ? safeParseAny(data.assistant) : null;
    if (inner && typeof inner === "object") data = { ...data, ...inner };
    const triage  = normTriage(data.triage_level ?? data.triage);
    const alerted = data.alert === true || data.alert_sent === true;
    const msgText =
      cleanAssistantText(
        data.assistant ?? data.answer ?? data.response ?? data.message ?? ""
      ) || "(no reply)";

    // Remove loading bubble *before* pushing assistant reply
    setLoading(false); 
    pushAssistant(msgText, { triage, alerted });

    if (alerted) {
      setCriticalError("🚨 Critical situation detected. An alert has been sent to your doctor.");
    } else {
      setCriticalError(""); // clear any previous banner
    }

  } catch (err) {
    setLoading(false); // Ensure loading is turned off on error
    showPopup(err.message || String(err), true);
  } finally {
    input.disabled = false;
    btn.disabled = false;
    btn.innerHTML = `Send`;
    btn.classList.remove('inline-flex', 'items-center', 'justify-center');
  }
});


// This array will hold our medication objects
let currentMedsArray = [];

// This function redraws the list of medication items
const renderMedsList = () => {
  const container = $("medsListContainer");
  if (!container) return; // Guard clause
  
  container.innerHTML = ""; // Clear the list
  
  // Show placeholder if empty
  if (currentMedsArray.length === 0) {
    container.innerHTML = `<span class="text-slate-400 italic text-center p-4">No medications added</span>`;
    return;
  }

  // Add each medication as a list item
  currentMedsArray.forEach((med, index) => {
    const item = document.createElement("div");
    item.className = "flex items-center justify-between gap-2 bg-white text-slate-700 px-3 py-2 border-b border-slate-200 last:border-b-0";
    
    item.innerHTML = `
      <span class="overflow-hidden whitespace-nowrap">
        <b class="font-medium text-sm text-slate-800">${med.name}</b>
        <span class="text-slate-500 ml-2">${med.dose || ''}</span>
        <span class="text-slate-500 ml-2">${med.freq || ''}</span>
      </span>
      <button type="button" class="remove-med-btn text-lg text-slate-400 hover:text-rose-500 flex-shrink-0" data-index="${index}">
        &times;
      </button>
    `;
    container.appendChild(item);
  });
};

// Handle adding a new med
const addMedBtn = $("addMedBtn");
if (addMedBtn) {
  addMedBtn.onclick = () => {
    const name = $("np_med_name").value.trim();
    const dose = $("np_med_dose").value.trim();
    const freq = $("np_med_freq").value.trim();

    if (!name) {
      showPopup("Medication name is required", true);
      return;
    }

    currentMedsArray.push({ name, dose, freq });
    renderMedsList();

    // Clear input fields
    $("np_med_name").value = "";
    $("np_med_dose").value = "";
    $("np_med_freq").value = "";
  };
}

// Handle removing a med (using event delegation)
const medsListContainer = $("medsListContainer");
if (medsListContainer) {
  medsListContainer.onclick = (e) => {
    const btn = e.target.closest(".remove-med-btn");
    if (btn) {
      const index = Number(btn.dataset.index);
      currentMedsArray.splice(index, 1); // Remove from array
      renderMedsList(); // Redraw UI
    }
  };
}

// Handle the main form submission
$("addPatientForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (role !== "doctor") return showPopup("Doctor role required", true);
  
  const btn = e.target.querySelector('button');
  
  try {
    btn.disabled = true;
    btn.innerHTML = `
      <span class="spinner"></span>
      <span class="ml-2">Adding Patient...</span>
    `;
    btn.classList.add('inline-flex', 'items-center', 'justify-center');

    const payload = {
      user_id: $("np_user_id").value,
      patient_id: $("np_patient_id").value,
      name: $("np_name").value,
      age: Number($("np_age").value),
      surgeon: $("np_surgeon").value,
      procedure: $("np_procedure").value,
      emergency_name: $("np_emname").value,
      emergency_phone: $("np_emphone").value,
      allergies: $("np_allergies").value.split(",").map(s=>s.trim()).filter(Boolean),
      
      medications: currentMedsArray,
      
      red_flags: $("np_flags").value.split("\n").map(s=>s.trim()).filter(Boolean),
    };

    const res = await fetch("/admin/add_patient", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${jwt}` },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || `Add failed (${res.status})`);
    
    showPopup(`✅ Added patient ${data.patient_id || payload.patient_id}`);
    e.target.reset(); // Reset form on success
    
    currentMedsArray = [];
    renderMedsList();
    
  } catch (err) {
    showPopup(err.message || String(err), true);
  } finally {
    // NEW: Restore button
    btn.disabled = false;
    btn.innerHTML = "Add Patient";
    btn.classList.remove('inline-flex', 'items-center', 'justify-center');
  }
});

// ---------- UI helpers ----------
function pushMsg(who, text){
  const wrap = document.createElement("div");
  wrap.className = `flex ${who === 'user' ? 'justify-end' : 'justify-start'} message-wrap-new`; 
  
  const bubble = document.createElement("div");
  bubble.className = (who === 'user' 
    ? 'bubble-user' 
    : 'bubble-assistant') +
    ' max-w-[85%] rounded-2xl px-4 py-3 whitespace-pre-wrap leading-relaxed';
  bubble.textContent = text;
  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
}

function pushAssistant(text, {triage, alerted} = {}){
  const wrap = document.createElement("div");
  wrap.className = 'flex justify-start message-wrap-new';
  
  const bubble = document.createElement("div");
  bubble.className = 'bubble-assistant max-w-[85%] rounded-2xl px-4 py-3 whitespace-pre-wrap leading-relaxed';
  if (triage || alerted) {
    const hdr = document.createElement('div');
    hdr.className = 'flex items-center gap-2 mb-2';
    if (triage) {
      const t = document.createElement('span');
      t.className = triage.class + ' inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium';
      t.textContent = `Priority: ${triage.label}`;
      hdr.appendChild(t);
    }
    if (alerted) {
      const a = document.createElement('span');
      a.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800';
      a.textContent = '⚠️ Alert sent';
      hdr.appendChild(a);
    }
    bubble.appendChild(hdr);
  }

  const body = document.createElement("div");
  body.textContent = text;
  bubble.appendChild(body);

  wrap.appendChild(bubble);
  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
}

const setLoading = (on) => {
  if (on) {
    const wrap = document.createElement("div");
    wrap.id = "loadingBubble";
    wrap.className = 'flex justify-start message-wrap-new'; 
    
    wrap.innerHTML = `
      <div class="bubble-assistant max-w-[85%] rounded-2xl px-4 py-3 flex items-center gap-3">
        <div class="dot-flashing mr-2"></div> 
        <span class="text-slate-500 italic">looking for ways to serve you better...</span>
      </div>
    `;
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  } else {
    const bubble = $("loadingBubble");
    if (bubble) bubble.remove();
  }
};

function normTriage(x){
  const n = Number(x);
  if (!n || n < 1) return null;
  if (n === 1) return { label: 'Low',      class: 'bg-emerald-100 text-emerald-800' };
  if (n === 2) return { label: 'Moderate', class: 'bg-amber-100 text-amber-800' };
  return            { label: 'High',     class: 'bg-rose-100 text-rose-800' };
}

// ---------- parsing utilities ----------
function safeParseAny(str){
  if (typeof str !== "string") return null;
  try { return JSON.parse(str); } catch {}
  const m = /```(?:json)?\s*([\sS]*?)\s*```/i.exec(str);
  if (m) { try { return JSON.parse(m[1]); } catch {} }
  const a = str.indexOf("{"), b = str.lastIndexOf("}");
  if (a !== -1 && b !== -1 && b > a) {
    try { return JSON.parse(str.slice(a, b + 1)); } catch {}
  }
  return null;
}

function stripCodeFences(str){
  if (typeof str !== "string") return str;
  return str.replace(/```(?:json)?\s*([\sS]*?)\s*```/gi, (_, inner) => inner.trim());
}

function cleanAssistantText(s){
  return stripCodeFences(String(s || "")).trim();
}

function normalizePayload(raw){
  const obj = safeParseAny(raw);
  if (obj && typeof obj === "object") {
    const maybeInner = typeof obj.assistant === "string" ? safeParseAny(obj.assistant) :null;
    if (maybeInner && typeof maybeInner === "object") {
      return { ...maybeInner, ...obj }; // inner fields + top-level fallbacks
    }
    return obj;
  }
  return { assistant: cleanAssistantText(raw) };
}