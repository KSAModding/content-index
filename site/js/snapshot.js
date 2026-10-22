import { semverCompare, threadOf } from "./rules.js";

const SNAPSHOT_FOLDER = "https://ksamodding.github.io/content-index-releases/v1/";

export const SNAPSHOT_URL = `${SNAPSHOT_FOLDER}index.json`;

// The files that hold vehicles and saves next to the main document, each with
// one array named after its key, as spec/snapshot.md "Fetching it" of the design
// repository proposes. This is the only place that names them. When the main
// document carries the two arrays itself, the map is empty and nothing else changes.
export const TYPE_FILES = {
  vehicles: `${SNAPSHOT_FOLDER}snapshot-vehicles.json`,
  saves: `${SNAPSHOT_FOLDER}snapshot-saves.json`,
};

// The snapshot arrays of RFC 0085 and the type of their entries.
const SHARE_ARRAYS = { vehicles: "vehicle", saves: "save" };

// The entries of one type file. The index publishes no file before the first
// listing of its type, so a 404 is an empty list. Any other failure throws,
// because an id is not free while the page cannot read who holds it.
export async function readTypeFile(response, key) {
  if (response.status === 404) return [];
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const document = await response.json();
  return document && Array.isArray(document[key]) ? document[key] : [];
}

// The main document with the arrays of the type files added after its own, in
// the shape indexFacts reads. The page then reads both a main document that
// carries the arrays and one that does not.
export function withTypeFiles(snapshot, parts) {
  const merged = { ...snapshot };
  for (const [key, entries] of Object.entries(parts)) {
    merged[key] = [...(Array.isArray(snapshot[key]) ? snapshot[key] : []), ...entries];
  }
  return merged;
}

function forumsOf(authored) {
  return authored && authored.links && typeof authored.links === "object" ? authored.links.forums : undefined;
}

// The time the watcher found the download gone from its host (RFC 0078), or null.
function goneSince(release) {
  const since = release.download ? release.download.unavailable_since : undefined;
  return typeof since === "string" && since ? since : null;
}

// The newest stable release that a client still offers, so not yanked and with
// its download still there.
export function newestStable(releases) {
  const stable = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && release.release_status === "stable" && !release.yanked && typeof release.version === "string" && !goneSince(release));
  stable.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return stable.length ? stable[0].version : null;
}

function releaseFacts(release) {
  return {
    version: release.version,
    status: typeof release.release_status === "string" ? release.release_status : "",
    gameMin: typeof release.game_min === "string" ? release.game_min : "",
    gameMinRevision: Number.isInteger(release.game_min_revision) ? release.game_min_revision : null,
  };
}

// The releases a pack can pin, which are stamped, not yanked and still
// downloadable, newest first.
export function pinnableReleases(releases) {
  const kept = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string" && !goneSince(release))
    .map(releaseFacts);
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return kept;
}

// The releases a dependency bound can name, which are stamped and not yanked,
// newest first. A release whose download is gone still counts.
export function boundReleases(releases) {
  const kept = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string")
    .map(releaseFacts);
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return kept;
}

// The dependencies that the mod.toml of the newest release that is not yanked
// declares, which the stamper derived, or null when there is no such release.
// An entry the author bounded is stamped as authored, so it is not among them.
export function derivedDependencies(releases) {
  const kept = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string");
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  if (!kept.length) return null;
  const dependencies = (Array.isArray(kept[0].dependencies) ? kept[0].dependencies : [])
    .filter((entry) => entry && entry.source === "derived" && entry.any_of === undefined && typeof entry.id === "string")
    .map((entry) => ({ id: entry.id, kind: entry.kind === "optional" ? "optional" : "required" }));
  return { release: kept[0].version, dependencies };
}

// The release_status of every stamped release, yanked ones included, because a
// pin can stay on a release that was yanked after the pack was published.
export function releaseStatuses(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && typeof release.version === "string")
    .map((release) => [release.version, typeof release.release_status === "string" ? release.release_status : ""]));
}

// Every stamped release by its version, yanked ones included, with what the
// member rules of tools/check_index.py read from its release file.
function stampedReleases(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && typeof release.version === "string")
    .map((release) => [release.version, {
      yanked: release.yanked === true,
      dependencies: Array.isArray(release.dependencies) ? release.dependencies : [],
    }]));
}

// The releases that the picker leaves out only because their download is gone,
// each with the time it went away. A yanked release is not in this map, because
// its pin gets the yank note. The mark does not change what a release needs, so
// the game_min proposal still counts a pin of a gone release.
function goneReleases(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string" && goneSince(release))
    .map((release) => [release.version, { ...releaseFacts(release), since: goneSince(release) }]));
}

