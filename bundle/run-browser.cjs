"use strict";

// One short-lived, anonymous browser per request. Only the site's own page requests
// data. The local tunnel preserves the browser's TLS connection and caps wire bytes.
const dns = require("node:dns/promises");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const ORIGIN = "https://aitag.win";
const MAX_CARDS = 250;
const MAX_WIRE = 24 * 1024 * 1024;
const MAX_IPC = 16 * 1024 * 1024;
const MESSAGES = {
  url: "https://aitag.win/i/작품번호 형식의 기본 묶음 주소를 입력하세요.",
  runtime: "기존 Playwright와 Microsoft Edge 또는 Chrome 실행 환경을 찾거나 시작할 수 없습니다.",
  network: "공개 작품 화면에 연결할 수 없습니다.",
  address: "공개 인터넷 주소로 확인되지 않아 연결을 중단했습니다.",
  restricted: "사이트의 정상 익명 화면에서 접근을 확인할 수 없습니다.",
  redirect: "요청한 작품 밖으로 이동해 읽기를 중단했습니다.",
  layout: "작품 화면에서 이미지 목록을 확인할 수 없습니다.",
  loading: "작품의 이미지 목록이 표시되지 않았습니다.",
  timeout: "작품을 읽는 제한 시간을 넘겼습니다.",
  changed: "읽는 동안 이미지 수 또는 순서가 바뀌었습니다. 다시 시도해 주세요.",
  limit: "이미지 수, 데이터 크기 또는 요청 수가 읽기 제한을 넘었습니다.",
  capture: "사이트의 읽기 쉬운 내용 복사 결과를 확인할 수 없습니다."
};

function fail(code) {
  return Object.assign(new Error(MESSAGES[code] || MESSAGES.layout), {code});
}

function canonical(input) {
  if (typeof input !== "string" || !/^https:\/\/aitag\.win(?::443)?\/i\/[0-9]{1,20}\/?(?:\?lang=(?:ko|en|zh))?$/.test(input) ||
      input.trim() !== input) throw fail("url");
  return new URL(input).href;
}

const nonPublic = new net.BlockList();
for (const [address, bits] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["192.88.99.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15], ["198.51.100.0", 24],
  ["203.0.113.0", 24], ["224.0.0.0", 4], ["240.0.0.0", 4]
]) nonPublic.addSubnet(address, bits);
function publicIP(address) {
  return net.isIPv4(address) && !nonPublic.check(address);
}

function findRuntime() {
  const roots = [path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime",
    "dependencies", "node", "node_modules", "playwright"), "playwright"];
  let chromium;
  for (const entry of roots) {
    try { ({chromium} = require(entry)); break; } catch {}
  }
  const browsers = [
    [process.env["ProgramFiles(x86)"], "Microsoft/Edge/Application/msedge.exe"],
    [process.env.ProgramFiles, "Microsoft/Edge/Application/msedge.exe"],
    [process.env.ProgramFiles, "Google/Chrome/Application/chrome.exe"],
    [process.env["ProgramFiles(x86)"], "Google/Chrome/Application/chrome.exe"]
  ];
  const executablePath = browsers.filter(([dir]) => dir).map(([dir, exe]) => path.join(dir, exe))
    .find(file => fs.existsSync(file));
  if (!chromium || !executablePath) throw fail("runtime");
  return {chromium, executablePath};
}

