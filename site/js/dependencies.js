import { parse } from "../vendor/smol-toml.js";
import { NOTE } from "./rules.js";
import { KINDS } from "./model.js";
import { StampError, relativePath, topLevelDirectories, entriesUnder, zipEntries, modTomlFiles } from "./archive.js";

// The help for the dependencies of a mod follows the listing editor of Borea:
// what the mod.toml already declares, a search over the listed mods and loaders
// for the id, and the stamped releases of the named mod for the bounds.

const MOD_TOML = "mod.toml";
// The characters str.strip of Python removes.
const PY_SPACE = "[\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]";
const PY_STRIP = new RegExp(`^${PY_SPACE}+|${PY_SPACE}+$`, "gu");

export const KIND_TEXTS = {
  required: "Your mod does not work without it, so a client always installs it too.",
  optional: "Your mod uses it when it is there. A client does not install it by itself.",
  recommends: "A client selects it for the install, and the player can deselect it.",
  suggests: "A client names it, and the player decides whether to install it.",
  conflict: "Your mod must not be installed together with it. Give the versions that conflict as the oldest and the newest version, or leave both empty when every version conflicts.",
};

export const TEXTS = {
  declared: (of) => `The mod.toml of ${of} declares these dependencies. The index adds them to each release by itself, so add an entry only for bounds or a conflict.`,
  declaredNone: (of) => `The mod.toml of ${of} declares no dependencies.`,
  noRoot: (archive) => `The page cannot find the install root in ${archive}, so the index reads no mod.toml from it. The usual layout is one top-level folder that holds mod.toml and has the id as its name.`,
  noModToml: (archive) => `${archive} has no mod.toml in its install root, so the index derives no dependencies from it.`,
  unreadable: (archive, problem) => `The page could not read ${archive}: ${problem}`,
  required: (id) => `Required by your mod.toml: ${id}`,
  optional: (id) => `Optional in your mod.toml: ${id}`,
  notListed: (id) => `${id} is not listed in the index, so players cannot install it.`,
  loaderSet: (id) => `${id} is a mod loader, so it is now the loader under Compatibility. Set its versions there.`,
  needsNewest: "Needs the newest",
  needsNewestHint: "Sets the oldest version to the newest stable release of the mod.",
};

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fold(id) {
  return typeof id === "string" ? id.trim().toLowerCase() : "";
}

// What the kind does, or null for a kind the index does not know.
export function kindText(kind) {
  return Object.hasOwn(KIND_TEXTS, kind) ? KIND_TEXTS[kind] : null;
}

// The kinds the index knows, and first a kind it does not know when the entry
// came with one, so the list can show it.
export function kindChoices(kind) {
  return !kind || KINDS.includes(kind) ? KINDS : [kind, ...KINDS];
}

// The listed mod or loader of an id that a client can install, or null.
export function listedOf(index, id) {
  const folded = fold(id);
  return index && folded ? index.searchable.find((listing) => listing.id.toLowerCase() === folded) || null : null;
}

export function isListedLoader(index, id) {
  const listing = listedOf(index, id);
  return Boolean(listing && listing.loader);
}

// The stamped releases of a listed mod, newest first and without the yanked
// ones, a release that is not stable marked with its status.
export function boundChoices(index, id) {
  const listing = listedOf(index, id);
  return listing ? listing.releases.map((release) => ({ version: release.version, status: release.status === "stable" ? "" : release.status })) : [];
}

// The release "Needs the newest" sets as the oldest version: the newest stable
// one, or the newest one when none is stable.
export function newestBound(index, id) {
  const listing = listedOf(index, id);
  if (!listing || !listing.releases.length) return null;
  const stable = listing.releases.find((release) => release.status === "stable");
  return (stable || listing.releases[0]).version;
}

// "Needs the newest" shows when the named mod has stamped releases, and not for
// a conflict, whose bounds name the versions that conflict.
export function canNeedNewest(index, entry) {
  return boundChoices(index, entry.id).length > 0 && entry.kind !== "conflict";
}

// The derived dependencies of the newest stamped release of a listing, or null.
export function derivedOf(index, id) {
  const folded = fold(id);
  return index && folded ? index.declared.get(folded) || null : null;
}

