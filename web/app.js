"use strict";

const state = {
  sessionId: null,
  streaming: false,
  lastQuestion: "",
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  return n;
};
const escapeHtml = (s) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TRASH_ICON =
  '<svg viewBox="0 0 20 20" fill="none"><path d="M4 6h12M8 6V4.5A1.5 1.5 0 0 1 9.5 3h1A1.5 1.5 0 0 1 12 4.5V6m-6.5 0 .6 9.4A1.5 1.5 0 0 0 7.6 17h4.8a1.5 1.5 0 0 0 1.5-1.6L14.5 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const SEARCH_ICON =
  '<svg viewBox="0 0 20 20" fill="none"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.6"/><path d="M16 16l-3.2-3.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

function deleteButton(title, onClick) {
  const btn = el("button", "del icon-del");
  btn.innerHTML = TRASH_ICON;
  btn.title = title;
  btn.onclick = onClick;
  return btn;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  setTimeout(() => (t.className = "toast hidden"), 3200);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    // FastAPI validation errors return `detail` as an array of {msg, loc, ...} objects;
    // stringify them into a readable message instead of the useless "[object Object]".
    if (Array.isArray(detail)) {
      detail = detail.map((e) => (e && e.msg) || JSON.stringify(e)).join("; ");
    } else if (detail && typeof detail === "object") {
      detail = detail.msg || JSON.stringify(detail);
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

/* -------------------------------------------------------------- sessions */
async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const { session_id } = await api("/api/sessions", { method: "POST" });
  state.sessionId = session_id;
  await loadSessions();
  return session_id;
}

async function loadSessions() {
  const { sessions } = await api("/api/sessions");
  const list = $("#session-list");
  list.innerHTML = "";
  for (const s of sessions) {
    const li = el("li");
    if (s.id === state.sessionId) li.classList.add("active");
    const title = el("span", "title");
    title.textContent = s.title || "New chat";
    const del = deleteButton("Delete session", (e) => {
      e.stopPropagation();
      deleteSession(s.id);
    });
    li.append(title, del);
    li.onclick = () => selectSession(s.id);
    list.append(li);
  }
}

async function selectSession(id) {
  const data = await api(`/api/sessions/${id}`);
  state.sessionId = id;
  closeHistory();
  renderEvidence([]);
  const log = $("#chat-log");
  log.innerHTML = "";
  for (const m of data.messages) {
    addMessage(m.role, m.content, m.sources || []);
  }
  await loadSessions();
  await refreshUploads();
  scrollChat();
}

async function deleteSession(id) {
  await api(`/api/sessions/${id}`, { method: "DELETE" });
  if (state.sessionId === id) startNewChat(false);
  await loadSessions();
}

function startNewChat(reload = true) {
  state.sessionId = null;
  $("#chat-log").innerHTML =
    '<div class="empty-state"><p class="empty-title">Ask the oracle about your documents</p>' +
    '<p class="muted">Answers come only from your vault and this session\'s uploads.</p></div>';
  renderEvidence([]);
  $("#upload-list").innerHTML = "";
  if (reload) loadSessions();
}

/* -------------------------------------------------------------- chat */
function addMessage(role, content, sources) {
  const empty = $(".empty-state");
  if (empty) empty.remove();
  const msg = el("div", `msg ${role}`);
  msg.textContent = content;
  $("#chat-log").append(msg);
  if (sources && sources.length) attachSources(msg, sources);
  scrollChat();
  return msg;
}

function messageActions(msgEl) {
  // One row per message holding the "Show evidence" button and source chips.
  let row = msgEl.querySelector(".msg-actions");
  if (!row) {
    row = el("div", "msg-actions");
    msgEl.append(row);
  }
  return row;
}

function attachSources(msgEl, sources) {
  const row = messageActions(msgEl);
  for (const s of sources) {
    const chip = el("span", "chip");
    const dot = el("span", `dot ${s.origin}`);
    chip.append(dot, document.createTextNode(s.name));
    chip.title = `From ${s.origin === "upload" ? "session upload" : "vault"}: ${s.name}`;
    chip.onclick = () => showMessageEvidence(msgEl, s.name);
    row.append(chip);
  }
}

function attachEvidenceButton(msgEl) {
  // Only live answers carry passages (evidence is in-session only, not persisted).
  const ev = msgEl._evidence;
  if (!ev || !ev.passages.length) return;
  const row = messageActions(msgEl);
  const btn = el("button", "evidence-btn");
  btn.innerHTML = SEARCH_ICON + "<span>Show evidence</span>";
  btn.title = "Show the passages this answer is based on";
  btn.onclick = () => showMessageEvidence(msgEl, null);
  row.prepend(btn);
}

function showError(msgEl, message) {
  msgEl.classList.add("error-msg");
  msgEl.innerHTML = '<span class="error-prefix">Error:</span> ' + escapeHtml(message);
}

function scrollChat() {
  const log = $("#chat-log");
  log.scrollTop = log.scrollHeight;
}

function currentQuestion() {
  return $("#chat-input").value.trim();
}

async function send() {
  const question = currentQuestion();
  if (!question || state.streaming) return;
  $("#chat-input").value = "";
  autoGrow();

  let sid;
  try {
    sid = await ensureSession();
  } catch (e) {
    toast(e.message, true);
    return;
  }

  addMessage("user", question, []);
  const assistant = addMessage("assistant", "", []);
  assistant.innerHTML = '<span class="cursor">▋</span>';
  state.streaming = true;
  $("#send-btn").disabled = true;

  const url = `/api/chat/stream?question=${encodeURIComponent(question)}&session_id=${encodeURIComponent(sid)}`;
  const es = new EventSource(url);
  let answer = "";

  const finish = () => {
    es.close();
    state.streaming = false;
    $("#send-btn").disabled = false;
  };

  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === "session") {
      state.sessionId = data.session_id;
    } else if (data.type === "token") {
      answer += data.token;
      assistant.textContent = answer;
      scrollChat();
    } else if (data.type === "done") {
      assistant.textContent = answer;
      assistant._evidence = { question, passages: data.passages || [] };
      if (data.sources && data.sources.length) attachSources(assistant, data.sources);
      attachEvidenceButton(assistant);
      loadSessions();
      finish();
    } else if (data.type === "error") {
      showError(assistant, data.message);
      finish();
    }
  };
  es.onerror = () => {
    if (state.streaming) {
      if (!answer) showError(assistant, "Connection to the server was lost.");
      finish();
    }
  };
}

