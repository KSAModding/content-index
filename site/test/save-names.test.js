import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { validSaveName, saveNameProblem } from "../js/savename.js";

const { vectors } = JSON.parse(fs.readFileSync(new URL("../../schemas/save-names.json", import.meta.url), "utf8"));

for (const vector of vectors) {
  test(`save name: ${vector.name}`, () => {
    assert.equal(validSaveName(vector.value), vector.accepted, vector.why);
    assert.equal(saveNameProblem(vector.value) === null, vector.accepted, vector.why);
  });
}

test("a refused name gets the reason of save_name_problem in the stamper", () => {
  const reasons = [
    [5, "the name is not a string"],
    ["", "the name is empty"],
    ["x".repeat(65), "the name has 65 UTF-16 code units, and the game keeps at most 64"],
    [`a${String.fromCodePoint(0x1f600)}`, "the name holds U+1F600, which is outside the Basic Multilingual Plane, and the game reads it as two surrogates, which it drops"],
    ["a!", "the name holds U+0021, and the game keeps only letters, digits, spaces, '-' and '_'"],
    [`a${String.fromCharCode(0xb2)}`, "the name holds U+00B2, and the game keeps only letters, digits, spaces, '-' and '_'"],
    [" a", "the name starts or ends with a space, which the game drops"],
    ["a  b", "the name holds two spaces together, which the game makes one"],
    ["lpt1", "the name 'lpt1' is a device name on Windows, which the game does not use"],
    ["Example Rover", null],
  ];
  for (const [name, reason] of reasons) assert.equal(saveNameProblem(name), reason, String(name));
});