// The ids the entries name, each id of a kept entry with alternatives too.
export function namedIds(entries) {
  const ids = new Set();
  for (const entry of entries) {
    const members = entry.kept === undefined
      ? [entry]
      : isObject(entry.kept) && Array.isArray(entry.kept.any_of) ? entry.kept.any_of : [entry.kept];
    for (const member of members) {
      if (isObject(member) && fold(member.id)) ids.add(fold(member.id));
    }
  }
  return ids;
}

// Whether [loader] of the form names the id. Only a mod has a loader.
export function isLoaderSet(form, id) {
  return form.type === "mod" && Boolean(fold(id)) && fold(form.loaderId) === fold(id);
}

// Whether no entry and not [loader] names the id yet, so bounds can be added.
export function canAddBounds(form, id) {
  return !namedIds(form.dependencies).has(fold(id)) && !isLoaderSet(form, id);
}

// The listed mods and loaders a dependency can name. A listing that is not a
// mod has no loader, so the search leaves the loaders out for it.
export function dependencyCandidates(index, form) {
  return index ? index.searchable.filter((listing) => form.type === "mod" || !listing.loader) : [];
}

function byId(a, b) {
  const x = a.id.toUpperCase();
  const y = b.id.toUpperCase();
  return x < y ? -1 : x > y ? 1 : 0;
}

// The candidates without an entry yet whose id, name or authors contain the
// query, sorted by id. The listing itself and the loader it names are left out.
export function dependencyMatches(index, form, query) {
  const typed = query.trim().toLowerCase();
  if (!typed) return [];
  const named = namedIds(form.dependencies);
  const own = fold(form.id);
  return dependencyCandidates(index, form)
    .filter((listing) => {
      const id = listing.id.toLowerCase();
      return id !== own && !named.has(id) && !isLoaderSet(form, listing.id);
    })
    .filter((listing) => [listing.id, listing.name, ...listing.authors].some((text) => text.toLowerCase().includes(typed)))
    .sort(byId);
}

// Turns on [loader] with the loader, and takes its newest stable release as
// the oldest version when the loader changes or has no oldest version yet.
export function useLoader(form, index, id) {
  if (fold(form.loaderId) !== fold(id) || !form.loaderMin.trim()) {
    const loader = index ? index.loaders.find((entry) => entry.id.toLowerCase() === fold(id)) : null;
    form.loaderMin = loader && loader.newest ? loader.newest : "";
  }
  form.loaderId = id;
}

// Adds an entry with the id in the spelling the index lists it, so the index
// takes it for the derived entry of the same id. A listed loader becomes the
// loader of a mod instead, and the answer is then its id.
export function addDependency(form, index, id, kind) {
  const listing = listedOf(index, id);
  if (listing && listing.loader && form.type === "mod") {
    useLoader(form, index, listing.id);
    return listing.id;
  }
  form.dependencies.push({ id: listing ? listing.id : id, kind, min: "", max: "" });
  return null;
}

// A note for each entry whose id no listing and no pack of the index holds,
// because no player can install that dependency. The checks already name an id
// the index holds with another type, and a dependency on the listing itself.
export function dependencyNotes(document, index, validId) {
  if (!index || !Array.isArray(document.dependencies)) return [];
  const own = fold(document.id);
  const found = [];
  document.dependencies.forEach((dependency, number) => {
    if (!isObject(dependency) || dependency.any_of !== undefined || typeof dependency.id !== "string") return;
    const id = dependency.id;
    if (!validId(id) || id.toLowerCase() === own || index.holders.has(id.toLowerCase())) return;
    found.push({ level: NOTE, path: `dependencies[${number}]`, text: TEXTS.notListed(id) });
  });
  return found;
}

// The truth of a value as Python reads it.
function truthy(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return value.length > 0;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "bigint") return value !== 0n;
  if (Array.isArray(value)) return value.length > 0;
  if (Object.getPrototypeOf(value) === Object.prototype) return Object.keys(value).length > 0;
  return true;
}

