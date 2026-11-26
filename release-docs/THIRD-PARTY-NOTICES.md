# Third-party software notices

Chaessi Metadata Reader 1.1.0 for Windows x64 includes the runtime components below. Their original copyright notices, license terms and disclaimers accompany this document. The terms listed here apply to their respective third-party components. Rights in Chaessi Metadata Reader and its Chrome extension remain with their respective rights holders.

| Component | Distribution terms |
|---|---|
| CPython 3.13.17 and its standard library | Python Software Foundation License Version 2, predecessor licenses and incorporated-software notices. The application includes selected modules and unmodified runtime binaries from the Windows x64 distribution. [Windows distribution terms](licenses/PYTHON-WINDOWS.txt) · [CPython acknowledgements](licenses/PYTHON-ACKNOWLEDGEMENTS.txt) |
| Microsoft Distributable Code | The additional conditions for the Windows build of Python apply to Microsoft’s code in the Windows runtime files. The original notices and trademarks are retained. [Windows distribution terms](licenses/PYTHON-WINDOWS.txt) |
| Tcl 8.6.15 and Tk 8.6.15 | Copyright the Regents of the University of California, Sun Microsystems, Scriptics, ActiveState and other contributors as indicated in the software. [Tcl terms](licenses/TCL.txt) · [Tk terms](licenses/TK.txt) · [Henry Spencer’s regular expression engine](licenses/TCL-REGEX.txt) · [LibTomMath](licenses/TCL-LIBTOMMATH.txt) |
| OpenSSL 3.5.9 | The OpenSSL Project Authors. Licensed under the Apache License, Version 2.0. [OpenSSL license](licenses/OPENSSL.txt) |
| libffi 3.4.4, zlib 1.3.1, bzip2 1.0.8, liblzma (XZ 5.2.5) and libmpdec 4.0.0 | Selected Windows standard-library modules include or use these libraries. [Windows distribution terms](licenses/PYTHON-WINDOWS.txt) · [zlib](licenses/ZLIB.txt) · [XZ Utils licensing](licenses/XZ.txt) · [CPython acknowledgements, including libmpdec](licenses/PYTHON-ACKNOWLEDGEMENTS.txt) |
| HACL* and BLAKE2 | CPython includes HACL* hash implementations (MIT) with portable support headers (Apache-2.0), and the BLAKE2 implementation by Samuel Neves. [HACL* notices](licenses/HACL.txt) · [Apache License](licenses/OPENSSL.txt) · [BLAKE2 notice](licenses/BLAKE2.txt) · [CC0 1.0](licenses/CC0.txt) |
| Unicode character data | Unicode data and software are distributed under the Unicode copyright and permission notice. [Unicode license](licenses/UNICODE.txt) |
| PyInstaller 6.22.3 | The application uses the standard compiled bootloader and runtime files. The upstream bootloader exception permits distribution of a combined executable. [PyInstaller licensing terms, exceptions and notices](licenses/PYINSTALLER.txt) |
| NSIS 3.0.4.1 | The installer and uninstaller use NSIS, its standard UI components and zlib compression. Copyright the NSIS contributors. [Original NSIS notices and licenses](licenses/NSIS.txt) |

Google Chrome and CHAESSI PRESET are obtained separately. NovelAI is a third-party service. Their names identify the software and services with which the reader interoperates.


The signed-release verifier additionally includes the following official wheel components:

| Component | Distribution terms and original notices |
|---|---|
| PyCA cryptography 50.0.2 | Dual licensed under Apache-2.0 or BSD-3-Clause. [License choice](licenses/CRYPTOGRAPHY.txt), [Apache terms](licenses/CRYPTOGRAPHY-APACHE.txt), [BSD terms](licenses/CRYPTOGRAPHY-BSD.txt). The official Windows wheel statically links OpenSSL 4.0.3; Apache-2.0 terms apply. Original vendor dependency inventory: [wheel SBOM](licenses/CRYPTOGRAPHY-sbom.json), [Rust dependency SBOM](licenses/CRYPTOGRAPHY-cryptography-rust.cyclonedx.json). |
| cffi 2.1.1 | MIT-style license, copyright Armin Rigo, Maciej Fijalkowski and contributors. [Original terms](licenses/CFFI.txt). |
| pycparser 3.12 | BSD-3-Clause, copyright Eli Bendersky and contributors. Build/runtime dependency, when collected. [Original terms](licenses/PYCPARSER.txt). |

Official sources: https://pypi.org/project/cryptography/50.0.2/ · https://pypi.org/project/cffi/2.1.1/ · https://pypi.org/project/pycparser/3.12/
