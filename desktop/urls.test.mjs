import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isAllowedExternalUrl, isAppOrigin, isEditorUrl } from "./urls.mjs";

describe("isAllowedExternalUrl", () => {
  it("allows GitHub, GitLab, and Bitbucket https PR links", () => {
    assert.equal(isAllowedExternalUrl("https://github.com/acme/demo/pull/12"), true);
    assert.equal(isAllowedExternalUrl("https://bitbucket.org/acme/demo/pull-requests/3"), true);
    assert.equal(isAllowedExternalUrl("https://gitlab.com/acme/demo/-/merge_requests/4"), true);
    assert.equal(isAllowedExternalUrl("https://id.atlassian.com/login"), true);
    assert.equal(isAllowedExternalUrl("https://github.mycompany.com/acme/demo/pull/1"), true);
    assert.equal(isAllowedExternalUrl("https://gitlab.internal.example/acme/demo/-/merge_requests/2"), true);
  });

  it("rejects credentials, other hosts, and non-https schemes", () => {
    assert.equal(isAllowedExternalUrl("https://user:pass@github.com/acme/demo"), false);
    assert.equal(isAllowedExternalUrl("https://github.com.evil.example/acme"), false);
    assert.equal(isAllowedExternalUrl("https://evil.example/github.com"), false);
    assert.equal(isAllowedExternalUrl("http://github.com/acme/demo"), false);
    assert.equal(isAllowedExternalUrl("file:///etc/passwd"), false);
    assert.equal(isAllowedExternalUrl("javascript:alert(1)"), false);
    assert.equal(isAllowedExternalUrl("not a url"), false);
  });
});

describe("isEditorUrl", () => {
  it("allows vscode and cursor file URLs without credentials", () => {
    assert.equal(isEditorUrl("vscode://file/tmp/acme/a.py:12"), true);
    assert.equal(isEditorUrl("cursor://file/tmp/acme/a.py"), true);
    assert.equal(isEditorUrl("vscode://user:pass@file/tmp"), false);
    assert.equal(isEditorUrl("https://github.com"), false);
  });
});

describe("isAppOrigin", () => {
  it("allows only the loopback backend origin", () => {
    assert.equal(isAppOrigin("http://127.0.0.1:7345/api/health", 7345), true);
    assert.equal(isAppOrigin("http://127.0.0.1:7345/", 9000), false);
    assert.equal(isAppOrigin("http://localhost:7345/", 7345), false);
    assert.equal(isAppOrigin("https://127.0.0.1:7345/", 7345), false);
  });
});
