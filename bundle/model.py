"""One record for every card in the source work. Never deduplicate by prompt text."""
import json
import re
from collections import Counter
from dataclasses import dataclass

from reader_parser import MAX_CHARACTERS, MAX_IMAGES, parse_work


FORMAT = "chaessi.readable-bundle"
URL = re.compile(r"https://aitag\.win(?::443)?/i/(?P<work>[0-9]{1,20})/?(?:\?lang=(?P<lang>ko|en|zh))?")
STATUS = {"ok": "읽음", "empty": "빈 원문", "missing": "누락", "failed": "읽기 실패"}
STRUCTURE = {"single": "단일 프롬프트", "characters": "캐릭터별 프롬프트", "unknown": "구조 미확인"}
UNREPRESENTABLE = re.compile(r"[\x00\ud800-\udfff]")
FORMAT_HEADER = re.compile(r"\A(?:Format|형식|形式|格式):([^\r\n]{1,64})(?=\r|\n|\Z)")
SOURCE_FORMATS = {
    "nai": "NAI", "novelai": "NAI", "sd": "SD", "stable diffusion": "SD",
    "a1111": "A1111", "comfyui": "ComfyUI",
}
PNG_ORIGINAL_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class Card:
    status: str
    readable: str | None = None
    structure: str = "unknown"
    base: str | None = None
    negative: str | None = None
    characters: tuple = ()
    local: bool = False
    origin: str | None = "aitag"
    filename: str | None = None
    issue: str | None = None

    @property
    def kind(self):
        if self.status not in ("ok", "empty"):
            return STATUS[self.status]
        if self.status == "empty":
            return STATUS["empty"]
        if self.structure == "characters":
            return f"캐릭터 {len(self.characters)}개 슬롯"
        return STRUCTURE[self.structure]

    @property
    def source_format(self):
        """Use Inspect's verified source or aitag's explicit format header."""
        if self.local or self.status != "ok" or not self.readable:
            return "unknown"
        if self.origin == "novelai_inspect":
            return "NAI"
        if self.origin != "aitag":
            return "unknown"
        header = FORMAT_HEADER.match(self.readable)
        if header is None:
            return "unknown"
        return SOURCE_FORMATS.get(header[1].strip(" \t").casefold(), "unknown")

    @property
    def model_family(self):
        declared = self.source_format
        return declared if declared in ("NAI", "SD") else "unknown"

    def fields(self):
        pairs = [("Base Positive", self.base), ("Base Undesired", self.negative)]
        for index, (positive, negative) in enumerate(self.characters, 1):
            pairs.extend([(f"Character {index} Positive", positive), (f"Character {index} Undesired", negative)])
        return [(label, value) for label, value in pairs if value is not None]


def _text(value):
    if value is not None and (not isinstance(value, str) or UNREPRESENTABLE.search(value)):
        raise ValueError("Windows에서 그대로 복사할 수 없는 문자열입니다.")
    return value


def _card(item):
    status = item["status"]
    if not isinstance(status, str) or status not in STATUS:
        raise ValueError("카드 상태 오류")
    origin = item.get("origin", "aitag")
    if origin not in ("aitag", "novelai_inspect"):
        origin = None
    if status in ("missing", "failed"):
        return Card(status, origin=origin)
    readable = _text(item["readable"])
    if readable is None or (readable == "") != (status == "empty"):
        raise ValueError("카드 원문 오류")
    if origin is None:
        return Card(status, readable, origin=None)
    # A usable official copy survives even when the separate field mapping is invalid.
    try:
        structure = item["structure"]
        chars = item["characters"]
        if not isinstance(chars, list) or len(chars) > MAX_CHARACTERS:
            raise ValueError("슬롯 목록 오류")
        slots = tuple((_text(row["positive"]), _text(row["negative"])) for row in chars)
        if structure not in STRUCTURE or (structure == "single" and slots) or (structure == "characters" and not slots):
            raise ValueError("구조 불일치")
        return Card(status, readable, structure, _text(item["base"]), _text(item["negative"]), slots, origin=origin)
    except (KeyError, ValueError, TypeError):
        return Card(status, readable, origin=origin)


def decode_bundle(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("지원하지 않는 묶음 파일입니다.")
    count, items = data.get("count"), data.get("cards")
    if type(count) is not int or not 1 <= count <= MAX_IMAGES or not isinstance(items, list) or len(items) > count:
        raise ValueError("묶음의 전체 이미지 수 또는 카드 목록을 확인할 수 없습니다.")
    rows = [Card("failed") for _ in range(count)]
    found = set()
    for item in items:
        index = item.get("index") if isinstance(item, dict) else None
        if type(index) is not int or not 0 <= index < count:
            continue
        if index in found:
            rows[index] = Card("failed")
            continue
        found.add(index)
        try:
            rows[index] = _card(item)
        except (KeyError, ValueError, TypeError):
            rows[index] = Card("failed")
    return rows


def decode_input(data, *, png=False, filename=None):
    if not png and isinstance(data, dict) and data.get("format") == FORMAT:
        return decode_bundle(data)
    rows = []
    # PNG text keywords are arbitrary. A keyword such as "images" or "format"
    # must not make the contents masquerade as a separate work envelope.
    for record in parse_work([data] if png else data):
        origin = "local_png" if png else None
        if record.status != "ok":
            status = "missing" if record.status == "no_metadata" else "failed"
            rows.append(Card(status, local=True, origin=origin, filename=filename, issue=record.status))
            continue
        slots = tuple((char.positive, char.negative) for char in record.characters)
        readable, issue = None, None
        if png:
            comment = data.get("Comment")
            readable = comment if isinstance(comment, str) else json.dumps(data, ensure_ascii=True, indent=2)
            # Keep original Comment bytes faithfully through Unicode copying.
            # Oversize originals stay unavailable instead of looking complete.
            if UNREPRESENTABLE.search(readable) or len(readable.encode("utf-8")) > PNG_ORIGINAL_LIMIT:
                readable, issue = None, "original_limit"
            _text(record.base)
            _text(record.negative)
            for positive, negative in slots:
                _text(positive)
                _text(negative)
        rows.append(Card("ok", readable, "characters" if slots else "single", record.base,
                         record.negative, slots, local=True, origin=origin, filename=filename, issue=issue))
    return rows


def summary(cards):
    counts = Counter(card.status for card in cards)
    return "  ·  ".join([f"전체 {len(cards)}장"] + [f"{label} {counts[key]}" for key, label in STATUS.items() if counts[key]])
