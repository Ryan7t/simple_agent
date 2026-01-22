const { app, BrowserWindow, ipcMain, dialog, Menu } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const path = require("path");
const http = require("http");

const DEFAULT_PORT = 8765;
const BACKEND_STARTUP_SOFT_TIMEOUT_MS = Number(process.env.BOSS_BACKEND_SOFT_TIMEOUT_MS || 15000);
const BACKEND_STARTUP_TIMEOUT_MS = Number(process.env.BOSS_BACKEND_TIMEOUT_MS || 30000);
let backendProcess = null;
let mainWindow = null;
let backendLogPath = null;
let backendLogStream = null;
let backendStartError = null;
let backendExitInfo = null;

function resolveBackendCommand(port) {
  if (app.isPackaged) {
    const backendName = process.platform === "win32" ? "backend.exe" : "backend";
    const backendPath = path.join(process.resourcesPath, "backend", backendName);
    return { command: backendPath, args: ["--host", "127.0.0.1", "--port", String(port)] };
  }

  const pythonCmd = process.env.BOSS_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const serverScript = path.join(__dirname, "..", "..", "server.py");
  return { command: pythonCmd, args: [serverScript, "--host", "127.0.0.1", "--port", String(port)] };
}

function initBackendLog() {
  const logDir = app.getPath("userData");
  fs.mkdirSync(logDir, { recursive: true });
  backendLogPath = path.join(logDir, "backend.log");
  backendLogStream = fs.createWriteStream(backendLogPath, { flags: "w" });
  backendLogStream.write(`[${new Date().toISOString()}] Backend startup log\n`);
}

function writeBackendLog(message) {
  if (!backendLogStream) {
    return;
  }
  backendLogStream.write(`${message}\n`);
}

function startBackend(port) {
  const { command, args } = resolveBackendCommand(port);
  backendStartError = null;
  backendExitInfo = null;
  initBackendLog();
  writeBackendLog(`command: ${command} ${args.join(" ")}`);
  backendProcess = spawn(command, args, {
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
    env: {
      ...process.env,
      BOSS_DATA_DIR: app.getPath("userData")
    }
  });
  writeBackendLog(`data_dir: ${app.getPath("userData")}`);
  writeBackendLog(`port: ${port}`);

  if (backendProcess.stdout) {
    backendProcess.stdout.on("data", data => {
      backendLogStream?.write(data);
    });
  }
  if (backendProcess.stderr) {
    backendProcess.stderr.on("data", data => {
      backendLogStream?.write(data);
    });
  }
  backendProcess.on("error", err => {
    backendStartError = err;
    writeBackendLog(`[error] ${err.stack || err.message || String(err)}`);
  });
  backendProcess.on("exit", (code, signal) => {
    backendExitInfo = { code, signal };
    writeBackendLog(`[exit] code=${code ?? "null"} signal=${signal ?? "null"}`);
  });
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  try {
    backendProcess.kill();
  } catch (err) {
    // ignore shutdown errors
  }
  if (backendLogStream) {
    backendLogStream.end();
  }
  backendProcess = null;
  backendLogStream = null;
}

function waitForBackend(port, timeoutMs = BACKEND_STARTUP_TIMEOUT_MS) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      if (backendStartError) {
        reject(backendStartError);
        return;
      }
      if (backendExitInfo) {
        const { code, signal } = backendExitInfo;
        reject(new Error(`Backend exited (code=${code ?? "null"}, signal=${signal ?? "null"})`));
        return;
      }
      const req = http.get(`http://127.0.0.1:${port}/health`, res => {
        if (res.statusCode === 200) {
          res.resume();
          resolve();
          return;
        }
        res.resume();
        retry();
      });
      req.on("error", retry);
    };

    const retry = () => {
      const elapsed = Date.now() - start;
      const softTimeout = Math.min(BACKEND_STARTUP_SOFT_TIMEOUT_MS, timeoutMs);
      if (elapsed > timeoutMs) {
        reject(new Error("Backend did not respond in time."));
        return;
      }
      setTimeout(check, elapsed > softTimeout ? 500 : 300);
    };

    check();
  });
}

