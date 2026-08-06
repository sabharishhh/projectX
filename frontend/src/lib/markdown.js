import { marked } from "marked";
import hljs from "highlight.js";

let _currentSources = {};

// OpenAI's Responses API occasionally leaks its own internal citation
// sentinel tokens into output_text instead of keeping them in the
// structured `annotations` field — observed pattern: \ue200 + "cite" +
// \ue202 + <number> + \ue201. The number is intact, so this recovers the
// citation into the [N] format citationExtension already expects, rather
// than just stripping it and losing the citation. Confirmed against real
// stored message content, not a guess at the shape.
const STRAY_CITATION_PATTERN = /\ue200cite\ue202(\d+)\ue201/g;

function escapeAttr(s) {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const citationExtension = {
  name: "citation",
  level: "inline",
  start(src) {
    return src.match(/\[\d+\](?!\()/)?.index;
  },
  tokenizer(src) {
    const rule = /^\[(\d+)\](?!\()/;
    const match = rule.exec(src);
    if (match) {
      return {
        type: "citation",
        raw: match[0],
        numStr: match[1],
      };
    }
  },
  renderer(token) {
    const src = _currentSources[Number(token.numStr)];
    if (!src) return token.raw;

    const label = src.title ? `${src.title} — ` : "";
    const preview = escapeAttr((label + (src.preview || "")).slice(0, 240));

    return `<span class="citation" data-preview="${preview}"><a href="${src.url}" target="_blank" rel="noreferrer">${token.numStr}</a></span>`;
  },
};

marked.use({
  gfm: true,
  breaks: true,
  extensions: [citationExtension],
  renderer: {
    code({ text, lang }) {
      const validLanguage = hljs.getLanguage(lang) ? lang : "plaintext";
      const highlighted = hljs.highlight(text, { language: validLanguage }).value;
      const label = (lang || "").trim().split(/\s+/)[0] || "text";
      return `<div class="code-block">
        <div class="code-block-header">
          <span class="code-lang">${label}</span>
          <button class="copy-btn" type="button">Copy</button>
        </div>
        <pre><code class="hljs ${validLanguage}">${highlighted}</code></pre>
      </div>`;
    }
  }
});

export function renderMarkdown(text, sources = {}) {
  const previousSources = _currentSources;
  _currentSources = sources;
  try {
    const normalized = text.replace(STRAY_CITATION_PATTERN, (_, num) => `[${num}]`);
    return marked.parse(normalized);
  } finally {
    _currentSources = previousSources;
  }
}