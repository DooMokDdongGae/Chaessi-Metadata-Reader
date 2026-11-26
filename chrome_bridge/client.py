"""The desktop reader's single-work request through the paired Chrome extension."""
from bundle.model import URL, decode_bundle
from chrome_bridge.automatic import AutomaticBridge as Bridge


def read_link(url, progress=lambda count: None):
    if not isinstance(url, str) or not URL.fullmatch(url):
        raise ValueError("https://aitag.win/i/작품번호 형식의 주소를 입력하세요.")
    try:
        bridge = Bridge()
    except OSError as error:
        raise OSError("Chrome 연결을 열지 못했습니다. 다른 리더나 Stage1 실행기가 열려 있는지 확인하세요.") from error
    try:
        return decode_bundle(bridge.request(url, progress, timeout=120))
    finally:
        bridge.close()


def read_inspect(progress=lambda count: None):
    try:
        bridge = Bridge()
    except OSError as error:
        raise OSError("Chrome 연결을 열지 못했습니다. 다른 리더나 시험기를 종료한 뒤 다시 시도하세요.") from error
    try:
        return decode_bundle(bridge.request_inspect(progress, timeout=120))
    finally:
        bridge.close()
