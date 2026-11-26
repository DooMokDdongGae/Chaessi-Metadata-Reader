const {test} = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const {readInspectSimplified} = require("../inspect.js");
const {collectFromOpenInspect, INSPECT_PERMISSION, INSPECT_URL} = require("../bridge.js");

const types = {row: "sc-a379a597-6", label: "sc-a379a597-3", value: "sc-a379a597-5",
  panel: "sc-a379a597-8", preview: "sc-a379a597-7", software: "sc-a379a597-2", spacer: "sc-a379a597-4"};
const rawText = "Synthetic settings\nPositive\n sky\r\nNegative\n";
const text = nodeValue => ({nodeType: 3, nodeValue});
class Element {
  constructor(tag, className, ...children) {
    Object.assign(this, {nodeType: 1, tag, className, childNodes: [], attributes: {}, style: {},
      isConnected: true, hidden: false});
    children.forEach(child => this.append(child));
  }
  append(child) {
    this.childNodes.push(child);
    child.parentElement = this;
    return child;
  }
  get children() { return this.childNodes.filter(child => child.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() {
    const list = this.parentElement?.children || [];
    return list[list.indexOf(this) + 1] || null;
  }
  get textContent() { return this.childNodes.map(child => child.nodeValue ?? child.textContent).join(""); }
  get innerText() { return this.rendered ?? this.textContent; }
  getClientRects() { return this.hidden ? [] : [{}]; }
  getAttribute(attr) { return this.attributes[attr] ?? null; }
  matches(selector) {
    if (selector === "div[style]") return this.tag === "div" && this.getAttribute("style") !== null;
    const [tag, cls] = selector.split(".");
    return tag === this.tag && (!cls || cls === this.className);
  }
  contains(child) {
    return this === child || this.children.some(el => el.contains(child));
  }
  querySelectorAll(selector) {
    return this.children.flatMap(el => [...(el.matches(selector) ? [el] : []), ...el.querySelectorAll(selector)]);
  }
}
const el = (tag = "div", cls = "", ...children) => new Element(tag, cls, ...children);
function row(name, value) {
  return el("div", types.row, el("span", types.label, text(name.slice(0, -2)), text(":"), text(" ")),
    text(" "), el("span", types.spacer),
    el("span", types.value, ...(value === "" ? [] : [text(value)])));
}
function fixture(items = [["Prompt: ", " sky\r\n"], ["Undesired Content: ", ""],
  ["Character 1 Prompt: ", " first "], ["Character 1 UC: ", ""], ["Character 2 UC: ", " last "]]) {
  const simple = el("button", "", text("Simplified")), raw = el("button", "", text("Raw Parameters"));
  const controls = el("div", "", el("div", "", simple, raw));
  const fieldBody = el("div", "", ...items.map(([key, value]) => row(key, value)));
  const panel = el("div", types.panel, fieldBody);
  panel.rendered = rawText;
  const software = el("div", types.row, el("span", types.software, text("Software:")),
    el("span", types.spacer), text("NovelAI"));
  const source = el("div", "", software, controls, panel);
  const preview = el("div");
  preview.attributes.style = "";
  preview.style.backgroundImage = 'url("blob:synthetic-image-one")';
  const doc = el("html", "", el("div", "", el("div", types.preview, preview), source));
  let clicks = 0;
  simple.click = () => { ++clicks; simple.onClick?.(); };
  const page = {window: {}, location: {href: INSPECT_URL}, document: doc, TextEncoder,
    setTimeout: cb => cb(), getComputedStyle: element => ({
      visibility: "visible", opacity: "1", display: "block", ...element.style})};
  page.window.top = page.window;
  const run = vm.runInNewContext("(" + readInspectSimplified.toString() + ")", page);
  return {simple, fieldBody, panel, preview, source, software, page, doc,
    clicks: () => clicks, read: async () => JSON.parse(JSON.stringify(await run()))};
}

test("reads the pane verbatim and preserves spaces, line breaks, empty and absent roles", async () => {
  const f = fixture(), result = await f.read();
  assert.deepEqual(result, {ok: true, card: {index: 0, status: "ok", readable: rawText,
    base: " sky\r\n", negative: "", characters: [
      {positive: " first ", negative: ""}, {positive: null, negative: " last "}], structure: "characters"}});
  assert.equal(f.clicks(), 0);
  const single = fixture([["Prompt: ", "second image"]]);
  assert.deepEqual((await single.read()).card, {index: 0, status: "ok", readable: rawText,
    base: "second image", negative: null, characters: [], structure: "single"});
  single.fieldBody.children[0].children[2].childNodes[0].nodeValue = "changed image";
  assert.equal((await single.read()).card.base, "changed image");
});

test("rejects duplicate roles, numbering gaps, partial and hidden recognized rows", async () => {
  const cases = [
    f => f.fieldBody.append(row("Character 1 UC: ", "duplicate")),
    f => f.fieldBody.append(row("Character 4 Prompt: ", "gap")),
    f => f.fieldBody.append(row("Character 01 Prompt: ", "malformed")),
    f => { f.fieldBody.children[0].childNodes.pop(); },
    f => { f.fieldBody.children[0].childNodes.shift(); },
    f => { f.fieldBody.children[0].children[2].hidden = true; },
    f => { f.fieldBody.children[0].children[2].append(el("span", "", text("nested"))); },
    f => { f.fieldBody.children[0].attributes["aria-hidden"] = "true"; }
  ];
  for (const mutate of cases) {
    const f = fixture();
    mutate(f);
    assert.deepEqual(await f.read(), {ok: false, code: "inspect_layout"});
  }
});

test("requires the confirmed Software row, exact top page, and an unobstructed preview", async () => {
  for (const [mutate, code] of [
    [f => { f.software.childNodes[2].nodeValue = "Other"; }, "inspect_source"],
    [f => { f.source.append(f.software); }, "inspect_source"],
    [f => { f.preview.style.backgroundImage = "none"; }, "inspect_empty"],
    [f => { f.page.location.href += "#other"; }, "inspect_changed"],
    [f => { f.page.window.top = {}; }, "inspect_changed"],
    [f => {
      const original = f.doc.querySelectorAll.bind(f.doc);
      f.doc.querySelectorAll = sel => sel.startsWith("dialog") ? [el("dialog")] : original(sel);
    }, "inspect_overlay"]
  ]) {
    const f = fixture(); mutate(f);
    assert.deepEqual(await f.read(), {ok: false, code});
    assert.equal(f.clicks(), 0);
  }
});

test("selects the ordinary Simplified button once and detects a simultaneous image replacement", async () => {
  const f = fixture([]);
  f.simple.onClick = () => f.fieldBody.append(row("Prompt: ", "from simple"));
  assert.equal((await f.read()).card.base, "from simple");
  assert.equal(f.clicks(), 1);
  const changed = fixture([]);
  changed.simple.onClick = () => { changed.preview.style.backgroundImage = 'url("blob:synthetic-new")'; };
  assert.deepEqual(await changed.read(), {ok: false, code: "inspect_changed"});
  const empty = fixture([]);
  assert.deepEqual(await empty.read(), {ok: false, code: "inspect_empty"});
  assert.equal(empty.clicks(), 1);
});

const job = {kind: "inspect", id: "e".repeat(32), url: INSPECT_URL};
function browser() {
  const current = {id: 8, url: INSPECT_URL};
  const state = {permitted: true, candidates: [current], focused: [], current,
    docs: ["original", "original", "original"]};
  const calls = [], events = [];
  let permissionsLookups = 0;
  const api = {runtime: {getManifest: () => ({optional_host_permissions: ["https://novelai.net/*"]})},
    permissions: {contains: async spec => {
    ++permissionsLookups; assert.deepEqual(Array.from(spec.origins), ["https://novelai.net/*"]); return state.permitted;
  }}, tabs: {
    query: async spec => {
      assert.equal(spec.url, "https://novelai.net/*");
      return spec.lastFocusedWindow && spec.active ? state.focused : state.candidates;
    }, get: async () => state.current
  }, scripting: {executeScript: async spec => {
    calls.push(spec);
    const actual = spec.func === readInspectSimplified;
    return [{frameId: 0, documentId: state.docs.shift(), result: actual ? await fixture().read() : true}];
  }}};
  const client = {event: async event => { events.push(event); return true; }};
  return {state, api, calls, events, permissionsLookups: () => permissionsLookups,
    run: (request = job) => collectFromOpenInspect(api, request, client, readInspectSimplified, () => true)};
}
test("uses the chosen existing top-level document in ISOLATED and returns its trusted source and origin", async () => {
  const b = browser();
  b.state.candidates.unshift({id: 3, url: INSPECT_URL + "?x"}, {id: 4, url: INSPECT_URL},
    {id: 5, url: "https://novelai.net.example/inspect"}, {id: 7, url: INSPECT_URL + "#home"});
  b.state.focused = [b.state.current];
  const result = await b.run();
  assert.equal(result.source, INSPECT_URL);
  assert.equal(result.count, 1);
  assert.equal(result.cards[0].origin, "novelai_inspect");
  assert.equal(result.cards[0].readable, rawText);
  assert.deepEqual(b.events, [{id: job.id, event: "count", count: 1}]);
  assert.equal(b.calls.length, 3);
  assert(b.calls.every(call => call.world === "ISOLATED" && call.target.tabId === 8));
  assert.deepEqual(b.calls[0].target.frameIds, [0]);
  for (const call of b.calls.slice(1)) assert.deepEqual(call.target.documentIds, ["original"]);
  assert.equal(b.permissionsLookups(), 1);
});

test("rejects wrong jobs, missing permissions/tabs, ambiguous choices and document changes before count", async () => {
  for (const [mutate, code] of [
    [b => { b.state.permitted = false; }, "inspect_permission"],
    [b => { b.state.candidates = [{id: 2, url: INSPECT_URL + "/"}]; }, "inspect_tab"],
    [b => { b.state.candidates.push({id: 3, url: INSPECT_URL}); }, "inspect_ambiguous"],
    [b => { b.state.current = {...b.state.current, pendingUrl: INSPECT_URL}; }, "inspect_changed"],
    [b => { b.state.docs[1] = "new"; }, "inspect_changed"],
    [b => { b.state.docs[2] = "new"; }, "inspect_changed"]
  ]) {
    const b = browser(); mutate(b);
    await assert.rejects(b.run(), err => err.code === code);
    assert.deepEqual(b.events, []);
  }
  const b = browser();
  await assert.rejects(b.run({...job, url: "https://novelai.net/elsewhere"}), err => err.code === "page");
  assert.equal(b.permissionsLookups(), 0);
  const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../manifest.json")));
  assert.deepEqual(manifest.optional_host_permissions, INSPECT_PERMISSION.origins);
  assert(!manifest.host_permissions.includes(INSPECT_PERMISSION.origins[0]));
});

async function settingsFor(b, choice = true) {
  const elements = new Map(), subscriber = {addListener() {}};
  let requests = 0;
  b.api.permissions.onAdded = b.api.permissions.onRemoved = subscriber;
  b.api.permissions.request = async spec => {
    assert.deepEqual(Array.from(spec.origins), ["https://novelai.net/*"]);
    ++requests;
    if (choice instanceof Error) throw choice;
    return (b.state.permitted = choice);
  };
  b.api.storage = {local: {get: async () => ({})}, onChanged: subscriber};
  const context = vm.createContext({chrome: b.api,
    window: {addEventListener() {}}, document: {getElementById(id) {
      if (!elements.has(id)) elements.set(id, {addEventListener(type, action) { this[type] = action; }});
      return elements.get(id);
    }}});
  for (const file of ["bridge.js", "connect.js"])
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, "..", file), "utf8"), context);
  await new Promise(resolve => setImmediate(resolve));
  return {button: elements.get("inspect-access"), status: elements.get("inspect-status"), requests: () => requests};
}