/* -------------------------------------------------------------- evidence */
function highlight(text, question) {
  const terms = (question || "")
    .toLowerCase()
    .split(/\W+/)
    .filter((w) => w.length > 2);
  let html = escapeHtml(text);
  const unique = [...new Set(terms)].sort((a, b) => b.length - a.length);
  for (const term of unique) {
    const re = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    html = html.replace(re, "<mark>$1</mark>");
  }
  return html;
}

function renderEvidence(passages) {
  const body = $("#evidence-body");
  body.innerHTML = "";
  if (!passages.length) {
    body.innerHTML =
      '<p class="muted pad">Click <b>Show evidence</b> under an answer (or one of its source chips) to see the exact passages it was based on.</p>';
    return;
  }
  const question = state.lastQuestion || "";
  passages.forEach((p, i) => {
    const card = el("div", "passage");
    card.dataset.source = p.source;
    card.id = `passage-${i}`;
    const head = el("div", "passage-head");
    const src = el("span", "passage-src");
    src.innerHTML = `<span class="dot ${p.origin}"></span>${escapeHtml(p.source)}${p.locator ? " · " + escapeHtml(p.locator) : ""}`;
    const score = el("span", "passage-score");
    score.textContent = `sim ${p.score}`;
    head.append(src, score);
    const txt = el("div", "passage-text");
    txt.innerHTML = highlight(p.text, question);
    card.append(head, txt);
    body.append(card);
  });
}

function showMessageEvidence(msgEl, source) {
  const ev = msgEl._evidence;
  if (!ev || !ev.passages.length) {
    toast("Evidence is only kept for the current session, not older chats.");
    return;
  }
  state.lastQuestion = ev.question;
  renderEvidence(ev.passages);
  openZone("evidence");
  if (source) highlightPassageSource(source);
}

function highlightPassageSource(source) {
  const cards = document.querySelectorAll(".passage");
  let target = null;
  cards.forEach((c) => {
    const match = c.dataset.source === source;
    c.classList.toggle("highlight", match);
    if (match && !target) target = c;
  });
  if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
}

/* -------------------------------------------------------------- vault + uploads */
async function loadDocuments() {
  const { documents } = await api("/api/documents");
  const list = $("#vault-list");
  list.innerHTML = "";
  if (!documents.length) {
    list.innerHTML = '<li class="muted small">No files in the vault yet. Add some to the documents/ folder.</li>';
    return;
  }
  for (const d of documents) {
    const li = el("li");
    const name = el("span", "fname");
    name.textContent = d.name;
    const meta = el("span", "meta");
    meta.textContent = `${d.chunks} chunks`;
    li.append(name, meta);
    list.append(li);
  }
}

