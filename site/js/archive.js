import { parse } from "../vendor/smol-toml.js";
import { saveNameProblem } from "./savename.js";

const MOD_TOML = "mod.toml";
const END = 0x06054b50;
const END_SIZE = 22;
const END_SEARCH = END_SIZE + 0xffff;
const LOCATOR = 0x07064b50;
const LOCATOR_SIZE = 20;
const END64 = 0x06064b50;
const END64_SIZE = 56;
const ENTRY = 0x02014b50;
const ENTRY_SIZE = 46;
const UTF8_NAME = 0x800;

export class StampError extends Error {}

class BadZip extends Error {}

async function bytesOf(file, start, end) {
  return new Uint8Array(await file.slice(start, end).arrayBuffer());
}

function viewOf(bytes) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

async function centralDirectory(file) {
  const tailStart = Math.max(0, file.size - END_SEARCH);
  const tail = await bytesOf(file, tailStart, file.size);
  const view = viewOf(tail);
  let end = -1;
  for (let position = tail.length - END_SIZE; position >= 0; position -= 1) {
    if (view.getUint32(position, true) === END) {
      end = position;
      break;
    }
  }
  if (end < 0) throw new BadZip("File is not a zip file");
  if (view.getUint16(end + 4, true) !== 0 || view.getUint16(end + 6, true) !== 0) {
    throw new BadZip("zipfiles that span multiple disks are not supported");
  }
  let size = view.getUint32(end + 12, true);
  let offset = view.getUint32(end + 16, true);
  let record = tailStart + end;
  const locator = record - LOCATOR_SIZE;
  if (locator >= 0) {
    const found = viewOf(await bytesOf(file, locator, record));
    if (found.byteLength === LOCATOR_SIZE && found.getUint32(0, true) === LOCATOR) {
      const start = locator - END64_SIZE;
      const header = start >= 0 ? viewOf(await bytesOf(file, start, locator)) : null;
      if (!header || header.getUint32(0, true) !== END64) {
        throw new BadZip("Corrupt zip64 end of central directory locator");
      }
      size = Number(header.getBigUint64(40, true));
      offset = Number(header.getBigUint64(48, true));
      record = start;
    }
  }
  if (size > record) throw new BadZip("Bad offset for central directory");
  // Bytes in front of the first entry move every offset the directory names,
  // and Python's zipfile adds them to each header offset.
  return { directory: await bytesOf(file, record - size, record), bias: record - size - offset };
}

const LOCAL = 0x04034b50;
const LOCAL_SIZE = 30;
const ZIP64_EXTRA = 0x0001;
const FULL32 = 0xffffffff;
const STORED = 0;
const DEFLATED = 8;
const ENCRYPTED = 0x1;
export const MOD_TOML_LIMIT = 1024 * 1024;

// The sizes and the offset that do not fit in 32 bits are in the zip64 extra
// field, in this order and only when the 32-bit field is full.
function zip64Values(directory, start, end, entry) {
  const view = viewOf(directory);
  let position = start;
  while (position + 4 <= end) {
    const kind = view.getUint16(position, true);
    const size = view.getUint16(position + 2, true);
    if (kind === ZIP64_EXTRA) {
      let field = position + 4;
      for (const key of ["size", "compressed", "offset"]) {
        if (entry[key] !== FULL32) continue;
        if (field + 8 > Math.min(position + 4 + size, end)) throw new BadZip("Corrupt extra field 0001");
        entry[key] = Number(view.getBigUint64(field, true));
        field += 8;
      }
      return;
    }
    position += 4 + size;
  }
}

