"""Read the public metadata blocks for a single aitag work. No media is fetched."""

import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


HOST = "aitag.win"
IMAGE_HOST = "ai-img.10118899.xyz"
MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 1000
TIMEOUT = 15
_DNS_SLOTS = threading.BoundedSemaphore(4)
_PUBLIC_V6 = ipaddress.ip_network("2000::/3")


class ReaderNetworkError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _work_path(url):
    if not isinstance(url, str) or len(url) > 512:
        raise ReaderNetworkError("url", "aitag.win 작품 상세 링크를 입력하세요.")
    clean = url.strip()
    match = re.fullmatch(r"https://aitag\.win(?::443)?(/i/[0-9]{1,20}/?)", clean,
                         flags=re.IGNORECASE | re.ASCII)
    if not match or not match[1].startswith("/i/"):
        raise ReaderNetworkError("url", "https://aitag.win/i/작품번호 형식의 상세 링크를 입력하세요.")
    return match[1]


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ReaderNetworkError("timeout", "사이트 응답 제한 시간을 넘겼습니다.")
    return seconds


def _public_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if address.version == 6:
        return address in _PUBLIC_V6 and not address.sixtofour and not address.teredo
    return True


def _resolve(deadline):
    # The OS resolver has no per-call deadline. Bound outstanding lookups as well.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ReaderNetworkError("dns", "이전 주소 조회가 진행 중입니다. 잠시 후 다시 시도하세요.")
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put(socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM))
        except OSError as error:
            result.put(error)
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=lookup, daemon=True).start()
    try:
        entries = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise ReaderNetworkError("timeout", "사이트 주소 조회 제한 시간을 넘겼습니다.") from None
    if isinstance(entries, OSError) or not entries:
        raise ReaderNetworkError("dns", "사이트 주소를 찾을 수 없습니다. 네트워크 연결을 확인하세요.")
    for family, _, _, _, target in entries:
        if family not in (socket.AF_INET, socket.AF_INET6) or not _public_address(target[0]):
            raise ReaderNetworkError("address", "공개 인터넷 주소에만 연결할 수 있습니다.")
    return entries


def _connect(deadline):
    entries = _resolve(deadline)
    context = ssl.create_default_context()
    for family, kind, protocol, _, address in entries:
        with socket.socket(family, kind, protocol) as raw:
            raw.settimeout(min(4, _remaining(deadline)))
            try:
                # Pin the exact address we checked. Preserve host identity for TLS.
                raw.connect(address)
            except OSError:
                continue
            raw.settimeout(_remaining(deadline))
            return context.wrap_socket(raw, server_hostname=HOST)
    _remaining(deadline)
    raise ReaderNetworkError("connection", "사이트에 연결할 수 없습니다.")


def _read_body(response):
    if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
        raise ReaderNetworkError("format", "서버의 콘텐츠 인코딩을 지원하지 않습니다.")
    length = response.getheader("Content-Length")
    if length is not None:
        if not re.fullmatch(r"[0-9]{1,18}", length.strip()):
            raise ReaderNetworkError("http", "사이트가 잘못된 응답 길이를 보냈습니다.")
        if int(length) > MAX_BYTES:
            raise ReaderNetworkError("size", "사이트 응답이 8 MiB 제한을 넘었습니다.")
    data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ReaderNetworkError("size", "사이트 응답이 8 MiB 제한을 넘었습니다.")
    if length is not None and len(data) != int(length):
        raise ReaderNetworkError("http", "사이트 응답이 중간에 끊겼습니다.")
    return data


def _get(path, deadline):
    with _connect(deadline) as channel:
        def interrupt():
            try:
                channel.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        watchdog = threading.Timer(_remaining(deadline), interrupt)
        watchdog.daemon = True
        watchdog.start()
        connection = http.client.HTTPConnection(HOST)
        connection.sock = channel
        try:
            connection.request("GET", path, headers={
                "User-Agent": "Chaessi-Metadata-Reader/1",
                "Accept": "text/html,application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
            })
            with connection.getresponse() as response:
                status = response.status
                location = response.getheader("Location", "")
                media = response.getheader("Content-Type", "").split(";")[0].strip().lower()
                data = _read_body(response) if status == 200 else b""
                _remaining(deadline)
                return status, location, media, data
        finally:
            watchdog.cancel()
            connection.close()


def _image_key(attributes):
    for name in ("data-src", "src"):
        value = attributes.get(name) or ""
        try:
            target = urlsplit(value)
            if target.hostname == IMAGE_HOST and target.scheme in ("", "https"):
                return target.path
        except ValueError:
            continue
    return None


class _SiteScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = set()

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            source = dict(attrs).get("src") or ""
            path = source.split("?", 1)[0].split("#", 1)[0]
            name = path.rsplit("/", 1)[-1]
            if name in ("app.js", "ai_metadata_view.js"):
                self.found.add(name)


def _site_view_required():
    return ReaderNetworkError(
        "site_view_required",
        "이 작품은 사이트 화면에서 접근 확인 후 표시됩니다. "
        "브라우저에서 볼 수 있는 이미지의 원본 JSON을 복사해 ‘JSON 입력…’으로 여세요.",
    )


