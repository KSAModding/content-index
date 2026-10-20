// The name rule of RFC 0085 for `name` in the meta.toml of a vehicle or a save.
// The game keeps a name only when `SaveName.Sanitize` gives it back unchanged,
// and `schemas/save-names.json` holds the cases that every copy of the rule runs.

export const SAVE_NAME_LIMIT = 64;

// The categories of `char.IsLetterOrDigit`, tested on one UTF-16 code unit at a
// time, so a surrogate of a letter outside the Basic Multilingual Plane fails.
const KEPT = /^[\p{Lu}\p{Ll}\p{Lt}\p{Lm}\p{Lo}\p{Nd} _-]$/u;
const RESERVED = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i;

function codePoint(value) {
  return `U+${value.toString(16).toUpperCase().padStart(4, "0")}`;
}

// Why the game would not keep the name, in the words of save_name_problem in the
// stamper of content-index-releases, or null.
export function saveNameProblem(name) {
  if (typeof name !== "string") return "the name is not a string";
  if (!name) return "the name is empty";
  if (name.length > SAVE_NAME_LIMIT) {
    return `the name has ${name.length} UTF-16 code units, and the game keeps at most ${SAVE_NAME_LIMIT}`;
  }
  for (const character of name) {
    const value = character.codePointAt(0);
    if (value > 0xffff) {
      return `the name holds ${codePoint(value)}, which is outside the Basic Multilingual Plane, and the game reads it as two surrogates, which it drops`;
    }
    if (!KEPT.test(character)) return `the name holds ${codePoint(value)}, and the game keeps only letters, digits, spaces, '-' and '_'`;
  }
  if (name.startsWith(" ") || name.endsWith(" ")) return "the name starts or ends with a space, which the game drops";
  if (name.includes("  ")) return "the name holds two spaces together, which the game makes one";
  if (RESERVED.test(name)) return `the name '${name}' is a device name on Windows, which the game does not use`;
  return null;
}

export function validSaveName(name) {
  return saveNameProblem(name) === null;
}
