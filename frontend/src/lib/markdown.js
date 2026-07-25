import { marked } from "marked";

const renderer = new marked.Renderer();

// custom code block: header bar with language + copy button, like Claude's UI
renderer.code = ({ text, lang }) => {
  const esc = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const label = (lang || "").trim().split(/\s+/)[0] || "text";
  return `<div class="code-block">
    <div class="code-block-header">
      <span class="code-lang">${esc(label)}</span>
      <button class="copy-btn" type="button">Copy</button>
    </div>
    <pre><code>${esc(text)}</code></pre>
  </div>`;
};

marked.use({ renderer, gfm: true, breaks: true });

export function renderMarkdown(text) {
  return marked.parse(text);
}