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
// historyCount removed; use record_index from server events/history
const toolRowsByMessageId = new Map();
const DEFAULT_REQUEST_TIMEOUT_MS = Number(window.bossApi.requestTimeoutMs || 12000);
const EVENTS_TIMEOUT_MS = Number(window.bossApi.eventsTimeoutMs || 8000);
const STREAM_TIMEOUT_MS = Number(window.bossApi.streamTimeoutMs || 150000);
let polling = false;
let uiBusy = false;
let contextMenu = null;
let contextMenuTarget = null;
let lastSchedulerState = null;  // 存储上一次的调度器状态
const startupDeadline =
  Date.now() + (Number(window.bossApi.startupTimeoutMs) || 30000);

async function apiFetch(path, options = {}, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS) {
  const response = await fetchWithTimeout(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options
  }, timeoutMs);
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`);
  }
  return response.json();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error("timeout");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

function setStatus(text, ok = true) {
  statusEl.textContent = text;
  statusEl.style.borderColor = ok ? "rgba(27, 29, 31, 0.12)" : "rgba(207, 63, 46, 0.6)";
  statusEl.style.color = ok ? "#1b1d1f" : "#cf3f2e";
}

function setUiBusy(busy) {
  uiBusy = busy;
  document.body.classList.toggle("ui-busy", busy);
  const controls = document.querySelectorAll("button, input, textarea, select");
  controls.forEach(control => {
    if (control === messageInput) {
      return;
    }
    control.disabled = busy;
  });
  if (messageInput) {
    messageInput.disabled = false;
  }
}

function isStartingUp() {
  return Date.now() < startupDeadline;
}

function createMessage(role, text, options = {}) {
  // New Structure: 
  // <div class="message-row {role}">
  //   <div class="message-role-label">{Label}</div> -- handled via CSS mostly, or distinct el
  //   <div class="message-bubble {extraClass}">{text}</div>
  // </div>

  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  if (options.rowMessageId) {
    row.dataset.messageId = options.rowMessageId;
  }

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
  bubble.dataset.role = role;
  if (options.recordIndex !== undefined) {
    bubble.dataset.recordIndex = String(options.recordIndex);
  }
  if (options.messageIndex !== undefined) {
    bubble.dataset.messageIndex = String(options.messageIndex);
  }

  bubble.addEventListener("contextmenu", event => {
    event.preventDefault();
    showContextMenu(event.clientX, event.clientY, bubble);
  });

  row.appendChild(bubble); // Label will be handled via CSS ::before on row, or explicit el if needed. 
  // Actually, user wants "ME" / "BOSS AGENT" clearly above. 
  // Let's rely on CSS ::before on the ROW or BUBBLE. 
  // Using ROW allows moving it outside the bubble background.

  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble; // Return bubble so existing logic (appendChunk, replaceMessage) works unchanged
}

function appendMessage(role, text, options = {}) {
  return createMessage(role, text, options);
}

function ensureAssistantMessage(messageId) {
  if (!messageId) {
    return null;
  }
  // messageMap stores the BUBBLE element
  let bubble = messageMap.get(messageId);
  if (!bubble) {
    // 尝试从 DOM 中查找现有的 assistant 气泡
    bubble = messagesEl.querySelector(`.message-bubble[data-message-id="${messageId}"]`);
    if (!bubble) {
      bubble = createMessage("assistant", "", { messageId });
      messageMap.set(messageId, bubble);
    }
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
  const resultText = event.result ? String(event.result).trim() : "";
  const message = resultText
    ? `工具调用 ${name}(${argsText})\n${resultText}`
    : `工具调用 ${name}(${argsText})`;
  const row = createMessage("debug", message, { rowMessageId: event.message_id });
  if (row && event.message_id) {
    if (!toolRowsByMessageId.has(event.message_id)) {
      toolRowsByMessageId.set(event.message_id, []);
    }
    toolRowsByMessageId.get(event.message_id).push(row.parentElement || row);
  }
  if (row && event.record_index !== undefined && event.record_index !== null) {
    const rowEl = row.parentElement || row;
    if (rowEl && rowEl.dataset) {
      rowEl.dataset.recordIndex = String(event.record_index);
    }
  }
  return row;
}

function parseToolArgs(toolCall) {
  if (!toolCall || !toolCall.function) {
    return {};
  }
  const argsText = toolCall.function.arguments;
  if (!argsText) {
    return {};
  }
  try {
    const parsed = JSON.parse(argsText);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    return {};
  }
}


function isTimeoutText(text) {
  const normalized = String(text || "").toLowerCase();
  return (
    normalized.includes("timeout") ||
    normalized.includes("timed out") ||
    normalized.includes("readtimeout") ||
    normalized.includes("etimedout")
  );
}

function isTimeoutEvent(event) {
  if (!event) {
    return false;
  }
  if (event.kind === "timeout") {
    return true;
  }
  return isTimeoutText(event.content || "");
}

function handleTimeout() {
  setUiBusy(false);
  setStatus("已连接");
}

function removeToolMessagesByRecordIndex(recordIndex) {
  if (recordIndex === undefined || recordIndex === null) {
    return;
  }
  const rows = messagesEl.querySelectorAll(`.message-row.debug[data-record-index="${recordIndex}"]`);
  rows.forEach(row => row.remove());
}

function startEditBubble(bubble) {
  if (!bubble || bubble.isContentEditable) {
    return;
  }
  const original = bubble.textContent || "";
  bubble.dataset.originalText = original;
  bubble.contentEditable = "true";
  bubble.focus();
  document.execCommand("selectAll", false, null);

  const onBlur = async () => {
    bubble.removeEventListener("blur", onBlur);
    bubble.removeEventListener("keydown", onKeydown);
    bubble.contentEditable = "false";
    const updated = bubble.textContent || "";
    if (updated === original) {
      return;
    }
    const recordIndex = bubble.dataset.recordIndex;
    const messageIndex = bubble.dataset.messageIndex;
    const role = bubble.dataset.role;
    if (recordIndex !== undefined) {
      await apiFetch("/history/update", {
        method: "POST",
        body: JSON.stringify({
          record_index: Number(recordIndex),
          message_index: messageIndex !== undefined ? Number(messageIndex) : null,
          role,
          content: updated
        })
      });
    }
  };

  const onKeydown = event => {
    if (event.key === "Escape") {
      bubble.textContent = original;
      bubble.blur();
      return;
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      bubble.blur();
    }
  };

  bubble.addEventListener("blur", onBlur);
  bubble.addEventListener("keydown", onKeydown);
}

function showContextMenu(x, y, bubble) {
  if (!contextMenu) {
    contextMenu = document.createElement("div");
    contextMenu.className = "context-menu";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "context-menu-btn";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => {
      if (!contextMenuTarget) {
        hideContextMenu();
        return;
      }
      startEditBubble(contextMenuTarget.bubble);
      hideContextMenu();
    });

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "context-menu-btn";
    retryBtn.dataset.action = "retry";
    retryBtn.textContent = "重试";
    retryBtn.addEventListener("click", async () => {
      if (!contextMenuTarget) {
        hideContextMenu();
        return;
      }
      const { bubble: targetBubble, recordIndex } = contextMenuTarget;
      if (uiBusy) {
        hideContextMenu();
        return;
      }
      if (recordIndex === undefined || recordIndex === null || recordIndex === "") {
        hideContextMenu();
        return;
      }
      targetBubble.classList.remove("error");
      targetBubble.textContent = "";
      removeToolMessagesByRecordIndex(recordIndex);
      hideContextMenu();
      setStatus("思考中...");
      setUiBusy(true);
      streamRetry(Number(recordIndex), targetBubble).catch(() => {
        setUiBusy(false);
        setStatus("未连接", false);
      });
    });

    contextMenu.appendChild(editBtn);
    contextMenu.appendChild(retryBtn);
    document.body.appendChild(contextMenu);
  }

  const recordIndex = bubble.dataset.recordIndex;
  const role = bubble.dataset.role;
  const canRetry = role === "assistant" && recordIndex !== undefined && recordIndex !== null && recordIndex !== "";
  const retryBtn = contextMenu.querySelector('[data-action="retry"]');
  if (retryBtn) {
    retryBtn.style.display = canRetry ? "block" : "none";
  }

  contextMenuTarget = { bubble, recordIndex };
  contextMenu.style.left = `${x}px`;
  contextMenu.style.top = `${y}px`;
  contextMenu.classList.add("visible");
}

function hideContextMenu() {
  if (!contextMenu) {
    return;
  }
  contextMenu.classList.remove("visible");
  contextMenuTarget = null;
}

document.addEventListener("click", event => {
  if (!contextMenu || !contextMenu.classList.contains("visible")) {
    return;
  }
  if (contextMenu.contains(event.target)) {
    return;
  }
  hideContextMenu();
});

window.addEventListener("blur", hideContextMenu);

function handleStreamEvent(event, fallbackMessageId) {
  if (!event) {
    return;
  }
  const messageId = event.message_id || fallbackMessageId;
  if (event.type === "chunk") {
    appendChunk(messageId, event.content || "");
    return;
  }
  if (event.type === "replace") {
    replaceMessage(messageId, event.content || "");
    return;
  }
  if (event.type === "tool") {
    appendToolEvent(event);
    return;
  }
  if (event.type === "error") {
    if (isTimeoutEvent(event)) {
      handleTimeout();
      return;
    }
    const content = event.content || "未知错误";
    showError(messageId, content);
    setStatus("未连接", false);
    setUiBusy(false);
    return;
  }
  if (event.type === "scheduler_update" && event.data) {
    renderScheduler(event.data);
    return;
  }
  if (event.type === "done") {
    if (event.response) {
      const bubble = messageMap.get(messageId);
      if (bubble && !bubble.textContent) {
        replaceMessage(messageId, event.response);
      }
    }
    setStatus("已连接");
    setUiBusy(false);
    // 清理已完成的 messageMap 条目
    messageMap.delete(messageId);
    toolRowsByMessageId.delete(messageId);
    if (event.saved && event.record_index !== undefined && event.record_index !== null) {
      const recordIndex = event.record_index;
      const assistantBubble = messageMap.get(messageId);
      if (assistantBubble) {
        assistantBubble.dataset.recordIndex = String(recordIndex);
        assistantBubble.dataset.messageIndex = "-1";
        assistantBubble.dataset.role = "assistant";
      }
      const userBubble = messagesEl.querySelector(`.message-row.user .message-bubble[data-message-id="${messageId}"]`);
      if (userBubble) {
        userBubble.dataset.recordIndex = String(recordIndex);
        userBubble.dataset.messageIndex = "0";
        userBubble.dataset.role = "user";
      }
      const toolRows = toolRowsByMessageId.get(messageId) || [];
      toolRows.forEach(row => {
        if (row && row.classList && row.classList.contains("message-row")) {
          row.dataset.recordIndex = String(recordIndex);
        }
      });
      toolRowsByMessageId.delete(messageId);
    }
  }
}

async function streamChat(message, messageId) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);
  let reader = null;
  try {
    const response = await fetch(`${apiBase}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, message_id: messageId }),
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }
    if (!response.body) {
      const data = await response.json();
      handleStreamEvent({ type: "done", message_id: data.message_id || messageId, response: data.response }, messageId);
      return;
    }
    reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) {
          return;
        }
        try {
          handleStreamEvent(JSON.parse(trimmed), messageId);
        } catch (err) {
          // ignore malformed fragments
        }
      });
    }
    if (buffer.trim()) {
      try {
        handleStreamEvent(JSON.parse(buffer.trim()), messageId);
      } catch (err) {
        // ignore trailing fragments
      }
    }
    if (uiBusy) {
      setUiBusy(false);
    }
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error("timeout");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    try {
      reader?.cancel();
    } catch (err) {
      // ignore
    }
  }
}

