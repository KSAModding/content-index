import { test } from "node:test";
import assert from "node:assert/strict";
import { renderPreview, scan } from "../js/markdown.js";

test("the preview shows only images measured in this session", () => {
  const html = renderPreview("![Shot](ksa-image:shot) ![Gone](ksa-image:gone) ![Web](https://example.invalid/x.png)", new Map([["shot", "blob:x"]]));
  assert.equal(html, "<p><img src=\"blob:x\" alt=\"Shot\"> <span class=\"missing-image\">Gone</span> Web</p>\n");
});

test("the preview escapes raw HTML and drops script links", () => {
  const html = renderPreview("<img src=x onerror=alert(1)>\n\n[a](javascript:alert(1))", new Map());
  assert.ok(!html.includes("<img"), html);
  assert.ok(!html.includes("href=\"javascript"), html);
});

test("the scan finds images as CommonMark parses them", () => {
  assert.deepEqual(scan("![a](ksa-image:a)\n\n```\n![b](ksa-image:b)\n```\n\n<img src=\"c\">\n"), {
    destinations: ["ksa-image:a"],
    html: 1,
  });
});
