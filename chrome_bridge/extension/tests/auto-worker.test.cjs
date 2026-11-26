const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.resolve(__dirname, "../auto-worker.js"), "utf8");
const savedKey = "a".repeat(64), sessionId = "b".repeat(32), id = "c".repeat(32);
const inspectUrl = "https://novelai.net/inspect", workUrl = "https://aitag.win/i/42";
const flush = () => new Promise(resolve => setImmediate(resolve));
const clone = value => JSON.parse(JSON.stringify(value));
function event() {
  const callbacks = [];
  return {addListener(cb) { callbacks.push(cb); }, fire(...args) { callbacks.forEach(cb => cb(...args)); }};
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {resolve, promise};
}
function fixture({localKey = savedKey, session = {}} = {}) {
  const timers = new Map(), alarms = new Map(), sockets = [], clients = [], imports = [], events = [], jobs = [];
  const stored = {readerKey: localKey}, tabs = new Map(), tabWrites = [], modes = [];
  let timerId = 0, now = 0, nextCalls = 0;
  const settings = {nextError: null, postError: null, collect: null};
  const chrome = {
    runtime: {id: "f".repeat(32), getURL: file => "chrome-extension://" + "f".repeat(32) + "/" + file,
      onStartup: event(), onInstalled: event(), onMessage: event()},
    storage: {local: {setAccessLevel: async spec => modes.push(spec.accessLevel),
      get: async () => stored}, session: {get: async () => session, set: async v => Object.assign(session, clone(v))},
      onChanged: event()},
    alarms: {get: async name => alarms.get(name), create: async (name, info) => {
      assert(!alarms.has(name), "one alarm per installation"); alarms.set(name, clone(info));
    }, onAlarm: event()},
    tabs: {get: async tab => { if (!tabs.has(tab)) throw Error("closed"); return tabs.get(tab); },
      create: async options => {
        const tab = {id: tabs.size + 1, ...options}; tabs.set(tab.id, tab);
        tabWrites.push({type: "create", ...clone(options)}); return tab;
      }, update: async (id, options) => {
        const tab = Object.assign(tabs.get(id), options);
        tabWrites.push({type: "update", id, ...clone(options)}); return tab;
      }}
  };
  class Socket {
    constructor(url) { assert.equal(url, "ws://127.0.0.1:47921/socket"); this.sent = []; sockets.push(this); }
    send(s) { this.sent.push(JSON.parse(s)); }
    close() { this.closed = true; }
    message(data) { this.onmessage?.({data: JSON.stringify(data)}); }
    closeFromReader(code = 1006) { this.onclose?.({code}); }
    ready(s = sessionId) { this.onopen?.(); this.message({type: "ready", session: s}); }
  }
  function error(code) { return Object.assign(new Error(code), {code}); }
  async function collect(kind, request, client) {
    if (settings.collect) return settings.collect(kind, request, client);
    await client.event({id: request.id, event: "count", count: 1});
    return {count: 1};
  }
  const fakeFetch = () => { throw Error("network is unavailable in synthetic tests"); };
  const context = {chrome, importScripts: (...files) => imports.push(...files), WebSocket: Socket,
    setTimeout: (fn, delay) => { const i = ++timerId; timers.set(i, {fn, at: now + delay}); return i; },
    clearTimeout: i => timers.delete(i), fetch: fakeFetch, INSPECT_URL: inspectUrl, bridgeError: error,
    bridgeClient: (key, fetch, session) => {
      assert.equal(fetch, fakeFetch); clients.push({key, session});
      return {next: async () => {
        ++nextCalls;
        if (settings.nextError) throw error(settings.nextError);
        return {job: jobs.shift() || null};
      }, event: async e => {
        if (settings.postError) throw error(settings.postError);
        events.push({session, ...clone(e)});
        return true;
      }};
    }, publicWork: url => {
      if (!/^https:\/\/aitag\.win\/i\/[0-9]+$/.test(url)) throw error("page");
      return new URL(url);
    }, sameWork: (requested, url) => requested.href === url,
    collectFromOpenInspect: (_chrome, req, client) => collect("inspect", req, client),
    collectInChrome: (_chrome, _tabId, req, client) => collect("aitag", req, client),
    collectChromeWork() {}, readInspectSimplified() {}};
  vm.runInNewContext(source, context);
  function health(sender = {id: chrome.runtime.id, url: chrome.runtime.getURL("connect.html")}) {
    let reply;
    chrome.runtime.onMessage.fire({type: "reader-health"}, sender, data => { reply = clone(data); });
    return reply;
  }
  async function advance(ms) {
    const end = now + ms;
    while (true) {
      const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > end) break;
      now = next[1].at;
      timers.delete(next[0]);
      next[1].fn();
      await flush();
    }
    now = end;
  }
  const alarm = () => chrome.alarms.onAlarm.fire({name: [...alarms.keys()][0]});
  function setKey(newValue) {
    stored.readerKey = newValue;
    chrome.storage.onChanged.fire({readerKey: {newValue}}, "local");
  }
  return {chrome, alarms, sockets, clients, imports, events, jobs, tabs, tabWrites, modes, session, settings,
    health, advance, alarm, setKey, nextCalls: () => nextCalls};
}

