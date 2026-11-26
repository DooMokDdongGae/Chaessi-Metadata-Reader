"""Read prompt fields from one image at a time, preserving the decoded strings."""
from __future__ import annotations

import json
import re
import struct
import zlib
from dataclasses import dataclass, field
from itertools import zip_longest


MAX_IMAGES = 1024
MAX_CHARACTERS = 256
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 4 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ParserError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Character:
    positive: str | None
    negative: str | None
    centers: object = None


@dataclass
class ImageRecord:
    raw: object
    status: str = "no_metadata"
    base: str | None = None
    negative: str | None = None
    characters: list[Character] = field(default_factory=list)
    message: str = ""


def _object(value: object, key: str) -> dict:
    if not isinstance(value, dict):
        raise ParserError("malformed", f"{key}에 JSON 객체가 필요합니다.")
    return value


def _metadata_object(value: object, key: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError) as exc:
            raise ParserError("malformed", f"{key}의 JSON을 읽을 수 없습니다.") from exc
    return _object(value, key)


def _text(source: dict, *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ParserError("malformed", f"{key}에 문자열이 필요합니다.")
        # Win32 clipboard text ends at NUL. Reject inputs we cannot show/copy intact.
        if "\x00" in value or re.search(r"[\ud800-\udfff]", value):
            raise ParserError("malformed", f"{key}에 복사할 수 없는 문자가 있습니다.")
        return value
    return None


def _caption(source: dict, key: str) -> tuple[str | None, list]:
    if key not in source:
        return None, []
    prompt = _object(source[key], key)
    caption = _object(prompt.get("caption", {}), "caption")
    slots = caption.get("char_captions", [])
    if not isinstance(slots, list):
        raise ParserError("malformed", "char_captions에 배열이 필요합니다.")
    if len(slots) > MAX_CHARACTERS:
        raise ParserError("unsupported", f"한 이미지에서 {MAX_CHARACTERS}개까지 캐릭터를 읽을 수 있습니다.")
    return _text(caption, "base_caption"), slots


def _read_fields(metadata: dict, record: ImageRecord) -> None:
    outer = metadata
    novelai = any(
        isinstance(outer.get(key), str) and "novelai" in outer[key].lower()
        for key in ("Software", "Source")
    )
    if "Comment" in outer and (novelai or "parameters" not in outer):
        metadata = _metadata_object(outer["Comment"], "Comment")
    # ComfyUI can store its entire node graph as JSON text in a PNG "prompt" chunk.
    if metadata is outer and not novelai and "v4_prompt" not in metadata and _is_node_graph(metadata.get("prompt")):
        raise ParserError("unsupported", "노드 그래프 형식의 프롬프트는 지원하지 않습니다.")
    base, positive_slots = _caption(metadata, "v4_prompt")
    negative, negative_slots = _caption(metadata, "v4_negative_prompt")
    if base is None:
        base = _text(metadata, "prompt")
    if negative is None:
        negative = _text(metadata, "uc", "negative_prompt")
    # Description is also a generic PNG field. Only NovelAI identifies it as a prompt.
    if base is None and novelai:
        base = _text(outer, "Description")

    characters = []
    for positive, neg in zip_longest(positive_slots, negative_slots):
        positive = {} if positive is None else _object(positive, "char_captions")
        neg = {} if neg is None else _object(neg, "char_captions")
        characters.append(Character(
            _text(positive, "char_caption"),
            _text(neg, "char_caption"),
            positive.get("centers", neg.get("centers")),
        ))
    if base is None and negative is None and "parameters" in metadata:
        base, negative = _split_parameters(_text(metadata, "parameters"))

    if base is not None or negative is not None or any(
        char.positive is not None or char.negative is not None for char in characters
    ):
        record.status = "ok"
    elif metadata and not any(
        key in metadata for key in ("v4_prompt", "v4_negative_prompt", "prompt", "uc", "negative_prompt", "seed")
    ):
        record.status = "unsupported"
    record.base, record.negative, record.characters = base, negative, characters


def _is_node_graph(value: object) -> bool:
    if isinstance(value, str):
        if not value.lstrip().startswith("{") or '"class_type"' not in value:
            return False
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return False
    return isinstance(value, dict) and any(
        isinstance(node, dict) and "class_type" in node and "inputs" in node
        for node in value.values()
    )


_SETTINGS = re.compile(r"(?:\A|\r\n|[\r\n])Steps: [0-9]+, Sampler: [^\r\n]*(?:\r\n|[\r\n])?\Z")
_NEGATIVE = re.compile(r"(?:\A|\r\n|[\r\n])Negative prompt: ?")


def _split_parameters(text: str | None) -> tuple[str | None, str | None]:
    if text is None:
        return None, None
    settings = _SETTINGS.search(text)
    body = text[:settings.start()] if settings else text
    marker = _NEGATIVE.search(body)
    if marker:
        return body[:marker.start()], body[marker.end():]
    if settings:
        return body, None
    raise ParserError("unsupported", "parameters에서 지원하는 SD 생성 정보 형식을 찾지 못했습니다.")


def _parse_image(raw: object) -> ImageRecord:
    record = ImageRecord(raw)
    if raw is None:
        return record
    try:
        metadata = _object(raw, "이미지")
        if "metadata" in metadata:
            nested = metadata["metadata"]
            if nested is None or nested == "":
                return record
            metadata = _metadata_object(nested, "metadata")
        _read_fields(metadata, record)
    except ParserError as exc:
        record.status, record.message = exc.code, str(exc)
    return record


def parse_work(raw: object) -> list[ImageRecord]:
    """Accept a metadata object, an image list, or an explicit images envelope."""
    if isinstance(raw, dict) and "images" in raw:
        images = raw["images"]
        if not isinstance(images, list):
            raise ParserError("malformed", "images에 이미지 목록이 필요합니다.")
    elif isinstance(raw, list):
        images = raw
    elif isinstance(raw, dict):
        images = [raw]
    else:
        raise ParserError("malformed", "메타데이터 객체 또는 이미지 배열을 선택해 주세요.")
    if not images:
        raise ParserError("no_metadata", "이미지 목록이 비어 있습니다.")
    if len(images) > MAX_IMAGES:
        raise ParserError("unsupported", f"작품당 {MAX_IMAGES}개까지 이미지를 읽을 수 있습니다.")
    return [_parse_image(image) for image in images]


def _inflate(data: bytes, budget: int) -> bytes:
    decoder = zlib.decompressobj()
    output = decoder.decompress(data, budget + 1)
    if len(output) > budget:
        raise ParserError("too_large", "PNG 텍스트가 허용 크기를 초과했습니다.")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("incomplete compressed text")
    return output


def _png_text(kind: bytes, payload: bytes, budget: int) -> tuple[str, str, int]:
    key, remainder = payload.split(b"\0", 1)
    if not 1 <= len(key) <= 79:
        raise ValueError("invalid keyword")
    encoding = "latin-1"
    if kind == b"iTXt":
        encoding = "utf-8"
        flag, method = remainder[:2]
        _, _, data = remainder[2:].split(b"\0", 2)
        if flag not in (0, 1) or (flag and method != 0):
            raise ValueError("invalid iTXt compression")
        if flag:
            data = _inflate(data, budget)
    elif kind == b"zTXt":
        if not remainder.startswith(b"\0"):
            raise ValueError("invalid zTXt compression")
        data = _inflate(remainder[1:], budget)
    else:
        data = remainder
    size = len(key) + len(data)
    if size > budget:
        raise ParserError("too_large", "PNG 텍스트가 허용 크기를 초과했습니다.")
    return key.decode("latin-1"), data.decode(encoding), size


def load_png(data: bytes) -> dict:
    """Read PNG text chunks. Pixel data is neither decoded nor sent elsewhere."""
    if len(data) > MAX_PNG_BYTES:
        raise ParserError("too_large", "64 MiB 이하의 PNG를 선택해 주세요.")
    if not data.startswith(PNG_SIGNATURE):
        raise ParserError("unsupported", "PNG 파일 서명을 확인할 수 없습니다.")
    pos = len(PNG_SIGNATURE)
    remaining = MAX_TEXT_BYTES
    metadata = {}
    seen_pixels = False
    chunks = 0
    while len(data) - pos >= 12:
        length, kind = struct.unpack_from(">I4s", data, pos)
        start = pos + 8
        end = start + length
        chunks += 1
        if chunks > 65536:
            raise ParserError("too_large", "PNG 청크 수가 허용 범위를 초과했습니다.")
        if end + 4 > len(data) or (chunks == 1 and (kind != b"IHDR" or length != 13)):
            break
        actual_crc = zlib.crc32(memoryview(data)[pos + 4:end])
        if actual_crc != struct.unpack_from(">I", data, end)[0]:
            break
        pos = end + 4
        if kind == b"IDAT":
            seen_pixels = True
        if kind == b"IEND":
            if length == 0 and seen_pixels and pos == len(data):
                return metadata
            break
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            try:
                key, value, size = _png_text(kind, data[start:end], remaining)
            except ParserError:
                raise
            except (ValueError, zlib.error) as exc:
                raise ParserError("malformed", "PNG 텍스트 청크를 읽을 수 없습니다.") from exc
            remaining -= size
            # Repeated PNG keywords are valid. Preserve all values, never silently choose a prompt.
            if key not in metadata:
                metadata[key] = value
            elif isinstance(metadata[key], list):
                metadata[key].append(value)
            else:
                metadata[key] = [metadata[key], value]
    raise ParserError("malformed", "PNG 청크 길이, 무결성 또는 끝 표시를 확인할 수 없습니다.")
