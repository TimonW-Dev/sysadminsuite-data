#!/usr/bin/env python3
"""Generate port lookup and substring search shards from the IANA registry."""

import argparse
import base64
import collections
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

from shard_mac_data import download

SOURCE_URL = "https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "ports"
MIN_ENTRIES = 1_000
SCHEMA_VERSION = 1
PORT_PATTERN = re.compile(r"([0-9]+)(?:-([0-9]+))?\Z")
FIELDS = {
    "Service Name": "name",
    "Transport Protocol": "protocol",
    "Description": "description",
    "Assignee": "assignee",
    "Contact": "contact",
    "Registration Date": "registration_date",
    "Modification Date": "modification_date",
    "Reference": "reference",
    "Service Code": "service_code",
    "Unauthorized Use Reported": "unauthorized_use_reported",
    "Assignment Notes": "notes",
}
REQUIRED_FIELDS = set(FIELDS) | {"Port Number"}
ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def normalize(text):
    return text.translate(ASCII_LOWER)


def port_shard(port):
    return port // 32 if port < 4096 else 128 + (port - 4096) // 480


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def parse_registry(text, min_entries=MIN_ENTRIES):
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if reader.fieldnames is None or not REQUIRED_FIELDS.issubset(reader.fieldnames):
        raise ValueError("IANA CSV is missing required columns")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("IANA CSV contains duplicate columns")
    records = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV row at line {reader.line_num}")
        record = {"source": "iana"}
        for column, field in FIELDS.items():
            value = row[column].strip()
            if value:
                record[field] = value
        raw_port = row["Port Number"].strip()
        if raw_port:
            match = PORT_PATTERN.fullmatch(raw_port)
            if not match:
                raise ValueError(f"Invalid port {raw_port!r} at line {reader.line_num}")
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) is not None else start
            if start > end or end > 65535:
                raise ValueError(f"Invalid port range {raw_port!r} at line {reader.line_num}")
            record["port"] = start if start == end else [start, end]
        else:
            record["port"] = None

        description = normalize(record.get("description", ""))
        if description in ("reserved", "unassigned"):
            record["status"] = description
        elif record["port"] is None:
            record["status"] = "service-only"
        elif record.get("name"):
            record["status"] = "assigned"
        else:
            record["status"] = "other"
        records.append(record)
    if len(records) < min_entries:
        raise ValueError(f"Only {len(records)} IANA entries; expected at least {min_entries}")
    return records


def search_texts(record):
    for field in ("name", "description"):
        if field in record:
            yield record[field]
    for field in ("aliases", "comments"):
        yield from record.get(field, [])


def build_shards(records):
    data = {f"{i:02x}": {} for i in range(256)}
    index = {f"{i:02x}": collections.defaultdict(set) for i in range(256)}
    occurrences = collections.Counter()
    ids = set()
    for record in records:
        canonical = json_bytes(record)
        ordinal = occurrences[canonical]
        occurrences[canonical] += 1
        digest = hashlib.sha256(canonical + str(ordinal).encode("ascii")).digest()
        record_id = base64.urlsafe_b64encode(digest[:12]).decode("ascii")
        if record_id in ids:
            raise ValueError(f"Record ID collision: {record_id}")
        ids.add(record_id)
        port = record["port"]
        if port is None:
            shard_numbers = [digest[0]]
        elif isinstance(port, int):
            shard_numbers = [port_shard(port)]
        else:
            shard_numbers = range(port_shard(port[0]), port_shard(port[1]) + 1)
        canonical_shard = f"{shard_numbers[0]:02x}"
        for shard_number in shard_numbers:
            data[f"{shard_number:02x}"][record_id] = record
        reference = canonical_shard + record_id
        grams = set()
        for text in search_texts(record):
            text = normalize(text)
            grams.update(text[i:i + 3] for i in range(len(text) - 2))
        for gram in grams:
            shard = hashlib.sha256(gram.encode("utf-8")).hexdigest()[:2]
            index[shard][gram].add(reference)
    return data, index


def write_shards(data, index, output_dir):
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".port-shards-", dir=output_dir.parent) as temp:
        temp_path = Path(temp)
        for directory, shards, key in (("data", data, "entries"), ("index", index, "grams")):
            (temp_path / directory).mkdir()
            for shard, content in shards.items():
                if key == "grams":
                    content = {gram: sorted(references) for gram, references in content.items()}
                payload = {"version": SCHEMA_VERSION, key: content}
                (temp_path / directory / f"{shard}.json").write_bytes(json_bytes(payload))
        for directory in ("data", "index"):
            target = output_dir / directory
            target.mkdir(parents=True, exist_ok=True)
            for i in range(256):
                filename = f"{i:02x}.json"
                os.replace(temp_path / directory / filename, target / filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    print(f"Downloading {SOURCE_URL}")
    records = parse_registry(download(SOURCE_URL))
    data, index = build_shards(records)
    write_shards(data, index, args.output_dir)
    print(f"Wrote {len(records)} records to 256 data and 256 index shards in {args.output_dir}")


if __name__ == "__main__":
    main()
