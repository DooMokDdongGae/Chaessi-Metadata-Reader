"use strict";

importScripts("collector.js", "bridge.js", "inspect.js");

(() => {
  const alarmName = "chaessi-reader-reconnect";
  const retryDelays = [1000, 3000, 10000];
  let key = null, channel = null, retryTimer = null, retryIndex = 0;
  let state = "unpaired", draining = false, initialization = null, keyRevision = 0;

  function validKey(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : null;
  }

  function current(c) { return channel === c && Boolean(c.client); }

  function stop(c) {
    channel = null;
    clearTimeout(c.timer);
    if (c.socket) {
      c.socket.onopen = c.socket.onmessage = c.socket.onerror = c.socket.onclose = null;
      try { c.socket.close(); } catch { /* Already closed. */ }
    }
  }

  function lost(c, code = "offline", normalShutdown = false) {
    if (channel !== c) return;
    const retry = c.retry || Boolean(c.client);
    stop(c);
    state = key ? code : "unpaired";
    if (!key || normalShutdown || code === "auth" || !retry || retryIndex >= retryDelays.length) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      dial(true);
    }, retryDelays[retryIndex++]);
  }

  function heartbeat(c) {
    c.timer = setTimeout(() => {
      if (!current(c)) return;
      if (c.awaitingPong) { lost(c); return; }
      try {
        c.awaitingPong = true;
        c.socket.send(JSON.stringify({type: "ping"}));
        heartbeat(c);
      } catch { lost(c); }
    }, 20000);
  }

  function dial(retry = false) {
    if (!key || channel || retryTimer !== null) return;
    if (!retry) retryIndex = 0;
    state = "connecting";
    const c = {retry, client: null, socket: null, timer: null, pending: false, awaitingPong: false};
    channel = c;
    try {
      c.socket = new WebSocket("ws://127.0.0.1:47921/socket");
      c.timer = setTimeout(() => lost(c), 8000);
      c.socket.onopen = () => {
        if (channel !== c) return;
        try { c.socket.send(JSON.stringify({type: "auth", key})); } catch { lost(c); }
      };
      c.socket.onmessage = event => {
        if (channel !== c) return;
        if (typeof event.data !== "string" || event.data.length > 512) { lost(c); return; }
        let message;
        try { message = JSON.parse(event.data); } catch { lost(c); return; }
        if (message?.type === "error" && message.code === "auth") { lost(c, "auth"); return; }
        if (!c.client) {
          if (message?.type !== "ready" || typeof message.session !== "string" ||
              !/^[a-f0-9]{32}$/.test(message.session)) { lost(c); return; }
          clearTimeout(c.timer);
          c.client = bridgeClient(key, fetch, message.session);
          state = "connected";
          heartbeat(c);
          wake(c);
        } else if (message?.type === "shutdown") { lost(c, "offline", true); }
        else if (message?.type === "wake") { wake(c); }
        else if (message?.type === "pong" && c.awaitingPong) {
          c.awaitingPong = false;
          retryIndex = 0;
        }
        else { lost(c); }
      };
      c.socket.onerror = () => lost(c);
      c.socket.onclose = event => lost(c, event.code === 1008 ? "auth" : "offline",
        event.code === 1000 || event.code === 1001);
    } catch { lost(c); }
  }

  async function remember(id) {
    const {seen = []} = await chrome.storage.session.get("seen");
    if (seen.includes(id)) return false;
    await chrome.storage.session.set({seen: [...seen.slice(-255), id]});
    return true;
  }

  async function workTab(url, active) {
    const {ownedTab} = await chrome.storage.session.get("ownedTab");
    let previous;
    if (Number.isInteger(ownedTab?.id)) {
      try { previous = await chrome.tabs.get(ownedTab.id); } catch { /* User closed the tab. */ }
    }
    if (!active()) throw bridgeError("connection");
    let tab;
    if (previous && !previous.pendingUrl && sameWork(publicWork(ownedTab.url), previous.url)) {
      tab = await chrome.tabs.update(previous.id, previous.url === url ? {active: true} : {active: true, url});
    } else {
      tab = await chrome.tabs.create({active: true, url});
    }
    await chrome.storage.session.set({ownedTab: {id: tab.id, url}});
    return tab.id;
  }

  async function handle(c, job) {
    if (typeof job?.id !== "string" || !/^[a-f0-9]{32}$/.test(job.id)) throw bridgeError("connection");
    const active = () => current(c);
    const client = {event: data => {
      if (!active()) throw bridgeError("connection");
      return c.client.event(data);
    }};
    const id = job.id;
    let event;
    try {
      const inspect = job.kind === "inspect";
      if (inspect ? job.url !== INSPECT_URL : job.kind !== undefined) throw bridgeError("page");
      const url = inspect ? INSPECT_URL : publicWork(job.url).href;
      if (!await remember(id)) throw bridgeError("duplicate");
      if (!active()) return;
      let bundle;
      if (inspect) {
        bundle = await collectFromOpenInspect(chrome, job, client, readInspectSimplified, active);
      } else {
        const tabId = await workTab(url, active);
        if (!active()) return;
        bundle = await collectInChrome(chrome, tabId, job, client, collectChromeWork, active);
      }
      bundle.source = job.url;
      event = {id, event: "result", url: job.url, bundle};
    } catch (error) {
      if (!active()) return;
      if (error.code === "auth") throw error;
      const safe = bridgeError(error.code);
      event = {id, event: "error", code: safe.code, message: safe.message};
    }
    for (let attempt = 0; active() && attempt < 3; ++attempt) {
      try { await client.event(event); return; }
      catch (error) {
        if (!active()) return;
        if (error.code === "auth" || attempt === 2) throw error;
        await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
      }
    }
  }

  function wake(c) {
    c.pending = true;
    if (!draining) void drain(c);
  }

  async function drain(c) {
    draining = true;
    try {
      while (current(c) && c.pending) {
        c.pending = false;
        const response = await c.client.next();
        if (!current(c)) break;
        if (!response || !Object.hasOwn(response, "job")) throw bridgeError("connection");
        if (response.job !== null) {
          state = "working";
          await handle(c, response.job);
          if (current(c)) state = "connected";
        }
      }
    } catch (error) {
      lost(c, error.code === "auth" ? "auth" : "offline");
    } finally {
      draining = false;
      if (channel?.pending && current(channel)) void drain(channel);
    }
  }

  function useKey(value) {
    const next = validKey(value);
    if (key !== next) {
      if (channel) stop(channel);
      clearTimeout(retryTimer);
      retryTimer = null;
      retryIndex = 0;
      key = next;
      state = key ? "offline" : "unpaired";
    }
    dial();
  }

  function initialize() {
    if (initialization) return initialization;
    const revision = keyRevision;
    initialization = (async () => {
      await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
      const {readerKey} = await chrome.storage.local.get("readerKey");
      if (!await chrome.alarms.get(alarmName)) {
        await chrome.alarms.create(alarmName, {periodInMinutes: 0.5});
      }
      if (revision === keyRevision) useKey(readerKey);
    })().catch(() => { if (!channel) state = "offline"; }).finally(() => { initialization = null; });
    return initialization;
  }

  chrome.runtime.onStartup.addListener(initialize);
  chrome.runtime.onInstalled.addListener(initialize);
  chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === alarmName && !channel && retryTimer === null) void initialize();
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && Object.hasOwn(changes, "readerKey")) {
      ++keyRevision;
      useKey(changes.readerKey.newValue);
    }
  });
  chrome.runtime.onMessage.addListener((request, sender, respond) => {
    if (request?.type === "reader-health" && sender.id === chrome.runtime.id &&
        sender.url === chrome.runtime.getURL("connect.html")) respond({state});
  });
  void initialize();
})();
