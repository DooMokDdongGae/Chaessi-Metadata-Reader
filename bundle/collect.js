// This function is also serialized as a bookmark and run in an isolated browser.
async function collectReadableBundle(options = {}) {
  const fail = (code, message) => Object.assign(new Error(message), { code });
  const path = /^\/i\/[0-9]{1,20}\/?$/.test(location.pathname);
  if (window !== window.top || location.origin !== "https://aitag.win" || !path ||
      !/^(?:\?lang=(?:ko|kr|en|zh|zh[_-](?:cn|tw|hant)|ja|jp))?$/i.test(location.search) || location.hash) {
    throw fail("page", "aitag.win 작품의 기본 상세 화면에서 실행하세요.");
  }
  const detail = document.getElementById("detailView");
  const grid = document.getElementById("detailImages");
  const pageAddress = location.href;
  const originScroll = [window.scrollX, window.scrollY];
  const blank = () => ({ base: null, negative: null, characters: [], structure: "unknown" });

  function displayed(element) {
    if (!element || !element.isConnected) return false;
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.hidden || node.inert || node.getAttribute("aria-hidden") === "true" ||
          node.classList.contains("hidden") || node.classList.contains("blocked-detail") ||
          style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0 ||
          style.contentVisibility === "hidden") return false;
    }
    return element.getClientRects().length > 0;
  }

  function checkDetail() {
    if (location.href !== pageAddress || detail !== document.getElementById("detailView") ||
        grid !== document.getElementById("detailImages")) {
      throw fail("changed", "읽는 동안 작품 화면이 바뀌었습니다. 다시 실행하세요.");
    }
    const modal = Array.from(document.querySelectorAll('dialog[open], [aria-modal="true"]')).some(displayed);
    if (modal || (detail && !displayed(detail))) {
      throw fail("restricted", "사이트에서 공개 작품 상세가 정상적으로 표시된 뒤 실행하세요.");
    }
    if (!detail || !grid || !detail.contains(grid) || !displayed(grid)) {
      throw fail("loading", "작품의 이미지 목록이 표시된 뒤 실행하세요.");
    }
  }

  function actionable(button) {
    if (!displayed(button) || button.disabled || button.getAttribute("aria-disabled") === "true") return false;
    const rect = button.getBoundingClientRect();
    return button.contains(document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2));
  }

  function showButton(button) {
    if (!button || !displayed(button)) return false;
    button.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
    return actionable(button);
  }

  // The public site's click listener calls writeText synchronously, before its
  // first await. Shadow it only on this object, only for this click stack.
  function clickForText(button) {
    const clipboard = navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") {
      throw fail("capture", "이 브라우저에서는 공식 복사 동작을 안전하게 읽을 수 없습니다.");
    }
    const previous = Object.getOwnPropertyDescriptor(clipboard, "writeText");
    if (previous && !previous.configurable) throw fail("capture", "복사 동작을 격리할 수 없습니다.");
    let calls = 0;
    let captured;
    const capture = function (value) {
      ++calls;
      const event = window.event;
      if (event && event.type === "click" && event.currentTarget === button && event.target === button &&
          typeof value === "string") captured = value;
      return Promise.resolve();
    };
    try {
      Object.defineProperty(clipboard, "writeText", { configurable: true, value: capture });
    } catch {
      throw fail("capture", "브라우저가 복사 동작 격리를 허용하지 않았습니다.");
    }
    try {
      button.click();
    } finally {
      if (previous) Object.defineProperty(clipboard, "writeText", previous);
      else delete clipboard.writeText;
    }
    return calls === 1 && typeof captured === "string" ? captured : null;
  }

  // The site's default public formatter labels prompt sections and numbered
  // character lines. Read values from the official copy, including its original
  // CR/LF sequences. The rendered section/slot counts disambiguate their roles.
  function fields(text, view) {
    const dictionaries = [
      ["Format", "Prompt", "Negative prompt", "Character prompts", "Character", "Character negative", "Position",
        "Models and assets", "LoRA", "Generation settings", "Workflow", "Other information", "Parser notes"],
      ["형식", "프롬프트", "네거티브 프롬프트", "캐릭터 프롬프트", "캐릭터", "캐릭터 네거티브 프롬프트", "위치",
        "모델 및 리소스", "LoRA", "생성 설정", "워크플로", "기타 정보", "파서 메모"],
      ["格式", "提示词", "负面提示词", "角色提示词", "角色", "角色负面提示词", "位置",
        "模型与资源", "LoRA", "生成参数", "工作流", "其他信息", "解析提示"],
      ["格式", "提示詞", "負面提示詞", "角色提示詞", "角色", "角色負面提示詞", "位置",
        "模型與資源", "LoRA", "生成參數", "工作流程", "其他資訊", "解析提示"],
      ["形式", "プロンプト", "ネガティブプロンプト", "キャラクタープロンプト", "キャラクター", "キャラクターのネガティブプロンプト", "位置",
        "モデルとリソース", "LoRA", "生成設定", "ワークフロー", "その他の情報", "解析メモ"]
    ];
    const words = dictionaries.find(labels => text.startsWith(labels[0] + ": ") &&
      labels.slice(1, 4).some(label => text.includes("\n\n" + label + ":")));
    if (!words) return blank();
    const headings = [];
    for (const match of text.matchAll(/\n\n([^:\n\r]{1,60}):(?=\n| |$)/gu)) {
      const name = match[1].replace(/ [1-9][0-9]*$/, "");
      if (words.slice(1, 4).includes(name) || words.slice(7).includes(name)) {
        headings.push({ name, start: match.index, body: match.index + match[0].length + 1 });
      }
    }
    const sections = new Map();
    for (let i = 0; i < headings.length; ++i) {
      const heading = headings[i];
      if (sections.has(heading.name)) return blank();
      sections.set(heading.name, text.slice(heading.body, headings[i + 1]?.start ?? text.length));
    }
    const find = selector => Array.from(view.querySelectorAll(selector));
    const roleCount = role => find(":scope > section.ai-meta-section." + role + " > .ai-meta-prompt-item").length;
    const base = sections.get(words[1]) ?? null;
    const negative = sections.get(words[2]) ?? null;
    if (roleCount("positive") !== Number(base !== null) || roleCount("negative") !== Number(negative !== null)) return blank();
    const slots = find(":scope > section.ai-meta-section.characters > .ai-meta-character");
    if (find(":scope > section.ai-meta-section.characters .ai-meta-limit-note").length ||
        sections.has(words[3]) !== Boolean(slots.length)) return blank();
    // Refuse ambiguous in-prompt secondary headings, including ones that do not
    // correspond to a section actually rendered by the site.
    for (const [offset, css] of [[7, "models"], [8, "loras"], [9, "settings"], [11, "other"]]) {
      if (sections.has(words[offset]) && !find(":scope > section.ai-meta-section." + css).length) return blank();
    }
    if ((sections.has(words[10]) && !find(".ai-meta-workflow-summary").length) ||
        (sections.has(words[12]) && !find(".ai-meta-warning, .ai-meta-warnings, .ai-meta-section.warnings").length)) return blank();
    const characters = [];
    if (slots.length) {
      const body = sections.get(words[3]);
      const markers = Array.from(body.matchAll(new RegExp("(?:^|\\n)" + words[4] + " ([1-9][0-9]*): ", "gu")));
      if (markers.length !== slots.length || markers[0].index !== 0) return blank();
      for (let slot = 0; slot < markers.length; ++slot) {
        const mark = markers[slot];
        if (Number(mark[1]) !== slot + 1) return blank();
        const value = body.slice(mark.index + mark[0].length, markers[slot + 1]?.index ?? body.length);
        let phrasing = value;
        const locationMarker = " | " + words[6] + ": ";
        if (value.includes(locationMarker)) {
          const title = slots[slot].querySelector(":scope > .ai-meta-character-title");
          if (!displayed(title) || title.children.length) return blank();
          // Only inspect the ordinary rendered slot label. The official title
          // prints "N · position" when the last segment really is a position.
          const label = title.innerText;
          const prefix = String(slot + 1) + " · ";
          if (label.startsWith(prefix)) {
            const suffix = locationMarker + label.slice(prefix.length);
            if (!value.endsWith(suffix)) return blank();
            phrasing = value.slice(0, -suffix.length);
          } else if (label !== String(slot + 1)) return blank();
        }
        const negativeShown = Boolean(slots[slot].querySelector(":scope > .ai-meta-inline-label"));
        const pair = negativeShown ? phrasing.split(" | " + words[5] + ": ") : [phrasing];
        const wraps = slots[slot].querySelectorAll(":scope > .ai-meta-text-wrap").length;
        const positiveShown = wraps - Number(negativeShown);
        if (pair.length > 2 || negativeShown !== (pair.length === 2) || positiveShown < 0 || positiveShown > 1 ||
            (!positiveShown && pair[0] !== "-")) return blank();
        characters.push({ positive: positiveShown ? pair[0] : null, negative: pair[1] ?? null });
      }
    }
    return { base, negative, characters, structure: characters.length ? "characters" : base !== null ? "single" : "unknown" };
  }

  function readCard(card, index) {
    const result = { index, status: "missing", readable: null, ...blank() };
    const boxes = card.querySelectorAll(":scope > .json-box");
    if (!displayed(card) || boxes.length > 1) return { ...result, status: "failed" };
    const box = boxes[0];
    if (!box) return result;
    const controls = () => box.querySelectorAll(':scope > .json-actions > button[data-mode="readable"]');
    let buttons = controls();
    let restore = null;
    try {
      if (buttons.length === 0) {
        const raw = box.querySelector(':scope > .json-actions > button[data-mode="json"]');
        const toggle = box.querySelector(':scope > .json-actions > button.json-view-toggle[aria-pressed="true"]');
        if (raw && toggle && showButton(toggle)) {
          restore = toggle;
          toggle.click();
          checkDetail();
          buttons = controls();
          if (buttons.length !== 1 || buttons[0] !== raw) return { ...result, status: "failed" };
        } else {
          if (box.querySelector(":scope > .json-actions > button[data-mode]")) result.status = "failed";
          return result;
        }
      }
      const button = buttons[0];
      const view = box.querySelector(":scope > .ai-metadata-view > .ai-meta-readable");
      if (buttons.length !== 1 || !displayed(view) || !showButton(button)) return { ...result, status: "failed" };
      const captured = clickForText(button);
      if (captured === null) return { ...result, status: "failed" };
      result.readable = captured;
      result.status = captured === "" ? "empty" : "ok";
      if (captured !== "") {
        try { Object.assign(result, fields(captured, view)); }
        catch { /* Keep the official copy even if this site's field markup has changed. */ }
      }
      return result;
    } finally {
      if (restore && restore.getAttribute("aria-pressed") === "false") {
        checkDetail();
        if (!showButton(restore)) throw new Error("view_restore");
        restore.click();
        if (restore.getAttribute("aria-pressed") !== "true") throw new Error("view_restore");
      }
    }
  }

  checkDetail();
  // A future handler could defer its first clipboard call until after click()
  // returns. Only the reviewed synchronous public builds are safe to invoke.
  const supportedBuild = ["260915h", "261121b"].some(version => document.querySelector(
    `script[src="/app.js?v=${version}"],script[src="https://aitag.win/app.js?v=${version}"]`));
  if (!supportedBuild) {
    throw fail("site_version", "현재 aitag.win의 공식 복사 기능 버전을 지원하지 않습니다. 리더와 Chrome 확장의 업데이트를 확인하세요.");
  }
  const nodes = Array.from(grid.querySelectorAll(":scope > .img-card"));
  if (!nodes.length) throw fail("loading", "작품에 표시된 이미지 카드가 없습니다.");
  if (nodes.length > 1000) throw fail("limit", "작품당 1,000장까지 읽을 수 있습니다.");
  if (options.expectedCount !== undefined && options.expectedCount !== nodes.length) {
    throw fail("changed", "화면에 표시된 이미지 수가 바뀌었습니다.");
  }
  // Keep card identities, including duplicate prompts, independent of changing
  // button captions such as 'Copied'. Never locate the nth matching caption.
  const cards = [];
  let bytes = 0;
  try {
    for (const [index, card] of nodes.entries()) {
      checkDetail();
      if (!card.isConnected || card.parentElement !== grid) throw fail("changed", "이미지 카드가 바뀌었습니다.");
      let result;
      try { result = readCard(card, index); }
      catch (error) {
        if (error.code) throw error;
        result = { index, status: "failed", readable: null, ...blank() };
      }
      bytes += new TextEncoder().encode(result.readable || "").length;
      if (bytes > 8 * 1024 * 1024) throw fail("limit", "묶음 원문의 8 MiB 제한을 넘었습니다.");
      cards.push(result);
    }
    checkDetail();
    const after = grid.querySelectorAll(":scope > .img-card");
    if (after.length !== nodes.length || nodes.some((node, index) => after[index] !== node)) {
      throw fail("changed", "이미지 순서가 바뀌었습니다. 다시 실행하세요.");
    }
  } finally {
    window.scrollTo({ left: originScroll[0], top: originScroll[1], behavior: "instant" });
  }
  const bundle = { format: "chaessi.readable-bundle", version: 1, count: cards.length, cards };
  const serialized = JSON.stringify(bundle);
  if (new TextEncoder().encode(serialized).length > 15 * 1024 * 1024) {
    throw fail("limit", "묶음 JSON의 15 MiB 제한을 넘었습니다.");
  }
  if (options.download === true) {
    const file = new Blob([serialized], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    try {
      link.href = url;
      link.download = "aitag-" + location.pathname.split("/")[2] + ".readable-bundle.json";
      document.body.append(link);
      link.click();
    } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  }
  return bundle;
}

if (typeof module !== "undefined" && module.exports) module.exports = { collectReadableBundle };
