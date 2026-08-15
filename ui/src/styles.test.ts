import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "styles.css"), "utf8");

function mount(html: string) {
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);
  document.body.innerHTML = html;
}

describe("graph selected-node overflow", () => {
  afterEach(() => {
    document.head.replaceChildren();
    document.body.replaceChildren();
  });

  it("wraps long identifiers in the selected-node inspector", () => {
    mount(
      `<aside class="inspector"><div class="n">test_index_summary_includes_contexts_and_more</div><div class="file">tests/e2e/test_index_architecture_flow.py</div></aside>`,
    );
    const inspector = document.querySelector(".inspector") as HTMLElement;
    const name = document.querySelector(".inspector .n") as HTMLElement;
    expect(getComputedStyle(inspector).overflowWrap).toBe("break-word");
    expect(getComputedStyle(inspector).overflowX).toBe("hidden");
    expect(getComputedStyle(inspector).maxWidth).not.toBe("none");
    expect(getComputedStyle(name).overflowWrap).toBe("break-word");
  });

  it("ellipsizes long titles inside graph nodes", () => {
    mount(`<div class="lp-node"><div class="n">test_index_summary_includes_contexts_and_more</div></div>`);
    const name = document.querySelector(".lp-node .n") as HTMLElement;
    expect(getComputedStyle(name).textOverflow).toBe("ellipsis");
    expect(getComputedStyle(name).overflow).toBe("hidden");
    expect(getComputedStyle(name).whiteSpace).toBe("nowrap");
  });
});
