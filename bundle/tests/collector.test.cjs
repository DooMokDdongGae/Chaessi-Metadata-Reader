const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { collectReadableBundle } = require("../collect.js");

function dom(parent = null) {
  return { parentElement: parent, isConnected: true, children: [],
    classList: { contains: () => false }, getAttribute: () => null,
    getClientRects: () => [{}], getBoundingClientRect: () => ({left: 0, top: 0, right: 40, bottom: 20}),
    contains(child) { while (child && child !== this) child = child.parentElement; return child === this; }
  };
}

function site(rows, scriptSrc = "/app.js?v=260915h") {
  const detail = dom(), grid = dom(detail);
  const state = { writes: 0, reads: 0, hit: null, modals: [], clicks: [], scrolls: 0, toggles: [] };
  const hostClipboard = {
    writeText() { ++state.writes; throw Error("OS clipboard write"); },
    readText() { ++state.reads; throw Error("OS clipboard read"); }
  };
  const clipboard = Object.create(hostClipboard);
  const window = { event: null, scrollX: 3, scrollY: 9, scrollTo() { ++state.scrolls; } };
  window.top = window;
  const cards = rows.map((row, index) => {
    const card = dom(grid), box = dom(card), button = dom(box), view = dom(box);
    card.box = box;
    let mode = row.rawMode ? "json" : "readable";
    const toggle = dom(box);
    toggle.getAttribute = key => key === "aria-pressed" ? String(mode === "json") : null;
    toggle.scrollIntoView = () => { state.hit = toggle; };
    toggle.click = () => { mode = mode === "json" ? "readable" : "json"; state.toggles.push([index, mode]); };
    card.querySelectorAll = s => s === ":scope > .json-box" ? [box] : [];
    box.querySelectorAll = s => s.includes('data-mode="readable"') && mode === "readable" && !row.missing ? [button] : [];
    box.querySelector = selector => {
      if (selector.includes(".ai-metadata-view")) return view;
      if (selector.includes("json-view-toggle")) return row.rawMode && mode === "json" ? toggle : null;
      if (selector.includes('data-mode="json"')) return row.rawMode && mode === "json" ? button : null;
      return selector.includes("button[data-mode]") && !row.missing ? button : null;
    };
    button.scrollIntoView = () => { state.hit = row.covered ? null : button; };
    button.click = () => {
      state.clicks.push(index);
      window.event = { type: "click", currentTarget: button, target: button };
      try {
        if (!row.noWrite) clipboard.writeText(row.text);
        if (row.duplicateWrite) clipboard.writeText("second");
        if (row.throws) throw new Error("changed listener");
      } finally { window.event = null; }
    };
    const slots = (row.slots || []).map((slot, i) => {
      const element = dom(view), title = dom(element);
      title.innerText = String(i + 1) + (slot.position ? " · " + slot.position : "");
      element.querySelector = s => s.includes("inline-label") ? (slot.negative ? dom(element) : null) : title;
      element.querySelectorAll = () => Array(Number(slot.positive) + Number(slot.negative)).fill(dom(element));
      return element;
    });
    view.querySelectorAll = s => {
      if (s.endsWith(".ai-meta-character")) return slots;
      if (s.includes("positive >") && row.base) return [dom(view)];
      if (s.includes("negative >") && row.negative) return [dom(view)];
      return [];
    };
    return card;
  });
  grid.querySelectorAll = () => cards;
  const document = {
    getElementById: id => id === "detailView" ? detail : grid,
    querySelector(selector) {
      const sources = selector.split(",").map(clause => {
        const attr = /^script\[src="([^"]+)"\]$/.exec(clause.trim());
        assert.ok(attr, "expected an exact script[src] selector");
        return attr[1];
      });
      return sources.includes(scriptSrc) ? {src: scriptSrc} : null;
    },
    querySelectorAll: () => state.modals, elementFromPoint: () => state.hit,
  };
  const location = { origin: "https://aitag.win", pathname: "/i/42", search: "?lang=ko", hash: "", href: "https://aitag.win/i/42?lang=ko" };
  const context = { document, window, navigator: {clipboard}, location, TextEncoder,
    getComputedStyle: () => ({ display: "block", visibility: "visible", opacity: "1" }) };
  return { state, location, clipboard, detail, cards,
    collect: options => vm.runInNewContext("(" + collectReadableBundle.toString() + ")", context)(options) };
}

