import { describe, expect, it } from "vitest";
import { formatApiError } from "./api";

describe("formatApiError", () => {
  it("unwraps FastAPI string detail", () => {
    expect(formatApiError('{"detail":"repo_path is required"}')).toBe("repo_path is required");
  });

  it("joins validation error messages", () => {
    expect(
      formatApiError('{"detail":[{"loc":["body","repo_path"],"msg":"Field required","type":"missing"}]}'),
    ).toBe("Field required");
  });

  it("falls back to raw text and empty fallback", () => {
    expect(formatApiError("boom")).toBe("boom");
    expect(formatApiError("", "Request failed")).toBe("Request failed");
  });
});
