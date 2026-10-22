// The name rule of RFC 0085 for `name` in the meta.toml of a vehicle or a save.
// The game keeps a name only when `SaveName.Sanitize` gives it back unchanged,
// and `schemas/save-names.json` holds the cases that every copy of the rule runs.

export const SAVE_NAME_LIMIT = 64;

// The categories of `char.IsLetterOrDigit`, tested on one UTF-16 code unit at a
// time, so a surrogate of a letter outside the Basic Multilingual Plane fails.
const KEPT = /^[\p{Lu}\p{Ll}\p{Lt}\p{Lm}\p{Lo}\p{Nd} _-]$/u;
const RESERVED = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i;

export function validSaveName(name) {
  if (typeof name !== "string" || name.length === 0 || name.length > SAVE_NAME_LIMIT) return false;
  for (let index = 0; index < name.length; index += 1) {
    if (!KEPT.test(name[index])) return false;
  }
  if (name.startsWith(" ") || name.endsWith(" ") || name.includes("  ")) return false;
  return !RESERVED.test(name);
}