async function streamRetry(recordIndex, bubble) {
  const messageId = generateMessageId();
  messageMap.set(messageId, bubble);
  bubble.dataset.messageId = messageId;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);
  let reader = null;
  try {
    const response = await fetch(`${apiBase}/history/retry/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_index: recordIndex, message_id: messageId }),
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }
    if (!response.body) {
      const data = await response.json();
      handleStreamEvent(
        { type: "done", message_id: data.message_id || messageId, response: data.response, saved: data.saved, record_index: recordIndex },
        messageId
      );
      return;
    }
    reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) {
          return;
        }
        try {
          handleStreamEvent(JSON.parse(trimmed), messageId);
        } catch (err) {
          // ignore malformed fragments
        }
      });
    }
    if (buffer.trim()) {
      try {
        handleStreamEvent(JSON.parse(buffer.trim()), messageId);
      } catch (err) {
        // ignore trailing fragments
      }
    }
    if (uiBusy) {
      setUiBusy(false);
    }
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error("timeout");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    try {
      reader?.cancel();
    } catch (err) {
      // ignore
    }
  }
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

  // UI Logic: Update Sidebar Active State
  openPromptsBtn.classList.add("active");
  backToChatBtn.classList.remove("active");
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
    const toolCallMap = new Map();
    const recordIndex = item.record_index ?? null;
    // 新格式：完整消息列表
    if (item.messages && Array.isArray(item.messages)) {
      item.messages.forEach((msg, messageIndex) => {
        if (msg.role === "user") {
          // 过滤掉系统触发的消息（以括号开头）
          if (!msg.content.startsWith("（") && !msg.content.startsWith("(")) {
            const bubble = appendMessage("user", msg.content, {
              recordIndex,
              messageIndex
            });
            if (bubble) {
              bubble.dataset.role = "user";
            }
          }
        } else if (msg.role === "assistant") {
          const content = msg.content || "";
          if (content.trim()) {
            const bubble = appendMessage("assistant", content, {
              recordIndex,
              messageIndex
            });
            if (bubble) {
              bubble.dataset.role = "assistant";
            }
          }
          if (Array.isArray(msg.tool_calls)) {
            msg.tool_calls.forEach(call => {
              if (call && call.id) {
                toolCallMap.set(call.id, call);
              }
            });
          }
        } else if (msg.role === "tool") {
          const toolCall = toolCallMap.get(msg.tool_call_id);
          const name = toolCall?.function?.name || msg.tool_call_id || "unknown_tool";
          const args = parseToolArgs(toolCall);
          const result = msg.content || "";
          const row = appendToolEvent({ name, args, result, message_id: "" });
          if (row && row.parentElement) {
            row.parentElement.dataset.recordIndex = String(recordIndex);
          }
        }
      });
    }
    // 旧格式兼容：user_input + response
    else if (item.user_input && item.response) {
      // 过滤掉系统触发的消息
      if (!item.user_input.startsWith("（") && !item.user_input.startsWith("(")) {
        appendMessage("user", item.user_input, {
          recordIndex,
          messageIndex: 0
        });
      }
      appendMessage("assistant", item.response, {
        recordIndex,
        messageIndex: 1
      });
    }
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

function renderScheduler(data) {
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
}

async function loadScheduler() {
  try {
    const data = await apiFetch("/scheduler");
    renderScheduler(data);
  } catch (err) {
    timerStatus.textContent = "未连接";
    timerRemaining.textContent = "--:--";
    timerMeta.textContent = "";
    timerFill.style.width = "0%";
  }
}

async function sendMessage() {
  if (uiBusy) {
    return;
  }
  const message = messageInput.value;
  if (!message.trim()) {
    return;
  }
  const messageId = generateMessageId();
  const userBubble = appendMessage("user", message);
  userBubble.dataset.messageId = messageId;
  userBubble.dataset.role = "user";
  ensureAssistantMessage(messageId);
  messageInput.value = "";

  // Reset input height immediately after sending
  autoResizeInput.call(messageInput);

  messageInput.focus();
  setStatus("思考中...");
  setUiBusy(true);
  try {
    await streamChat(message, messageId);
  } catch (err) {
    const errText = String(err);
    if (isTimeoutText(errText)) {
      handleTimeout();
      return;
    }
    showError(messageId, errText);
    setStatus("未连接", false);
    setUiBusy(false);
  }
}

async function sendNudge() {
  if (uiBusy) {
    return;
  }
  const messageId = generateMessageId();
  ensureAssistantMessage(messageId);
  setStatus("思考中...");
  setUiBusy(true);
  try {
    await streamChat("", messageId);
  } catch (err) {
    const errText = String(err);
    if (isTimeoutText(errText)) {
      handleTimeout();
      return;
    }
    showError(messageId, errText);
    setStatus("未连接", false);
    setUiBusy(false);
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
    const data = await apiFetch("/events", {}, EVENTS_TIMEOUT_MS);
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
    // 主动获取最新调度器状态并对比
    const currentData = await apiFetch("/scheduler");
    if (JSON.stringify(currentData) !== JSON.stringify(lastSchedulerState)) {
      renderScheduler(currentData);
      lastSchedulerState = currentData;
    }
  } catch (err) {
    if (isTimeoutText(String(err))) {
      if (isStartingUp()) {
        setStatus("后端启动中...", true);
      }
      return;
    }
    if (isStartingUp()) {
      setStatus("后端启动中...", true);
    } else {
      setStatus("未连接", false);
    }
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
  }
});

saveConfigBtn.addEventListener("click", saveConfig);
savePromptsBtn.addEventListener("click", savePrompts);
clearHistoryBtn.addEventListener("click", clearHistory);
openPromptsBtn.addEventListener("click", async () => {
  showPromptsPage();
  try {
    await loadPrompts();
  } catch (err) {
    setStatus("未连接", false);
  }
});
backToChatBtn.addEventListener("click", showChatPage);

pickDirBtn.addEventListener("click", async () => {
  const selected = await window.bossApi.selectDirectory();
  if (selected) {
    docsDirInput.value = selected;
  }
});

async function init() {
  setStatus("后端启动中...", true);
  try {
    await loadConfig();
    await loadPrompts();
    await loadHistory();
    await loadDocuments();
    await loadScheduler();
    setStatus("已连接");
  } catch (err) {
    if (isStartingUp()) {
      setStatus("后端启动中...", true);
    } else {
      setStatus("未连接", false);
    }
  }
  setInterval(pollEvents, 500);
}

init();
