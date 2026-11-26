"use strict";

const READER_ERRORS = Object.freeze({
  page: "승인된 aitag.win 작품 링크가 아닙니다.",
  restricted: "사이트가 접근 확인을 요구합니다. Chrome 작품 탭에서 상태를 확인하세요.",
  changed: "수집 중 작품 주소 또는 화면이 바뀌었습니다.",
  unavailable: "수집 전용 Chrome 탭과 확장의 aitag.win 사이트 접근 권한을 확인하세요.",
  layout: "작품의 공식 복사 화면 또는 형식을 확인할 수 없습니다.",
  site_version: "현재 aitag.win의 공식 복사 기능 버전을 지원하지 않습니다. 리더와 Chrome 확장의 업데이트를 확인하세요.",
  capture: "공식 복사 동작을 격리할 수 없습니다.",
  timeout: "시간 안에 작품의 이미지 목록을 확인하지 못했습니다.",
  loading: "작품의 이미지 목록이 아직 준비되지 않았습니다.",
  limit: "묶음의 수집 크기 또는 이미지 수 제한을 넘었습니다.",
  duplicate: "이미 처리한 요청입니다. 리더에서 다시 요청하세요.",
  connection: "로컬 리더 연결을 확인하세요.",
  auth: "연결 키를 확인하세요.",
  inspect_permission: "Chrome 확장 연결 탭에서 NovelAI Inspect 접근을 허용하세요.",
  inspect_manifest: "Chrome에 이전 확장 설정이 남아 있습니다. 확장 관리에서 ‘채씨 메타데이터 리더 연결’을 새로고침한 뒤 연결 탭을 다시 여세요.",
  inspect_permission_declined: "Chrome이 NovelAI 접근을 허용하지 않았습니다. 연결 탭의 권한 요청 결과를 확인하세요.",
  inspect_permission_request: "Chrome에서 NovelAI 권한 요청에 오류가 발생했습니다. 연결 탭에 표시된 Chrome 오류를 확인하세요.",
  inspect_tab: "Chrome에서 NovelAI Inspect를 열고 이미지를 선택하세요.",
  inspect_ambiguous: "Inspect 탭이 여러 개입니다. 가져올 Inspect 탭을 활성화한 뒤 다시 시도하세요.",
  inspect_empty: "Inspect에서 이미지의 Simplified 메타데이터를 확인한 뒤 다시 시도하세요.",
  inspect_source: "Inspect에서 NovelAI가 생성한 이미지의 메타데이터를 확인하세요.",
  inspect_layout: "Inspect의 Simplified 필드 구성을 확인할 수 없습니다.",
  inspect_overlay: "Inspect의 대화상자를 닫은 뒤 다시 시도하세요.",
  inspect_changed: "가져오는 동안 Inspect 탭 또는 이미지가 바뀌었습니다. 다시 시도하세요.",
});

const INSPECT_URL = "https://novelai.net/inspect";
const INSPECT_PERMISSION = Object.freeze({origins: ["https://novelai.net/*"]});

function inspectManifestReady(chromeApi) {
  return chromeApi.runtime.getManifest().optional_host_permissions?.includes(INSPECT_PERMISSION.origins[0]) === true;
}

function bridgeError(code) {
  const safe = Object.hasOwn(READER_ERRORS, code) ? code : "layout";
  return Object.assign(new Error(READER_ERRORS[safe]), { code: safe });
}

function publicWork(url) {
  if (typeof url !== "string" || !/^https:\/\/aitag\.win(?::443)?\/i\/[0-9]{1,20}\/?(?:\?lang=(?:ko|en|zh))?$/.test(url))
    throw bridgeError("page");
  return new URL(url);
}

function sameWork(requested, current) {
  if (!current) return false;
  try {
    const actual = publicWork(current);
    return requested.pathname.replace(/\/$/, "") === actual.pathname.replace(/\/$/, "") &&
      (!requested.search || requested.search === actual.search);
  } catch { return false; }
}

