#!/usr/bin/env python3
"""Download the official IEEE MA-L/MA-M/MA-S registries and split them into 256 JSON shards.

Each shard is named after the first two hex characters of the MAC prefix
(00.json ... ff.json) and maps the full lowercase prefix (hex only, no
separators) to the organization name.
"""

import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Official IEEE Registration Authority public listings: (url, assignment length in hex characters)
SOURCES = [
    ("https://standards-oui.ieee.org/oui/oui.csv", 6),  # MA-L
    ("https://standards-oui.ieee.org/oui28/mam.csv", 7),  # MA-M
    ("https://standards-oui.ieee.org/oui36/oui36.csv", 9),  # MA-S
]
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "mac-vendors",
)
USER_AGENT = "sysadminsuite-data/1.0 (+https://github.com/TimonW-Dev/sysadminsuite-data)"
MIN_ENTRIES = 1_000  # per source; sanity check so a broken download never overwrites good data
RETRIES = 3
TIMEOUT = 120

HEX = re.compile(r"[0-9a-f]+")


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read().decode("utf-8-sig")
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
            print(f"Attempt {attempt}/{RETRIES} failed: {exc}", file=sys.stderr)
            if attempt == RETRIES:
                raise
            time.sleep(5 * attempt)


def parse_registry(text, key_length):
    """Return ({prefix: organization name}, skipped) for one IEEE CSV file."""
    entries = {}
    skipped = 0
    for row in csv.DictReader(io.StringIO(text)):
        key = (row.get("Assignment") or "").strip().lower()
        name = " ".join((row.get("Organization Name") or "").split())
        if len(key) != key_length or not HEX.fullmatch(key) or not name or name.lower() == "private":
            skipped += 1
            continue
        entries[key] = name
    return entries, skipped


def build_shards(registries):
    shards = {f"{i:02x}": {} for i in range(256)}
    for entries in registries:
        for key, name in entries.items():
            shards[key[:2]][key] = name
    return shards


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
    registries = []
    skipped_total = 0
    for url, key_length in SOURCES:
        print(f"Downloading {url}")
        entries, skipped = parse_registry(download(url), key_length)
        if len(entries) < MIN_ENTRIES:
            print(f"Only {len(entries)} usable entries from {url}; aborting.", file=sys.stderr)
            return 1
        registries.append(entries)
        skipped_total += skipped

    shards = build_shards(registries)
    total = sum(len(shard) for shard in shards.values())
    write_shards(shards)
    non_empty = sum(1 for shard in shards.values() if shard)
    print(f"Wrote 256 shards to {OUTPUT_DIR} ({total} entries, {non_empty} non-empty, {skipped_total} skipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
