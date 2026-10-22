import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { validSaveName } from "../js/savename.js";

const { vectors } = JSON.parse(fs.readFileSync(new URL("../../schemas/save-names.json", import.meta.url), "utf8"));

for (const vector of vectors) {
  test(`save name: ${vector.name}`, () => {
    assert.equal(validSaveName(vector.value), vector.accepted, vector.why);
  });
}