// Executed in the extension's isolated world. Only inspects ordinary public UI
// state. Does not read prompt text, page internals, session state or credentials.
function probeWorkPage(expectedUrl) {
  if (window.top !== window || location.href !== expectedUrl) return { state: "changed" };
  function visible(node) {
    return !node.hidden && !node.closest('[hidden],[inert],[aria-hidden="true"],.hidden') &&
      node.getClientRects().length > 0 && getComputedStyle(node).visibility === "visible";
  }
  const detail = document.getElementById("detailView");
  const modal = [...document.querySelectorAll('dialog[open],[aria-modal="true"],[role="dialog"]')].some(visible);
  if (modal || detail?.classList.contains("blocked-detail") ||
      (!detail && /just a moment|attention required|access denied/i.test(document.title))) return { state: "restricted" };
  const grid = document.getElementById("detailImages");
  if (!detail || !grid || !detail.contains(grid) || !visible(detail) || !visible(grid)) return { state: "loading" };
  const cards = grid.querySelectorAll(":scope > .img-card");
  if (cards.length > 1000) return { state: "limit" };
  if (!cards.length) return { state: "loading" };
  const supportedBuild = ["260915h", "261121b"].some(version => document.querySelector(
    `script[src="/app.js?v=${version}"],script[src="https://aitag.win/app.js?v=${version}"]`));
  if (!supportedBuild) return { state: "site_version" };
  const pending = [...cards].some(card => {
    const pane = card.querySelector(":scope > .json-box > .ai-metadata-view");
    return pane && visible(pane) && !pane.querySelector(".ai-meta-readable");
  });
  return { state: "cards", count: cards.length, pending };
}

function validateBundle(value, count) {
  if (!Number.isInteger(count) || count < 1 || count > 1000 || value?.format !== "chaessi.readable-bundle" ||
      value.version !== 1 || value.count !== count || !Array.isArray(value.cards) || value.cards.length !== count)
    throw bridgeError("layout");
  function field(text) {
    if (text !== null && typeof text !== "string") throw bridgeError("layout");
    return text;
  }
  const cards = value.cards.map((row, index) => {
    if (!row || row.index !== index || !["ok", "empty", "failed", "missing"].includes(row.status) ||
        !["unknown", "single", "characters"].includes(row.structure) || !Array.isArray(row.characters)) throw bridgeError("layout");
    const readable = field(row.readable);
    if ((row.status === "ok" && !readable) || (row.status === "empty" && readable !== "") ||
        (["missing", "failed"].includes(row.status) && readable !== null)) throw bridgeError("layout");
    return { index, status: row.status, readable, base: field(row.base), negative: field(row.negative),
      characters: row.characters.map(c => ({ positive: field(c.positive), negative: field(c.negative) })), structure: row.structure };
  });
  const result = { format: "chaessi.readable-bundle", version: 1, count, cards };
  if (new TextEncoder().encode(JSON.stringify(result)).length > 15 * 1024 * 1024) throw bridgeError("limit");
  return result;
}

function bridgeClient(key, fetcher = fetch, session) {
  if (!/^[0-9a-f]{64}$/.test(key)) throw bridgeError("auth");
  async function request(path, body) {
    const headers = { Authorization: "Bearer " + key, Accept: "application/json" };
    if (session !== undefined) {
      if (typeof session !== "string" || !/^[a-f0-9]{32}$/.test(session)) throw bridgeError("auth");
      headers["X-Reader-Session"] = session;
    }
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetcher("http://127.0.0.1:47921" + path, {
      method: body === undefined ? "GET" : "POST", headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(12000), credentials: "omit", redirect: "error", cache: "no-store",
      referrerPolicy: "no-referrer", mode: "cors",
    });
    if (response.status === 401 || response.status === 403) throw bridgeError("auth");
    if (body !== undefined && response.status === 409) return false;
    if (!response.ok) throw bridgeError("connection");
    return body === undefined ? await response.json() : true;
  }
  return { next: () => request("/next"), event: body => request("/event", body) };
}

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitForWork(chromeApi, tabId, requested, isActive, sleep = delay, now = Date.now) {
  const start = now();
  let stable = null;
  while (now() - start < 75000) {
    if (!isActive()) throw bridgeError("connection");
    let tab;
    try { tab = await chromeApi.tabs.get(tabId); } catch { throw bridgeError("unavailable"); }
    if (tab.pendingUrl && !sameWork(requested, tab.pendingUrl)) throw bridgeError("changed");
    if (!sameWork(requested, tab.url)) {
      // A newly opened tab can briefly show an empty URL or its old document.
      if ((tab.pendingUrl && sameWork(requested, tab.pendingUrl)) || (!tab.url && now() - start < 4000)) {
        await sleep(300); continue;
      }
      throw bridgeError("changed");
    }
    let observation;
    try {
      [observation] = await chromeApi.scripting.executeScript({
        target: { tabId, frameIds: [0] }, world: "ISOLATED", func: probeWorkPage, args: [tab.url],
      });
    } catch {
      if (tab.status !== "loading") throw bridgeError("unavailable");
    }
    const props = observation?.result || {state: "loading"};
    if (props.state === "loading") stable = null;
    else if (props.state !== "cards") throw bridgeError(props.state);
    else {
      if (!observation.documentId || !Number.isInteger(props.count) || props.count < 1 || props.count > 1000)
        throw bridgeError("layout");
      const next = { documentId: observation.documentId, count: props.count, url: tab.url };
      if (stable && stable.documentId === next.documentId && stable.count === next.count && stable.url === next.url) {
        if (now() - stable.since >= (props.pending ? 7000 : 650)) return next;
      } else stable = {...next, since: now()};
    }
    await sleep(350);
  }
  throw bridgeError("timeout");
}

