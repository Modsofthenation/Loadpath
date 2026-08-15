import assert from "node:assert/strict";
import path from "node:path";
import { describe, it } from "node:test";

import { backendBinaryName, backendCommand, waitForHealth } from "./backend.mjs";

describe("backendBinaryName", () => {
  it("uses .exe on Windows", () => {
    assert.equal(backendBinaryName("win32"), "loadpath.exe");
  });

  it("uses a bare name on macOS and Linux", () => {
    assert.equal(backendBinaryName("darwin"), "loadpath");
    assert.equal(backendBinaryName("linux"), "loadpath");
  });
});

describe("backendCommand", () => {
  it("runs python -m loadpath serve in development", () => {
    const result = backendCommand({
      packaged: false,
      platform: "linux",
      port: 7345,
      python: "python3",
      repoRoot: "/repo",
    });
    assert.equal(result.command, "python3");
    assert.deepEqual(result.args, [
      "-m",
      "loadpath",
      "serve",
      "--host",
      "127.0.0.1",
      "--port",
      "7345",
      "--no-open",
    ]);
    assert.equal(result.cwd, "/repo");
    assert.equal(result.env.PYTHONPATH, path.join("/repo", "src"));
  });

  it("defaults to python.exe-style interpreter name on Windows", () => {
    const result = backendCommand({
      packaged: false,
      platform: "win32",
      port: 8000,
      repoRoot: "C:\\\\src",
    });
    assert.equal(result.command, "python");
    assert.equal(result.args[6], "8000");
  });

  it("points at the bundled sidecar when packaged", () => {
    const result = backendCommand({
      packaged: true,
      platform: "darwin",
      port: 9000,
      resourcesPath: "/App/Contents/Resources",
    });
    assert.equal(result.command, path.join("/App/Contents/Resources", "loadpath", "loadpath"));
    assert.deepEqual(result.args, ["serve", "--host", "127.0.0.1", "--port", "9000", "--no-open"]);
    assert.equal(result.cwd, undefined);
  });

  it("uses loadpath.exe under extraResources on Windows", () => {
    const result = backendCommand({
      packaged: true,
      platform: "win32",
      port: 7345,
      resourcesPath: "C:\\\\app\\\\resources",
    });
    assert.equal(result.command, path.join("C:\\\\app\\\\resources", "loadpath", "loadpath.exe"));
  });
});

describe("waitForHealth", () => {
  it("returns once /api/health is ok", async () => {
    let calls = 0;
    const body = await waitForHealth("http://127.0.0.1:9", {
      timeoutMs: 1000,
      intervalMs: 1,
      fetchImpl: async (url) => {
        calls += 1;
        assert.equal(url, "http://127.0.0.1:9/api/health");
        if (calls < 3) throw new Error("connection refused");
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "ok", version: "0.1.0" }),
        };
      },
    });
    assert.equal(calls, 3);
    assert.equal(body.status, "ok");
  });

  it("fails when the backend process already exited", async () => {
    await assert.rejects(
      () =>
        waitForHealth("http://127.0.0.1:9", {
          timeoutMs: 500,
          intervalMs: 1,
          isAborted: () => true,
          fetchImpl: async () => {
            throw new Error("should not fetch");
          },
        }),
      /exited before it became ready/,
    );
  });
});