async function openTunnel(ip, stop, stats) {
  if (!publicIP(ip)) throw fail("address");
  const sockets = new Set();
  const server = http.createServer((_, res) => { res.writeHead(403); res.end(); });
  server.on("connection", socket => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    socket.on("error", () => socket.destroy());
  });
  server.on("connect", (request, client, head) => {
    if (request.url !== "aitag.win:443" || sockets.size > 48) return client.destroy();
    const remote = net.connect({host: ip, port: 443, family: 4});
    sockets.add(remote);
    remote.on("error", () => client.destroy());
    client.on("close", () => remote.destroy());
    remote.on("close", () => { sockets.delete(remote); client.destroy(); });
    remote.on("connect", () => {
      client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head.length) remote.write(head);
      client.pipe(remote);
      remote.on("data", bytes => {
        stats.wireBytes += bytes.length;
        if (stats.wireBytes > MAX_WIRE) { remote.destroy(); stop("limit"); }
      });
      remote.pipe(client);
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    address: "http://127.0.0.1:" + server.address().port,
    close() { for (const socket of sockets) socket.destroy(); server.close(); }
  };
}

const passive = new Set(["Image", "Media", "Font", "Ping", "Other", "Prefetch", "Manifest"]);
const accepted = new Set(["Script", "Stylesheet", "Document", "XHR", "Fetch"]);
function browserIntegrity(url, type, method) {
  return method === "POST" && ["XHR", "Fetch"].includes(type) && url.origin === ORIGIN &&
    !url.username && !url.password && url.pathname.startsWith("/cdn-cgi/challenge-platform/") &&
    url.pathname.includes("/jsd/");
}
function requestPolicy(input, resourceType, method, work) {
  if (passive.has(resourceType)) return "skip";
  let url;
  try { url = new URL(input); } catch { return "restricted"; }
  if (resourceType === "Stylesheet" && url.protocol === "https:" &&
      ["fonts.googleapis.com", "fonts.gstatic.com"].includes(url.hostname)) return "skip";
  // Block common third-party telemetry without making it a prerequisite for the work.
  if (url.protocol === "https:" && ["Script", "XHR", "Fetch"].includes(resourceType) &&
      (url.hostname === "static.cloudflareinsights.com" && url.pathname.startsWith("/beacon") ||
       ["www.googletagmanager.com", "www.google-analytics.com"].includes(url.hostname))) return "skip";
  if (url.origin !== ORIGIN || url.username || url.password) return "restricted";
  // Let Chromium deliver the site's own anonymous JS Detection result unchanged.
  // Never create, inspect, replay or alter this request. Interactive gates remain a stop.
  if (browserIntegrity(url, resourceType, method)) return "allow";
  if (method !== "GET") {
    if (/auth|captcha|challenge|turnstile|token|consent|verif|access|age.check|session|sensitive/i.test(url.pathname)) {
      return "restricted";
    }
    return ["XHR", "Fetch"].includes(resourceType) ? "skipWrite" : "restricted";
  }
  if (resourceType === "Document" && url.href !== work) return "redirect";
  return accepted.has(resourceType) ? "allow" : "skip";
}

function staticRedirect(from, target, type) {
  if (!target || !["Script", "Stylesheet"].includes(type)) return false;
  let dest;
  try { dest = new URL(target, from); } catch { return false; }
  if (dest.origin !== ORIGIN || dest.username || dest.password) return false;
  return type === "Stylesheet" ? /\.css$/i.test(dest.pathname)
    : /\.js$/i.test(dest.pathname) || dest.pathname.startsWith("/cdn-cgi/");
}

function routeKind(input) {
  const p = new URL(input).pathname;
  if (p.startsWith("/cdn-cgi/challenge-platform/")) return "cloudflare-security";
  if (p.startsWith("/cdn-cgi/rum")) return "cloudflare-rum";
  if (/^\/api\/(?:v[0-9]\/)?[a-z_-]{1,32}(?:\/[a-z_-]{1,24})?$/.test(p)) return p;
  if (/^\/api\/works?\/\d+$/.test(p)) return "work";
  return "other";
}

async function guardPage(context, page, work, stop, stats) {
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", {cacheDisabled: true});
  cdp.on("Network.dataReceived", event => {
    stats.decodedBytes += event.dataLength;
    if (stats.decodedBytes > MAX_WIRE) stop("limit");
  });
  cdp.on("Fetch.requestPaused", async event => {
    const {requestId, resourceType, request} = event;
    const reply = async (method, options = {}) => cdp.send("Fetch." + method, {requestId, ...options});
    try {
      const policy = requestPolicy(request.url, resourceType, request.method, work);
      if (policy === "skip" || policy === "skipWrite") {
        if (policy === "skipWrite") (stats.writesBlocked ??= []).push(routeKind(request.url));
        await reply("failRequest", {errorReason: "BlockedByClient"});
        return;
      }
      if (event.responseStatusCode !== undefined || event.responseErrorReason !== undefined) {
        const status = event.responseStatusCode || 0;
        if (resourceType === "Document" && !stats.documentStatus) stats.documentStatus = status;
        if ((status >= 400 || (status >= 200 && status < 300)) &&
            browserIntegrity(new URL(request.url), resourceType, request.method)) {
          // Return the real, unmodified verdict to the website. Only its rendered,
          // accessible work may be collected, regardless of the callback outcome.
          stats.integrityStatus = status;
          await reply("continueResponse");
          return;
        }
        if ([301, 302, 303, 307, 308].includes(status)) {
          const target = event.responseHeaders?.find(header => header.name.toLowerCase() === "location")?.value;
          if (staticRedirect(request.url, target, resourceType) && (stats.staticRedirects || 0) < 4) {
            stats.staticRedirects = (stats.staticRedirects || 0) + 1;
            await reply("continueResponse");
            return;
          }
        }
        const route = routeKind(request.url);
        if (status >= 400 && ["XHR", "Fetch"].includes(resourceType)) {
          // A rejected auxiliary widget must receive its real error. The normal
          // work view and its own access checks remain required before collection.
          (stats.widgetErrors ??= []).push({resourceType, route, status});
          if (/(?:^|\/)(?:config|works?|auth|access|verify|session|protected)(?:\/|$)/.test(route) ||
              [401, 403, 429, 451].includes(status)) stats.siteDenial = status;
          await reply("continueResponse");
          return;
        }
        if (status < 200 || status >= 300) stats.failure ??= {resourceType, status, route,
          sameOrigin: request.url.startsWith(ORIGIN + "/")};
        if ((status >= 300 && status <= 399) || status === 401 || status === 403 ||
            status === 429 || status === 451 || event.responseErrorReason) {
          stop(status >= 300 && status <= 399 ? "redirect" : (status ? "restricted" : "network"));
          await reply("failRequest", {errorReason: "BlockedByClient"});
          return;
        }
        if (status < 200 || status >= 400) {
          stop("network");
          await reply("failRequest", {errorReason: "BlockedByClient"});
          return;
        }
        const length = event.responseHeaders?.find(header => header.name.toLowerCase() === "content-length");
        if (length && Number(length.value) > MAX_WIRE) {
          stop("limit");
          await reply("failRequest", {errorReason: "BlockedByClient"});
          return;
        }
        await reply("continueResponse");
        return;
      }
      if (policy !== "allow" || ++stats.requests > 120) {
        if (policy !== "skip") stats.failure ??= {resourceType, policy, sameOrigin: request.url.startsWith(ORIGIN + "/"),
          method: request.method, endpointKind: routeKind(request.url)};
        if (policy !== "skip") stop(policy === "allow" ? "limit" : policy);
        await reply("failRequest", {errorReason: "BlockedByClient"});
        return;
      }
      await reply("continueRequest");
    } catch {
      if (!page.isClosed()) stop("network");
    }
  });
  await cdp.send("Fetch.enable", {patterns: [
    {urlPattern: "*", requestStage: "Request"}, {urlPattern: "*", requestStage: "Response"}
  ]});
}

function visibleCount() {
  const view = document.getElementById("detailView");
  const gates = document.querySelectorAll('form#challenge-form, #challenge-running, dialog[open], [aria-modal="true"]');
  if (Array.from(gates).some(gate => gate.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}))) return -1;
  if (view?.classList.contains("blocked-detail")) return -1;
  if (!view || view.hidden || view.classList.contains("hidden")) return 0;
  if (!view.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return 0;
  return view.querySelectorAll("#detailImages > .img-card").length;
}

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function collectPage(page, work, stats, onCount) {
  const {collectReadableBundle} = require("./collect.js");
  if (page.url() !== work) throw fail("redirect");
  let count = 0, consecutive = 0;
  for (let i = 0; i < 65; i++) {
    const current = await page.evaluate(visibleCount);
    if (current < 0) throw fail("restricted");
    if (current > MAX_CARDS) throw fail("limit");
    consecutive = current && current === count ? consecutive + 1 : 0;
    count = current;
    if (consecutive >= 2) break;
    await delay(250);
  }
  if (stats.siteDenial || !count || consecutive < 2) throw fail(stats.siteDenial ? "restricted" : "loading");
  stats.cardCount = count;
  if (onCount) onCount(count);
  const collector = await page.evaluateHandle("(" + collectReadableBundle.toString() + ")");
  const result = await collector.evaluate(async (collect, expectedCount) => {
    try {
      return {ok: true, bundle: await collect({expectedCount})};
    } catch (error) {
      return {ok: false, code: String(error.code || "layout")};
    }
  }, count);
  if (!result.ok) throw fail(Object.hasOwn(MESSAGES, result.code) ? result.code : "layout");
  if (page.url() !== work || await page.evaluate(visibleCount) !== count) throw fail("changed");
  if (Buffer.byteLength(JSON.stringify(result), "utf8") + 1 > MAX_IPC) throw fail("limit");
  return result.bundle;
}

