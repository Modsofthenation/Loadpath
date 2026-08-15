import net from "node:net";
import path from "node:path";

export function backendBinaryName(platform) {
  return platform === "win32" ? "loadpath.exe" : "loadpath";
}

export function backendCommand({
  packaged,
  platform,
  port,
  resourcesPath,
  python,
  repoRoot,
}) {
  const serveArgs = ["serve", "--host", "127.0.0.1", "--port", String(port), "--no-open"];
  if (packaged) {
    return {
      command: path.join(resourcesPath, "loadpath", backendBinaryName(platform)),
      args: serveArgs,
      cwd: undefined,
      env: {},
    };
  }
  const command = python || (platform === "win32" ? "python" : "python3");
  return {
    command,
    args: ["-m", "loadpath", ...serveArgs],
    cwd: repoRoot,
    env: repoRoot ? { PYTHONPATH: path.join(repoRoot, "src") } : {},
  };
}

export function pickFreePort(host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((err) => (err ? reject(err) : resolve(port)));
    });
  });
}

export async function waitForHealth(baseUrl, options = {}) {
  const {
    fetchImpl = globalThis.fetch,
    timeoutMs = 45_000,
    intervalMs = 200,
    isAborted = () => false,
  } = options;
  const url = `${String(baseUrl).replace(/\/$/, "")}/api/health`;
  const start = Date.now();
  let lastError = "backend did not become ready";
  while (Date.now() - start < timeoutMs) {
    if (isAborted()) {
      throw new Error("backend exited before it became ready");
    }
    try {
      const res = await fetchImpl(url, { signal: AbortSignal.timeout(1500) });
      if (res.ok) {
        return res.json().catch(() => ({}));
      }
      lastError = `health check HTTP ${res.status}`;
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Loadpath backend failed to start: ${lastError}`);
}
