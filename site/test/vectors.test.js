import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { parseDocument } from "../js/toml.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const schema = JSON.parse(read("../../schemas/authored.schema.json"));
const tagsText = read("../../tags.toml");
const checker = createChecker({ schema, tagsText });
const { vectors } = JSON.parse(read("../../schemas/vectors.json"));

// A vector with `gated` names a type that the rollout gate of RFC 0085 holds.
// While the schema refuses that type, the vector is refused with the title of
// the gate, and its own verdict holds against a copy of the schema without it.
const gate = schema.properties.type.not;
const gated = new Set(gate ? gate.enum : []);
const ungatedSchema = structuredClone(schema);
delete ungatedSchema.properties.type.not;
const ungated = createChecker({ schema: ungatedSchema, tagsText });

function lines(found) {
  return found.map((entry) => `${entry.path}: ${entry.text}`);
}

function run(rules, vector) {
  const document = parseDocument(vector.toml);
  return vector.game_versions
    ? rules.check(document, { gameVersions: vector.game_versions })
    : rules.offline(document);
}

function agrees(found, vector) {
  const said = lines(found);
  assert.equal(!found.some((entry) => entry.level === ERROR), vector.accepted, said.join("\n"));
  assert.equal(found.some((entry) => entry.level === NOTE), vector.noted, said.join("\n"));
  if (vector.says) {
    assert.ok(said.some((line) => line.includes(vector.says)), said.join("\n"));
  }
}

for (const vector of vectors) {
  test(`${vector.rule}: ${vector.name}`, () => {
    const found = run(checker, vector);
    if (gated.has(vector.gated)) {
      const said = lines(found);
      assert.ok(said.includes(`type: '${vector.gated}' is ${gate.title}`), said.join("\n"));
      assert.equal(found.some((entry) => entry.level === NOTE), vector.noted, said.join("\n"));
      return;
    }
    agrees(found, vector);
  });

  if (vector.gated) {
    test(`${vector.rule}: ${vector.name}, without the gate`, () => {
      agrees(run(ungated, vector), vector);
    });
  }
}