async function refreshUploads() {
  if (!state.sessionId) { $("#upload-list").innerHTML = ""; return; }
  const { files } = await api(`/api/sessions/${state.sessionId}/uploads`);
  const list = $("#upload-list");
  list.innerHTML = "";
  for (const f of files) {
    const li = el("li");
    const name = el("span", "fname");
    name.textContent = f;
    const del = deleteButton("Remove upload", () => deleteUpload(f));
    li.append(name, del);
    list.append(li);
  }
}

async function uploadFiles(fileList) {
  // Snapshot the files NOW, before any await. `input.files` is a *live* FileList: the
  // change handler clears the input (`input.value = ""`) right after calling us, and if we
  // waited until after `await ensureSession()` to read it, the list would already be empty
  // — producing a request with no files and a 422. Array.from freezes the selection.
  const files = Array.from(fileList);
  if (!files.length) return;
  let sid;
  try { sid = await ensureSession(); } catch (e) { return toast(e.message, true); }
  const form = new FormData();
  for (const f of files) form.append("files", f);
  toast("Indexing upload…");
  try {
    const res = await api(`/api/sessions/${sid}/uploads`, { method: "POST", body: form });
    const errors = res.uploads.filter((u) => u.error);
    const empty = res.uploads.filter((u) => !u.error && u.chunks === 0);
    if (errors.length) toast(errors.map((e) => `${e.name}: ${e.error}`).join("; "), true);
    else if (empty.length) toast(`No readable text found in ${empty.map((e) => e.name).join(", ")}.`, true);
    else toast("Uploaded — searchable in this session.");
    await refreshUploads();
  } catch (e) {
    toast(e.message, true);
  }
}

async function deleteUpload(name) {
  await api(`/api/sessions/${state.sessionId}/uploads/${encodeURIComponent(name)}`, { method: "DELETE" });
  await refreshUploads();
}

async function reloadVault() {
  toast("Reloading vault…");
  try {
    const r = await api("/api/reindex", { method: "POST" });
    toast(`Vault reloaded: ${r.files} files (${r.added} new, ${r.updated} updated, ${r.removed} removed).`);
    await loadDocuments();
  } catch (e) {
    toast(e.message, true);
  }
}

/* -------------------------------------------------------------- zones / UI */
function openZone(name) {
  const zone = $(`#${name}-zone`);
  zone.classList.remove("collapsed");
  $(".workspace").classList.remove(`no-${name}`);
}
function toggleZone(name) {
  const zone = $(`#${name}-zone`);
  const collapsed = zone.classList.toggle("collapsed");
  $(".workspace").classList.toggle(`no-${name}`, collapsed);
}

function openVault() { $("#vault-overlay").classList.remove("hidden"); loadDocuments(); refreshUploads(); }
function closeVault() { $("#vault-overlay").classList.add("hidden"); }

function openHistory() { $("#history-overlay").classList.remove("hidden"); loadSessions(); }
function closeHistory() { $("#history-overlay").classList.add("hidden"); }

function autoGrow() {
  const ta = $("#chat-input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
}

/* -------------------------------------------------------------- wiring */
function wire() {
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    state.lastQuestion = currentQuestion();
    send();
  });
  $("#chat-input").addEventListener("input", autoGrow);
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      state.lastQuestion = currentQuestion();
      send();
    }
  });

  $("#new-chat").onclick = () => { startNewChat(); closeHistory(); };
  $("#toggle-sessions").onclick = openHistory;
  $("#toggle-evidence").onclick = () => toggleZone("evidence");
  $("#toggle-vault").onclick = openVault;
  $("#reindex-btn").onclick = reloadVault;
  document.querySelectorAll(".close-zone").forEach((b) => {
    const closers = { vault: closeVault, history: closeHistory };
    const which = b.dataset.close;
    b.onclick = closers[which] || (() => toggleZone(which));
  });
  $("#vault-overlay").addEventListener("click", (e) => {
    if (e.target.id === "vault-overlay") closeVault();
  });
  $("#history-overlay").addEventListener("click", (e) => {
    if (e.target.id === "history-overlay") closeHistory();
  });

  // uploads
  const input = $("#file-input");
  input.addEventListener("change", () => { uploadFiles(input.files); input.value = ""; });
  const dz = $("#dropzone");
  // Some browsers (notably Safari) don't reliably delegate a click on a <label> to a
  // hidden file <input>. Drive it explicitly instead of relying on that implicit link.
  // Guard against the input's own (programmatically-triggered) click bubbling back up
  // through the label and re-firing this handler.
  dz.addEventListener("click", (e) => {
    if (e.target === input) return;
    e.preventDefault();
    input.click();
  });
  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); })
  );
  dz.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));
}

async function init() {
  wire();
  try {
    const h = await api("/api/health");
    document.title = `CloakedOracle · ${h.chunks} chunks`;
  } catch (_) {}
  await loadSessions();
}

init();
