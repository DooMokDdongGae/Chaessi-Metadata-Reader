const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { runInNewContext } = require("node:vm");

const source = readFileSync(join(__dirname, "..", "browser", "visible-json.js"), "utf8");
const rectangle = { left: 20, top: 30, right: 420, bottom: 200, width: 400, height: 170 };
const styles = {
  display: "block", visibility: "visible", opacity: "1", contentVisibility: "visible",
  clipPath: "none", filter: "none", overflowY: "visible", position: "static",
  color: "rgb(11, 20, 30)", fontSize: "16px", textTransform: "none", transform: "none",
};

function element(tag, parent, name) {
  return {
    tagName: tag, parentElement: parent, className: name, rect: rectangle,
    style: { ...styles, display: tag === "SPAN" ? "inline" : "block" },
    attributes: [{ name: "class", value: name }], aria: {}, children: [],
    scrollHeight: 170, clientHeight: 170, hidden: false, inert: false,
    classList: { contains(value) { return name.split(" ").includes(value); } },
    getAttribute(key) { return this.aria[key] ?? null; },
    getClientRects() { return [this.rect]; },
    getBoundingClientRect() { return this.rect; },
    contains(child) { return child === this || this.children.includes(child); },
    querySelectorAll(selector) { assert.equal(selector, "*"); return this.children; },
  };
}

function fixture(raw = '{"Comment":{"prompt":"  종이 정원  ","uc":""}}\n') {
  const alerts = [], files = [], revoked = [], read = { text: 0, dom: 0 };
  const detail = element("SECTION", null, "");
  const card = element("DIV", detail, "img-card");
  const box = element("DIV", card, "json-box short");
  const panel = element("PRE", box, "json-content metadata-raw-view");
  const panels = [panel];
  Object.defineProperty(panel, "innerText", { get() { ++read.text; return raw; } });
  Object.defineProperty(panel, "textContent", { get() { throw Error("hidden data access"); } });
  box.toggle = box.copy = true;
  box.querySelector = selector => {
    if (selector === ':scope > .json-actions > button.json-view-toggle[aria-pressed="true"]') return box.toggle;
    assert.equal(selector, ':scope > .json-actions > button[data-mode="json"]');
    return box.copy;
  };
  const downloads = [];
  const document = {
    documentElement: { clientWidth: 1000, clientHeight: 700 },
    body: { append() {} },
    elementFromPoint: () => panel,
    querySelectorAll(selector) {
      ++read.dom;
      assert.equal(selector, "#detailView #detailImages > .img-card > .json-box > pre.json-content.metadata-raw-view");
      return panels;
    },
    createElement(tag) {
      assert.equal(tag, "a");
      return { click() { downloads.push(this.download); }, remove() {} };
    },
  };
  const location = { origin: "https://aitag.win", pathname: "/i/42", search: "", hash: "" };
  const window = { alert: message => alerts.push(message) };
  window.top = window;
  const context = {
    window, document, location, getComputedStyle: node => node.style, Blob,
    URL: { createObjectURL(file) { files.push(file); return "blob:synthetic"; },
           revokeObjectURL(url) { revoked.push(url); } },
    setTimeout(callback) { callback(); },
  };
  return { raw, window, location, document, box, panel, panels, files, downloads, alerts, read, revoked,
           execute: () => runInNewContext(source + "\nsaveVisibleJson();", context) };
}

function rejected(f, pattern, reads = 0) {
  f.execute();
  assert.equal(f.files.length, 0);
  assert.equal(f.alerts.length, 1);
  assert.match(f.alerts[0], pattern);
  assert.equal(f.read.text, reads);
}

test("one selected public raw panel is saved byte-for-byte as a local JSON file", async () => {
  const f = fixture();
  f.location.search = "?lang=en";
  f.execute();
  assert.deepEqual(f.downloads, ["aitag-42.json"]);
  assert.deepEqual(f.revoked, ["blob:synthetic"]);
  assert.equal(await f.files[0].text(), f.raw);
  assert.equal(f.alerts.length, 0);
  assert.equal(f.read.text, 1);
});

test("legal highlight spans with unambiguous text are accepted", async () => {
  const f = fixture();
  f.panel.children = [element("SPAN", f.panel, "k")];
  f.execute();
  assert.equal(await f.files[0].text(), f.raw);
});

test("origin, protocol, frame, path and access-dependent links are checked before the DOM", () => {
  for (const change of [{ origin: "http://aitag.win" }, { origin: "https://aitag.win.evil.example" },
                        { pathname: "/search" }, { search: "?secret=synthetic" }, { hash: "#x" }]) {
    const f = fixture();
    Object.assign(f.location, change);
    rejected(f, /기본 주소/);
    assert.equal(f.read.dom, 0);
  }
  const f = fixture();
  f.window.top = {};
  rejected(f, /기본 주소/);
  assert.equal(f.read.dom, 0);
});

test("hidden and off-screen panels are never read", () => {
  for (const change of [f => { f.panel.hidden = true; }, f => { f.panel.parentElement.inert = true; },
                        f => { f.box.aria["aria-hidden"] = "true"; },
                        f => { f.panel.style.display = "none"; },
                        f => { f.panel.parentElement.style.opacity = "0"; },
                        f => { f.panel.rect = { ...rectangle, top: 800, bottom: 970 }; }]) {
    const f = fixture();
    change(f);
    rejected(f, /한 장/);
  }
});

test("overlapping modal or more than one visible raw panel stops without reading", () => {
  const covered = fixture();
  covered.document.elementFromPoint = () => ({});
  rejected(covered, /다른 화면/);
  const multiple = fixture();
  multiple.panels.push(element("PRE", multiple.box, "json-content metadata-raw-view"));
  rejected(multiple, /한 장/);
});

test("inactive, collapsed, and clipped raw previews are rejected", () => {
  for (const change of [f => { f.box.copy = false; }, f => { f.box.toggle = false; },
                        f => { f.box.classList = { contains: c => c === "collapsed" }; }]) {
    const f = fixture();
    change(f);
    rejected(f, /펼쳐/);
  }
  const f = fixture();
  f.panel.style.overflowY = "hidden";
  f.panel.scrollHeight = 800;
  rejected(f, /일부 가려/);
});

test("hidden and unexpected descendants stop before innerText is read", () => {
  for (const change of [
    s => { s.aria["aria-hidden"] = "true"; }, s => { s.style.display = "none"; },
    s => { s.style.opacity = "0"; }, s => { s.style.color = "rgba(0, 0, 0, 0)"; },
    s => { s.style.position = "absolute"; }, s => { s.tagName = "SCRIPT"; },
    s => { s.attributes.push({ name: "style" }); }, s => { s.className = "unknown"; },
  ]) {
    const f = fixture();
    const span = element("SPAN", f.panel, "s");
    change(span);
    f.panel.children.push(span);
    rejected(f, /확인할 수 없는/);
  }
});

test("malformed or truncated displays, multi-image values, and ambiguous highlight output stop", () => {
  rejected(fixture('{"prompt":"paper\ncloud"}'), /완전한 JSON/, 1);
  rejected(fixture('{"prompt":"paper"}\n... truncated ...'), /완전한 JSON/, 1);
  rejected(fixture('{"images":[{},{}]}'), /한 장/, 1);
  const weighted = fixture('{"prompt":"(cloud:1.2)"}');
  weighted.panel.children.push(element("SPAN", weighted.panel, "n"));
  rejected(weighted, /공백/, 1);
});