function entriesIn({ directory, bias }) {
  const view = viewOf(directory);
  const utf8 = new TextDecoder("utf-8");
  const latin1 = new TextDecoder("latin1");
  const entries = [];
  let position = 0;
  while (position < directory.length) {
    if (position + ENTRY_SIZE > directory.length) throw new BadZip("Truncated central directory");
    if (view.getUint32(position, true) !== ENTRY) throw new BadZip("Bad magic number for central directory");
    const flags = view.getUint16(position + 8, true);
    const nameEnd = position + ENTRY_SIZE + view.getUint16(position + 28, true);
    if (nameEnd > directory.length) throw new BadZip("Truncated central directory");
    const extraEnd = nameEnd + view.getUint16(position + 30, true);
    const name = (flags & UTF8_NAME ? utf8 : latin1).decode(directory.subarray(position + ENTRY_SIZE, nameEnd));
    const cut = name.indexOf("\0");
    const entry = {
      name: cut < 0 ? name : name.slice(0, cut),
      flags,
      method: view.getUint16(position + 10, true),
      compressed: view.getUint32(position + 20, true),
      size: view.getUint32(position + 24, true),
      offset: view.getUint32(position + 42, true),
    };
    zip64Values(directory, nameEnd, Math.min(extraEnd, directory.length), entry);
    entry.offset += bias;
    entries.push(entry);
    position = extraEnd + view.getUint16(position + 32, true);
  }
  return entries;
}

export async function zipEntries(file) {
  try {
    return entriesIn(await centralDirectory(file));
  } catch (error) {
    if (error instanceof BadZip) throw new StampError(`the archive is not a readable zip, ${error.message}`);
    throw error;
  }
}

export async function zipNames(file) {
  return (await zipEntries(file)).map((entry) => entry.name);
}

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// The bytes of one entry. Release zips store or deflate their entries.
export async function readEntry(file, entry) {
  const fail = (reason) => new StampError(`the archive's ${entry.name} cannot be read, ${reason}`);
  if (entry.flags & ENCRYPTED) throw fail("it is encrypted");
  if (entry.method !== STORED && entry.method !== DEFLATED) throw fail(`its compression method ${entry.method} is not supported`);
  const header = entry.offset < 0 ? null : viewOf(await bytesOf(file, entry.offset, entry.offset + LOCAL_SIZE));
  if (!header || header.byteLength < LOCAL_SIZE || header.getUint32(0, true) !== LOCAL) throw fail("its local header is missing");
  const start = entry.offset + LOCAL_SIZE + header.getUint16(26, true) + header.getUint16(28, true);
  const stored = await bytesOf(file, start, start + entry.compressed);
  if (stored.length !== entry.compressed) throw fail("it is cut short");
  let bytes;
  try {
    bytes = entry.method === STORED ? stored : await inflate(stored);
  } catch (error) {
    throw fail(error.message);
  }
  if (bytes.length !== entry.size) throw fail(`it holds ${bytes.length} bytes, not the ${entry.size} its header names`);
  return bytes;
}

// The bytes of every mod.toml in the archive by its name, or why the stamper
// cannot read it. Of a name that is in the zip twice, the stamper reads the
// last entry.
export async function modTomlFiles(file, entries) {
  const latest = new Map();
  for (const entry of entries) {
    if (entry.name === MOD_TOML || entry.name.endsWith(`/${MOD_TOML}`)) latest.set(entry.name, entry);
  }
  const files = new Map();
  for (const [name, entry] of latest) {
    if (entry.size > MOD_TOML_LIMIT) {
      files.set(name, { problem: `the archive's ${name} is ${entry.size} bytes, above the ${MOD_TOML_LIMIT} byte limit` });
      continue;
    }
    try {
      files.set(name, { bytes: await readEntry(file, entry) });
    } catch (error) {
      if (!(error instanceof StampError)) throw error;
      files.set(name, { problem: error.message });
    }
  }
  return files;
}

// The archive rules of a vehicle and a save (RFC 0085), as the stamper of
// content-index-releases checks them. The game sees a folder only when it holds
// its game file (`VehicleSaveData.ExistsIn`, `UniverseData.ExistsIn`).
export const META_TOML = "meta.toml";
export const GAME_FILES = { vehicle: "vehicle.xml", save: "universe.xml" };
const META_VERSION = /^v?([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$/;
const GAME_FILE_LIMIT = 256 * 1024 * 1024;
// A save can be large, and the page parses in the browser, so above this it
// leaves the game file to the watcher.
export const PAGE_XML_LIMIT = 32 * 1024 * 1024;
const NOTE_NAMES = 20;

function gameFileOf(type) {
  return Object.hasOwn(GAME_FILES, type) ? GAME_FILES[type] : null;
}

// A TOML file as the stamper reads it, which drops a UTF-8 BOM.
export function readToml(bytes, name, options = {}) {
  try {
    return parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes), options);
  } catch (error) {
    throw new StampError(`the archive's ${name} is not valid TOML, ${error.message}`);
  }
}

