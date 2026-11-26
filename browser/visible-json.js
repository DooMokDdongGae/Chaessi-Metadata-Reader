// Self-contained so the local installer can put this function in a bookmark.
function saveVisibleJson() {
  function stop(message) {
    throw new Error(message);
  }

  function displayed(element) {
    for (let node = element; node; node = node.parentElement) {
      if (node.hidden || node.inert || node.getAttribute("aria-hidden") === "true" ||
          node.classList.contains("hidden") || node.classList.contains("blocked-detail")) return false;
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility !== "visible" ||
          Number(style.opacity) === 0 || style.contentVisibility === "hidden" ||
          style.clipPath !== "none" || style.filter !== "none" ||
          (style.clip && style.clip !== "auto") ||
          (style.maskImage && style.maskImage !== "none")) return false;
    }
    return Array.from(element.getClientRects()).some(rect => rect.width > 0 && rect.height > 0);
  }

  function onScreen(element) {
    const rect = element.getBoundingClientRect();
    const left = Math.max(0, rect.left);
    const right = Math.min(document.documentElement.clientWidth, rect.right);
    const top = Math.max(0, rect.top);
    const bottom = Math.min(document.documentElement.clientHeight, rect.bottom);
    return right - left >= 2 && bottom - top >= 2 ? { left, right, top, bottom } : null;
  }

  try {
    const path = /^\/i\/([0-9]{1,20})\/?$/.exec(location.pathname);
    if (window !== window.top || location.origin !== "https://aitag.win" || !path ||
        !/^(?:\?lang=(?:en|zh))?$/.test(location.search) || location.hash) {
      stop("aitag.win 작품 상세 화면의 기본 주소에서 실행하세요.");
    }
    const selector = "#detailView #detailImages > .img-card > .json-box > pre.json-content.metadata-raw-view";
    const panels = Array.from(document.querySelectorAll(selector)).filter(
      element => displayed(element) && onScreen(element)
    );
    if (panels.length !== 1) stop("저장할 이미지 한 장의 원본 JSON만 화면에 보이게 한 뒤 다시 누르세요.");
    const panel = panels[0];
    const box = panel.parentElement;
    const toggle = box.querySelector(':scope > .json-actions > button.json-view-toggle[aria-pressed="true"]');
    const copy = box.querySelector(':scope > .json-actions > button[data-mode="json"]');
    if (box.classList.contains("collapsed") || !toggle || !copy) {
      stop("해당 이미지에서 원본 JSON을 선택하고 접힌 내용은 모두 펼쳐 주세요.");
    }
    for (const node of [panel, box]) {
      const style = getComputedStyle(node);
      if (["hidden", "clip"].includes(style.overflowY) && node.scrollHeight > node.clientHeight + 1) {
        stop("원본 JSON이 일부 가려져 있습니다. 전체 내용을 펼쳐 주세요.");
      }
    }
    const bounds = onScreen(panel);
    // The panel must actually receive hits across its visible area. A dialog
    // above the data must not turn into a route to the obscured document.
    for (const xPart of [0.1, 0.5, 0.9]) {
      for (const yPart of [0.1, 0.5, 0.9]) {
        const x = bounds.left + (bounds.right - bounds.left) * xPart;
        const y = bounds.top + (bounds.bottom - bounds.top) * yPart;
        const hit = document.elementFromPoint(x, y);
        if (!hit || !panel.contains(hit)) stop("원본 JSON 위에 다른 화면이 있습니다. 원본을 보이게 해 주세요.");
      }
    }

    const spans = panel.querySelectorAll("*");
    if (spans.length > 100000) stop("표시된 JSON이 너무 큽니다. 사이트의 원본 복사를 이용하세요.");
    for (const child of spans) {
      if (child.tagName !== "SPAN" || !displayed(child) ||
          !/^(k|s|n|b|sd|sd-lora)$/.test(child.className) || child.attributes.length !== 1) {
        stop("이 원본 패널에는 확인할 수 없는 표시 요소가 있습니다. 사이트의 원본 복사를 이용하세요.");
      }
      const style = getComputedStyle(child);
      if (style.position !== "static" || style.display !== "inline" || style.transform !== "none" ||
          style.textTransform !== "none" || parseFloat(style.fontSize) <= 0 ||
          style.color === "transparent" || /,\s*0\)$/.test(style.color)) {
        stop("표시를 확인할 수 없는 원본 텍스트가 있습니다. 사이트의 원본 복사를 이용하세요.");
      }
    }
    // Read only the rendered text after validating the selected visible panel.
    const text = panel.innerText;
    if (text.length > 8 * 1024 * 1024) stop("원본 JSON의 8 MiB 파일 제한을 넘었습니다.");
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      stop("화면에 표시된 내용이 완전한 JSON이 아닙니다. 사이트의 원본 복사 후 리더에서 ‘JSON 입력…’을 사용하세요.");
    }
    if (!data || typeof data !== "object" || Array.isArray(data) || Array.isArray(data.images)) {
      stop("이미지 한 장의 원본 JSON 객체만 저장할 수 있습니다.");
    }
    if (spans.length) {
      // The site's highlighter can remove spaces after a colon inside a string.
      // The visible view cannot distinguish the original spellings in that case.
      const strings = text.match(/"(?:[^"\\]|\\.)*"/g) || [];
      if (strings.some(token => /:(?:[0-9]|true|false|null|")/.test(token))) {
        stop("사이트 강조 표시에서 문자열의 공백이 바뀌었을 수 있습니다. 사이트의 원본 복사 후 ‘JSON 입력…’을 사용하세요.");
      }
    }
    const file = new Blob([text], { type: "application/json;charset=utf-8" });
    if (file.size > 8 * 1024 * 1024) stop("원본 JSON의 8 MiB 파일 제한을 넘었습니다.");
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    try {
      link.href = url;
      link.download = "aitag-" + path[1] + ".json";
      document.body.append(link);
      link.click();
    } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } catch (error) {
    window.alert(error.message || "원본 JSON을 저장하지 못했습니다.");
  }
}
