import { semverCompare, threadOf } from "./rules.js";

export const SNAPSHOT_URL = "https://ksamodding.github.io/content-index-releases/v1/index.json";

function forumsOf(authored) {
  return authored && authored.links && typeof authored.links === "object" ? authored.links.forums : undefined;
}

export function newestStable(releases) {
  const stable = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && release.release_status === "stable" && !release.yanked && typeof release.version === "string");
  stable.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return stable.length ? stable[0].version : null;
}

export function indexFacts(snapshot, threadPattern) {
  const holders = new Map();
  const threads = [];
  const loaders = [];
  const mods = [];
  for (const listing of Array.isArray(snapshot.listings) ? snapshot.listings : []) {
    if (!listing || typeof listing.id !== "string") continue;
    const folded = listing.id.toLowerCase();
    const authored = listing.authored;
    const type = authored && typeof authored.type === "string" ? authored.type : null;
    const where = `listings/${listing.id}.toml`;
    if (!holders.has(folded)) holders.set(folded, { id: listing.id, type, where });
    const thread = threadOf(threadPattern, forumsOf(authored));
    if (thread !== null) threads.push({ holder: folded, where, thread });
    if (type === "mod-loader") loaders.push({ id: listing.id, newest: newestStable(listing.releases) });
    if (type === "mod") mods.push(listing.id);
  }
  for (const pack of Array.isArray(snapshot.packs) ? snapshot.packs : []) {
    if (!pack || typeof pack.id !== "string") continue;
    const folded = pack.id.toLowerCase();
    const versions = Array.isArray(pack.versions) ? pack.versions : [];
    const wheres = versions.map((entry) => {
      const version = entry && entry.authored ? entry.authored.version : undefined;
      return [entry, `packs/${pack.id}/${version}.toml`];
    });
    if (!holders.has(folded)) {
      holders.set(folded, { id: pack.id, type: "modpack", where: wheres.length ? wheres[0][1] : `packs/${pack.id}/` });
    }
    for (const [entry, where] of wheres) {
      const thread = threadOf(threadPattern, forumsOf(entry && entry.authored));
      if (thread !== null) threads.push({ holder: folded, where, thread });
    }
  }
  const gameVersions = snapshot.game_versions && Array.isArray(snapshot.game_versions.versions)
    ? snapshot.game_versions.versions.filter((version) => typeof version === "string")
    : [];
  loaders.sort((a, b) => a.id.localeCompare(b.id));
  mods.sort((a, b) => a.localeCompare(b));
  return { holders, threads, threadPattern, loaders, mods, gameVersions };
}

export function gameVersionChoices(gameVersions) {
  const months = [];
  for (const version of gameVersions) {
    const match = /^(\d{4})\.(\d{1,2})\./.exec(version);
    const month = match ? `${match[1]}.${Number(match[2])}` : null;
    if (month && !months.includes(month)) months.push(month);
  }
  return [...gameVersions].reverse().concat(months.reverse());
}
