"""Download and normalize the structured gaokao champion source.

This project currently ships the 1996--2026 champion slice.  The
raw response is retained byte-for-byte and a SHA-256 manifest is written next
to it so a later source refresh cannot silently replace historical data.
"""

import os
import sys
import json
import time
import re
import urllib.parse
import urllib.request
import hashlib
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(BASE_DIR, "raw_data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(RAW_DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古",
    "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南",
    "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"
]

YEARS = list(range(1996, 2027))
SOURCE_URL = "https://pastebin.com/raw/z3XiLUfa"
SOURCE_PAGE = "https://pastebin.com/z3XiLUfa"
SOURCE_FILENAME = "pastebin-z3XiLUfa.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted)
    with open(os.path.join(LOGS_DIR, "crawler.log"), "a", encoding="utf-8") as f:
        f.write(formatted + "\n")

def fetch_url(url, timeout=10, retries=2):
    """Safely fetch UTF-8 web content with bounded retries."""
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status == 200:
                    return response.read().decode("utf-8-sig")
        except Exception as e:
            log(f"Fetch failed for {url} (attempt {attempt}): {type(e).__name__}")
            if attempt < retries:
                time.sleep(1)
    return None


def download_source(timeout=20, retries=3):
    """Fetch the source, preserving bytes and provenance metadata."""
    request = urllib.request.Request(SOURCE_URL, headers=HEADERS)
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                raw = response.read()
            path = os.path.join(RAW_DATA_DIR, SOURCE_FILENAME)
            with open(path, "wb") as file:
                file.write(raw)
            manifest_path = os.path.join(RAW_DATA_DIR, "source_manifest.json")
            try:
                with open(manifest_path, encoding="utf-8") as file:
                    manifest = json.load(file)
            except (OSError, ValueError):
                manifest = {"sources": []}
            sources = [x for x in manifest.get("sources", []) if x.get("file") != SOURCE_FILENAME]
            sources.append({"url": SOURCE_URL, "page": SOURCE_PAGE, "file": SOURCE_FILENAME,
                            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            manifest = {"sources": sources,
                        "retrieved_at": datetime.now().astimezone().date().isoformat()}
            with open(manifest_path, "w", encoding="utf-8") as file:
                json.dump(manifest, file, ensure_ascii=False, indent=2)
                file.write("\n")
            log(f"Saved {SOURCE_URL} ({len(raw)} bytes, sha256={sources[-1]['sha256']})")
            return manifest
        except Exception as error:
            last_error = error
            log(f"Download failed (attempt {attempt}): {type(error).__name__}")
            if attempt < retries:
                time.sleep(1)
    raise RuntimeError("source download failed") from last_error

def save_raw_record(filename, data):
    """Save raw record or list of records to raw_data directory."""
    path = os.path.join(RAW_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, (dict, list)):
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            f.write(str(data))
    log(f"Saved raw file: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="download the pinned source")
    parser.add_argument("--normalize", action="store_true", help="normalize the downloaded source")
    args = parser.parse_args()
    if not args.download and not args.normalize:
        parser.error("choose --download or --normalize")
    if args.download:
        download_source()
    if args.normalize:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from normalize_source import main as normalize_main
        normalize_main([])