async function readBundle(input, {onCount, stats = {}} = {}) {
  const work = canonical(input);
  const {chromium, executablePath} = findRuntime();
  Object.assign(stats, {requests: 0, wireBytes: 0, decodedBytes: 0, documentStatus: 0});
  let browser, tunnel, stopped = false, rejectStop;
  const deadline = new Promise((_, reject) => { rejectStop = reject; });
  const stop = code => { if (!stopped) { stopped = true; rejectStop(fail(code)); } };
  const timer = setTimeout(() => stop("timeout"), 55000);
  const main = async () => {
    let ips;
    try { ips = await dns.lookup("aitag.win", {all: true, family: 4}); }
    catch { throw fail("network"); }
    if (!ips.length || !ips.every(row => publicIP(row.address))) throw fail("address");
    if (stopped) return;
    tunnel = await openTunnel(ips[0].address, stop, stats);
    if (stopped) { tunnel.close(); return; }
    try {
      browser = await chromium.launch({
        executablePath, headless: true, chromiumSandbox: true, timeout: 12000,
        proxy: {server: tunnel.address, bypass: "<-loopback>"},
        args: ["--disable-background-networking", "--disable-quic",
          "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
      });
    } catch { throw fail("runtime"); }
    if (stopped) { await browser.close(); return; }
    const context = await browser.newContext({
      acceptDownloads: false, serviceWorkers: "block", locale: "ko-KR", permissions: [],
      viewport: {width: 1200, height: 850}
    });
    await context.routeWebSocket(/.*/, ws => ws.close());
    const page = await context.newPage();
    page.on("dialog", dialog => { stop("restricted"); dialog.dismiss().catch(() => {}); });
    context.on("page", popup => { stop("redirect"); popup.close().catch(() => {}); });
    page.on("download", file => { stop("restricted"); file.cancel().catch(() => {}); });
    await guardPage(context, page, work, stop, stats);
    await page.goto(work, {waitUntil: "domcontentloaded", timeout: 22000});
    return await collectPage(page, work, stats, onCount);
  };
  try {
    return await Promise.race([main(), deadline]);
  } finally {
    stopped = true;
    clearTimeout(timer);
    if (tunnel) tunnel.close();
    if (browser) await browser.close().catch(() => {});
  }
}

async function cli() {
  try {
    const chunks = [];
    let size = 0;
    for await (const chunk of process.stdin) {
      size += chunk.length;
      if (size > 2048) throw fail("url");
      chunks.push(chunk);
    }
    let request;
    try { request = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { throw fail("url"); }
    const onCount = request?.progress === true
      ? count => process.stdout.write(JSON.stringify({event: "count", count}) + "\n") : undefined;
    const bundle = await readBundle(request?.url, {onCount});
    process.stdout.write(JSON.stringify({ok: true, bundle}) + "\n");
  } catch (error) {
    const code = Object.hasOwn(MESSAGES, error.code) ? error.code : "network";
    process.stdout.write(JSON.stringify({ok: false, code, message: MESSAGES[code]}) + "\n");
  }
}

module.exports = {canonical, publicIP, requestPolicy, staticRedirect, guardPage, collectPage, readBundle};
if (require.main === module) cli();
