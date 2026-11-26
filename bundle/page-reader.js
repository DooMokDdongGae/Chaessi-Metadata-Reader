// Serialized by the local installer. The collector is passed in so both
// bookmark actions use precisely the same official-copy path.
async function openReadableBundle(collect) {
  const hostId = "chaessi-bundle-reader";
  const previous = document.getElementById(hostId);
  if (previous) {
    const open = previous.shadowRoot?.querySelector("dialog#reader[open]");
    if (open) {
      open.focus();
      return;
    }
    throw new Error("같은 이름의 화면이 이미 열려 있습니다. 작품을 다시 연 뒤 실행하세요.");
  }
  const address = location.href;
  const bundle = await collect();
  const detail = document.getElementById("detailView");
  function available() {
    if (location.href !== address || !detail?.isConnected || detail.hidden ||
        detail.classList.contains("hidden") || detail.classList.contains("blocked-detail") ||
        detail.getAttribute("aria-hidden") === "true" || !detail.getClientRects().length ||
        getComputedStyle(detail).visibility !== "visible") return false;
    return !Array.from(document.querySelectorAll('dialog[open], [aria-modal="true"], [role="dialog"]')).some(node =>
      !node.hidden && node.getClientRects().length && getComputedStyle(node).visibility === "visible");
  }
  if (!available()) throw new Error("공개 작품 화면이 바뀌었습니다. 작품을 확인한 뒤 다시 실행하세요.");
  const active = document.activeElement;
  const host = document.createElement("div");
  host.id = hostId;
  const shadow = host.attachShadow({ mode: "open" });

  function make(tag, parent, props = {}) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) node[key] = value;
    if (parent) parent.append(node);
    return node;
  }

  const sheet = make("style", shadow);
  sheet.textContent = `
    :host { all: initial; }
    *, *::before, *::after { box-sizing: border-box; }
    dialog { color-scheme: light; color: #192f2b; background: #fff; border: 1px solid #b9cbc2;
      border-radius: 16px; box-shadow: 0 22px 75px #112d2745; padding: 0; margin: auto;
      width: min(940px, calc(100vw - 24px)); height: min(740px, calc(100dvh - 32px)); max-width: 100vw;
      max-height: 100dvh; overflow: hidden; font: 15px/1.5 "Malgun Gothic", system-ui, sans-serif; }
    dialog[open] { display: flex; flex-direction: column; }
    dialog::backdrop { background: rgb(15 35 30 / 48%); }
    h1, h2, h3, p, pre { margin: 0; }
    h1 { font-size: clamp(20px, 3vw, 27px); line-height: 1.24; }
    h2 { font-size: 20px; }
    h3 { font-size: 14px; }
    button, select { font: inherit; color: inherit; }
    button { cursor: pointer; border: 1px solid #b9c9c0; border-radius: 7px; padding: 5px 11px; background: white; }
    button:disabled { color: #718078; background: #f1f3f1; cursor: default; }
    button:not(:disabled):hover, button[aria-pressed=true] { background: #e1eee7; border-color: #608373; }
    button:focus-visible, select:focus-visible { outline: 3px solid #a65c15; outline-offset: 2px; }
    header, .toolbar, .section-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    header { padding: 20px 24px 16px; border-bottom: 1px solid #dce4de; }
    #summary, #kind, .absent { color: #556760; }
    #summary { margin-top: 4px; font-size: 13px; }
    .layout { display: grid; grid-template-columns: minmax(150px, 23%) 1fr; min-height: 0; flex: 1; }
    aside { padding: 18px 14px; border-right: 1px solid #dce4de; background: #f5f8f5; }
    label { display: block; margin-bottom: 6px; font-weight: 650; }
    select { width: 100%; background: #fff; border: 1px solid #bdcdc3; border-radius: 6px; }
    option { padding: 7px; }
    article { padding: 18px clamp(14px, 3vw, 24px); min-width: 0; overflow: auto; overscroll-behavior: contain; }
    .toolbar { margin: 14px 0; flex-wrap: wrap; }
    .modes { display: inline-flex; gap: 4px; }
    #copy-readable:not(:disabled) { background: #17634f; border-color: #17634f; color: white; }
    .field { padding: 12px 0; border-top: 1px solid #dce4de; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 15px/1.65 "Malgun Gothic", system-ui, sans-serif;
      user-select: text; margin-top: 7px; tab-size: 4; }
    #feedback { min-height: 37px; padding: 8px 24px; color: #255242; font-size: 13px; border-top: 1px solid #dce4de; }
    [hidden] { display: none !important; }
    @media(max-width: 560px) {
      dialog { border-radius: 10px; }
      header { padding: 14px; }
      .layout { display: flex; flex-direction: column; }
      aside { padding: 8px 14px; border: 0; }
      select { max-height: 82px; }
      article { flex: 1; }
      #feedback { padding-inline: 14px; }
    }
  `;
  const dialog = make("dialog", shadow, { id: "reader", tabIndex: -1 });
  dialog.setAttribute("aria-labelledby", "reader-title");
  const header = make("header", dialog);
  const heading = make("div", header);
  make("h1", heading, { id: "reader-title", textContent: "묶음 메타데이터 리더" });
  const states = { ok: "읽음", empty: "빈 원문", missing: "누락", failed: "읽기 실패" };
  const counts = { ok: 0, empty: 0, missing: 0, failed: 0 };
  for (const card of bundle.cards) counts[card.status]++;
  const summary = ["전체 " + bundle.count + "장"];
  for (const [status, count] of Object.entries(counts)) if (count) summary.push(states[status] + " " + count);
  make("p", heading, { id: "summary", textContent: summary.join(" · ") });
  const close = make("button", header, { id: "close", type: "button", textContent: "닫기" });
  const layout = make("div", dialog, { className: "layout" });
  const aside = make("aside", layout);
  make("label", aside, { htmlFor: "card", textContent: "이미지 선택" });
  const select = make("select", aside, { id: "card", size: Math.min(10, bundle.count) });
  function kind(card) {
    if (card.status !== "ok") return states[card.status];
    if (card.structure === "characters") return "캐릭터 " + card.characters.length + "개";
    return card.structure === "single" ? "단일 프롬프트" : "구조 미확인";
  }
  for (const card of bundle.cards) {
    make("option", select, { value: String(card.index), textContent: (card.index + 1) + " · " + kind(card) });
  }
  const article = make("article", layout);
  const title = make("h2", article);
  const category = make("p", article, { id: "kind" });
  const toolbar = make("div", article, { className: "toolbar" });
  const modes = make("div", toolbar, { className: "modes" });
  const fieldsButton = make("button", modes, { id: "fields-tab", type: "button", textContent: "필드별 보기" });
  const rawButton = make("button", modes, { id: "raw-tab", type: "button", textContent: "읽기 쉬운 원문" });
  const whole = make("button", toolbar, { id: "copy-readable", type: "button", textContent: "원문 복사" });
  const fields = make("div", article, { id: "fields" });
  const readable = make("pre", article, { id: "readable", dir: "auto" });
  fieldsButton.setAttribute("aria-controls", "fields");
  rawButton.setAttribute("aria-controls", "readable");
  const statusLine = make("div", dialog, { id: "feedback" });
  statusLine.setAttribute("role", "status");
  let card = bundle.cards[0];
  let rawMode = false;

  async function copy(event, value, label) {
    if (!event.isTrusted || typeof value !== "string" || !dialog.open) return;
    const sourceCard = card;
    try {
      await navigator.clipboard.writeText(value);
      if (sourceCard === card) statusLine.textContent = label + " 복사 완료";
    } catch {
      if (sourceCard === card) statusLine.textContent = "복사할 수 없습니다. 브라우저의 클립보드 권한을 확인하세요.";
    }
  }
  function field(key, label, value) {
    const section = make("section", fields, { className: "field" });
    section.dataset.field = key;
    const row = make("div", section, { className: "section-head" });
    make("h3", row, { textContent: label });
    const button = make("button", row, { type: "button", className: "copy", textContent: "복사", disabled: value === null });
    button.setAttribute("aria-label", label + " 복사");
    button.addEventListener("click", event => copy(event, value, label));
    const pre = make("pre", section, { className: "value", dir: "auto" });
    if (value === null || value === "") pre.classList.add("absent");
    pre.textContent = value === null ? "제공되지 않음" : value === "" ? "빈 문자열" : value;
  }
  function mode(next) {
    rawMode = next;
    rawButton.setAttribute("aria-pressed", String(next));
    fieldsButton.setAttribute("aria-pressed", String(!next));
    readable.hidden = !next;
    fields.hidden = next;
  }
  function render(index) {
    card = bundle.cards[index];
    select.value = String(index);
    title.textContent = "이미지 " + (index + 1);
    category.textContent = kind(card);
    whole.disabled = typeof card.readable !== "string";
    const notice = card.status === "failed" ? "이 카드의 공식 복사 결과를 읽지 못했습니다."
      : card.status === "missing" ? "이 카드에 읽기 쉬운 복사 항목이 없습니다."
      : card.status === "empty" ? "공식 복사 결과가 빈 문자열입니다." : "";
    readable.textContent = notice || card.readable;
    fields.replaceChildren();
    if (notice) make("p", fields, { textContent: notice });
    else if (card.structure === "unknown" && card.base === null && card.negative === null && !card.characters.length) {
      make("p", fields, { textContent: "필드 구성을 확인할 수 없습니다. 읽기 쉬운 원문을 확인하세요." });
    } else {
      field("base", "기본 프롬프트", card.base);
      field("negative", "네거티브 프롬프트", card.negative);
      for (const [slot, character] of card.characters.entries()) {
        const ordinal = String(slot + 1);
        field("character-" + ordinal + "-positive", "캐릭터 " + ordinal + " · 프롬프트", character.positive);
        field("character-" + ordinal + "-negative", "캐릭터 " + ordinal + " · 네거티브", character.negative);
      }
    }
    article.scrollTop = 0;
    statusLine.textContent = "";
    mode(rawMode);
  }

  let observer;
  let removed = false;
  function remove() {
    if (removed) return;
    removed = true;
    observer?.disconnect();
    window.removeEventListener("pagehide", remove);
    window.removeEventListener("popstate", remove);
    window.removeEventListener("hashchange", remove);
    if (dialog.open) dialog.close();
    host.remove();
    if (active?.isConnected && typeof active.focus === "function") active.focus({ preventScroll: true });
  }
  close.addEventListener("click", remove);
  dialog.addEventListener("close", remove);
  dialog.addEventListener("cancel", event => { event.preventDefault(); remove(); });
  select.addEventListener("change", () => render(Number(select.value)));
  rawButton.addEventListener("click", () => mode(true));
  fieldsButton.addEventListener("click", () => mode(false));
  whole.addEventListener("click", event => copy(event, card.readable, "원문"));
  render(0);
  document.body.append(host);
  try {
    dialog.showModal();
    select.focus();
    observer = new MutationObserver(() => { if (!available()) remove(); });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true,
      attributeFilter: ["class", "aria-hidden", "aria-modal", "hidden", "open"] });
    for (const event of ["pagehide", "popstate", "hashchange"]) window.addEventListener(event, remove);
  } catch (error) {
    remove();
    throw error;
  }
}

function publicWorkLink(fragment) {
  const match = /^#work=([0-9]{1,20})(?:&lang=(ko|en|zh))?$/.exec(fragment);
  return match ? "https://aitag.win/i/" + match[1] + (match[2] ? "?lang=" + match[2] : "") : null;
}

if (typeof module !== "undefined" && module.exports) module.exports = { openReadableBundle, publicWorkLink };
