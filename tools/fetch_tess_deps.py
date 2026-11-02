"""Tải bộ DLL phụ thuộc cho Tesseract portable từ conda-forge (không cài đặt)."""
from __future__ import annotations

import io
import json
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import pefile
import zstandard

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / ".runtime" / "tesseract" / "Library" / "bin"

PKG_FOR_DLL = {
    "leptonica": "leptonica",
    "tiff": "libtiff",
    "archive": "libarchive",
    "libcurl": "libcurl",
    "libpng16": "libpng",
    "jpeg": "libjpeg-turbo",
    "libwebp": "libwebp",
    "libsharpyuv": "libwebp",
    "gif": "giflib",
    "openjp2": "openjpeg",
    "zlib": "zlib",
    "zlib1": "zlib",
    "zstd": "zstd",
    "lzma": "xz",
    "libssh2": "libssh2",
    "libcrypto": "openssl",
    "libssl": "openssl",
    "nghttp2": "nghttp2",
    "brotlidec": "brotli",
    "brotlicommon": "brotli",
    "iconv": "libiconv",
    "libxml2": "libxml2",
    "lz4": "lz4-c",
    "libdeflate": "libdeflate",
    "jbig": "jbig",
    "lerc": "lerc",
    "libexpat": "expat",
    "charset": "libiconv",
    "deflate": "libdeflate",
    "gif-7": "giflib",
    "jpeg8": "libjpeg-turbo",
    "lerc": "lerc",
    "libbz2": "bzip2",
    "liblzma": "xz",
    "libpng16": "libpng",
    "libwebpmux": "libwebp",
    "libwebpdemux": "libwebp",
    "lz4": "lz4-c",
    "psl-5": "libpsl",
    "zlib1": "zlib",
}

SYSTEM = {"kernel32.dll", "ws2_32.dll", "msvcp140.dll", "vcruntime140.dll",
          "vcruntime140_1.dll", "user32.dll", "gdi32.dll", "shell32.dll",
          "ole32.dll", "advapi32.dll", "crypt32.dll", "normaliz.dll", "wldap32.dll",
          "bcrypt.dll", "iphlpapi.dll", "secur32.dll", "winmm.dll", "version.dll"}

VERSION_PIN = {"leptonica": "1.86.0"}


def imports_of(path: Path):
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    out = []
    for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        out.append(e.dll.decode().lower())
    return out


def have():
    return {p.name.lower() for p in BIN.glob("*.dll")} | {p.name.lower() for p in BIN.glob("*.exe")}


def missing():
    need = set()
    for p in list(BIN.glob("*.dll")) + list(BIN.glob("*.exe")):
        for d in imports_of(p):
            if d.startswith("api-ms-") or d in SYSTEM:
                continue
            need.add(d)
    return sorted(need - have())


def fetch_pkg(name: str):
    url = f"https://api.anaconda.org/package/conda-forge/{name}"
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.load(r)
    files = [f for f in d["files"] if f["attrs"].get("subdir") == "win-64"]
    pin = VERSION_PIN.get(name)
    if pin:
        files = [f for f in files if f["version"] == pin] or files
    if not files:
        raise RuntimeError(f"no win-64 build for {name}")
    f = files[-1]
    dl = "https://conda.anaconda.org/conda-forge/" + f["basename"]
    print("fetch", name, f["version"])
    with urllib.request.urlopen(dl, timeout=300) as r:
        blob = r.read()
    z = zipfile.ZipFile(io.BytesIO(blob))
    inner = [n for n in z.namelist() if n.startswith("pkg-")][0]
    raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read(inner)))
    tf = tarfile.open(fileobj=raw, mode="r|")
    n = 0
    for m in tf:
        norm = m.name.replace("\\", "/")
        if m.isfile() and "Library/bin/" in norm and norm.endswith(".dll"):
            target = BIN / Path(m.name).name
            if not target.exists():
                with tf.extractfile(m) as src:
                    target.write_bytes(src.read())
                n += 1
    print("  added", n, "dlls")


def main():
    BIN.mkdir(parents=True, exist_ok=True)
    for _ in range(12):
        miss = missing()
        if not miss:
            print("OK: no missing dlls")
            return 0
        print("missing:", miss)
        pkgs = []
        for d in miss:
            stem = d[:-4]
            pkg = None
            for key, val in PKG_FOR_DLL.items():
                if stem.startswith(key):
                    pkg = val
                    break
            if pkg is None:
                print("UNKNOWN dll:", d)
                return 1
            if pkg not in pkgs:
                pkgs.append(pkg)
        for p in pkgs:
            fetch_pkg(p)
    print("still missing:", missing())
    return 1


if __name__ == "__main__":
    sys.exit(main())
