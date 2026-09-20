import { parse, TomlDate } from "../vendor/smol-toml.js";

const ORDER = {
  "": [
    "spec_version", "id", "type", "name", "authors", "abstract", "description", "license", "tags",
    "status", "superseded_by", "version", "released_at", "changelog",
    "releases", "links", "compatibility", "loader", "dependencies", "install", "provides", "images",
    "mods", "vehicles", "saves",
  ],
  releases: ["github", "spacedock", "authority"],
  compatibility: ["game_min", "game_max", "os"],
  loader: ["id", "min", "max"],
  "dependencies[]": ["id", "any_of", "kind", "min", "max"],
  "dependencies[].any_of[]": ["id", "min", "max"],
  install: ["root", "target", "path", "manages", "steps", "uninstall"],
  provides: ["launch", "content-dir", "content-path", "configure", "instance", "platform"],
  "provides.configure": ["file", "format", "game-path"],
  "provides.instance": ["flag", "variable"],
  "provides.platform": ["windows", "linux", "macos"],
  "provides.platform.*": ["runtime", "launch"],
  images: ["icon", "description"],
  "images.icon": ["id", "url", "sha256", "width", "height", "size", "license", "attribution", "source"],
  "images.description[]": ["id", "url", "sha256", "width", "height", "size", "license", "attribution", "source"],
  "mods[]": ["id", "version"],
  "vehicles[]": ["id", "version"],
  "saves[]": ["id", "version"],
};

const TABLE_ARRAYS = new Set(["dependencies", "images.description", "mods", "vehicles", "saves"]);
const LONG_ARRAYS = new Set(["install.manages", "install.steps", "install.uninstall", "dependencies[].any_of"]);
const BARE_KEY = /^[A-Za-z0-9_-]+$/;

function normalise(value) {
  if (value instanceof TomlDate) {
    const text = value.toISOString();
    return text.endsWith("+00:00") ? text.slice(0, -6) + "Z" : text;
  }
  if (Array.isArray(value)) {
    return value.map(normalise);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalise(item)]));
  }
  return value;
}

export function parseDocument(text) {
  return normalise(parse(text));
}

function isTable(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function escapeCharacter(character, multiline) {
  switch (character) {
    case "\\": return "\\\\";
    case "\b": return "\\b";
    case "\t": return multiline ? "\t" : "\\t";
    case "\n": return multiline ? "\n" : "\\n";
    case "\f": return "\\f";
    case "\r": return "\\r";
    case "\"": return multiline ? "\"" : "\\\"";
  }
  const code = character.codePointAt(0);
  if (code < 0x20 || code === 0x7f) {
    return "\\u" + code.toString(16).toUpperCase().padStart(4, "0");
  }
  return character;
}

export function quote(text) {
  return "\"" + Array.from(text, (character) => escapeCharacter(character, false)).join("") + "\"";
}

function literal(text) {
  return text.includes("\\") && !text.includes("'''") && !text.endsWith("'") && !/[\u0000-\u0008\u000b-\u001f\u007f]/.test(text);
}

function multiline(text) {
  if (literal(text)) {
    return "'''\n" + text + "'''";
  }
  const characters = Array.from(text);
  let body = "";
  let run = 0;
  characters.forEach((character, index) => {
    if (character === "\"") {
      const last = index === characters.length - 1;
      if (run === 2 || last) {
        body += "\\\"";
        run = 0;
      } else {
        body += "\"";
        run += 1;
      }
      return;
    }
    run = 0;
    body += escapeCharacter(character, true);
  });
  return "\"\"\"\n" + body + "\"\"\"";
}

function key(name) {
  return BARE_KEY.test(name) ? name : quote(name);
}

function ordered(table, path) {
  const order = ORDER[path] || ORDER[path.replace(/\.[^.]+$/, ".*")] || [];
  const keys = Object.keys(table);
  return [...order.filter((name) => keys.includes(name)), ...keys.filter((name) => !order.includes(name))];
}

function inline(value, path) {
  if (typeof value === "string") {
    return quote(value);
  }
  if (typeof value === "number" || typeof value === "bigint") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    const items = value.map((item) => inline(item, path + "[]"));
    if (LONG_ARRAYS.has(path) && items.length) {
      return "[\n" + items.map((item) => "  " + item + ",\n").join("") + "]";
    }
    return "[" + items.join(", ") + "]";
  }
  if (isTable(value)) {
    const parts = ordered(value, path).map((name) => key(name) + " = " + inline(value[name], path + "." + name));
    return parts.length ? "{ " + parts.join(", ") + " }" : "{}";
  }
  return quote(String(value));
}

function pathOf(parent, name) {
  return parent ? parent + "." + name : name;
}

function isTableArray(path, value) {
  return TABLE_ARRAYS.has(path) && Array.isArray(value) && value.length > 0 && value.every(isTable);
}

function writeTable(table, header, path, schemaPath, blocks, arrayItem) {
  const lines = [];
  const children = [];
  for (const name of ordered(table, schemaPath)) {
    const value = table[name];
    const childPath = pathOf(path, name);
    const childSchema = pathOf(schemaPath, name);
    if (isTable(value) && !arrayItem) {
      children.push(() => writeTable(value, childPath, childPath, childSchema, blocks, false));
    } else if (isTableArray(childSchema, value) && !arrayItem) {
      children.push(() => {
        for (const item of value) {
          writeTable(item, childPath, childPath, childSchema + "[]", blocks, true);
        }
      });
    } else if (name === "description" && typeof value === "string" && value.includes("\n")) {
      lines.push(key(name) + " = " + multiline(value));
    } else {
      lines.push(key(name) + " = " + inline(value, childSchema));
    }
  }
  if (header && (lines.length || !children.length || arrayItem)) {
    const name = header.split(".").map(key).join(".");
    lines.unshift(arrayItem ? "[[" + name + "]]" : "[" + name + "]");
  }
  if (lines.length) {
    blocks.push(lines.join("\n"));
  }
  children.forEach((write) => write());
}

export function writeDocument(document) {
  const blocks = [];
  writeTable(document, "", "", "", blocks, false);
  return blocks.join("\n\n") + "\n";
}
