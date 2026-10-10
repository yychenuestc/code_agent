// Code Agent 前端逻辑：SSE 流式对话 + 节点执行过程展示
let threadId = "";

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const modeSel = document.getElementById("mode");
const langSel = document.getElementById("lang");
const projectInp = document.getElementById("project");
const tidSpan = document.getElementById("tid");

function setThread(id) {
  threadId = id || "";
  tidSpan.textContent = threadId ? ("会话: " + threadId) : "";
}

document.getElementById("newSession").addEventListener("click", () => {
  setThread("");
  chat.innerHTML = "";
});

function addMsg(role, text) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const r = document.createElement("div");
  r.className = "role";
  r.textContent = role === "user" ? "你" : "助手";
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = text;
  wrap.appendChild(r);
  wrap.appendChild(b);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return wrap;
}

function addTrace(wrap) {
  const t = document.createElement("div");
  t.className = "trace";
  t.innerHTML = "<b>执行过程</b>";
  wrap.appendChild(t);
  return t;
}

async function send() {
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  sendBtn.disabled = true;

  addMsg("user", message);
  const botWrap = addMsg("assistant", "");
  const bubble = botWrap.querySelector(".bubble");
  bubble.textContent = "思考中…";
  const trace = addTrace(botWrap);

  const payload = {
    message,
    task_type: modeSel.value || null,
    language: langSel.value || "",
    project_path: projectInp.value.trim(),
    thread_id: threadId || null,
  };

  try {
    const resp = await fetch("/api/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let finalText = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const ev = parseSSE(part);
        if (!ev) continue;
        handleEvent(ev, { bubble, trace, setFinal: (t) => (finalText = t) });
      }
    }
    if (finalText) bubble.textContent = finalText;
    else if (bubble.textContent === "思考中…") bubble.textContent = "(无输出)";
  } catch (e) {
    bubble.textContent = "请求失败: " + e;
  } finally {
    sendBtn.disabled = false;
    chat.scrollTop = chat.scrollHeight;
  }
}

function parseSSE(block) {
  let event = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try { return { event, data: JSON.parse(data) }; } catch { return null; }
}

function handleEvent(ev, ctx) {
  if (ev.event === "session") {
    setThread(ev.data.thread_id);
  } else if (ev.event === "node") {
    const step = document.createElement("div");
    step.className = "step";
    const prev = ev.data.preview ? (": " + ev.data.preview) : "";
    step.innerHTML = '<span class="node">[' + ev.data.node + "]</span> " +
      escapeHtml(prev).slice(0, 500);
    ctx.trace.appendChild(step);
    chat.scrollTop = chat.scrollHeight;
  } else if (ev.event === "final") {
    ctx.setFinal(ev.data.output || "");
  } else if (ev.event === "error") {
    ctx.bubble.textContent = "错误: " + ev.data.message;
  }
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

// ===== 模型 / API Key 配置 =====
const modal = document.getElementById("modal");
const cfgStatus = document.getElementById("cfgStatus");
const cfgProvider = document.getElementById("cfgProvider");
const cfgKey = document.getElementById("cfgKey");
const cfgMsg = document.getElementById("cfgMsg");

async function loadConfig() {
  try {
    const r = await fetch("/api/config");
    const s = await r.json();
    renderConfig(s);
  } catch (e) {
    cfgStatus.textContent = "读取配置失败: " + e;
  }
}

function renderConfig(s) {
  const lines = ["当前模型: " + s.active_model];
  for (const [name, p] of Object.entries(s.providers || {})) {
    const tag = p.configured ? ("已配置 " + p.masked) : "未配置";
    lines.push(`${name}: ${tag}  (${p.model})`);
  }
  cfgStatus.textContent = lines.join("\n");
  cfgStatus.style.whiteSpace = "pre-wrap";
}

document.getElementById("settingsBtn").addEventListener("click", () => {
  cfgMsg.textContent = "";
  cfgKey.value = "";
  modal.classList.remove("modal-hidden");
  loadConfig();
});
document.getElementById("cfgClose").addEventListener("click", () => {
  modal.classList.add("modal-hidden");
});
// 点击遮罩空白处关闭
modal.addEventListener("click", (e) => {
  if (e.target === modal) modal.classList.add("modal-hidden");
});
// Esc 关闭
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") modal.classList.add("modal-hidden");
});

document.getElementById("cfgSave").addEventListener("click", async () => {
  const key = cfgKey.value.trim();
  if (!key) { cfgMsg.className = "cfg-msg err"; cfgMsg.textContent = "请输入 API Key"; return; }
  cfgMsg.className = "cfg-msg";
  cfgMsg.textContent = "保存中…";
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: cfgProvider.value, api_key: key }),
    });
    const data = await r.json();
    if (data.ok) {
      cfgMsg.className = "cfg-msg ok";
      cfgMsg.textContent = "已保存并生效（下次对话使用新 Key）";
      cfgKey.value = "";
      renderConfig(data.status);
    } else {
      cfgMsg.className = "cfg-msg err";
      cfgMsg.textContent = "保存失败: " + (data.error || "未知错误");
    }
  } catch (e) {
    cfgMsg.className = "cfg-msg err";
    cfgMsg.textContent = "请求失败: " + e;
  }
});
