import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { parseDocument } from "../js/toml.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const checker = createChecker({ schema: JSON.parse(read("../../schemas/authored.schema.json")), tagsText: read("../../tags.toml") });
const { vectors } = JSON.parse(read("../../schemas/vectors.json"));

for (const vector of vectors) {
  test(`${vector.rule}: ${vector.name}`, () => {
    const found = checker.offline(parseDocument(vector.toml));
    const lines = found.map((entry) => `${entry.path}: ${entry.text}`);
    assert.equal(!found.some((entry) => entry.level === ERROR), vector.accepted, lines.join("\n"));
    assert.equal(found.some((entry) => entry.level === NOTE), vector.noted, lines.join("\n"));
    if (vector.says) {
      assert.ok(lines.some((line) => line.includes(vector.says)), lines.join("\n"));
    }
  });
}
