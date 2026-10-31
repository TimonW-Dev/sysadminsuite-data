import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shard_port_data as ports


def registry(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["Port Number", *ports.FIELDS])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


ROWS = [
    {"Service Name": "microsoft-ds", "Port Number": "445", "Transport Protocol": "tcp", "Description": "Microsoft-DS"},
    {"Service Name": "microsoft-ds", "Port Number": "445", "Transport Protocol": "udp", "Description": "Microsoft-DS"},
    {"Port Number": "250-260", "Description": "Reserved"},
    {"Service Name": "noport", "Description": "Portless service"},
    {"Service Name": "wide", "Port Number": "256-258", "Transport Protocol": "sctp", "Description": "Wide range"},
    {"Service Name": "false-positive", "Port Number": "999", "Transport Protocol": "dccp", "Description": "abcXbcd"},
    {"Service Name": "unicode", "Port Number": "65535", "Description": "fun 😀xyz"},
]


class PortDataTests(unittest.TestCase):
    def test_parse_all_records_and_statuses(self):
        records = ports.parse_registry(registry(ROWS), min_entries=1)
        self.assertEqual(len(records), len(ROWS))
        self.assertEqual(records[0]["port"], 445)
        self.assertEqual(records[0]["source"], "iana")
        self.assertEqual(records[0]["status"], "assigned")
        self.assertEqual(records[2]["port"], [250, 260])
        self.assertEqual(records[2]["status"], "reserved")
        self.assertEqual(records[3]["status"], "service-only")
        self.assertEqual(records[4]["protocol"], "sctp")
        self.assertEqual(records[5]["protocol"], "dccp")

    def test_invalid_input_rejected(self):
        for value in ("-1", "65536", "500-400", "0-65536", "1-2-3", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ports.parse_registry(registry([{"Port Number": value}]), min_entries=1)
        with self.assertRaises(ValueError):
            ports.parse_registry("wrong,columns\n1,2\n", min_entries=1)
        with self.assertRaises(ValueError):
            ports.parse_registry(registry([]), min_entries=1)
        with self.assertRaises(ValueError):
            ports.parse_registry(registry([ROWS[0]]) + "too,many,columns,for,this,row,1,2,3,4,5,6,7,8\n", min_entries=1)

    def test_shards_deterministic_and_preserve_duplicates(self):
        records = ports.parse_registry(registry(ROWS + [ROWS[0]]), min_entries=1)
        first_data, first_index = ports.build_shards(records)
        second_data, second_index = ports.build_shards(list(reversed(records)))
        self.assertEqual(first_data, second_data)
        self.assertEqual(first_index, second_index)
        self.assertEqual(len(first_data), 256)
        self.assertEqual(len(first_index), 256)
        self.assertEqual(sum(r.get("name") == "microsoft-ds" for r in first_data["0d"].values()), 3)
        self.assertEqual(sum(r.get("description") == "Reserved" for r in first_data["07"].values()), 1)
        self.assertEqual(sum(r.get("description") == "Reserved" for r in first_data["08"].values()), 1)
        self.assertEqual(ports.port_shard(4095), 127)
        self.assertEqual(ports.port_shard(4096), 128)
        self.assertEqual(ports.port_shard(65535), 255)
        all_grams = {gram for shard in first_index.values() for gram in shard}
        self.assertIn("😀xy", all_grams)
        gram_shards = {}
        for shard, grams in first_index.items():
            if grams:
                gram_shards.setdefault(shard, set()).update(grams)
        self.assertTrue(any(len(grams) > 1 for grams in gram_shards.values()))
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            ports.write_shards(first_data, first_index, first_dir)
            ports.write_shards(second_data, second_index, second_dir)
            for kind in ("data", "index"):
                for path in (Path(first_dir) / kind).glob("*.json"):
                    self.assertEqual(path.read_bytes(), (Path(second_dir) / kind / path.name).read_bytes())

    def test_hash_collision_aborts(self):
        records = ports.parse_registry(registry(ROWS[:2]), min_entries=1)
        digest = ports.hashlib.sha256(b"fixed")
        with patch.object(ports.hashlib, "sha256", return_value=digest):
            with self.assertRaisesRegex(ValueError, "collision"):
                ports.build_shards(records)

    def test_javascript_client_end_to_end(self):
        records = ports.parse_registry(registry(ROWS), min_entries=1)
        records[0]["aliases"] = ["SMB"]
        records[0]["comments"] = ["Windows file sharing"]
        data, index = ports.build_shards(records)
        with tempfile.TemporaryDirectory() as directory:
            ports.write_shards(data, index, directory)
            self.assertEqual(len(list((Path(directory) / "data").glob("*.json"))), 256)
            self.assertEqual(len(list((Path(directory) / "index").glob("*.json"))), 256)
            environment = dict(os.environ, PORT_TEST_DIR=directory)
            subprocess.run(
                [os.environ.get("NODE", "node"), "--test", str(ROOT / "tests" / "port_lookup.test.mjs")],
                check=True,
                env=environment,
            )


if __name__ == "__main__":
    unittest.main()
