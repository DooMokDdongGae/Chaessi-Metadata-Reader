"""Run with the PSF 3.13.17 x64 ZIP runtime to provision a private build venv."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    target = parser.parse_args().destination.resolve()
    sources = Path(__file__).resolve().parent
    if sys.version_info[:3] != (3, 13, 17) or sys.maxsize <= 2**32:
        parser.error("run with the verified PSF CPython 3.13.17 x64 runtime")
    if target.exists() or target.is_relative_to(sources.parent):
        parser.error("use a new build directory outside the source checkout")
    venv.EnvBuilder(with_pip=True).create(target)
    python = target / "Scripts" / "python.exe"
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
                    "install", "--no-cache-dir", "--no-deps", "--only-binary=:all:", "--require-hashes",
                    "--index-url", "https://pypi.org/simple", "-r", str(sources / "requirements-build.txt")],
                   check=True)
    print(python)


if __name__ == "__main__":
    main()
