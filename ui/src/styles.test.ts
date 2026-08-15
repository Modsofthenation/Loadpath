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
    expect(getComputedStyle(inspector).overflowY).toBe("auto");
    expect(getComputedStyle(inspector).maxWidth).not.toBe("none");
    expect(getComputedStyle(inspector).maxHeight).not.toBe("none");
    expect(getComputedStyle(name).overflowWrap).toBe("break-word");
  });

  it("lets inspector fact values shrink and wrap", () => {
    mount(
      `<aside class="inspector"><div class="inspector-fact"><dt>Type</dt><dd>VeryLongDecimalFieldNameThatShouldWrap</dd></div></aside>`,
    );
    const fact = document.querySelector(".inspector-fact") as HTMLElement;
    const dd = document.querySelector(".inspector-fact dd") as HTMLElement;
    expect(getComputedStyle(fact).display).toBe("grid");
    expect(getComputedStyle(dd).overflowWrap).toBe("break-word");
  });

  it("gives the inspector close control a 24px target", () => {
    mount(`<aside class="inspector"><button class="inspector-close">×</button></aside>`);
    const btn = document.querySelector(".inspector-close") as HTMLElement;
    expect(getComputedStyle(btn).width).toBe("24px");
    expect(getComputedStyle(btn).height).toBe("24px");
  });

  it("clamps long titles inside graph nodes to two lines", () => {
    mount(`<div class="lp-node"><div class="n">test_index_summary_includes_contexts_and_more</div></div>`);
    const box = document.querySelector(".lp-node") as HTMLElement;
    const name = document.querySelector(".lp-node .n") as HTMLElement;
    const style = getComputedStyle(name);
    expect(getComputedStyle(box).width).toBe("208px");
    expect(getComputedStyle(box).height).toBe("64px");
    expect(style.overflow).toBe("hidden");
    expect(style.display).toBe("-webkit-box");
    expect(style.webkitLineClamp).toBe("2");
  });
});