async function collectInChrome(chromeApi, tabId, job, client, injectedCollector, isActive, sleep = delay, now = Date.now) {
  const ready = await waitForWork(chromeApi, tabId, publicWork(job.url), isActive, sleep, now);
  const accepted = await client.event({ id: job.id, event: "count", count: ready.count });
  if (!accepted || !isActive()) throw bridgeError("connection");
  let output;
  try {
    [output] = await chromeApi.scripting.executeScript({ target: {tabId, documentIds: [ready.documentId]},
      world: "MAIN", func: injectedCollector, args: [ready.url, ready.count] });
  } catch { throw bridgeError("unavailable"); }
  if (output?.documentId !== ready.documentId || !isActive()) throw bridgeError("changed");
  if (!output?.result?.ok) throw bridgeError(output?.result?.code);
  const tab = await chromeApi.tabs.get(tabId);
  if (tab.url !== ready.url) throw bridgeError("changed");
  return validateBundle(output.result.bundle, ready.count);
}

async function collectFromOpenInspect(chromeApi, job, client, injectedReader, isActive) {
  if (job.kind !== "inspect" || job.url !== INSPECT_URL) throw bridgeError("page");
  if (!isActive()) throw bridgeError("connection");
  if (!inspectManifestReady(chromeApi)) throw bridgeError("inspect_manifest");
  if (!await chromeApi.permissions.contains(INSPECT_PERMISSION)) throw bridgeError("inspect_permission");
  const match = {url: "https://novelai.net/*"};
  const exact = tab => tab.url === INSPECT_URL && !tab.pendingUrl && !tab.discarded && Number.isInteger(tab.id);
  const candidates = (await chromeApi.tabs.query(match)).filter(exact);
  if (!candidates.length) throw bridgeError("inspect_tab");
  let chosen = candidates[0];
  if (candidates.length > 1) {
    const focused = (await chromeApi.tabs.query({...match, active: true, lastFocusedWindow: true})).filter(exact);
    if (focused.length !== 1 || !candidates.some(tab => tab.id === focused[0].id))
      throw bridgeError("inspect_ambiguous");
    chosen = focused[0];
  }
  const tabId = chosen.id;
  async function current() {
    if (!isActive()) throw bridgeError("connection");
    let tab;
    try { tab = await chromeApi.tabs.get(tabId); } catch { throw bridgeError("inspect_changed"); }
    if (!exact(tab)) throw bridgeError("inspect_changed");
  }
  function checkLocation(expected) { return window === window.top && location.href === expected; }
  async function inject(target, func, args) {
    try {
      const results = await chromeApi.scripting.executeScript({target, world: "ISOLATED", func, args});
      if (results.length === 1 && results[0].frameId === 0) return results[0];
    } catch { /* A pinned document can vanish on navigation or tab closure. */ }
    throw bridgeError("inspect_changed");
  }
  await current();
  const first = await inject({tabId, frameIds: [0]}, checkLocation, [INSPECT_URL]);
  if (!first.result || !first.documentId) throw bridgeError("inspect_changed");
  const pinned = {tabId, documentIds: [first.documentId]};
  const reading = await inject(pinned, injectedReader, []);
  if (reading.documentId !== first.documentId) throw bridgeError("inspect_changed");
  if (!reading.result?.ok) throw bridgeError(reading.result?.code || "inspect_layout");
  const result = validateBundle({format: "chaessi.readable-bundle", version: 1, count: 1,
    cards: [reading.result.card]}, 1);
  result.cards[0].origin = "novelai_inspect";
  result.source = INSPECT_URL;
  await current();
  const last = await inject(pinned, checkLocation, [INSPECT_URL]);
  if (!last.result || last.documentId !== first.documentId) throw bridgeError("inspect_changed");
  if (!isActive() || !await client.event({id: job.id, event: "count", count: 1}))
    throw bridgeError("connection");
  return result;
}

if (typeof module !== "undefined" && module.exports)
  module.exports = { publicWork, sameWork, bridgeClient, waitForWork, collectInChrome, validateBundle, probeWorkPage,
    collectFromOpenInspect, INSPECT_PERMISSION, INSPECT_URL };
