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

export function inspectArchive(names, document) {
  const problems = [];
  const install = document.install && typeof document.install === "object" ? document.install : {};
  const provides = document.provides && typeof document.provides === "object" ? document.provides : {};
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
    return { root: null, derived, problems, launches: [] };
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
  return { root, derived, problems, launches };
}
