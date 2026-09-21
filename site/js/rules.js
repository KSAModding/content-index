import Ajv2020 from "../vendor/ajv2020.js";
import { parse as parseSpdx, exceptions } from "../vendor/spdx.js";
import { LICENSES as LICENSE_IDS, EXCEPTIONS as EXCEPTION_IDS } from "./licenses.js";
import { parseDocument } from "./toml.js";
import { records, ICON, DESCRIPTION, LIMITS, outsideLimits, centerSquare } from "./images.js";
import { scan, SCHEME } from "./markdown.js";

export const ERROR = "error";
export const NOTE = "note";

export const ABSTRACT_LIMIT = 280;
export const TAGS_SPEC = "https://github.com/KSAModding/content-manager-design/blob/main/spec/tags.md";
const SPDX_LIST = "https://spdx.org/licenses/";
const TAG_VOCABULARY = { mod: "mod", "mod-loader": "mod", modpack: "mod" };

const REVISION_BOUND = /^[0-9]{4}\.[0-9]+\.[0-9]+\.([0-9]+)(?![\s\S])/;
const MONTH_BOUND = /^([0-9]{4})\.([0-9]+)(?![\s\S])/;
const GAME_VERSION = /^v?(\d+)\.(\d+)\.(\d+)\.(\d+)(?:-[^+]+)?(?:\+.*)?$/;
const LICENSE_REF = /^(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+(?![\s\S])/;
const THREAD_ID = "[0-9]+";
const SYMBOL = /^[\p{L}\p{N}_.+:-]+$/u;

const LICENSES = new Set(LICENSE_IDS.map((name) => name.toLowerCase()));
const EXCEPTIONS = new Set(EXCEPTION_IDS.map((name) => name.toLowerCase()));
const PLACEHOLDER = { license: "MIT", exception: exceptions[0] };

function message(level, path, text) {
  return { level, path, text };
}

function fold(value) {
  return typeof value === "string" ? value.toLowerCase() : null;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function pyString(text) {
  let body = "";
  for (const character of text) {
    const code = character.codePointAt(0);
    if (character === "\\") body += "\\\\";
    else if (character === "\n") body += "\\n";
    else if (character === "\r") body += "\\r";
    else if (character === "\t") body += "\\t";
    else if (code < 0x20 || code === 0x7f) body += "\\x" + code.toString(16).padStart(2, "0");
    else body += character;
  }
  if (body.includes("'") && !body.includes("\"")) {
    return "\"" + body + "\"";
  }
  return "'" + body.replace(/'/g, "\\'") + "'";
}

export function pyRepr(value) {
  if (typeof value === "string") return pyString(value);
  if (typeof value === "boolean") return value ? "True" : "False";
  if (value === null || value === undefined) return "None";
  if (Array.isArray(value)) return "[" + value.map(pyRepr).join(", ") + "]";
  if (typeof value === "object") {
    return "{" + Object.entries(value).map(([key, item]) => pyRepr(key) + ": " + pyRepr(item)).join(", ") + "}";
  }
  return String(value);
}

function decode(segment) {
  return segment.replace(/~1/g, "/").replace(/~0/g, "~");
}

function pointer(document, instancePath, extra) {
  const steps = instancePath ? instancePath.split("/").slice(1).map(decode) : [];
  if (extra !== undefined) {
    steps.push(extra);
  }
  let node = document;
  let text = "";
  for (const step of steps) {
    if (Array.isArray(node)) {
      text += `[${step}]`;
      node = node[Number(step)];
    } else {
      text += text ? `.${step}` : step;
      node = isObject(node) ? node[step] : undefined;
    }
  }
  return text;
}

function explain(error) {
  const instance = error.propertyName !== undefined ? error.propertyName : error.data;
  const parent = error.parentSchema || {};
  switch (error.keyword) {
    case "pattern": {
      if (Array.isArray(parent.examples) && parent.examples.length) {
        return `${pyRepr(instance)} does not match ${pyRepr(error.schema)}; for example, use ${pyRepr(parent.examples[0])}`;
      }
      return parent.title ? `${pyRepr(instance)} is not ${parent.title}` : `${pyRepr(instance)} does not match ${pyRepr(error.schema)}`;
    }
    case "not":
      if (isObject(error.schema) && Object.keys(error.schema).length === 0) {
        return "this key is not allowed here";
      }
      return isObject(error.schema) && error.schema.title
        ? `${pyRepr(instance)} is ${error.schema.title}`
        : `${pyRepr(instance)} should not be valid under ${pyRepr(error.schema)}`;
    case "required":
      return `${pyRepr(error.params.missingProperty)} is a required property`;
    case "additionalProperties":
      return `Additional properties are not allowed (${pyRepr(error.params.additionalProperty)} was unexpected)`;
    case "enum":
      return `${pyRepr(instance)} is not one of ${pyRepr(error.params.allowedValues)}`;
    case "const":
      return `${pyRepr(error.params.allowedValue)} was expected`;
    case "type":
      return `${pyRepr(instance)} is not of type ${String(error.params.type).split(",").map(pyRepr).join(", ")}`;
    case "minLength":
    case "minItems":
      return error.params.limit === 1 ? `${pyRepr(instance)} should be non-empty` : `${pyRepr(instance)} is too short`;
    case "maxLength":
    case "maxItems":
      return `${pyRepr(instance)} is too long`;
    case "minProperties":
      return `${pyRepr(instance)} should be non-empty`;
    case "minimum":
      return `${instance} is less than the minimum of ${error.params.limit}`;
    case "maximum":
      return `${instance} is greater than the maximum of ${error.params.limit}`;
    case "uniqueItems":
      return `${pyRepr(instance)} has non-unique elements`;
    case "dependentRequired":
      return `${pyRepr(error.params.missingProperty)} is a dependency of ${pyRepr(error.params.property)}`;
    case "anyOf":
    case "oneOf": {
      const passing = error.params && error.params.passingSchemas;
      if (!Array.isArray(passing)) return `${pyRepr(instance)} is not valid under any of the given schemas`;
      const [first, ...more] = passing;
      return `${pyRepr(instance)} is valid under each of ${[...more, first].map((at) => pyRepr(error.schema[at])).join(", ")}`;
    }
    default:
      return error.message;
  }
}

function extraStep(error) {
  if (error.keyword === "required") return error.params.missingProperty;
  if (error.keyword === "additionalProperties") return error.params.additionalProperty;
  if (error.keyword === "dependentRequired") return error.params.missingProperty;
  return error.propertyName;
}

export function schemaMessages(validate, document) {
  if (validate(document)) {
    return [];
  }
  const errors = validate.errors.filter((error) => error.keyword !== "if" && error.keyword !== "propertyNames");
  const parents = errors.filter((error) => error.keyword === "anyOf" || error.keyword === "oneOf");
  const kept = errors.filter(
    (error) => !parents.some((parent) => parent !== error && error.schemaPath.startsWith(parent.schemaPath + "/")),
  );
  kept.sort((a, b) => (a.instancePath < b.instancePath ? -1 : a.instancePath > b.instancePath ? 1 : 0));
  const seen = new Set();
  const found = [];
  for (const error of kept) {
    const where = pointer(document, error.instancePath) || "the document";
    const text = explain(error);
    const unique = where + "\n" + text;
    if (seen.has(unique)) {
      continue;
    }
    seen.add(unique);
    const field = pointer(document, error.instancePath, extraStep(error));
    found.push({ ...message(ERROR, where, text), field: field || where });
  }
  return found;
}

export function semverCompare(left, right) {
  const key = (version) => {
    if (typeof version !== "string") return null;
    const withoutBuild = version.split("+")[0];
    const dash = withoutBuild.indexOf("-");
    const core = dash < 0 ? withoutBuild : withoutBuild.slice(0, dash);
    const pre = dash < 0 ? "" : withoutBuild.slice(dash + 1);
    const numbers = core.split(".");
    if (numbers.length !== 3 || !numbers.every((part) => /^[0-9]+$/.test(part))) return null;
    return { core: numbers.map(Number), pre: pre ? pre.split(".") : null };
  };
  const a = key(left);
  const b = key(right);
  if (a === null || b === null) return null;
  for (let index = 0; index < 3; index += 1) {
    if (a.core[index] !== b.core[index]) return a.core[index] < b.core[index] ? -1 : 1;
  }
  if (!a.pre || !b.pre) {
    return !a.pre && !b.pre ? 0 : a.pre ? -1 : 1;
  }
  for (let index = 0; index < Math.min(a.pre.length, b.pre.length); index += 1) {
    const x = a.pre[index];
    const y = b.pre[index];
    const xNumeric = /^[0-9]+$/.test(x);
    const yNumeric = /^[0-9]+$/.test(y);
    if (xNumeric && yNumeric) {
      if (Number(x) !== Number(y)) return Number(x) < Number(y) ? -1 : 1;
    } else if (xNumeric !== yNumeric) {
      return xNumeric ? -1 : 1;
    } else if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return a.pre.length === b.pre.length ? 0 : a.pre.length < b.pre.length ? -1 : 1;
}

function checkBounds(where, bounds, found) {
  if (!isObject(bounds)) return;
  const order = semverCompare(bounds.max, bounds.min);
  if (order !== null && order < 0) {
    found.push(message(ERROR, where, `max '${bounds.max}' is below min '${bounds.min}'`));
  }
}

function gameBoundKey(bound) {
  if (typeof bound !== "string") return null;
  const revision = REVISION_BOUND.exec(bound);
  if (revision) return ["revision", [Number(revision[1])]];
  const month = MONTH_BOUND.exec(bound);
  return month ? ["month", [Number(month[1]), Number(month[2])]] : null;
}

function before(a, b) {
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return (a[index] ?? -1) < (b[index] ?? -1);
  }
  return false;
}

function checkGameBounds(compatibility, found) {
  const low = gameBoundKey(compatibility.game_min);
  const high = gameBoundKey(compatibility.game_max);
  if (!low || !high || low[0] !== high[0]) return;
  if (before(high[1], low[1])) {
    found.push(message(ERROR, "compatibility",
      `game_max '${compatibility.game_max}' is older than game_min '${compatibility.game_min}'`));
  }
}

function checkParentheses(expression, found) {
  if (typeof expression !== "string") return;
  let depth = 0;
  for (const character of expression) {
    if (character === "(") depth += 1;
    else if (character === ")") {
      depth -= 1;
      if (depth < 0) break;
    }
  }
  if (depth !== 0) {
    found.push(message(ERROR, "license", `'${expression}' has unbalanced parentheses`));
  }
}

function checkLinkKeys(links, found) {
  if (!isObject(links)) return;
  const seen = new Map();
  for (const name of Object.keys(links)) {
    const folded = name.toLowerCase();
    if (seen.has(folded)) {
      found.push(message(ERROR, "links", `'${name}' and '${seen.get(folded)}' are the same key`));
    }
    seen.set(folded, name);
  }
}

function checkDependencies(document, own, found) {
  const entries = document.dependencies;
  if (!Array.isArray(entries)) return;
  const seen = new Map();
  entries.forEach((dependency, index) => {
    if (!isObject(dependency)) return;
    const where = `dependencies[${index}]`;
    checkBounds(where, dependency, found);
    const alternatives = dependency.any_of;
    const members = Array.isArray(alternatives) ? alternatives : [dependency];
    const local = new Map();
    members.forEach((member, offset) => {
      if (alternatives !== undefined) checkBounds(`${where}.any_of[${offset}]`, member, found);
      const identifier = isObject(member) ? fold(member.id) : null;
      if (identifier === null) return;
      if (identifier === own) found.push(message(ERROR, where, "a listing cannot depend on itself"));
      if (local.has(identifier)) found.push(message(ERROR, where, `names '${member.id}' more than once`));
      if (!local.has(identifier)) local.set(identifier, member.id);
    });
    for (const [identifier, written] of local) {
      if (seen.has(identifier)) found.push(message(ERROR, where, `'${written}' already has a dependency entry`));
      if (!seen.has(identifier)) seen.set(identifier, written);
    }
  });
}

export function documentRules(document) {
  const found = [];
  const own = fold(document.id);
  checkLinkKeys(document.links, found);
  if (isObject(document.compatibility)) checkGameBounds(document.compatibility, found);
  checkParentheses(document.license, found);
  if (typeof document.superseded_by === "string" && fold(document.superseded_by) === own) {
    found.push(message(ERROR, "superseded_by", "a listing cannot supersede itself"));
  }
  if (isObject(document.loader)) {
    checkBounds("loader", document.loader, found);
    if (fold(document.loader.id) === own) found.push(message(ERROR, "loader", "a listing cannot be its own loader"));
  }
  checkDependencies(document, own, found);
  return found;
}

function onList(token, exceptionPlace) {
  return (exceptionPlace ? EXCEPTIONS : LICENSES).has(token.toLowerCase());
}

function known(token) {
  return onList(token, false) || onList(token, true);
}

function missingOperator(expression) {
  return (
    `'${expression}' has two license identifiers with no operator between them; join ` +
    "several licenses with AND or OR, such as GPL-2.0-only AND CC-BY-SA-4.0"
  );
}

function notOnTheList(expression, named) {
  return `'${expression}' names ${named}, which is not on the SPDX license list; the identifiers are at ${SPDX_LIST}`;
}

function holdsAReference(name) {
  const words = name.split(" ");
  return words.length > 1 && words.some((word) => LICENSE_REF.test(word));
}

export function licenseErrors(expression) {
  if (typeof expression !== "string" || !expression.trim()) return [];
  const unknown = new Set();
  const tokens = [];
  const words = [];
  let afterWith = false;
  let sequence = false;
  let misplaced = null;
  let run = [];
  // Like license-expression, neighbouring words that neither list knows are one
  // name, and a name beside another name is a missing operator. A name in the
  // wrong place is read first of all, so an exception away from the place after
  // WITH, and anything but an exception in it, are reported before the rest.
  const endRun = () => {
    if (!run.length) return;
    const names = [];
    for (const word of run) {
      const onEitherList = known(word);
      const last = names[names.length - 1];
      if (!onEitherList && last && !last.known) last.text += ` ${word}`;
      else names.push({ text: word, known: onEitherList });
    }
    names.forEach((name, place) => {
      const exceptionPlace = afterWith && place === 0;
      const stray = exceptionPlace
        ? !onList(name.text, true) && !LICENSE_REF.test(name.text)
        : onList(name.text, true) && !onList(name.text, false);
      if (stray && misplaced === null) misplaced = name.text;
    });
    if (names.length > 1) sequence = true;
    else if (!onList(names[0].text, afterWith) && !LICENSE_REF.test(names[0].text)) unknown.add(names[0].text);
    tokens.push(afterWith ? PLACEHOLDER.exception : PLACEHOLDER.license);
    afterWith = false;
    run = [];
  };
  for (const token of expression.match(/\(|\)|[^\s()]+/g) || []) {
    const upper = token.toUpperCase();
    if (token === "(" || token === ")" || upper === "AND" || upper === "OR" || upper === "WITH") {
      endRun();
      tokens.push(token === "(" || token === ")" ? token : upper);
      afterWith = upper === "WITH";
      continue;
    }
    run.push(token);
    words.push(token);
  }
  endRun();
  try {
    if (tokens.some((token, place) => token === "(" && tokens[place + 1] === ")")) throw new Error("empty group");
    if (words.some((word) => !SYMBOL.test(word))) throw new Error("not a symbol");
    parseSpdx(tokens.join(" "));
  } catch {
    return [
      `'${expression}' does not parse as an SPDX license expression; join several ` +
      "licenses with AND or OR, such as GPL-2.0-only AND CC-BY-SA-4.0",
    ];
  }
  if (misplaced === null && sequence) return [missingOperator(expression)];
  const named = misplaced !== null ? [misplaced] : [...unknown].sort();
  if (named.some(holdsAReference)) return [missingOperator(expression)];
  if (named.length) return [notOnTheList(expression, named.join(", "))];
  return [];
}

export function licenseRules(document) {
  const found = licenseErrors(document.license).map((text) => message(ERROR, "license", text));
  for (const [place, , record] of records(document)) {
    for (const text of licenseErrors(record.license)) found.push(message(ERROR, `${place}.license`, text));
  }
  return found;
}

export function curatedTags(tagsText) {
  const vocabulary = parseDocument(tagsText);
  const entries = Array.isArray(vocabulary.mod) ? vocabulary.mod : [];
  return entries.filter((entry) => isObject(entry) && typeof entry.tag === "string");
}

export function tagNotes(document, curated) {
  if (!TAG_VOCABULARY[document.type]) return [];
  const known = new Set(curated);
  const tags = Array.isArray(document.tags) ? document.tags : [];
  const found = [];
  for (const tag of tags) {
    if (!known.has(tag)) {
      found.push(message(NOTE, "tags",
        `'${tag}' is not a curated tag, so no client shows it as a filter; the list is at ${TAGS_SPEC}`));
    }
  }
  if (!tags.some((tag) => known.has(tag))) {
    found.push(message(NOTE, "tags",
      `the document has no curated tag, so no client can include it through a curated filter; the list is at ${TAGS_SPEC}`));
  }
  return found;
}

export function imageRules(document) {
  const found = [];
  const seen = new Map();
  for (const [place, role, record] of records(document)) {
    const { width, height } = record;
    const limits = LIMITS[role];
    if (
      role === ICON && Number.isInteger(width) && Number.isInteger(height) &&
      limits.low <= Math.min(width, height) && Math.max(width, height) <= limits.high * limits.ratio
    ) {
      const outside = outsideLimits(role, width, height);
      if (outside) {
        found.push(message(ERROR, place, outside));
      } else if (width !== height) {
        const [left, top, right, bottom] = centerSquare(width, height);
        found.push(message(NOTE, place,
          `the icon is ${width} by ${height} pixels, so clients show the square from ${left},${top} to ${right},${bottom}`));
      }
    }
    if (role === DESCRIPTION && typeof record.id === "string") {
      if (seen.has(record.id)) found.push(message(ERROR, place, `id '${record.id}' is already used by ${seen.get(record.id)}`));
      if (!seen.has(record.id)) seen.set(record.id, place);
    }
  }
  return found.concat(referenceRules(document));
}

export function referenceRules(document) {
  const found = [];
  const { destinations, html } = typeof document.description === "string"
    ? scan(document.description)
    : { destinations: [], html: 0 };
  const ids = new Set(records(document).filter(([, role]) => role === DESCRIPTION).map(([, , record]) => record.id));
  const referenced = new Set();
  for (const destination of destinations) {
    if (destination.startsWith(SCHEME)) {
      const identifier = destination.slice(SCHEME.length);
      referenced.add(identifier);
      if (!ids.has(identifier)) {
        found.push(message(ERROR, "description", `'${destination}' names no record in [[images.description]]`));
      }
    } else {
      found.push(message(NOTE, "description",
        `the image '${destination}' is not a ${SCHEME} reference, so no client shows it`));
    }
  }
  if (html) found.push(message(NOTE, "description", `${html} image(s) in raw HTML, which no client shows`));
  for (const [place, role, record] of records(document)) {
    if (role === DESCRIPTION && typeof record.id === "string" && !referenced.has(record.id)) {
      found.push(message(NOTE, place, `nothing in the description references '${record.id}', so no client shows it`));
    }
  }
  return found;
}

export function abstractNotes(document) {
  const abstract = document.abstract;
  if (typeof abstract !== "string") return [];
  const length = Array.from(abstract).length;
  if (length <= ABSTRACT_LIMIT) return [];
  return [message(NOTE, "abstract",
    `${length} characters is longer than ${ABSTRACT_LIMIT}, and an abstract is one or two sentences for list views`)];
}

export function threadPattern(schema) {
  const rule = schema.$defs.forumsUrl.pattern;
  if (rule.split(THREAD_ID).length !== 2) {
    throw new Error("forumsUrl has no single thread id to capture");
  }
  return new RegExp(rule.replace(THREAD_ID, `(${THREAD_ID})`), "u");
}

export function threadOf(pattern, forums) {
  const match = typeof forums === "string" ? pattern.exec(forums) : null;
  return match ? Number(match[1]) : null;
}

export function indexRules(document, index, own) {
  const found = [];
  if (!index) return found;
  const self = fold(own);
  const folded = fold(document.id);
  if (folded !== null && folded !== self) {
    const holder = index.holders.get(folded);
    if (holder) {
      found.push(message(ERROR, "id",
        `the id '${document.id}' is already held by ${holder.where}, and ids compare case-insensitively`));
    }
  }
  const resolve = (value, where) => {
    const target = typeof value === "string" ? index.holders.get(value.toLowerCase()) : null;
    if (!target || value.toLowerCase() === folded || !target.type) return null;
    if (value !== target.id) {
      found.push(message(ERROR, where, `'${value}' does not use the canonical id spelling '${target.id}'`));
    }
    return target.type;
  };
  resolve(document.superseded_by, "superseded_by");
  if (isObject(document.loader)) {
    const type = resolve(document.loader.id, "loader");
    if (type && type !== "mod-loader") {
      found.push(message(ERROR, "loader", `'${document.loader.id}' is listed as a ${type}, and a loader has to be a mod-loader`));
    }
  }
  if (Array.isArray(document.dependencies)) {
    document.dependencies.forEach((dependency, number) => {
      if (!isObject(dependency)) return;
      const members = Array.isArray(dependency.any_of)
        ? dependency.any_of.map((member, offset) => [member, `dependencies[${number}].any_of[${offset}]`])
        : [[dependency, `dependencies[${number}]`]];
      for (const [member, where] of members) {
        if (!isObject(member)) continue;
        const type = resolve(member.id, where);
        if (type && type !== "mod") {
          found.push(message(ERROR, where, `'${member.id}' is listed as a ${type}, and a dependency has to be a mod`));
        }
      }
    });
  }
  const links = isObject(document.links) ? document.links : {};
  const thread = threadOf(index.threadPattern, links.forums);
  if (thread !== null) {
    const others = [...new Set(index.threads
      .filter((entry) => entry.thread === thread && entry.holder !== self)
      .map((entry) => entry.where))].sort();
    if (others.length) {
      found.push(message(NOTE, "links.forums",
        `thread ${thread} is also the forums thread of ${others.join(", ")}, so the thread cannot settle an id dispute between them`));
    }
  }
  return found;
}

function monthOf(version) {
  const match = GAME_VERSION.exec(version.trim());
  return match ? [Number(match[1]), Number(match[2])] : null;
}

export function releaseListRules(document, gameVersions, now = new Date()) {
  const found = [];
  const compatibility = isObject(document.compatibility) ? document.compatibility : {};
  if (!Array.isArray(gameVersions) || !gameVersions.length) return found;
  for (const which of ["game_min", "game_max"]) {
    const bound = compatibility[which];
    if (typeof bound !== "string" || GAME_VERSION.test(bound.trim())) continue;
    const match = /^(\d{4})\.(\d{1,2})$/.exec(bound.trim());
    if (!match) continue;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const over = now.getUTCFullYear() > year || (now.getUTCFullYear() === year && now.getUTCMonth() + 1 > month);
    if (which === "game_max" && !over) continue;
    const has = gameVersions.some((version) => {
      const shown = monthOf(version);
      return shown && shown[0] === year && shown[1] === month;
    });
    if (!has) {
      found.push(message(ERROR, `compatibility.${which}`,
        `${which} '${bound}' names a month with no build in the game release list`));
    }
  }
  return found;
}

export function createChecker({ schema, tagsText }) {
  const ajv = new Ajv2020({ allErrors: true, strict: false, verbose: true });
  const validate = ajv.compile(schema);
  const vocabulary = curatedTags(tagsText);
  const curated = vocabulary.map((entry) => entry.tag);
  const pattern = threadPattern(schema);
  return {
    vocabulary,
    curated,
    threadPattern: pattern,
    maxDescriptionImages: schema.properties.images.properties.description.maxItems,
    offline(document) {
      return [
        ...schemaMessages(validate, document),
        ...documentRules(document),
        ...licenseRules(document),
        ...imageRules(document),
        ...tagNotes(document, curated),
        ...abstractNotes(document),
      ];
    },
    check(document, { index = null, own = null, gameVersions = null } = {}) {
      return [
        ...this.offline(document),
        ...indexRules(document, index, own),
        ...releaseListRules(document, gameVersions),
      ];
    },
  };
}
