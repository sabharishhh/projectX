import { marked } from "marked";
import hljs from "highlight.js";

let _currentSources = {};

function escapeAttr(s) {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// 1. Define a custom extension for citations
// This safely parses [1], [2] without breaking bold/italic markdown
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
        raw: match[0],      // The full match (e.g., "[1]")
        numStr: match[1],   // Just the number (e.g., "1")
      };
    }
  },
  renderer(token) {
    const src = _currentSources[Number(token.numStr)];
    if (!src) return token.raw; // Fallback to plain text if no source is found
    
    const label = src.title ? `${src.title} — ` : "";
    const preview = escapeAttr((label + (src.preview || "")).slice(0, 240));
    
    return `<span class="citation" data-preview="${preview}"><a href="${src.url}" target="_blank" rel="noreferrer">${token.numStr}</a></span>`;
  },
};

// 2. Pass the extension to marked.use() and remove the text() override
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
  _currentSources = sources;
  return marked.parse(text);
}