function readBackendLogTail(maxBytes = 6000) {
  if (!backendLogPath || !fs.existsSync(backendLogPath)) {
    return "";
  }
  try {
    const stats = fs.statSync(backendLogPath);
    const size = stats.size;
    if (size <= maxBytes) {
      return fs.readFileSync(backendLogPath, "utf-8");
    }
    const fd = fs.openSync(backendLogPath, "r");
    const buffer = Buffer.alloc(maxBytes);
    fs.readSync(fd, buffer, 0, maxBytes, size - maxBytes);
    fs.closeSync(fd);
    return buffer.toString("utf-8");
  } catch (err) {
    return "";
  }
}

async function findAvailablePort(preferredPort) {
  const tryListen = port =>
    new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once("error", reject);
      server.listen(port, "127.0.0.1", () => {
        const address = server.address();
        const actualPort = typeof address === "object" ? address.port : port;
        server.close(() => resolve(actualPort));
      });
    });

  if (preferredPort) {
    try {
      return await tryListen(preferredPort);
    } catch (err) {
      writeBackendLog(`[warn] preferred port ${preferredPort} unavailable: ${err.code || err.message}`);
    }
  }
  return tryListen(0);
}

function createMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac
      ? [
          {
            label: "BossAgent",
            submenu: [
              { role: "about", label: "关于" },
              { type: "separator" },
              { role: "hide", label: "隐藏" },
              { role: "hideOthers", label: "隐藏其他" },
              { role: "unhide", label: "显示全部" },
              { type: "separator" },
              { role: "quit", label: "退出" }
            ]
          }
        ]
      : []),
    {
      label: "文件",
      submenu: [
        {
          label: "刷新",
          accelerator: "CmdOrCtrl+R",
          click: () => {
            if (mainWindow) {
              mainWindow.reload();
            }
          }
        },
        {
          label: "重新加载",
          accelerator: "CmdOrCtrl+Shift+R",
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.reloadIgnoringCache();
            }
          }
        },
        { type: "separator" },
        { role: isMac ? "close" : "quit", label: isMac ? "关闭窗口" : "退出" }
      ]
    },
    {
      label: "查看",
      submenu: [
        {
          label: "打开调试面板",
          accelerator: isMac ? "Alt+Cmd+I" : "Ctrl+Shift+I",
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.toggleDevTools();
            }
          }
        },
        { type: "separator" },
        { role: "togglefullscreen", label: "全屏" }
      ]
    },
    {
      label: "窗口",
      submenu: [
        { role: "minimize", label: "最小化" },
        { role: "zoom", label: "缩放" }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

function createWindow(port) {
  process.env.BOSS_API_BASE = `http://127.0.0.1:${port}`;

  const win = new BrowserWindow({
    width: 1200,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0f1113",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow = win;
  createMenu();
}

app.whenReady().then(async () => {
  const preferredPort = Number(process.env.BOSS_BACKEND_PORT || DEFAULT_PORT);
  let port = preferredPort;
  try {
    port = await findAvailablePort(preferredPort);
  } catch (err) {
    dialog.showErrorBox("Backend Error", `无法获取可用端口: ${err.message}`);
    app.quit();
    return;
  }
  process.env.BOSS_STARTUP_TIMEOUT_MS = String(BACKEND_STARTUP_TIMEOUT_MS);
  startBackend(port);
  createWindow(port);

  try {
    await waitForBackend(port);
  } catch (err) {
    if (backendLogStream) {
      backendLogStream.end();
      backendLogStream = null;
    }
    const logTail = readBackendLogTail();
    const logHint = backendLogPath ? `\n\n日志文件: ${backendLogPath}` : "";
    const details = logTail ? `\n\n日志内容:\n${logTail}` : "";
    dialog.showErrorBox("Backend Error", `${err.message}${logHint}${details}`);
    if (mainWindow) {
      mainWindow.close();
    }
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

ipcMain.handle("select-directory", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openDirectory"]
  });
  if (result.canceled || result.filePaths.length === 0) {
    return "";
  }
  return result.filePaths[0];
});