test("click identity, mixed line endings, duplicates, partial status and clipboard restoration", async () => {
  const text = "형식: nai\n\n프롬프트:\n  씨앗:1.3\r\n종이  \n\n네거티브 프롬프트:\n<점>\n\n캐릭터 프롬프트:\n캐릭터 1: 연필 | 캐릭터 네거티브 프롬프트: 금속 | 위치: 0.4,0.5";
  const character = { positive: true, negative: true, position: "0.4,0.5" };
  const full = { text, base: true, negative: true, slots: [character] };
  const f = site([full, { text: "" }, {missing: true}, {noWrite: true}, full, {duplicateWrite: true}]);
  const result = await f.collect({expectedCount: 6});
  assert.equal(result.count, 6);
  assert.deepEqual([...result.cards].map(c => c.status), ["ok", "empty", "missing", "failed", "ok", "failed"]);
  assert.deepEqual([...result.cards].map(c => c.index), [0, 1, 2, 3, 4, 5]);
  assert.equal(result.cards[0].base, "  씨앗:1.3\r\n종이  ");
  assert.equal(result.cards[0].negative, "<점>");
  assert.equal(result.cards[0].structure, "characters");
  assert.equal(result.cards[0].characters[0].positive, "연필");
  assert.equal(result.cards[0].characters[0].negative, "금속");
  assert.equal(result.cards[0].readable, text);
  assert.equal(result.cards[4].readable, text);
  assert.deepEqual(f.state.clicks, [0, 1, 3, 4, 5]);
  assert.equal(f.state.reads + f.state.writes, 0);
  assert.equal(Object.hasOwn(f.clipboard, "writeText"), false);
});

test("empty structured value and absence are distinct", async () => {
  const f = site([{text: "Format: nai\n\nPrompt:\n\nNegative prompt:\nrain", base: true, negative: true},
                  {text: "Format: nai\n\nPrompt:\ncloud", base: true}]);
  const {cards} = await f.collect();
  assert.equal(cards[0].base, "");
  assert.equal(cards[0].negative, "rain");
  assert.equal(cards[1].negative, null);
  assert.equal(cards[1].structure, "single");
});

test("both official builds copy the exact text and fields with either script URL spelling", async () => {
  const text = "Format: nai\n\nPrompt:\n  vellum:1.3\r\n  cloud  \n\nNegative prompt:\nrain" +
    "\n\nCharacter prompts:\nCharacter 1: paper | Character negative: ink";
  const row = {text, base: true, negative: true, slots: [{positive: true, negative: true}]};
  for (const build of ["260915h", "261121b"]) {
    for (const origin of ["", "https://aitag.win"]) {
      const scriptSrc = origin + "/app.js?v=" + build;
      const f = site([row], scriptSrc);
      const result = await f.collect({expectedCount: 1});
      assert.deepEqual(structuredClone(result.cards), [{
        index: 0, status: "ok", readable: text, base: "  vellum:1.3\r\n  cloud  ", negative: "rain",
        characters: [{positive: "paper", negative: "ink"}], structure: "characters"
      }], scriptSrc);
      assert.deepEqual(f.state.clicks, [0]);
      assert.equal(f.state.reads + f.state.writes, 0);
      assert.equal(Object.hasOwn(f.clipboard, "writeText"), false);
    }
  }
});