test("startup, install and alarms coalesce, handshake authenticates before first claim", async () => {
  const f = fixture(); f.chrome.runtime.onStartup.fire(); f.chrome.runtime.onInstalled.fire(); await flush();
  assert.deepEqual(f.imports, ["collector.js", "bridge.js", "inspect.js"]);
  assert.deepEqual(f.modes, ["TRUSTED_CONTEXTS"]);
  assert.deepEqual([...f.alarms.values()], [{periodInMinutes: 0.5}]);
  assert.deepEqual(f.health(), {state: "connecting"});
  assert.equal(f.health({id: "other", url: f.chrome.runtime.getURL("connect.html")}), undefined);
  assert.equal(f.health({id: f.chrome.runtime.id, url: "https://aitag.win/i/42"}), undefined);
  const ws = f.sockets[0];
  ws.onopen(); f.alarm();
  assert.deepEqual(ws.sent, [{type: "auth", key: savedKey}]);
  assert.equal(f.nextCalls(), 0);
  ws.message({type: "ready", session: sessionId});
  await flush();
  assert.deepEqual(f.clients, [{key: savedKey, session: sessionId}]);
  assert.deepEqual(f.health(), {state: "connected"});
  assert.equal(f.nextCalls(), 1);
  await f.advance(20000);
  assert.deepEqual(ws.sent.at(-1), {type: "ping"});
  ws.message({type: "pong"});
  await f.advance(20000);
  assert.equal(f.sockets.length, 1);
  assert.equal(f.nextCalls(), 1);
  assert.deepEqual(f.tabWrites, []);
});

test("absent reader makes one attempt per alarm; malformed handshake and missed pong never claim more work", async () => {
  const f = fixture(); await flush();
  f.sockets[0].closeFromReader();
  await f.advance(60000);
  assert.equal(f.sockets.length, 1);
  f.alarm(); f.alarm(); await flush();
  f.sockets[1].message({type: "wake"});
  assert.equal(f.nextCalls(), 0);
  f.alarm(); await flush();
  f.sockets[2].message({type: "ready", session: "bad"});
  assert.equal(f.clients.length, 0);
  f.alarm(); await flush();
  f.sockets[3].ready(); await flush();
  await f.advance(40000);
  assert.deepEqual(f.health(), {state: "offline"});
  assert.equal(f.nextCalls(), 1);
});

test("reader shutdown waits for discovery; unexpected loss gets 1/3/10 seconds then a single alarm", async () => {
  const f = fixture(); await flush();
  f.sockets[0].ready(); await flush();
  f.sockets[0].closeFromReader(1001);
  await f.advance(25000);
  assert.equal(f.sockets.length, 1);
  f.alarm(); await flush(); f.sockets.at(-1).ready(); await flush();
  for (const delay of [1000, 3000, 10000]) {
    f.sockets.at(-1).closeFromReader();
    const count = f.sockets.length;
    f.alarm(); await flush();
    await f.advance(delay - 1); assert.equal(f.sockets.length, count);
    await f.advance(1); assert.equal(f.sockets.length, count + 1);
    f.sockets.at(-1).ready(); await flush();
  }
  f.sockets.at(-1).closeFromReader();
  await f.advance(60000);
  assert.equal(f.sockets.length, 5);
  f.alarm(); await flush();
  assert.equal(f.sockets.length, 6);
});

