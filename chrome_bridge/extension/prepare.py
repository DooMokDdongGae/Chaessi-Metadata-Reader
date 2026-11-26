"""Package the verified, project-owned readable collector for MV3 function injection."""
import hashlib
import os
from pathlib import Path
import tempfile


DIRECTORY = Path(__file__).resolve().parent
SOURCE = DIRECTORY.parents[1] / "bundle" / "collect.js"
OUTPUT = DIRECTORY / "collector.js"
EXPECTED = "88bc2c15453ce8fd78ec57faf2f6f5ba3a5a7e78696924c953a8f590112a2060"


def build():
    original = SOURCE.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(original).hexdigest() != EXPECTED:
        raise SystemExit("The collector changed. Review its official-copy behavior and re-pin its SHA-256.")
    function, marker, _ = original.decode("utf-8").partition('\nif (typeof module !== "undefined"')
    if not marker:
        raise SystemExit("Unsupported collector module layout.")
    # Chrome serializes this function into MAIN. Keep dependencies lexical and
    # the URL checks in the same invocation, including same-document SPA changes.
    output = ("// Generated locally by prepare.py from the verified bundle collector.\n"
              "async function collectChromeWork(expectedUrl, count) {\n" + function +
              "\n  if (location.href !== expectedUrl) return {ok:false, code:'changed'};\n"
              "  try {\n"
              "    const bundle = await collectReadableBundle({expectedCount:count});\n"
              "    return location.href === expectedUrl ? {ok:true, bundle} : {ok:false, code:'changed'};\n"
              "  } catch (error) { return {ok:false, code:String(error.code || 'layout')}; }\n"
              "}\n").encode("utf-8")
    if not OUTPUT.exists() or OUTPUT.read_bytes() != output:
        with tempfile.NamedTemporaryFile(dir=DIRECTORY, suffix=".tmp", delete=False) as temp:
            temp.write(output)
            temp_path = temp.name
        try:
            os.replace(temp_path, OUTPUT)
        finally:
            Path(temp_path).unlink(missing_ok=True)
    print("collector.js SHA-256", hashlib.sha256(output).hexdigest())


if __name__ == "__main__":
    build()