test("an unsupported script stops before a view toggle, official copy, or clipboard access", async () => {
  for (const scriptSrc of [null, "/app.js", "/app.js?v=unreviewed", "/app.js?v=261121b.extra",
                           "/app.js?v=260915h&extra=1", "https://aitag.win.example/app.js?v=261121b"]) {
    const f = site([{text: "synthetic", rawMode: true}], scriptSrc);
    await assert.rejects(f.collect({expectedCount: 1}), err => err.code === "site_version");
    assert.deepEqual(f.state.toggles, []);
    assert.deepEqual(f.state.clicks, []);
    assert.equal(f.state.reads + f.state.writes, 0);
    assert.equal(Object.hasOwn(f.clipboard, "writeText"), false);
  }
});

test("literal position marker without a position is preserved; artificial section never truncates", async () => {
  const f = site([{text: "Format: nai\n\nCharacter prompts:\nCharacter 1: blue | Position: fiction",
                   slots: [{positive: true, negative: false}]},
                  {text: "Format: nai\n\nPrompt:\ncloud\n\nWorkflow: imaginary", base: true}]);
  const {cards} = await f.collect();
  assert.equal(cards[0].characters[0].positive, "blue | Position: fiction");
  assert.equal(cards[1].structure, "unknown");
  assert.equal(cards[1].base, null);
  assert.equal(cards[1].readable, "Format: nai\n\nPrompt:\ncloud\n\nWorkflow: imaginary");
});

test("no action for a gate, unexpected count, other origin or covered button", async () => {
  for (const [alter, code] of [
    [f => { f.state.modals = [dom()]; }, "restricted"],
    [f => { f.location.origin = "https://example.invalid"; }, "page"],
    [() => {}, "changed"]
  ]) {
    const f = site([{text: "example"}]);
    alter(f);
    await assert.rejects(f.collect({expectedCount: 2}), err => err.code === code);
    assert.equal(f.state.clicks.length, 0);
  }
  const f = site([{text: "example", covered: true}]);
  assert.equal((await f.collect()).cards[0].status, "failed");
  assert.equal(f.state.clicks.length, 0);
});

test("non-configurable clipboard methods block the click; original own descriptor is restored on error", async () => {
  const blocked = site([{text: ""}]);
  Object.defineProperty(blocked.clipboard, "writeText", {value() {}, configurable: false});
  await assert.rejects(blocked.collect(), err => err.code === "capture");
  assert.equal(blocked.state.clicks.length, 0);
  const f = site([{text: "example", throws: true}, {text: ""}]);
  const original = () => {};
  Object.defineProperty(f.clipboard, "writeText", {value: original, configurable: true, enumerable: true});
  const descriptor = Object.getOwnPropertyDescriptor(f.clipboard, "writeText");
  const result = await f.collect();
  assert.deepEqual([...result.cards].map(c => c.status), ["failed", "empty"]);
  assert.deepEqual(Object.getOwnPropertyDescriptor(f.clipboard, "writeText"), descriptor);
  assert.equal(f.state.scrolls, 1);
});

test("a rendered raw tab is switched publicly and restored even after a card failure", async () => {
  const f = site([{text: "Format: nai\n\nPrompt:\nsky", base: true, rawMode: true},
                  {text: "example", throws: true, rawMode: true}]);
  const {cards} = await f.collect();
  assert.deepEqual([...cards].map(c => c.status), ["ok", "failed"]);
  assert.equal(cards[0].base, "sky");
  assert.deepEqual(f.state.toggles, [[0, "readable"], [0, "json"], [1, "readable"], [1, "json"]]);
  assert.equal(Object.hasOwn(f.clipboard, "writeText"), false);
});

test("raw and serialized bundle caps apply before returning a file", async () => {
  const tooLarge = "x".repeat(8 * 1024 * 1024 + 1);
  await assert.rejects(site([{text: tooLarge}]).collect(), error => error.code === "limit");
  const doubled = "x".repeat(Math.round(7.6 * 1024 * 1024));
  await assert.rejects(site([{text: "Format: nai\n\nPrompt:\n" + doubled, base: true}]).collect(), error => error.code === "limit");
});