test("authenticated shutdown tears down heartbeat and skips quick retry even when transport then closes abnormally", async () => {
  const f = fixture(); await flush();
  const first = f.sockets[0];
  first.message({type: "shutdown"});
  assert.equal(f.nextCalls(), 0);
  f.alarm(); await flush();
  const ws = f.sockets[1];
  ws.ready(); await flush();
  ws.message({type: "shutdown"}); ws.closeFromReader(1006);
  assert.equal(ws.closed, true);
  assert.deepEqual(f.health(), {state: "offline"});
  await f.advance(60000);
  assert.equal(f.sockets.length, 2);
  assert.deepEqual(ws.sent.map(message => message.type), ["auth"]);
  f.alarm(); await flush();
  assert.equal(f.sockets.length, 3);
});

test("only explicit server jobs create an aitag tab, and session ownership protects repurposed tabs", async () => {
  const f = fixture(); await flush();
  const ws = f.sockets[0];
  const inspectJob = {kind: "inspect", id, url: inspectUrl};
  f.jobs.push(inspectJob); ws.ready(); await flush();
  assert.deepEqual(f.events.map(e => e.event), ["count", "result"]);
  assert.equal(f.events[1].bundle.source, inspectUrl);
  assert.deepEqual(f.tabWrites, []);
  f.jobs.push(inspectJob); ws.message({type: "wake"}); await flush();
  assert.equal(f.events.at(-1).code, "duplicate");
  for (const [i, url] of [workUrl, workUrl, workUrl.replace("42", "43")].entries()) {
    f.jobs.push({id: String(i).repeat(32), url}); ws.message({type: "wake"}); await flush();
  }
  f.tabs.get(1).url = "https://example.invalid/";
  f.jobs.push({id: "4".repeat(32), url: workUrl}); ws.message({type: "wake"}); await flush();
  assert.deepEqual(f.tabWrites.map(t => t.type), ["create", "update", "update", "create"]);
  assert.deepEqual(f.session.ownedTab, {id: 2, url: workUrl});
  assert.deepEqual(f.session.seen, [id, ...["0","1","2","4"].map(i => i.repeat(32))]);
  const fresh = fixture({session: f.session}); await flush();
  fresh.jobs.push(inspectJob); fresh.sockets[0].ready(); await flush();
  assert.equal(fresh.events.at(-1).code, "duplicate");
});

test("a late collection on a lost socket never sends across sessions; overlapping wakes run serially", async () => {
  const f = fixture(), pending = deferred(); await flush();
  f.settings.collect = async () => pending.promise;
  f.jobs.push({id, kind: "inspect", url: inspectUrl}); f.sockets[0].ready(); await flush();
  assert.deepEqual(f.health(), {state: "working"});
  f.sockets[0].message({type: "wake"}); f.sockets[0].message({type: "wake"});
  assert.equal(f.nextCalls(), 1);
  f.sockets[0].closeFromReader();
  await f.advance(1000);
  f.settings.collect = null;
  const freshId = "d".repeat(32), freshSession = "e".repeat(32);
  f.jobs.push({id: freshId, kind: "inspect", url: inspectUrl});
  f.sockets[1].ready(freshSession); await flush(); assert.equal(f.nextCalls(), 1);
  pending.resolve({count: 1}); await flush();
  assert.deepEqual(f.events.map(e => [e.session, e.id, e.event]), [
    [freshSession, freshId, "count"], [freshSession, freshId, "result"]]);
  assert.equal(f.nextCalls(), 2);
});

test("HTTP auth failures close the socket, and changing or forgetting the key replaces the session", async () => {
  const f = fixture({localKey: null}); await flush();
  assert.equal(f.sockets.length, 0); assert.deepEqual(f.health(), {state: "unpaired"});
  f.setKey(savedKey); f.settings.nextError = "auth";
  f.sockets[0].ready(); await flush();
  assert.equal(f.sockets[0].closed, true); assert.deepEqual(f.health(), {state: "auth"});
  await f.advance(20000); assert.equal(f.sockets.length, 1);
  f.settings.nextError = null; f.alarm(); await flush(); f.sockets[1].ready(); await flush();
  f.settings.postError = "auth";
  f.jobs.push({id, kind: "inspect", url: inspectUrl}); f.sockets[1].message({type: "wake"}); await flush();
  assert.deepEqual(f.health(), {state: "auth"});
  const differentKey = "1".repeat(64);
  f.setKey(differentKey); f.sockets[2].ready(); await flush();
  assert.equal(f.clients.at(-1).key, differentKey);
  f.setKey(undefined);
  assert.equal(f.sockets[2].closed, true); assert.deepEqual(f.health(), {state: "unpaired"});
  f.alarm(); await flush(); assert.equal(f.sockets.length, 3);
});
