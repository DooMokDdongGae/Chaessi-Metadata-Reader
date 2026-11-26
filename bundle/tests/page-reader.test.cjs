const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { openReadableBundle, publicWorkLink } = require("../page-reader.js");

function surface() {
  const listeners = new Map(), writes = [];
  const state = { overlays: [], observer: null };
  function node(tag) {
    const attrs = {}, events = {}, classes = new Set();
    return {
      tag, children: [], dataset: {}, hidden: false, isConnected: true,
      classList: { add: value => classes.add(value), contains: value => classes.has(value) },
      setAttribute(key, value) { attrs[key] = value; }, getAttribute(key) { return attrs[key]; },
      addEventListener(type, handler) { events[type] = handler; },
      fire(type, trusted = true) { return events[type]?.({isTrusted: trusted, preventDefault() {}}); },
      append(child) { this.children.push(child); child.parent = this; },
      replaceChildren() { this.children = []; },
      remove() { this.isConnected = false; if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this); },
      attachShadow() { this.shadowRoot = node("shadow"); return this.shadowRoot; },
      showModal() { this.open = true; }, close() { this.open = false; },
      focus() { state.focused = this; }, getClientRects() { return [{}]; },
      querySelector(s) { return s === "dialog#reader[open]" ? walk(this, n => n.id === "reader" && n.open) : null; },
    };
  }
  function walk(root, predicate) {
    if (predicate(root)) return root;
    for (const child of root.children) { const found = walk(child, predicate); if (found) return found; }
    return root.shadowRoot ? walk(root.shadowRoot, predicate) : null;
  }
  const body = node("body"), detail = node("section");
  detail.id = "detailView";
  body.append(detail);
  const document = {
    body, activeElement: detail, createElement: node, querySelectorAll: () => state.overlays,
    getElementById: id => walk(body, n => n.id === id),
  };
  const context = {
    document, getComputedStyle: () => ({ visibility: "visible" }),
    navigator: { clipboard: { writeText: async text => { writes.push(text); if (state.deny) throw Error("denied"); } } },
    window: { addEventListener: (t, f) => listeners.set(t, f), removeEventListener: t => listeners.delete(t) },
    location: { href: "https://aitag.win/i/42" },
    MutationObserver: class { constructor(callback) { state.observer = callback; } observe() {} disconnect() { state.observer = null; } },
  };
  const open = vm.runInNewContext("(" + openReadableBundle.toString() + ")", context);
  return { open, state, detail, writes, context, listeners, get: document.getElementById,
           field: key => walk(body, n => n.dataset.field === key) };
}

const row = {
  index: 0, status: "ok", readable: "원문\r\n\n  끝  ", base: "  <img onerror=demo>  ",
  negative: "", structure: "characters", characters: [{ positive: "연필\r\n", negative: null }]
};
const partial = { index: 1, status: "failed", readable: null, base: null, negative: null, structure: "unknown", characters: [] };
const bundle = { format: "chaessi.readable-bundle", version: 1, count: 2, cards: [row, partial] };

test("one collection, full image list, literal field text and trusted exact-copy actions", async () => {
  const f = surface();
  let collects = 0;
  await f.open(async () => { collects++; return bundle; });
  const again = () => { throw Error("unexpected recollection"); };
  await f.open(again);
  assert.equal(collects, 1);
  assert.equal(f.get("card").children.length, 2);
  assert.match(f.get("summary").textContent, /전체 2장/);
  const field = f.field("base");
  assert.equal(field.children[1].textContent, row.base);
  assert.equal(field.children[1].children.length, 0);
  const button = field.children[0].children[1];
  await button.fire("click", false);
  assert.deepEqual(f.writes, []);
  await button.fire("click");
  await f.field("negative").children[0].children[1].fire("click");
  await f.field("character-1-positive").children[0].children[1].fire("click");
  assert.equal(f.field("character-1-negative").children[0].children[1].disabled, true);
  await f.get("raw-tab").fire("click");
  assert.equal(f.get("readable").hidden, false);
  assert.equal(f.get("readable").textContent, row.readable);
  await f.get("copy-readable").fire("click");
  assert.deepEqual(f.writes, [row.base, "", row.characters[0].positive, row.readable]);
  f.get("card").value = "1";
  f.get("card").fire("change");
  assert.equal(f.get("copy-readable").disabled, true);
  assert.match(f.get("readable").textContent, /읽지 못했/);
  assert.equal(f.field("base"), null);
});

test("a rejected collector or a gate appearing during collection never displays data", async () => {
  const f = surface();
  await assert.rejects(f.open(async () => { throw Error("제한"); }), /제한/);
  assert.equal(f.get("chaessi-bundle-reader"), null);
  await assert.rejects(f.open(async () => { f.detail.hidden = true; return bundle; }), /작품 화면/);
  assert.equal(f.get("chaessi-bundle-reader"), null);
  assert.deepEqual(f.writes, []);
});

test("a clipboard failure is reported; close, Escape, a new gate or navigation releases the UI", async () => {
  for (const action of ["close", "escape", "gate", "location"]) {
    const f = surface();
    await f.open(async () => bundle);
    f.state.deny = true;
    await f.get("copy-readable").fire("click");
    assert.match(f.get("feedback").textContent, /복사할 수 없/);
    if (action === "close") f.get("close").fire("click");
    if (action === "escape") f.get("reader").fire("cancel");
    if (action === "gate") { f.detail.classList.add("blocked-detail"); f.state.observer(); }
    if (action === "location") { f.context.location.href += "/new"; f.state.observer(); }
    assert.equal(f.get("chaessi-bundle-reader"), null);
    assert.equal(f.state.observer, null);
    assert.equal(f.listeners.size, 0);
    assert.equal(f.state.focused, f.detail);
  }
});

test("only literal work ids and the three supported languages become clickable links", () => {
  assert.equal(publicWorkLink("#work=42"), "https://aitag.win/i/42");
  for (const lang of ["ko", "en", "zh"]) {
    assert.equal(publicWorkLink("#work=00042&lang=" + lang), "https://aitag.win/i/00042?lang=" + lang);
  }
  for (const bad of ["", "#work=", "#work=１２", "#work=42&lang=ja", "#work=42&lang=ko&x=1",
                     "#work=https://example.test/", "#work=42%2Fother", "#work=1&lang=ko#more",
                     "#work=123456789012345678901", "#work=42\n"]) {
    assert.equal(publicWorkLink(bad), null, bad);
  }
});
