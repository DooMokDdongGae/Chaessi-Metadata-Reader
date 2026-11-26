const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { publicWork, sameWork, bridgeClient, waitForWork, collectInChrome, validateBundle } = require("../bridge.js");

const directory = path.resolve(__dirname, "..");
const url = "https://aitag.win/i/42?lang=ko";
const job = {id: "1234567890abcdef".repeat(2), url};
const row = { index: 0, status: "ok", readable: "원문\r\n\n", base: " 구름 ", negative: "",
  characters: [{positive: "종이", negative: null}], structure: "characters" };
const bundle = {format: "chaessi.readable-bundle", version: 1, count: 2, cards: [
  row, {...row, index: 1, status: "missing", readable: null, base: null, negative: null, characters: [], structure: "unknown"}
]};
const work = async function syntheticCollector() {};

function clock() {
  let elapsed = 0;
  return { now: () => elapsed, sleep: async ms => { elapsed += ms; } };
}

function browser(probeContext) {
  const calls = [];
  const state = { current: url, doc: "public-document", phase: "cards", count: 2, pending: false,
                  result: {ok: true, bundle} };
  const api = {
    tabs: { get: async () => ({url: state.current, status: "complete", pendingUrl: state.navigation}) },
    scripting: { executeScript: async instruction => {
      calls.push(instruction);
      if (instruction.world === "ISOLATED") {
        const result = probeContext
          ? vm.runInNewContext("(" + instruction.func.toString() + ")", probeContext)(...instruction.args)
          : {state: state.phase, count: state.count, pending: state.pending};
        return [{documentId: state.doc, result}];
      }
      return [{documentId: state.postDoc || state.doc, result: state.result}];
    }}
  };
  return { api, state, calls };
}

test("only the named work and allowed ordinary language variant are accepted", () => {
  assert.equal(publicWork("https://aitag.win:443/i/42/").href, "https://aitag.win/i/42/");
  for (const value of ["https://aitag.win.evil.example/i/42", "https://x@aitag.win/i/42", "http://aitag.win/i/42",
                       "https://aitag.win/i/42?token=synthetic", "https://aitag.win/i/42#next", "file:///tmp/42"]) {
    assert.throws(() => publicWork(value), err => err.code === "page");
  }
  assert.equal(sameWork(publicWork(url), url.replace("=ko", "=en")), false);
  assert.equal(sameWork(publicWork(url.split("?")[0]), url), true);
  assert.equal(sameWork(publicWork(url), "https://aitag.win/i/43?lang=ko"), false);
});

test("bridge offers only two fixed loopback routes and never follows redirects or sends cookies", async () => {
  const calls = [], sampleKey = "f".repeat(64);
  const mock = async (target, args) => {
    calls.push({target, ...args});
    return {ok: true, status: 200, json: async () => ({job: null})};
  };
  const session = "1".repeat(32), client = bridgeClient(sampleKey, mock, session);
  assert.deepEqual(await client.next(), {job: null});
  assert.equal(await client.event({id: job.id, event: "count", count: 2}), true);
  assert.deepEqual(calls.map(c => [c.method, c.target]), [
    ["GET", "http://127.0.0.1:47921/next"], ["POST", "http://127.0.0.1:47921/event"]]);
  assert(calls.every(c => c.headers.Authorization === "Bearer " + sampleKey && c.headers["X-Reader-Session"] === session &&
    c.credentials === "omit" &&
    c.redirect === "error" && c.cache === "no-store"));
  assert.throws(() => bridgeClient("bad"), err => err.code === "auth");
  await assert.rejects(bridgeClient(sampleKey, mock, "wrong-session").next(), err => err.code === "auth");
  const conflict = bridgeClient(sampleKey, async () => ({ok: false, status: 409}));
  assert.equal(await conflict.event({event: "result"}), false);
});

test("readiness stays in the isolated world, waits for stable count, then pins the MAIN document", async () => {
  const {api, calls} = browser(), timer = clock(), events = [];
  const output = await collectInChrome(api, 9, job, {event: async data => { events.push(data); return true; }},
    work, () => true, timer.sleep, timer.now);
  assert.deepEqual(events, [{id: job.id, event: "count", count: 2}]);
  assert.deepEqual(output, bundle);
  assert(calls.length >= 4);
  const last = calls.at(-1);
  assert.deepEqual(last.target, {tabId: 9, documentIds: ["public-document"]});
  assert.equal(last.func, work);
  assert.deepEqual(last.args, [url, 2]);
  assert(calls.slice(0, -1).every(c => c.world === "ISOLATED" && c.target.frameIds[0] === 0));
});

