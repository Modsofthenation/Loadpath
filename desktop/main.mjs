import { app, BrowserWindow, dialog, shell } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { backendCommand, pickFreePort, waitForHealth } from "./backend.mjs";
import { isAllowedExternalUrl, isAppOrigin, isEditorUrl } from "./urls.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let backendProcess = null;
let backendPort = null;
let mainWindow = null;
let quitting = false;

function repoRoot() {
  return path.resolve(__dirname, "..");
}

function openExternalIfAllowed(url) {
  if (!isAllowedExternalUrl(url) && !isEditorUrl(url)) return;
  shell.openExternal(url).catch((err) => {
    dialog.showErrorBox("Loadpath", `Could not open link: ${err.message}`);
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "Loadpath",
    backgroundColor: "#070b10",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  if (process.platform !== "darwin") {
    win.setMenuBarVisibility(false);
  }
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalIfAllowed(url);
    return { action: "deny" };
  });
  win.webContents.on("will-attach-webview", (event) => event.preventDefault());
  win.once("ready-to-show", () => win.show());
  return win;
}

function splashUrl() {
  const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>Loadpath</title>
<style>
  html,body{height:100%;margin:0;background:#070b10;color:#e7eef6;
    font:500 15px/1.4 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif}
  main{height:100%;display:grid;place-items:center}
  p{margin:0;letter-spacing:.04em;color:#8b9bb0}
</style></head>
<body><main><p>Starting Loadpath…</p></main></body></html>`;
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}

function stopBackend() {
  backendPort = null;
  if (!backendProcess || backendProcess.killed) return;
  backendProcess.kill();
  backendProcess = null;
}

async function startBackend() {
  const port = await pickFreePort();
  const { command, args, cwd, env } = backendCommand({
    packaged: app.isPackaged,
    platform: process.platform,
    port,
    resourcesPath: process.resourcesPath,
    python: process.env.LOADPATH_PYTHON,
    repoRoot: repoRoot(),
  });
  const logDir = app.getPath("userData");
  fs.mkdirSync(logDir, { recursive: true });
  const logPath = path.join(logDir, "backend.log");
  const log = fs.createWriteStream(logPath, { flags: "a" });
  log.write(`\n[${new Date().toISOString()}] ${command} ${args.join(" ")}\n`);

  backendProcess = spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backendProcess.stdout.pipe(log);
  backendProcess.stderr.pipe(log);
  backendProcess.on("error", (err) => {
    log.write(`spawn error: ${err.message}\n`);
  });
  backendProcess.on("exit", () => {
    backendPort = null;
  });

  try {
    await waitForHealth(`http://127.0.0.1:${port}`, {
      isAborted: () => Boolean(backendProcess?.exitCode != null || backendProcess?.signalCode),
    });
  } catch (err) {
    stopBackend();
    throw new Error(`${err.message}\nLog: ${logPath}`);
  }
  backendPort = port;
  return port;
}

async function ensureBackend() {
  if (backendProcess && backendProcess.exitCode == null && backendPort) {
    return backendPort;
  }
  return startBackend();
}

async function boot() {
  mainWindow = createWindow();
  await mainWindow.loadURL(splashUrl());
  try {
    const port = await ensureBackend();
    mainWindow.webContents.on("will-navigate", (event, url) => {
      if (isAppOrigin(url, port)) return;
      event.preventDefault();
      openExternalIfAllowed(url);
    });
    await mainWindow.loadURL(`http://127.0.0.1:${port}`);
    if (process.env.LOADPATH_DEVTOOLS === "1") {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    dialog.showErrorBox("Loadpath failed to start", message);
    app.quit();
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.whenReady().then(boot);
  app.on("before-quit", () => {
    quitting = true;
    stopBackend();
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0 && !quitting) boot();
  });
}
