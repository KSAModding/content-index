import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { parseDocument, writeDocument } from "../js/toml.js";

const LISTINGS = new URL("../../listings/", import.meta.url);
const files = fs.readdirSync(LISTINGS).filter((name) => name.endsWith(".toml"));

test("every listing keeps its content through the writer", () => {
  for (const name of files) {
    const document = parseDocument(fs.readFileSync(new URL(name, LISTINGS), "utf8"));
    assert.deepEqual(parseDocument(writeDocument(document)), document, name);
  }
});

test("listings in the usual layout come out byte for byte", () => {
  for (const name of ["StarMap.toml", "DeltaVMap.toml", "KSArmory.toml"]) {
    const text = fs.readFileSync(new URL(`fixtures/${name}`, import.meta.url), "utf8");
    assert.equal(writeDocument(parseDocument(text)), text, name);
  }
});

test("hard strings survive the escaping", () => {
  const strings = [
    "ends with a quote\"",
    "ends with two quotes\"\"",
    "three \"\"\" in a row and four \"\"\"\"",
    "a backslash \\ and a line end \\\nnext",
    "\ttab, " + String.fromCodePoint(1) + " control, " + String.fromCodePoint(0x7f) + " delete and \r return",
    "\nstarts with a line break",
    "Unicode: " + String.fromCodePoint(0xe9, 0x4e2d, 0x1f680),
  ];
  for (const value of strings) {
    for (const key of ["description", "name"]) {
      const document = { [key]: value };
      assert.deepEqual(parseDocument(writeDocument(document)), document, JSON.stringify(value));
    }
  }
});

test("a multi-line description is written as a multi-line string", () => {
  const text = writeDocument({ spec_version: 1, description: "One.\nTwo.\n" });
  assert.equal(text, "spec_version = 1\ndescription = \"\"\"\nOne.\nTwo.\n\"\"\"\n");
});

test("keys that are not bare are quoted", () => {
  const text = writeDocument({ links: { forums: "https://x.invalid/", "my site": "https://y.invalid/" } });
  assert.match(text, /^"my site" = /m);
});