// How Python prints a value with repr, which the stamper puts into its messages.
function pythonRepr(value) {
  if (value === undefined || value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value !== "string") return typeof value === "object" ? JSON.stringify(value) : String(value);
  const quote = value.includes("'") && !value.includes("\"") ? "\"" : "'";
  const escaped = value.replace(/[\\\n\r\t]|[\x00-\x1f\x7f]/g, (character) => (
    { "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t" }[character] || `\\x${character.charCodeAt(0).toString(16).padStart(2, "0")}`
  ));
  return quote + (quote === "'" ? escaped.replace(/'/g, "\\'") : escaped) + quote;
}

function atTop(name, file) {
  const parts = name.split("/");
  return parts[parts.length - 1] === file && parts.length <= 2;
}

// The meta.toml files and the verdicts on the game files at the archive root or
// one folder down, where the root of a vehicle or a save is. The type can change
// after the zip is chosen, so both game files are read. `wellFormed` gives null
// for well-formed XML and else what is wrong.
export async function gameFiles(file, entries, wellFormed) {
  const latest = new Map();
  for (const entry of entries) {
    if ([META_TOML, ...Object.values(GAME_FILES)].some((name) => atTop(entry.name, name))) latest.set(entry.name, entry);
  }
  const files = new Map();
  for (const [name, entry] of latest) {
    try {
      files.set(name, atTop(name, META_TOML) ? await metaFile(file, entry) : await xmlVerdict(file, entry, wellFormed));
    } catch (error) {
      if (!(error instanceof StampError)) throw error;
      files.set(name, { problem: error.message });
    }
  }
  return files;
}

async function metaFile(file, entry) {
  if (entry.size > MOD_TOML_LIMIT) {
    throw new StampError(`the archive's ${entry.name} is ${entry.size} bytes, above the ${MOD_TOML_LIMIT} byte limit`);
  }
  return { meta: readToml(await readEntry(file, entry), entry.name) };
}

// `XmlSerializer` never writes a DOCTYPE, and the stamper refuses one, so the
// page refuses it before any parse.
async function xmlVerdict(file, entry, wellFormed) {
  if (entry.size > GAME_FILE_LIMIT) {
    throw new StampError(`the archive's ${entry.name} is ${entry.size} bytes, above the ${GAME_FILE_LIMIT} byte limit`);
  }
  if (entry.size > PAGE_XML_LIMIT) return { unchecked: true };
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(await readEntry(file, entry));
  } catch (error) {
    if (error instanceof StampError) throw error;
    throw new StampError(`the archive's ${entry.name} is not well-formed XML, it is not UTF-8 text`);
  }
  if (text.includes("<!DOCTYPE")) throw new StampError(`the archive's ${entry.name} carries a DOCTYPE, which the game never writes`);
  const detail = wellFormed(text);
  if (detail) throw new StampError(`the archive's ${entry.name} is not well-formed XML, ${detail}`);
  return { xml: true };
}

// The root of a vehicle or a save, as _game_root of the stamper: the archive root
// when it holds meta.toml and the game file, else the one top-level folder that
// holds both, else the one place with a meta.toml, so the checks can name what is missing.
function gameRoot(names, gameFile) {
  const present = new Set(names);
  if (present.has(META_TOML) && present.has(gameFile)) return "";
  const directories = topLevelDirectories(names);
  const complete = directories.filter((name) => present.has(`${name}/${META_TOML}`) && present.has(`${name}/${gameFile}`));
  if (complete.length) return complete.length === 1 ? complete[0] : null;
  const withMeta = [...(present.has(META_TOML) ? [""] : []), ...directories.filter((name) => present.has(`${name}/${META_TOML}`))];
  return withMeta.length === 1 ? withMeta[0] : null;
}

// The checks of game_folder in the stamper, in its order and words, and the
// folder the release installs as. A file the page did not read is left to the watcher.
function gameFolder(names, files, root, type, notes) {
  const metaEntry = root ? `${root}/${META_TOML}` : META_TOML;
  if (!names.includes(metaEntry)) throw new StampError(`the archive has no ${metaEntry}, which the game reads for every folder`);
  const metaFile = files.get(metaEntry);
  if (!metaFile) {
    notes.push(`the page reads ${META_TOML} only at the top of the zip or one folder down, so the watcher checks ${metaEntry}`);
    return null;
  }
  if (metaFile.problem) throw new StampError(metaFile.problem);
  const meta = metaFile.meta;
  const name = meta.name;
  if (typeof name !== "string") throw new StampError(`the archive's ${metaEntry} has no \`name\` string, which the game shows`);
  const problem = saveNameProblem(name);
  if (problem) throw new StampError(`\`name\` in the archive's ${metaEntry} is ${pythonRepr(name)}, and ${problem} (RFC 0085)`);
  const folder = root ? root.slice(root.lastIndexOf("/") + 1) : null;
  if (folder !== null && folder !== name) {
    if (folder.toLowerCase() === name.toLowerCase()) {
      throw new StampError(
        `the archive's folder is '${folder}' and \`name\` in its meta.toml is '${name}': ` +
        "the game saves into a folder named after `name`, so the casing has to match",
      );
    }
    throw new StampError(
      `the archive's folder is '${folder}', which does not match \`name\` '${name}' in its meta.toml: ` +
      "the game saves into a folder named after `name`",
    );
  }
  const game = GAME_FILES[type];
  const entry = root ? `${root}/${game}` : game;
  if (!names.includes(entry)) {
    const near = names.find((other) => other.toLowerCase() === entry.toLowerCase());
    if (near !== undefined) {
      throw new StampError(`the archive has ${pythonRepr(near)} and no ${pythonRepr(entry)}, and the game opens ${game} with that exact case`);
    }
    throw new StampError(`the archive has no ${entry}, so the game does not see the ${type}`);
  }
  const verdict = files.get(entry);
  if (verdict && verdict.problem) throw new StampError(verdict.problem);
  if (!verdict || verdict.unchecked) notes.push(`the page did not parse ${entry}, so the watcher checks that it is well-formed XML`);
  if (type === "vehicle") {
    const prefix = root ? `${root}/` : "";
    const others = entriesUnder(names, root)
      .map((other) => other.replace(/\\/g, "/"))
      .filter((other) => other !== metaEntry && other !== entry)
      .map((other) => other.slice(prefix.length));
    if (others.length) {
      // json.dumps of the stamper escapes every character outside ASCII.
      const quoted = others.slice(0, NOTE_NAMES).map((other) => JSON.stringify(other).replace(/[^\x00-\x7f]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`));
      const more = others.length > NOTE_NAMES ? `, and ${others.length - NOTE_NAMES} more` : "";
      notes.push(`the vehicle folder holds files besides ${META_TOML} and ${game}, which the game drops when it saves the vehicle again: ${quoted.join(", ")}${more}`);
    }
  }
  return meta;
}

// meta_game_min of the stamper, which runs only when the listing authors no game_min.
function metaGameMin(meta) {
  const version = meta.version;
  const match = typeof version === "string" ? META_VERSION.exec(version) : null;
  let reason = null;
  if (!match) reason = "not a game version Y.M.B.R without a suffix";
  else if (Number(match[4]) === 0) reason = "the game's mark of an unknown build";
  if (reason) throw new StampError(`meta.toml says version ${pythonRepr(version)}, which is ${reason}, and the listing authors no game_min`);
}

export function topLevelDirectories(names) {
  const seen = [];
  for (const entry of names) {
    const name = entry.replace(/\\/g, "/");
    const slash = name.indexOf("/");
    const head = slash < 0 ? name : name.slice(0, slash);
    const rest = slash < 0 ? "" : name.slice(slash + 1);
    if (!head || (!rest && !name.endsWith("/"))) continue;
    if (!seen.includes(head)) seen.push(head);
  }
  return seen;
}

export function entriesUnder(names, root) {
  const prefix = root ? `${root}/` : "";
  return names.filter((name) => !name.endsWith("/") && name.replace(/\\/g, "/").startsWith(prefix));
}

export function deriveRoot(names, listingId, contentType) {
  if (gameFileOf(contentType)) return gameRoot(names, gameFileOf(contentType));
  if (contentType !== "mod") return "";
  const directories = topLevelDirectories(names);
  const withManifest = directories.filter((name) => names.includes(`${name}/${MOD_TOML}`));
  const candidates = withManifest.length ? withManifest : directories;
  if (candidates.length !== 1) return null;
  const name = candidates[0];
  if (name === listingId) return name;
  if (name.toLowerCase() === String(listingId).toLowerCase()) {
    throw new StampError(
      `the archive's top-level directory is '${name}' and the id is '${listingId}': ` +
      "the folder name is the identity the game sees, so the casing has to match",
    );
  }
  throw new StampError(`the archive's top-level directory is '${name}', which does not match the id '${listingId}'`);
}

export function relativePath(value, what) {
  const text = String(value);
  if (!text || text.startsWith("/") || text.startsWith("~") || text.includes("\\") || /^[A-Za-z]:/.test(text)) {
    throw new StampError(`${what} '${text}' is not a relative path with '/' separators`);
  }
  const parts = [];
  for (const part of text.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (!parts.length) throw new StampError(`${what} '${text}' escapes its anchor`);
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  return parts.join("/");
}

function launchIn(names, root, launch, what) {
  const path = relativePath(launch, what);
  const entry = root ? `${root}/${path}` : path;
  if (!names.some((name) => name.replace(/\\/g, "/") === entry)) {
    throw new StampError(`${what} '${path}' is not in the release archive`);
  }
}

// `files` holds what readArchive read from the zip. Without it, a vehicle or a
// save gets only the checks of the file names.
export function inspectArchive(names, document, files = new Map()) {
  const problems = [];
  const notes = [];
  const install = document.install && typeof document.install === "object" ? document.install : {};
  const provides = document.provides && typeof document.provides === "object" ? document.provides : {};
  const game = gameFileOf(document.type);
  let root = null;
  let derived = false;
  try {
    if (install.root !== undefined) {
      root = relativePath(install.root, "the authored install root");
      if (root && !entriesUnder(names, root).length) {
        throw new StampError(`the authored install root '${root}' is not in the archive`);
      }
    } else {
      derived = true;
      root = deriveRoot(names, document.id, document.type);
      if (root === null && game) {
        throw new StampError(
          "the install root is neither derivable from the archive nor authored: " +
          `the standard layout is one top-level directory named after \`name\` in its meta.toml, holding meta.toml and ${game}`,
        );
      }
      if (root === null) {
        throw new StampError(
          "the install root is neither derivable from the archive nor authored: " +
          `the standard layout is one top-level directory containing mod.toml, named '${document.id}'`,
        );
      }
    }
  } catch (error) {
    if (!(error instanceof StampError)) throw error;
    problems.push(error.message);
    return { root: null, derived, problems, notes, launches: [], folder: null };
  }
  if (game) {
    let folder = null;
    try {
      const meta = gameFolder(names, files, root, document.type, notes);
      const compatibility = document.compatibility && typeof document.compatibility === "object" ? document.compatibility : {};
      if (meta) {
        folder = meta.name;
        if (!compatibility.game_min) metaGameMin(meta);
      }
    } catch (error) {
      if (!(error instanceof StampError)) throw error;
      problems.push(error.message);
    }
    return { root, derived, problems, notes, launches: [], folder };
  }
  const launches = [];
  const check = (launch, what) => {
    try {
      launchIn(names, root, launch, what);
      launches.push(launch);
    } catch (error) {
      if (!(error instanceof StampError)) throw error;
      problems.push(error.message);
    }
  };
  if (document.type === "mod-loader") {
    if (provides.launch !== undefined) check(provides.launch, "the provides launch path");
    const platforms = provides.platform && typeof provides.platform === "object" ? provides.platform : {};
    for (const platform of Object.keys(platforms).sort()) {
      const entry = platforms[platform];
      if (entry && typeof entry === "object" && entry.launch !== undefined) {
        check(entry.launch, `the provides platform ${platform} launch path`);
      }
    }
  }
  return { root, derived, problems, notes, launches, folder: null };
}
