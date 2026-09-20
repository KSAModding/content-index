# Vendored libraries

Each file is a single ES module bundled with esbuild 0.28.2 (`--bundle --format=esm --platform=neutral --minify`) from the pinned npm packages below, so the page loads nothing from a CDN.
The license texts are in `licenses/`.
After the build, the two non-ASCII characters that esbuild leaves in regular expression literals of `markdown-it.js` are written as `\u` escapes, so every file is ASCII.

| File | Packages |
|---|---|
| `ajv2020.js` | ajv 8.20.0 (`ajv/dist/2020`), fast-deep-equal 3.1.3, fast-uri 3.1.8, json-schema-traverse 1.0.0 |
| `smol-toml.js` | smol-toml 1.8.0 |
| `spdx.js` | spdx-expression-parse 5.0.0, spdx-license-ids 3.0.24, spdx-exceptions 2.5.0 |
| `markdown-it.js` | markdown-it 14.1.0, entities 4.5.0, linkify-it 5.0.2, mdurl 2.1.0, punycode.js 2.3.1, uc.micro 2.1.0 |

The entry of each bundle re-exports what the page uses, for example `export { parse, TomlDate } from "smol-toml";`.
