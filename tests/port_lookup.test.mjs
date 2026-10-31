import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { lookupPort, searchPorts } from "../examples/port-lookup.mjs";

const root = process.env.PORT_TEST_DIR;
let requests = [];
globalThis.fetch = async url => {
  const pathname = new URL(url).pathname;
  requests.push(pathname);
  const text = await readFile(path.join(root, pathname), "utf8");
  return { ok: true, json: async () => JSON.parse(text) };
};
const base = "https://fixtures.invalid";

test("port lookup loads one shard and respects ranges and protocol", async () => {
  requests = [];
  const records = await lookupPort(base, 445);
  assert.equal(requests.length, 1);
  assert.deepEqual(records.map(record => record.protocol).sort(), ["tcp", "udp"]);
  assert.deepEqual((await lookupPort(base, 445, "TCP")).map(record => record.protocol), ["tcp"]);
  assert.equal((await lookupPort(base, 255)).filter(record => record.status === "reserved").length, 1);
  assert.equal((await lookupPort(base, 256)).filter(record => record.status === "reserved").length, 1);
  assert.equal((await lookupPort(base, 256, "tcp")).length, 0);
  assert.equal((await lookupPort(base, 256, "sctp"))[0].name, "wide");
  assert.equal((await lookupPort(base, 0)).length, 0);
  await assert.rejects(lookupPort(base, -1), RangeError);
  await assert.rejects(lookupPort(base, 65536), RangeError);
  await assert.rejects(lookupPort(base, 1.5), RangeError);
  await assert.rejects(lookupPort(base, 1, ""), TypeError);
});

test("substring search returns complete filtered matches and future fields", async () => {
  assert.deepEqual((await searchPorts(base, "SMB")).map(record => record.protocol), ["tcp"]);
  assert.deepEqual((await searchPorts(base, "file shar")).map(record => record.name), ["microsoft-ds"]);
  assert.equal((await searchPorts(base, "MICROSOFT")).length, 2);
  assert.equal((await searchPorts(base, "reserved")).length, 1);
  assert.equal((await searchPorts(base, "portless"))[0].port, null);
  assert.equal((await searchPorts(base, "abcD")).length, 0);
  assert.equal((await searchPorts(base, "😀xy"))[0].name, "unicode");
  assert.deepEqual(await searchPorts(base, "not-present"), []);
  await assert.rejects(searchPorts(base, "ab"), RangeError);
  await assert.rejects(searchPorts(base, "   "), RangeError);
  await assert.rejects(searchPorts(base, null), TypeError);
});

test("HTTP and index consistency failures are explicit", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, status: 404 });
    await assert.rejects(lookupPort(base, 445), /HTTP 404/);
    globalThis.fetch = async url => {
      const response = await original(url);
      if (url.includes("/data/")) return { ok: true, json: async () => ({ version: 1, entries: {} }) };
      return response;
    };
    await assert.rejects(searchPorts(base, "microsoft"), /missing record/);
  } finally {
    globalThis.fetch = original;
  }
});
