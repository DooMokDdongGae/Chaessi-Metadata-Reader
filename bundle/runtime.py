"""Private in-memory IPC to the disposable browser process."""
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from bundle.model import URL, decode_bundle


SCRIPT = Path(__file__).resolve().with_name("run-browser.cjs")
MAX_REPLY = 16 * 1024 * 1024


def read_link(url, progress):
    if not URL.fullmatch(url):
        raise ValueError("https://aitag.win/i/작품번호 형식의 묶음 링크를 입력해 주세요.")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js를 찾을 수 없습니다. 열린 작품에서는 브라우저 묶음 저장을 사용할 수 있습니다.")
    request = json.dumps({"url": url, "progress": True}).encode("utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("NODE_OPTIONS", "NODE_DEBUG", "DEBUG", "PWDEBUG")}
    with subprocess.Popen([node, str(SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        timeout = threading.Event()

        def expire():
            timeout.set()
            process.kill()

        timer = threading.Timer(70, expire)
        timer.daemon = True
        timer.start()
        try:
            process.stdin.write(request)
            process.stdin.close()
            count = None
            while True:
                line = process.stdout.readline(MAX_REPLY + 1)
                if timeout.is_set():
                    raise ValueError("묶음 읽기 시간이 초과됐습니다.")
                if not line or len(line) > MAX_REPLY:
                    raise ValueError("브라우저에서 완전한 묶음 결과를 받지 못했습니다.")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("브라우저 응답 형식을 확인할 수 없습니다.")
                if message.get("event") == "count" and count is None:
                    count = message.get("count")
                    if type(count) is not int or not 1 <= count <= 1024:
                        raise ValueError("브라우저가 확인한 이미지 수가 올바르지 않습니다.")
                    progress(count)
                    continue
                if message.get("ok") is not True:
                    error = message.get("message")
                    raise ValueError(error if isinstance(error, str) and len(error) < 400 else "묶음을 읽을 수 없습니다.")
                cards = decode_bundle(message.get("bundle"))
                if count is not None and len(cards) != count:
                    raise ValueError("읽는 동안 작품의 이미지 수가 달라졌습니다. 다시 읽어 주세요.")
                return cards
        finally:
            timer.cancel()
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