test("the isolated page probe accepts the two reviewed scripts and rejects other sources before MAIN", async () => {
  const visible = {closest: () => null, getClientRects: () => [{}]};
  const pane = {...visible, querySelector: css => css === ".ai-meta-readable" ? {} : null};
  const card = {querySelector: css => css === ":scope > .json-box > .ai-metadata-view" ? pane : null};
  const grid = {...visible, querySelectorAll: css => css === ":scope > .img-card" ? [card, card] : []};
  const detail = {...visible, contains: node => node === grid, classList: {contains: () => false}};
  const window = {};
  window.top = window;
  const cases = [
    ["/app.js?v=260915h", true], ["https://aitag.win/app.js?v=260915h", true],
    ["/app.js?v=261121b", true], ["https://aitag.win/app.js?v=261121b", true],
    [null, false], ["/app.js", false], ["/app.js?v=unreviewed", false],
    ["/app.js?v=261121b.extra", false], ["/app.js?v=260915h&extra=1", false],
    ["https://aitag.win.example/app.js?v=261121b", false],
  ];
  for (const [scriptSrc, supported] of cases) {
    const document = {
      getElementById: id => ({detailView: detail, detailImages: grid})[id],
      querySelectorAll: () => [],
      querySelector(selector) {
        const candidates = selector.split(",").map(clause => {
          const attr = /^script\[src="([^"]+)"\]$/.exec(clause.trim());
          assert.ok(attr, "expected an exact script[src] selector");
          return attr[1];
        });
        return candidates.includes(scriptSrc) ? {src: scriptSrc} : null;
      },
    };
    const {api, calls} = browser({window, document, location: {href: url},
                                  getComputedStyle: () => ({visibility: "visible"})});
    const timer = clock(), events = [];
    const client = {event: async event => { events.push(event); return true; }};
    const attempt = collectInChrome(api, 9, job, client, work, () => true, timer.sleep, timer.now);
    if (supported) {
      assert.deepEqual(await attempt, bundle, scriptSrc);
      assert.deepEqual(events, [{id: job.id, event: "count", count: 2}]);
      assert.equal(calls.filter(c => c.world === "MAIN").length, 1);
    } else {
      await assert.rejects(attempt, err => err.code === "site_version");
      assert.deepEqual(events, []);
      assert.deepEqual(calls.map(c => c.world), ["ISOLATED"]);
    }
  }
});

test("gate, navigation, cancellation, or document replacement stops the job", async () => {
  for (const [change, code] of [[{phase: "restricted"}, "restricted"], [{navigation: "https://example.invalid/"}, "changed"],
                                [{postDoc: "new-doc"}, "changed"], [{result: {ok: false, code: "layout"}}, "layout"]]) {
    const {state, api} = browser(), timer = clock();
    Object.assign(state, change);
    await assert.rejects(collectInChrome(api, 9, job, {event: async () => true}, work, () => true, timer.sleep, timer.now),
      err => err.code === code);
  }
  const {api, calls} = browser(), timer = clock();
  await assert.rejects(waitForWork(api, 9, publicWork(url), () => false, timer.sleep, timer.now),
    err => err.code === "connection");
  assert.equal(calls.length, 0);
});

test("result schema drops unrelated fields, preserves nulls/empty strings and checks order", () => {
  const data = structuredClone(bundle);
  data.privateExtra = "unrelated";
  data.cards[0].unknown = true;
  data.cards[0].characters[0].another = true;
  assert.deepEqual(validateBundle(data, 2), bundle);
  data.cards[1].index = 0;
  assert.throws(() => validateBundle(data, 2), err => err.code === "layout");
});

test("generated MAIN wrapper refuses a wrong URL before reading any DOM", async () => {
  const source = fs.readFileSync(path.join(directory, "collector.js"), "utf8");
  const context = vm.createContext({location: {href: url.replace("/42?", "/43?")}});
  const wrapper = vm.runInContext(source + "\ncollectChromeWork", context);
  const result = await wrapper(url, 2);
  assert.equal(result.ok, false);
  assert.equal(result.code, "changed");
});

test("MV3 manifest limits host access and excludes cookie, debugger, clipboard and broad tab permissions", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.minimum_chrome_version, "120");
  assert.deepEqual(manifest.permissions.sort(), ["alarms", "scripting", "storage"]);
  assert.deepEqual(manifest.host_permissions.sort(), ["http://127.0.0.1/*", "https://aitag.win/*"]);
  assert.deepEqual(manifest.optional_host_permissions, ["https://novelai.net/*"]);
  const policies = manifest.content_security_policy.extension_pages.split(";").map(part => part.trim());
  assert.deepEqual(policies.filter(part => part.startsWith("connect-src ")),
    ["connect-src http://127.0.0.1:47921 ws://127.0.0.1:47921"]);
  assert.equal(manifest.content_scripts, undefined);
  assert.equal(manifest.externally_connectable, undefined);
});

