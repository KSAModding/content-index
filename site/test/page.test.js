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

test("the type is chosen before the releases and the id", () => {
  const type = html.indexOf('id="type"');
  assert.ok(type > 0 && type < html.indexOf('id="releases-section"') && type < html.indexOf('id="id"'));
});

test("a text that a pack shows names what is listed through the word the type sets", () => {
  for (const id of ["hint-forums", "hint-link-spacedock", "hint-game-min", "hint-game-max"]) {
    const hint = new RegExp(`<p id="${id}"[^>]*>([\\s\\S]*?)</p>`).exec(html)[1];
    assert.match(hint, /<span class="noun">mod<\/span>/, id);
    assert.doesNotMatch(hint.replace(/<span class="noun">mod<\/span>/g, ""), /\b(your|the) mod\b/, id);
  }
  assert.match(html, /<label for="license">License of your <span class="noun">mod<\/span><\/label>/);
  const render = /function renderTypeSections\(\) \{([\s\S]*?)\n\}/.exec(app)[1];
  assert.match(render, /querySelectorAll\("\.noun"\)\) word\.textContent = nounOf\(state\.form\.type\)/);
  assert.match(render, /querySelectorAll\("\.not-pack"\)\) part\.hidden = shown\.pack/);
});

function body(start) {
  const from = app.indexOf(start);
  assert.ok(from >= 0, `js/app.js has no ${start}`);
  return app.slice(from, app.indexOf("\n}\n", from));
}

test("the since field shows next to a release host and tells what the watcher stamps", () => {
  const input = html.match(/<input id="since"[^>]*>/);
  assert.ok(input && /aria-describedby="[^"]*\bmsg-releases\.since\b/.test(input[0]), "the since input does not name msg-releases.since");
  assert.match(app, /\n  since: \["since"\],\n/, "the since input is not bound to state.form.since");
  assert.match(body("function refresh()"), /\$\("since-field"\)\.hidden = !\(state\.form\.github\.trim\(\) \|\| state\.form\.spacedock\.trim\(\)\);/);
  const hint = /<p id="hint-since"[^>]*>([\s\S]*?)<\/p>/.exec(html)[1];
  assert.match(hint, /stamps every older release from that version on, with the facts this listing states today/);
  assert.match(hint, /amendment/);
});

test("a hidden field does not mark its section as done", () => {
  assert.match(body("function renderSections()"), /const filled = \[\.\.\.section\.querySelectorAll\("input, select, textarea"\)\]\.some\(\(field\) =>\s+!field\.closest\("\[hidden\]"\) && /);
});

test("a refused tag shows at the tag input and does not outlive its form", () => {
  const input = html.match(/<input id="tag-input"[^>]*>/);
  assert.ok(input && /aria-describedby="[^"]*\bmsg-tags\b/.test(input[0]), "the tag input does not name msg-tags");
  const clear = body("function clearTagEntry()");
  assert.match(clear, /tagError = null;/);
  assert.match(clear, /\$\("tag-input"\)\.value = "";/);
  for (const start of ['$("reset").addEventListener', "function useBase("]) {
    assert.match(body(start), /clearTagEntry\(\);/, `${start} keeps the refused tag of the earlier form`);
  }
});