test("only an explicit settings click requests optional access; the existing Inspect pipeline consumes the grant", async () => {
  const b = browser(); b.state.permitted = false;
  const ui = await settingsFor(b);
  await assert.rejects(b.run(), err => err.code === "inspect_permission");
  assert.equal(ui.requests(), 0);
  assert.equal(ui.button.hidden, false);
  await ui.button.click();
  assert.equal(ui.button.hidden, true);
  assert.equal(b.calls.length, 0);
  const result = await b.run();
  assert.equal(result.source, INSPECT_URL);
  assert.equal(result.cards[0].origin, "novelai_inspect");
  assert.equal(ui.requests(), 1);
  assert.deepEqual(b.events, [{id: job.id, event: "count", count: 1}]);
});

test("a loaded older manifest is reported before permission lookup or page access", async () => {
  const b = browser();
  b.api.runtime.getManifest = () => ({version: "0.1.0"});
  const ui = await settingsFor(b);
  assert.equal(ui.button.disabled, true);
  assert.match(ui.status.textContent, /새로고침/);
  await assert.rejects(b.run(), error => error.code === "inspect_manifest");
  assert.equal(ui.requests(), 0);
  assert.equal(b.permissionsLookups(), 0);
  assert.equal(b.calls.length, 0);
  assert.equal(b.events.length, 0);
});

test("settings distinguishes permission denial from a native error while ungranted jobs stop before DOM access", async () => {
  for (const failure of [false, new Error("Permission must be declared in the manifest.")]) {
    const b = browser();
    b.state.permitted = false;
    const ui = await settingsFor(b, failure);
    assert.equal(ui.requests(), 0);
    await ui.button.click();
    assert.equal(ui.button.disabled, false);
    assert.equal(ui.button.hidden, false);
    assert.match(ui.status.textContent, failure instanceof Error ? /Chrome: Permission must/ : /허용하지 않았습니다/);
    await assert.rejects(b.run(), err => err.code === "inspect_permission");
    assert.equal(ui.requests(), 1);
    assert.equal(b.calls.length, 0);
  }
});
