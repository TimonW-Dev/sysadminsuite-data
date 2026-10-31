import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { lookupPort, searchPorts } from "../examples/port-lookup.mjs";

const root = process.argv[2];
if (!root) throw new Error("Provide the generated port dataset directory");
let requests = [];
globalThis.fetch = async url => {
  const pathname = new URL(url).pathname;
  const filename = path.join(root, pathname);
  const data = await readFile(filename);
  requests.push({ pathname, bytes: data.length });
  return { ok: true, json: async () => JSON.parse(data) };
};

for (const [label, operation] of [
  ["port 445/tcp", () => lookupPort("https://benchmark.invalid", 445, "tcp")],
  ["port 65535", () => lookupPort("https://benchmark.invalid", 65535)],
  ["search microsoft", () => searchPorts("https://benchmark.invalid", "microsoft")],
  ["search minecraft", () => searchPorts("https://benchmark.invalid", "minecraft")],
  ["search unassigned", () => searchPorts("https://benchmark.invalid", "unassigned")],
]) {
  requests = [];
  const results = await operation();
  console.log(`${label}: ${results.length} results, ${requests.length} files, ${requests.reduce((n, item) => n + item.bytes, 0)} JSON bytes`);
}
let total = 0;
for (const kind of ["data", "index"]) {
  for (let i = 0; i < 256; i++) {
    total += (await stat(path.join(root, kind, `${i.toString(16).padStart(2, "0")}.json`))).size;
  }
}
console.log(`complete generated dataset: ${total} JSON bytes`);
