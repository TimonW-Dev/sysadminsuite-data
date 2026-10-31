import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { lookupPort, searchPorts } from "../examples/port-lookup.mjs";

const root = process.argv[2];
if (!root) throw new Error("Provide the generated port dataset directory");
globalThis.fetch = async url => {
  const data = await readFile(path.join(root, new URL(url).pathname));
  return { ok: true, json: async () => JSON.parse(data) };
};
const records = new Map();
for (let i = 0; i < 256; i++) {
  const shard = i.toString(16).padStart(2, "0");
  const data = JSON.parse(await readFile(path.join(root, "data", `${shard}.json`), "utf8"));
  for (const [id, record] of Object.entries(data.entries)) {
    if (records.has(id)) assert.deepEqual(records.get(id), record);
    records.set(id, record);
  }
}
const fold = text => text.replace(/[A-Z]/g, character => character.toLowerCase());
const ids = results => results.map(record => record.id).sort();
for (const query of ["microsoft", "minecraft", "unassigned", "service", "tcp", "ssh", "dns"]) {
  const expected = [...records].filter(([, record]) =>
    [record.name, record.description, ...(record.aliases ?? []), ...(record.comments ?? [])]
      .some(text => typeof text === "string" && fold(text).includes(fold(query))))
    .map(([id]) => id).sort();
  assert.deepEqual(ids(await searchPorts("https://verify.invalid", query)), expected, query);
}
for (const port of [0, 1, 80, 250, 255, 256, 445, 4095, 4096, 32768, 65535]) {
  for (const protocol of [null, "tcp", "udp", "sctp", "dccp"]) {
    const expected = [...records].filter(([, record]) => {
      if (record.port === null || (protocol !== null && record.protocol !== protocol)) return false;
      const bounds = Array.isArray(record.port) ? record.port : [record.port, record.port];
      return bounds[0] <= port && port <= bounds[1];
    }).map(([id]) => id).sort();
    assert.deepEqual(ids(await lookupPort("https://verify.invalid", port, protocol)), expected, `${port}/${protocol}`);
  }
}
console.log(`Verified ${records.size} distinct IANA records, 7 searches and 55 port/protocol combinations against a full scan.`);
