#!/usr/bin/env python3
"""Download the OUI master database and split it into 256 JSON shards.

Each shard is named after the first two hex characters of the MAC prefix
(00.json ... ff.json) and maps the full lowercase prefix (hex only, no
separators) to the vendor name.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SOURCE_URL = (
    "https://raw.githubusercontent.com/Ringmast4r/OUI-Master-Database/"
    "master/LISTS/master_oui.min.json"
)
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "mac-vendors",
)
USER_AGENT = "sysadminsuite-data/1.0 (+https://github.com/TimonW-Dev/sysadminsuite-data)"
MIN_ENTRIES = 10_000  # sanity check so a broken download never overwrites good data
RETRIES = 3
TIMEOUT = 120

NON_HEX = re.compile(r"[^0-9a-f]")


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Attempt {attempt}/{RETRIES} failed: {exc}", file=sys.stderr)
            if attempt == RETRIES:
                raise
            time.sleep(5 * attempt)


def normalize_key(raw_key):
    return NON_HEX.sub("", raw_key.lower())


def vendor_name(entry):
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        name = entry.get("manufacturer") or entry.get("registrant_raw") or ""
        return str(name).strip()
    return ""


def build_shards(data):
    shards = {f"{i:02x}": {} for i in range(256)}
    skipped = 0
    for raw_key, entry in data.items():
        key = normalize_key(raw_key)
        name = vendor_name(entry)
        if len(key) < 6 or not name:
            skipped += 1
            continue
        shards[key[:2]][key] = name
    return shards, skipped


def write_shards(shards):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for prefix, content in shards.items():
        path = os.path.join(OUTPUT_DIR, f"{prefix}.json")
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(content, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(tmp_path, path)

    for filename in os.listdir(OUTPUT_DIR):
        if not filename.endswith(".json") or filename[:-5] not in shards:
            os.remove(os.path.join(OUTPUT_DIR, filename))


def main():
    print(f"Downloading {SOURCE_URL}")
    data = download(SOURCE_URL)
    if not isinstance(data, dict) or len(data) < MIN_ENTRIES:
        size = len(data) if hasattr(data, "__len__") else "?"
        print(f"Unexpected data (entries: {size}); aborting.", file=sys.stderr)
        return 1

    shards, skipped = build_shards(data)
    total = sum(len(shard) for shard in shards.values())
    if total < MIN_ENTRIES:
        print(f"Only {total} usable entries; aborting.", file=sys.stderr)
        return 1

    write_shards(shards)
    non_empty = sum(1 for shard in shards.values() if shard)
    print(f"Wrote 256 shards to {OUTPUT_DIR} ({total} entries, {non_empty} non-empty, {skipped} skipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
