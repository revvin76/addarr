"""
Run this once to download JSZip and epub.js into static/js/
so the Kindle reader can load them without hitting an external CDN.

Usage:  python download_js_libs.py
"""
import urllib.request
import pathlib
import sys

LIBS = [
    (
        "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js",
        "static/js/jszip.min.js",
    ),
    (
        "https://cdnjs.cloudflare.com/ajax/libs/epub.js/0.3.93/epub.min.js",
        "static/js/epub.min.js",
    ),
]

base = pathlib.Path(__file__).parent
dest_dir = base / "static" / "js"
dest_dir.mkdir(parents=True, exist_ok=True)

ok = True
for url, rel_path in LIBS:
    dest = base / rel_path
    print(f"Downloading {url} …", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        size = dest.stat().st_size
        print(f"OK ({size:,} bytes) → {dest}")
    except Exception as e:
        print(f"FAILED: {e}")
        ok = False

sys.exit(0 if ok else 1)