test("the authenticated worker retries the same source-bound result after a failed delivery without recollecting", async () => {
  const {api, calls} = browser(), timer = clock();
  const storage = {}, events = [], sampleKey = "f".repeat(64), sessionId = "5".repeat(32);
  const subscriber = {addListener() {}};
  let created = 0, terminalAttempts = 0, socket;
  api.tabs.create = async ({url: target}) => {
    assert.equal(target, url); ++created; return {id: 91};
  };
  api.storage = {
    local: {setAccessLevel: async () => {}, get: async () => ({readerKey: sampleKey})},
    session: {get: async () => storage, set: async value => Object.assign(storage, value)},
    onChanged: subscriber,
  };
  api.runtime = {onStartup: subscriber, onInstalled: subscriber, onMessage: subscriber};
  api.alarms = {onAlarm: subscriber, get: async () => ({})};
  const context = vm.createContext({
    chrome: api, URL, TextEncoder, AbortSignal, Date: {now: timer.now},
    setTimeout(fn, ms) { if (ms <= 1000) { timer.sleep(ms); queueMicrotask(fn); } return 1; }, clearTimeout() {},
    WebSocket: class { constructor() { socket = this; } send() {} close() {} },
    fetch: async (target, args) => {
      assert.equal(args.headers["X-Reader-Session"], sessionId);
      if (target.endsWith("/next")) return {ok: true, status: 200, json: async () => ({job})};
      assert.equal(target, "http://127.0.0.1:47921/event");
      const event = JSON.parse(args.body);
      events.push(event);
      if (event.event === "result" && terminalAttempts++ === 0) throw Error("synthetic delivery failure");
      return {ok: true, status: 200};
    }, importScripts: (...files) => {
      for (const file of files) vm.runInContext(fs.readFileSync(path.join(directory, file), "utf8"), context);
    },
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  vm.runInContext(fs.readFileSync(path.join(directory, "auto-worker.js"), "utf8"), context);
  await settle();
  socket.onopen();
  socket.onmessage({data: JSON.stringify({type: "ready", session: sessionId})});
  await settle();
  socket.onmessage({data: JSON.stringify({type: "wake"})});
  await settle();
  assert.deepEqual(events.map(e => e.event), ["count", "result", "result", "error"]);
  assert.equal(events.at(-1).code, "duplicate");
  assert.deepEqual(events[1], events[2]);
  assert.equal(events[1].url, url);
  assert.deepEqual(events[1].bundle, {...bundle, source: url});
  assert.equal(calls.filter(c => c.world === "MAIN").length, 1);
  assert.equal(created, 1);
  assert.deepEqual([...storage.seen], [job.id]);
});

test("settings validates and saves only the pairing key, reads health, and can close without disconnecting", async () => {
  const elements = new Map(), windowEvents = {}, health = [], saved = {};
  const subscriber = {addListener() {}};
  let status = "connected";
  const chrome = {
    runtime: {getManifest: () => ({optional_host_permissions: ["https://novelai.net/*"]}),
      sendMessage: async msg => { health.push(JSON.parse(JSON.stringify(msg))); return {state: status}; }},
    storage: {local: {get: async () => saved, set: async fields => Object.assign(saved, fields),
      remove: async name => { delete saved[name]; }}, onChanged: subscriber},
    permissions: {contains: async () => true, onAdded: subscriber, onRemoved: subscriber},
  };
  const context = vm.createContext({chrome, window: {addEventListener(type, handler) { windowEvents[type] = handler; }},
    document: {getElementById(id) {
      if (!elements.has(id)) elements.set(id, {addEventListener(type, fn) { this[type] = fn; }});
      return elements.get(id);
    }}});
  for (const name of ["bridge.js", "connect.js"]) vm.runInContext(fs.readFileSync(path.join(directory, name), "utf8"), context);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const submit = () => elements.get("pair").submit({preventDefault() {}});
  const input = elements.get("key");
  await settle();
  assert.equal(health.length, 0);
  input.value = "invalid"; await submit(); assert.deepEqual(saved, {});
  input.value = " " + "F".repeat(64) + " "; await submit(); await settle();
  assert.deepEqual(saved, {readerKey: "f".repeat(64)});
  assert.equal(input.value, "");
  assert.equal(elements.get("pair").hidden, true);
  assert.match(elements.get("status").textContent, /연결되었습니다/);
  status = "auth"; windowEvents.focus(); await settle();
  assert.match(elements.get("status").textContent, /일치하지 않습니다/);
  assert.deepEqual(health, [{type: "reader-health"}, {type: "reader-health"}]);
  for (const type of ["pagehide", "beforeunload", "unload"]) windowEvents[type]?.();
  assert.equal(saved.readerKey.length, 64);
  assert.equal(health.length, 2);
  await elements.get("forget").click(); await settle();
  assert.deepEqual(saved, {});
  assert.equal(elements.get("pair").hidden, false);
});
