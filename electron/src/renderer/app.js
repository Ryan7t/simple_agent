const apiBase = window.bossApi.baseUrl;
const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const nudgeBtn = document.getElementById("nudgeBtn");
const clearHistoryBtn = document.getElementById("clearHistory");
const saveConfigBtn = document.getElementById("saveConfigBtn");
const savePromptsBtn = document.getElementById("savePromptsBtn");
const openPromptsBtn = document.getElementById("openPromptsBtn");
const backToChatBtn = document.getElementById("backToChatBtn");
const pickDirBtn = document.getElementById("pickDirBtn");
const modelInput = document.getElementById("modelInput");
const baseUrlInput = document.getElementById("baseUrlInput");
const apiKeyInput = document.getElementById("apiKeyInput");
const docsDirInput = document.getElementById("docsDirInput");
const docList = document.getElementById("docList");
const systemPromptInput = document.getElementById("systemPromptInput");
const contextPromptInput = document.getElementById("contextPromptInput");
const timerStatus = document.getElementById("timerStatus");
const timerRemaining = document.getElementById("timerRemaining");
const timerMeta = document.getElementById("timerMeta");
const timerFill = document.getElementById("timerFill");
const chatPage = document.getElementById("chatPage");
const promptsPage = document.getElementById("promptsPage");
const messageMap = new Map();
let polling = false;

