"use strict";

// Injected alone into the top frame's ISOLATED world on an explicit reader request.
async function readInspectSimplified() {
  const expected = "https://novelai.net/inspect";
  const fail = code => { throw Object.assign(new Error(), {code}); };
  const atInspect = () => window === window.top && location.href === expected;
  const rows = "div.sc-a379a597-6";
  const labelSelector = "span.sc-a379a597-3";
  const valueSelector = "span.sc-a379a597-5";

  function visible(node) {
    if (!node?.isConnected || !node.getClientRects().length) return false;
    for (let el = node; el; el = el.parentElement) {
      const style = getComputedStyle(el);
      if (el.hidden || el.inert || el.getAttribute("aria-hidden") === "true" ||
          style.display === "none" || style.visibility !== "visible" || style.opacity === "0" ||
          style.contentVisibility === "hidden") return false;
    }
    return true;
  }

  function view() {
    if (!atInspect()) fail("inspect_changed");
    if ([...document.querySelectorAll('dialog[open],[aria-modal="true"],[role="dialog"]')].some(visible))
      fail("inspect_overlay");
    const buttons = [...document.querySelectorAll("button")].filter(visible);
    const simple = buttons.filter(b => b.innerText.trim() === "Simplified");
    const raw = buttons.filter(b => b.innerText.trim() === "Raw Parameters");
    if (!simple.length && !raw.length) fail("inspect_empty");
    if (simple.length !== 1 || raw.length !== 1) fail("inspect_layout");
    const switches = simple[0].parentElement?.parentElement;
    const panel = switches?.nextElementSibling;
    if (!switches?.contains(raw[0]) || !panel?.matches("div.sc-a379a597-8") || !visible(panel))
      fail("inspect_layout");
    const source = panel.parentElement;
    const previewBox = source.parentElement?.firstElementChild;
    const preview = previewBox?.firstElementChild;
    if (!previewBox?.matches("div.sc-a379a597-7") || !preview?.matches("div[style]") || !visible(preview))
      fail("inspect_empty");
    // Use a local equality check only. The image and its object URL never leave the page.
    const imageStyle = getComputedStyle(preview).backgroundImage;
    if (!imageStyle || imageStyle === "none") fail("inspect_empty");
    const softwareRows = [...source.children].filter(row => {
      if (!row.matches(rows)) return false;
      const first = row.firstElementChild;
      return first?.matches("span.sc-a379a597-2") && visible(first) && first.children.length === 0 &&
        first.textContent === "Software:";
    });
    if (softwareRows.length !== 1) fail("inspect_source");
    const software = softwareRows[0], nodes = software.childNodes;
    if (nodes.length !== 3 || nodes[1].nodeType !== 1 || !nodes[1].matches("span.sc-a379a597-4") ||
        nodes[1].childNodes.length || nodes[2].nodeType !== 3 || nodes[2].nodeValue !== "NovelAI")
      fail("inspect_source");
    return {panel, source, preview, imageStyle, button: simple[0]};
  }

  function assertSame(before, after) {
    if (before.source !== after.source || before.preview !== after.preview ||
        before.imageStyle !== after.imageStyle) fail("inspect_changed");
  }

  function parse(panel) {
    const body = panel.firstElementChild;
    if (!body || !visible(body)) return null;
    const labels = [...body.querySelectorAll(labelSelector)];
    if (!labels.length) return null;
    const promptRows = new Set(body.querySelectorAll(rows));
    const roles = new Map(), characters = new Map();
    for (const label of labels) {
      const row = label.parentElement;
      if (!visible(label) || !promptRows.has(row) || label.children.length)
        fail("inspect_layout");
      const name = label.textContent;
      const character = /^Character ([1-9][0-9]*) (Prompt|UC): $/.exec(name);
      const base = name === "Prompt: " || name === "Undesired Content: ";
      if (!character && !base) {
        if (/^(Prompt\s*:|Undesired Content\s*:|Character\s+\S+\s+(?:Prompt|UC)\s*:)/i.test(name))
          fail("inspect_layout");
        continue;
      }
      const [onlyLabel, gap, spacer, value] = row.childNodes;
      if (row.childNodes.length !== 4 || onlyLabel !== label || gap.nodeType !== 3 || gap.nodeValue !== " " ||
          spacer.nodeType !== 1 || !spacer.matches("span.sc-a379a597-4") || spacer.childNodes.length ||
          value.nodeType !== 1 || !value.matches(valueSelector) ||
          !visible(value) || [...value.childNodes].some(child => child.nodeType !== 3) || roles.has(name))
        fail("inspect_layout");
      roles.set(name, value.textContent);
      if (character) {
        const index = Number(character[1]);
        if (!Number.isSafeInteger(index) || index > 1000 ||
            (!characters.has(index) && index !== characters.size + 1)) fail("inspect_layout");
        if (!characters.has(index)) characters.set(index, {positive: null, negative: null});
        characters.get(index)[character[2] === "Prompt" ? "positive" : "negative"] = value.textContent;
      }
    }
    if (!roles.size) return null;
    // A value left without its label would silently drop a field.
    for (const value of body.querySelectorAll(valueSelector)) {
      if (!value.parentElement.matches(rows) || !value.parentElement.firstElementChild?.matches(labelSelector))
        fail("inspect_layout");
    }
    const readable = panel.innerText;
    if (!readable) fail("inspect_layout");
    return {index: 0, status: "ok", readable, base: roles.get("Prompt: ") ?? null,
      negative: roles.get("Undesired Content: ") ?? null, characters: [...characters.values()],
      structure: characters.size ? "characters" : "single"};
  }

  try {
    const start = view();
    let current = start, card = parse(start.panel);
    if (!card) {
      if (start.button.disabled || start.button.getAttribute("aria-disabled") === "true") fail("inspect_empty");
      start.button.click();
      for (let attempt = 0; attempt < 24; ++attempt) {
        current = view();
        assertSame(start, current);
        card = parse(current.panel);
        if (card) break;
        await new Promise(resolve => setTimeout(resolve, 75));
      }
    }
    if (!card) fail("inspect_empty");
    const end = view();
    assertSame(start, end);
    if (current.panel !== end.panel) fail("inspect_changed");
    if (new TextEncoder().encode(JSON.stringify(card)).length > 15 * 1024 * 1024) fail("limit");
    return {ok: true, card};
  } catch (error) { return {ok: false, code: error?.code || "inspect_layout"}; }
}

if (typeof module !== "undefined" && module.exports) module.exports = {readInspectSimplified};
