import markdownit from "../vendor/markdown-it.js";

export const SCHEME = "ksa-image:";
const HTML_IMAGE = /<\s*(?:img|image|picture|svg)\b/gi;

const scanner = markdownit("commonmark");
scanner.validateLink = () => true;
scanner.normalizeLink = (url) => url;

export function scan(text) {
  const destinations = [];
  let html = 0;
  const pending = scanner.parse(text, {}).reverse();
  while (pending.length) {
    const token = pending.pop();
    if (token.type === "image") {
      destinations.push(token.attrGet("src") || "");
    } else if (token.type === "html_inline" || token.type === "html_block") {
      html += (token.content.match(HTML_IMAGE) || []).length;
    }
    if (token.children) {
      pending.push(...[...token.children].reverse());
    }
  }
  return { destinations, html };
}

const previewer = markdownit("commonmark", { html: false });

previewer.renderer.rules.image = (tokens, index, options, env, self) => {
  const token = tokens[index];
  const source = token.attrGet("src") || "";
  const alt = self.renderInlineAsText(token.children, options, env);
  const escaped = previewer.utils.escapeHtml(alt);
  if (source.startsWith(SCHEME)) {
    const url = env.images && env.images.get(source.slice(SCHEME.length));
    if (url) {
      return `<img src="${previewer.utils.escapeHtml(url)}" alt="${escaped}">`;
    }
    return `<span class="missing-image">${escaped || "missing image"}</span>`;
  }
  return escaped;
};

export function renderPreview(text, images) {
  return previewer.render(text, { images });
}