class _Gallery(HTMLParser):
    """Associate each original JSON code block with its preceding gallery image."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.slots = []
        self.keys = []
        self.capture = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            key = _image_key(dict(attrs))
            if key:
                if self.capture is not None or len(self.slots) >= MAX_IMAGES + 1:
                    raise ReaderNetworkError("layout", "이미지 목록 형식을 확인할 수 없습니다.")
                # The public detail header repeats the first gallery preview.
                if self.keys == [key] and self.slots == [None]:
                    return
                self.keys.append(key)
                self.slots.append(None)
        elif self.slots and self.capture is None and tag in ("pre", "code", "textarea"):
            self.capture = tag
            self.parts = []

    def handle_data(self, data):
        if self.capture is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != self.capture:
            return
        source = "".join(self.parts).strip()
        self.parts = []
        self.capture = None
        if not source.startswith("{") and source != "null":
            return
        try:
            metadata = json.loads(source)
        except (ValueError, RecursionError) as error:
            raise ReaderNetworkError("malformed", "이미지의 원본 JSON을 해석할 수 없습니다.") from error
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict) or self.slots[-1] is not None:
            raise ReaderNetworkError("layout", "이미지와 원본 JSON의 대응을 확인할 수 없습니다.")
        self.slots[-1] = metadata


def _images(media, data):
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ReaderNetworkError("format", "사이트 응답의 문자 인코딩을 읽을 수 없습니다.") from None
    if media == "application/json":
        try:
            document = json.loads(source)
        except (ValueError, RecursionError):
            raise ReaderNetworkError("malformed", "사이트의 원본 JSON을 해석할 수 없습니다.") from None
        if isinstance(document, dict) and "images" in document:
            if "work" in document:
                raise _site_view_required()
            document = document["images"]
        elif isinstance(document, dict):
            document = [document]
        if not isinstance(document, list) or not all(item is None or isinstance(item, dict)
                                                     for item in document):
            raise ReaderNetworkError("format", "사이트 JSON의 이미지 목록을 읽을 수 없습니다.")
        if len(document) > MAX_IMAGES:
            raise ReaderNetworkError("size", "작품의 이미지가 1,000장 제한을 넘었습니다.")
        return [item or {} for item in document]
    if media not in ("text/html", "application/xhtml+xml"):
        raise ReaderNetworkError("format", "작품 상세 페이지 형식을 지원하지 않습니다.")
    gallery = _Gallery()
    try:
        # The official interactive detail checks access before displaying data.
        # Its work-data response and any embedded previews do not grant access.
        scripts = _SiteScripts()
        scripts.feed(source)
        scripts.close()
        if scripts.found:
            raise _site_view_required()
        gallery.feed(source)
        gallery.close()
    except (ValueError, AssertionError) as error:
        if isinstance(error, ReaderNetworkError):
            raise
        raise ReaderNetworkError("layout", "사이트 HTML 형식을 읽을 수 없습니다.") from error
    if gallery.capture is not None or all(slot is None for slot in gallery.slots):
        raise ReaderNetworkError("layout", "사이트에서 이미지별 원본 JSON 구조를 찾지 못했습니다.")
    if len(gallery.slots) > MAX_IMAGES:
        raise ReaderNetworkError("size", "작품의 이미지가 1,000장 제한을 넘었습니다.")
    return [item or {} for item in gallery.slots]


def fetch_work(url):
    """Fetch one explicit detail URL and return original metadata in gallery order."""
    path = _work_path(url)
    base_path = path.rstrip("/")
    deadline = time.monotonic() + TIMEOUT
    for hop in range(3):
        try:
            status, location, media, data = _get(path, deadline)
        except TimeoutError:
            raise ReaderNetworkError("timeout", "사이트 응답 제한 시간을 넘겼습니다.") from None
        except ssl.SSLError:
            raise ReaderNetworkError("tls", "사이트의 보안 연결을 확인할 수 없습니다.") from None
        except (OSError, http.client.HTTPException):
            _remaining(deadline)
            raise ReaderNetworkError("connection", "사이트 연결 중 오류가 발생했습니다.") from None
        if status in (301, 302, 303, 307, 308):
            try:
                target = _work_path(urljoin("https://" + HOST + path, location))
            except ValueError:
                raise ReaderNetworkError("redirect", "허용 범위 밖으로 이동하는 링크입니다.") from None
            if not location or target.rstrip("/") != base_path or hop == 2:
                raise ReaderNetworkError("redirect", "작품 상세 링크의 이동 경로를 확인할 수 없습니다.")
            path = target
            continue
        if status in (401, 403, 429, 451):
            raise ReaderNetworkError("restricted", f"사이트가 접근을 제한했습니다 (HTTP {status}). 원본 JSON을 직접 열 수 있습니다.")
        if status != 200:
            raise ReaderNetworkError("http", f"사이트가 HTTP {status} 오류를 반환했습니다.")
        images = _images(media, data)
        if not any(images):
            raise ReaderNetworkError("no_metadata", "이 작품에는 읽을 수 있는 원본 메타데이터가 없습니다.")
        return images