// The facts of a pack's forum member list, found the way Borea finds them. A pin
// can name a mod or a mod-loader, and a release that was yanked after the pack
// was published still has its line.
function forumFacts(listing, authored) {
  const forums = forumsOf(authored);
  return {
    id: listing.id,
    name: typeof authored.name === "string" ? authored.name : "",
    authors: Array.isArray(authored.authors) ? authored.authors.filter((author) => typeof author === "string") : [],
    license: typeof authored.license === "string" ? authored.license : "",
    forums: typeof forums === "string" ? forums : "",
    downloads: new Map((Array.isArray(listing.releases) ? listing.releases : [])
      .filter((release) => release && typeof release.version === "string")
      .map((release) => [release.version, release.download && typeof release.download.url === "string" ? release.download.url : ""])),
  };
}

// A listed mod or loader that a dependency can name, in the words the search
// matches and with the releases its bounds can name.
function listedFacts(listing, authored) {
  return {
    id: listing.id,
    name: typeof authored.name === "string" ? authored.name : "",
    authors: Array.isArray(authored.authors) ? authored.authors.filter((author) => typeof author === "string") : [],
    loader: authored.type === "mod-loader",
    releases: boundReleases(listing.releases),
  };
}

// A listing that a pack can pin, a mod, a vehicle or a save, with the releases the picker offers.
function memberFacts(listing, type) {
  const name = typeof listing.authored.name === "string" ? listing.authored.name : "";
  return { id: listing.id, type, name, releases: pinnableReleases(listing.releases), statuses: releaseStatuses(listing.releases), gone: goneReleases(listing.releases) };
}

// Every version of a pack, retracted ones included, highest first.
function packVersions(versions) {
  const kept = versions
    .filter((entry) => entry && entry.authored && typeof entry.authored.version === "string")
    .map((entry) => ({
      version: entry.authored.version,
      releasedAt: typeof entry.authored.released_at === "string" ? entry.authored.released_at : "",
      retracted: entry.index_status && entry.index_status.state === "retracted" ? entry.index_status : null,
    }));
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return kept;
}

export function indexFacts(snapshot, threadPattern) {
  const holders = new Map();
  const threads = [];
  const loaders = [];
  const mods = [];
  const members = [];
  const searchable = [];
  const declared = new Map();
  const forum = new Map();
  const packs = new Map();
  const listed = new Map();
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
    if (!declared.has(folded)) declared.set(folded, derivedDependencies(listing.releases));
    if (type === "mod") mods.push(listing.id);
    const state = listing.index_status && typeof listing.index_status.state === "string" ? listing.index_status.state : null;
    const delisted = state === "delisted";
    if (!listed.has(folded)) listed.set(folded, { id: listing.id, type, state, stamped: stampedReleases(listing.releases) });
    if (type === "mod" && !delisted) members.push(memberFacts(listing, type));
    if ((type === "mod" || type === "mod-loader") && !delisted && !forum.has(folded)) forum.set(folded, forumFacts(listing, authored));
    if ((type === "mod" || type === "mod-loader") && !delisted) searchable.push(listedFacts(listing, authored));
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
    if (!packs.has(folded)) packs.set(folded, { id: pack.id, status: pack.index_status || null, versions: packVersions(versions) });
  }
  // A tombstone has no authored document, so its type is the one of its array.
  for (const [key, shareType] of Object.entries(SHARE_ARRAYS)) {
    for (const entry of Array.isArray(snapshot[key]) ? snapshot[key] : []) {
      if (!entry || typeof entry.id !== "string") continue;
      const folded = entry.id.toLowerCase();
      const authored = entry.authored;
      const type = authored && typeof authored.type === "string" ? authored.type : shareType;
      const where = `${key}/${entry.id}.toml`;
      if (!holders.has(folded)) holders.set(folded, { id: entry.id, type, where });
      const thread = threadOf(threadPattern, forumsOf(authored));
      if (thread !== null) threads.push({ holder: folded, where, thread });
      const state = entry.index_status && typeof entry.index_status.state === "string" ? entry.index_status.state : null;
      if (!listed.has(folded)) listed.set(folded, { id: entry.id, type, state, stamped: stampedReleases(entry.releases) });
      if (authored && type === shareType && state !== "delisted") members.push(memberFacts(entry, type));
    }
  }
  const gameVersions = snapshot.game_versions && Array.isArray(snapshot.game_versions.versions)
    ? snapshot.game_versions.versions.filter((version) => typeof version === "string")
    : [];
  loaders.sort((a, b) => a.id.localeCompare(b.id));
  mods.sort((a, b) => a.localeCompare(b));
  members.sort((a, b) => a.id.localeCompare(b.id));
  return { holders, threads, threadPattern, loaders, mods, members, listed, searchable, declared, forum, packs, gameVersions };
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