// The blocks of [[StarMap.ModDependencies]] as derived_dependencies of the
// stamper reads them. A mod.toml it cannot read gives no release at all.
export function modTomlDependencies(manifest) {
  const starMap = manifest.StarMap;
  if (!truthy(starMap)) return [];
  if (!isObject(starMap) || Object.getPrototypeOf(starMap) !== Object.prototype) {
    throw new StampError("[StarMap] of the mod.toml is not a table");
  }
  const blocks = starMap.ModDependencies;
  if (!truthy(blocks)) return [];
  if (!Array.isArray(blocks)) {
    throw new StampError("StarMap.ModDependencies of the mod.toml is not a list of [[StarMap.ModDependencies]] blocks");
  }
  return blocks.map((block) => {
    if (!isObject(block) || Object.getPrototypeOf(block) !== Object.prototype) {
      throw new StampError("a [[StarMap.ModDependencies]] block is not a table");
    }
    if (!truthy(block.ModId)) throw new StampError("a [[StarMap.ModDependencies]] block carries no ModId");
    if (typeof block.ModId !== "string") throw new StampError("a [[StarMap.ModDependencies]] block has a ModId that is not text");
    const id = block.ModId.replace(PY_STRIP, "");
    if (!id) throw new StampError("a [[StarMap.ModDependencies]] block carries no ModId");
    return { id, kind: truthy(block.Optional) ? "optional" : "required" };
  });
}

// A mod.toml as read_mod_toml of the stamper reads it, which drops a UTF-8 BOM
// and reads an integer of any size.
export function readModToml(bytes, name) {
  try {
    return parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes), { integersAsBigInt: "asNeeded" });
  } catch (error) {
    throw new StampError(`the archive's ${name} is not valid TOML, ${error.message}`);
  }
}

// The names and the mod.toml files of a release zip.
export async function readArchive(file) {
  const entries = await zipEntries(file);
  return { names: entries.map((entry) => entry.name), files: await modTomlFiles(file, entries) };
}

// The root whose mod.toml the stamper reads: the authored install root, or else
// the one top-level folder of the archive, preferring the folders with a
// mod.toml. The root is null when the archive gives none.
export function modTomlRoot(names, document) {
  const install = isObject(document.install) ? document.install : {};
  if (install.root !== undefined) {
    const root = relativePath(install.root, "the authored install root");
    if (root && !entriesUnder(names, root).length) throw new StampError(`the authored install root '${root}' is not in the archive`);
    return root;
  }
  const directories = topLevelDirectories(names);
  const withManifest = directories.filter((name) => names.includes(`${name}/${MOD_TOML}`));
  const candidates = withManifest.length ? withManifest : directories;
  return candidates.length === 1 ? candidates[0] : null;
}

// What the mod.toml of a read archive declares for the document: the
// dependencies, or why the stamper reads none, or why it reads no release.
export function archiveDependencies(archive, document) {
  try {
    const root = modTomlRoot(archive.names, document);
    if (root === null) return { missing: "root" };
    const name = root ? `${root}/${MOD_TOML}` : MOD_TOML;
    const file = archive.files.get(name);
    if (!file) return { missing: MOD_TOML };
    if (file.problem) return { problem: file.problem };
    return { dependencies: modTomlDependencies(readModToml(file.bytes, name)) };
  } catch (error) {
    if (!(error instanceof StampError)) throw error;
    return { problem: error.message };
  }
}

// What the declared box shows for the document: what the mod.toml of the
// selected zip declares, else the derived dependencies of the newest stamped
// release of the loaded listing, and the line of the zip read. When it has none
// of them, it says when the dependencies show, unless the snapshot of a loaded
// listing is still loading. Only a mod has them, because the stamper reads no
// mod.toml for any other type.
export function declaredFor({ document, index, base, archive }) {
  const help = { shown: false, declared: null, read: null, pending: false };
  if (document.type !== "mod") return help;
  if (archive) {
    const result = archiveDependencies(archive, document);
    if (result.dependencies) help.declared = { of: archive.fileName, dependencies: result.dependencies };
    else if (result.problem) help.read = [NOTE, TEXTS.unreadable(archive.fileName, result.problem)];
    else help.read = [null, result.missing === "root" ? TEXTS.noRoot(archive.fileName) : TEXTS.noModToml(archive.fileName)];
  }
  if (!help.declared && base) {
    const derived = derivedOf(index, base.id);
    if (derived) help.declared = { of: `release ${derived.release}`, dependencies: derived.dependencies };
  }
  help.pending = !help.declared && !help.read && !(base && !index);
  help.shown = Boolean(help.declared || help.read || help.pending);
  return help;
}
