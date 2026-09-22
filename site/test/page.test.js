import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");

function markupIds() {
  return [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
}

function tokens(attribute) {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]+)"`, "g"))].flatMap((match) => match[1].split(" "));
}

test("the markup names every element once", () => {
  const seen = new Set();
  for (const id of markupIds()) {
    assert.ok(!seen.has(id), `${id} is used twice`);
    seen.add(id);
  }
});

test("every element the page looks up is in the markup", () => {
  const known = new Set(markupIds());
  for (const [, id] of app.matchAll(/\$\("([^"]+)"\)/g)) {
    assert.ok(known.has(id), `js/app.js looks up ${id}, which the markup has not`);
  }
});

test("every label, hint and message container belongs to a field of the markup", () => {
  const known = new Set(markupIds());
  for (const attribute of ["for", "aria-describedby", "aria-labelledby"]) {
    for (const id of tokens(attribute)) {
      assert.ok(known.has(id), `${attribute} names ${id}, which the markup has not`);
    }
  }
});
