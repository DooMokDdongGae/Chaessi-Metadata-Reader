"use strict";

// Setup only. Requests and reconnects belong to the background service worker.
const form = document.getElementById("pair");
const input = document.getElementById("key");
const forget = document.getElementById("forget");
const statusLine = document.getElementById("status");
const inspectAccess = document.getElementById("inspect-access");
const inspectStatus = document.getElementById("inspect-status");

async function refresh() {
  const {readerKey} = await chrome.storage.local.get("readerKey");
  const paired = typeof readerKey === "string" && /^[a-f0-9]{64}$/.test(readerKey);
  form.hidden = paired;
  forget.hidden = !paired;
  if (!paired) { statusLine.textContent = "최초 연결 키를 입력하세요."; return; }
  const health = await chrome.runtime.sendMessage({type: "reader-health"});
  const messages = {
    connected: "리더와 연결되었습니다. 이 설정 탭은 닫아도 됩니다.",
    working: "리더의 요청을 처리하고 있습니다. 이 탭은 닫아도 됩니다.",
    connecting: "리더에 자동으로 연결하고 있습니다. 이 탭은 닫아도 됩니다.",
    auth: "연결 설정이 일치하지 않습니다. 리더의 최초 연결 안내를 확인하세요.",
  };
  statusLine.textContent = messages[health?.state] || "설정이 저장되었습니다. 리더를 실행하면 자동 연결됩니다. 이 탭은 닫아도 됩니다.";
}
function refreshSafely() {
  refresh().catch(() => { statusLine.textContent = "확장 설정을 읽지 못했습니다. Chrome 확장을 갱신한 뒤 이 설정을 다시 여세요."; });
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  const key = input.value.trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(key)) { statusLine.textContent = "최초 연결 안내의 64자리 키를 입력하세요."; return; }
  try {
    await chrome.storage.local.set({readerKey: key});
    input.value = "";
    refreshSafely();
  } catch { statusLine.textContent = "이 Chrome 프로필에 연결 설정을 저장할 수 없습니다."; }
});
forget.addEventListener("click", async () => {
  await chrome.storage.local.remove("readerKey");
  refreshSafely();
});
async function showInspectAccess() {
  if (!inspectManifestReady(chrome)) {
    inspectAccess.disabled = true;
    inspectStatus.textContent = READER_ERRORS.inspect_manifest;
    return;
  }
  const granted = await chrome.permissions.contains(INSPECT_PERMISSION);
  inspectAccess.hidden = granted;
  inspectAccess.disabled = false;
  inspectStatus.textContent = granted ? "NovelAI Inspect 접근이 허용되었습니다." :
    "Inspect 가져오기를 사용하려면 사이트 접근을 한 번 허용하세요.";
}
inspectAccess.addEventListener("click", async () => {
  try {
    const granted = await chrome.permissions.request(INSPECT_PERMISSION);
    await showInspectAccess();
    if (!granted) inspectStatus.textContent = READER_ERRORS.inspect_permission_declined;
  } catch (error) {
    inspectStatus.textContent = READER_ERRORS.inspect_permission_request + "\nChrome: " +
      (typeof error?.message === "string" ? error.message.slice(0, 400) : "오류 세부 정보 없음");
  }
});
const inspectRefresh = () => showInspectAccess().catch(() => {
  inspectStatus.textContent = "Inspect 접근 설정을 읽지 못했습니다.";
});
chrome.permissions.onAdded.addListener(inspectRefresh);
chrome.permissions.onRemoved.addListener(inspectRefresh);
chrome.storage.onChanged.addListener((_changes, area) => { if (area === "local") refreshSafely(); });
window.addEventListener("focus", refreshSafely);
refreshSafely();
inspectRefresh();