async function apiFetch(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`);
  }
  return response.json();
}

function setStatus(text, ok = true) {
  statusEl.textContent = text;
  statusEl.style.borderColor = ok ? "rgba(27, 29, 31, 0.12)" : "rgba(207, 63, 46, 0.6)";
  statusEl.style.color = ok ? "#1b1d1f" : "#cf3f2e";
}

function createMessage(role, text, options = {}) {
  // New Structure: 
  // <div class="message-row {role}">
  //   <div class="message-role-label">{Label}</div> -- handled via CSS mostly, or distinct el
  //   <div class="message-bubble {extraClass}">{text}</div>
  // </div>

  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  const bubble = document.createElement("div");
  const classes = ["message-bubble"];
  if (options.extraClass) {
    classes.push(options.extraClass);
  }
  bubble.className = classes.join(" ");
  bubble.textContent = text || "";

  // Store ID on the bubble for direct text updates
  if (options.messageId) {
    bubble.dataset.messageId = options.messageId;
  }

  row.appendChild(bubble); // Label will be handled via CSS ::before on row, or explicit el if needed. 
  // Actually, user wants "ME" / "BOSS AGENT" clearly above. 
  // Let's rely on CSS ::before on the ROW or BUBBLE. 
  // Using ROW allows moving it outside the bubble background.

  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble; // Return bubble so existing logic (appendChunk, replaceMessage) works unchanged
}

function appendMessage(role, text) {
  createMessage(role, text);
}

function ensureAssistantMessage(messageId) {
  if (!messageId) {
    return null;
  }
  // messageMap stores the BUBBLE element
  let bubble = messageMap.get(messageId);
  if (!bubble) {
    bubble = createMessage("assistant", "", { messageId });
    messageMap.set(messageId, bubble);
  }
  return bubble;
}

function appendChunk(messageId, text) {
  const bubble = ensureAssistantMessage(messageId);
  if (!bubble) {
    appendMessage("assistant", text);
    return;
  }
  bubble.textContent += text || "";
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function replaceMessage(messageId, text) {
  const bubble = ensureAssistantMessage(messageId);
  if (!bubble) {
    appendMessage("assistant", text);
    return;
  }
  bubble.textContent = text || "";
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showError(messageId, text) {
  const bubble = ensureAssistantMessage(messageId);
  const content = text || "未知错误";
  if (!bubble) {
    createMessage("assistant", content, { extraClass: "error" });
    return;
  }
  bubble.textContent = content;
  bubble.classList.add("error");
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendToolEvent(event) {
  const name = event.name || "unknown_tool";
  const argsText = event.args ? JSON.stringify(event.args) : "{}";
  const resultText = event.result ? String(event.result) : "";
  const message = `工具调用 ${name}(${argsText})\n${resultText}`;
  createMessage("debug", message);
}

function generateMessageId() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function showPromptsPage() {
  if (!chatPage || !promptsPage) {
    return;
  }
  chatPage.classList.add("hidden");
  promptsPage.classList.remove("hidden");
}

function showChatPage() {
  if (!chatPage || !promptsPage) {
    return;
  }
  promptsPage.classList.add("hidden");
  chatPage.classList.remove("hidden");
  messageInput.focus();

  // UI Logic: Update Sidebar Active State
  backToChatBtn.classList.add("active");
  openPromptsBtn.classList.remove("active");
}

/* UI Logic: Auto-resize Input */
function autoResizeInput() {
  this.style.height = 'auto'; // Reset to recalculate
  const newHeight = Math.min(this.scrollHeight, 200); // 200px max height
  this.style.height = (newHeight > 48 ? newHeight : 48) + 'px';
}

messageInput.addEventListener('input', autoResizeInput);
// Also trigger on load/content change if needed, but input event handles typing.


function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "--:--";
  }
  const total = Math.max(0, Math.round(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

async function loadHistory() {
  const data = await apiFetch("/history");
  messageMap.clear();
  messagesEl.innerHTML = "";
  data.items.forEach(item => {
    appendMessage("user", item.user_input);
    appendMessage("assistant", item.response);
  });
}

async function loadConfig() {
  const data = await apiFetch("/config");
  modelInput.value = data.llm_model || "";
  baseUrlInput.value = data.openai_base_url || "";
  apiKeyInput.value = data.openai_api_key || "";
  docsDirInput.value = data.documents_dir || "";
}

async function loadDocuments() {
  const data = await apiFetch("/documents");
  if (data.count === 0) {
    docList.textContent = "未找到 .docx 文案文件";
    return;
  }
  docList.innerHTML = data.files.map(name => `<div>${name}</div>`).join("");
}

async function loadPrompts() {
  const data = await apiFetch("/prompts");
  systemPromptInput.value = data.system_prompt || "";
  contextPromptInput.value = data.context_intro || "";
}

async function loadScheduler() {
  try {
    const data = await apiFetch("/scheduler");
    if (!data.active) {
      timerStatus.textContent = "未设置";
      timerRemaining.textContent = "--:--";
      timerMeta.textContent = "";
      timerFill.style.width = "0%";
      return;
    }

    timerStatus.textContent = "进行中";
    timerRemaining.textContent = formatDuration(data.remaining_seconds);
    if (data.deadline) {
      const deadline = data.deadline.replace("T", " ").split(".")[0];
      timerMeta.textContent = `截止时间 ${deadline}`;
    } else {
      timerMeta.textContent = "";
    }

    if (data.interval_minutes) {
      const total = data.interval_minutes * 60;
      const remaining = Math.max(0, data.remaining_seconds || 0);
      const percent = Math.min(100, Math.max(0, ((total - remaining) / total) * 100));
      timerFill.style.width = `${percent}%`;
    } else {
      timerFill.style.width = "0%";
    }
  } catch (err) {
    timerStatus.textContent = "未连接";
    timerRemaining.textContent = "--:--";
    timerMeta.textContent = "";
    timerFill.style.width = "0%";
  }
}

async function sendMessage() {
  const message = messageInput.value;
  if (!message.trim()) {
    return;
  }
  const messageId = generateMessageId();
  appendMessage("user", message);
  ensureAssistantMessage(messageId);
  messageInput.value = "";
  messageInput.focus();
  setStatus("思考中...");
  try {
    const data = await apiFetch("/chat", {
      method: "POST",
      body: JSON.stringify({ message, message_id: messageId })
    });
    if (data.message_id && data.message_id !== messageId) {
      const bubble = messageMap.get(messageId);
      if (bubble) {
        messageMap.delete(messageId);
        bubble.dataset.messageId = data.message_id;
        messageMap.set(data.message_id, bubble);
      }
    }
    const bubble = messageMap.get(data.message_id || messageId);
    if (bubble && !bubble.textContent) {
      replaceMessage(data.message_id || messageId, data.response || "");
    }
    setStatus("已连接");
  } catch (err) {
    showError(messageId, String(err));
    setStatus("未连接", false);
  }
}

async function sendNudge() {
  const messageId = generateMessageId();
  ensureAssistantMessage(messageId);
  setStatus("思考中...");
  try {
    const data = await apiFetch("/chat", {
      method: "POST",
      body: JSON.stringify({ message: "", message_id: messageId })
    });
    if (data.message_id && data.message_id !== messageId) {
      const bubble = messageMap.get(messageId);
      if (bubble) {
        messageMap.delete(messageId);
        bubble.dataset.messageId = data.message_id;
        messageMap.set(data.message_id, bubble);
      }
    }
    const bubble = messageMap.get(data.message_id || messageId);
    if (bubble && !bubble.textContent) {
      replaceMessage(data.message_id || messageId, data.response || "");
    }
    setStatus("已连接");
  } catch (err) {
    showError(messageId, String(err));
    setStatus("未连接", false);
  }
}

async function saveConfig() {
  setStatus("正在保存配置...");
  await apiFetch("/config", {
    method: "POST",
    body: JSON.stringify({
      llm_model: modelInput.value.trim(),
      openai_base_url: baseUrlInput.value.trim(),
      openai_api_key: apiKeyInput.value.trim(),
      documents_dir: docsDirInput.value.trim()
    })
  });
  await loadDocuments();
  await loadScheduler();
  setStatus("配置已保存");
}

async function savePrompts() {
  setStatus("正在保存提示词...");
  await apiFetch("/prompts", {
    method: "POST",
    body: JSON.stringify({
      system_prompt: systemPromptInput.value,
      context_intro: contextPromptInput.value
    })
  });
  await loadPrompts();
  setStatus("提示词已保存");
}

async function clearHistory() {
  await apiFetch("/history/clear", { method: "POST" });
  messageMap.clear();
  messagesEl.innerHTML = "";
  await loadHistory();
  await loadScheduler();
  setStatus("对话已清空");
}

async function pollEvents() {
  if (polling) {
    return;
  }
  polling = true;
  try {
    const data = await apiFetch("/events");
    if (Array.isArray(data.items)) {
      data.items.forEach(event => {
        if (!event) {
          return;
        }
        if (event.type === "chunk") {
          appendChunk(event.message_id, event.content || "");
          return;
        }
        if (event.type === "replace") {
          replaceMessage(event.message_id, event.content || "");
          return;
        }
        if (event.type === "tool") {
          appendToolEvent(event);
          return;
        }
        if (event.type === "error") {
          showError(event.message_id, event.content || "未知错误");
          return;
        }
        if (event.type === "auto_followup") {
          appendMessage("assistant", event.message || "");
          return;
        }
        if (event.message) {
          appendMessage("assistant", event.message);
          return;
        }
        if (event.content) {
          appendMessage("assistant", event.content);
        }
      });
    }
    await loadScheduler();
  } catch (err) {
    setStatus("未连接", false);
  } finally {
    polling = false;
  }
}

sendBtn.addEventListener("click", sendMessage);
nudgeBtn.addEventListener("click", sendNudge);
messageInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
    // Reset height after send
    messageInput.style.height = 'auto';
  }
});

saveConfigBtn.addEventListener("click", saveConfig);
savePromptsBtn.addEventListener("click", savePrompts);
clearHistoryBtn.addEventListener("click", clearHistory);
openPromptsBtn.addEventListener("click", async () => {
  try {
    await loadPrompts();
  } catch (err) {
    setStatus("未连接", false);
  }
  showPromptsPage();

  // UI Logic: Update Sidebar Active State
  openPromptsBtn.classList.add("active");
  backToChatBtn.classList.remove("active");
});
backToChatBtn.addEventListener("click", showChatPage);

pickDirBtn.addEventListener("click", async () => {
  const selected = await window.bossApi.selectDirectory();
  if (selected) {
    docsDirInput.value = selected;
  }
});

async function init() {
  try {
    await loadConfig();
    await loadPrompts();
    await loadHistory();
    await loadDocuments();
    await loadScheduler();
    setStatus("已连接");
  } catch (err) {
    setStatus("未连接", false);
  }
  setInterval(pollEvents, 500);
}

init();
