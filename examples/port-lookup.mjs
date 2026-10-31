const VERSION = 1;

function normalize(text) {
  return text.replace(/[A-Z]/g, character => character.toLowerCase());
}

function portShard(port) {
  const shard = port < 4096 ? Math.floor(port / 32) : 128 + Math.floor((port - 4096) / 480);
  return shard.toString(16).padStart(2, "0");
}

async function gramShard(gram) {
  const hash = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(gram));
  return new Uint8Array(hash)[0].toString(16).padStart(2, "0");
}

async function readShard(baseUrl, kind, shard) {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/${kind}/${shard}.json`);
  if (!response.ok) throw new Error(`Failed to load ${kind}/${shard}.json: HTTP ${response.status}`);
  const payload = await response.json();
  const key = kind === "data" ? "entries" : "grams";
  if (payload.version !== VERSION || !payload[key] || typeof payload[key] !== "object" || Array.isArray(payload[key])) {
    throw new Error(`Invalid ${kind}/${shard}.json schema`);
  }
  return payload[key];
}

function searchable(record) {
  return [record.name, record.description, ...(record.aliases ?? []), ...(record.comments ?? [])]
    .filter(text => typeof text === "string");
}

export async function lookupPort(baseUrl, port, protocol = null) {
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new RangeError("Port must be an integer from 0 to 65535");
  if (protocol !== null && (typeof protocol !== "string" || !protocol.trim())) throw new TypeError("Protocol must be a non-empty string");
  const entries = await readShard(baseUrl, "data", portShard(port));
  return Object.entries(entries).filter(([, record]) => {
    const bounds = Array.isArray(record.port) ? record.port : [record.port, record.port];
    return bounds[0] !== null && bounds[0] <= port && port <= bounds[1] &&
      (protocol === null || normalize(record.protocol ?? "") === normalize(protocol));
  }).map(([id, record]) => ({ id, ...record }));
}

export async function searchPorts(baseUrl, query) {
  if (typeof query !== "string") throw new TypeError("Search query must be a string");
  const normalized = normalize(query);
  const characters = Array.from(normalized);
  if (characters.length < 3 || !normalized.trim()) throw new RangeError("Search query must contain at least three characters");
  const grams = [...new Set(characters.slice(0, -2).map((_, i) => characters.slice(i, i + 3).join("")))];
  const shardsByGram = await Promise.all(grams.map(gramShard));
  const indexShards = new Map(await Promise.all([...new Set(shardsByGram)].map(async shard =>
    [shard, await readShard(baseUrl, "index", shard)])));
  const postingLists = grams.map((gram, i) => indexShards.get(shardsByGram[i])[gram] ?? []);
  postingLists.sort((a, b) => a.length - b.length);
  const otherLists = postingLists.slice(1).map(list => new Set(list));
  const references = postingLists[0].filter(reference => otherLists.every(list => list.has(reference)));
  const shardNames = [...new Set(references.map(reference => reference.slice(0, 2)))];
  const dataShards = new Map(await Promise.all(shardNames.map(async shard =>
    [shard, await readShard(baseUrl, "data", shard)])));
  const results = [];
  for (const reference of references) {
    const id = reference.slice(2);
    const record = dataShards.get(reference.slice(0, 2))[id];
    if (!record) throw new Error(`Index references missing record ${reference}`);
    if (searchable(record).some(text => normalize(text).includes(normalized))) results.push({ id, ...record });
  }
  return results;
}
