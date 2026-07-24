// minimal markdown: fenced code, inline code, bold
export function renderMarkdown(text) {
  const esc = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const parts = text.split(/```(\w*)\n?([\s\S]*?)```/g);
  let out = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 3 === 0) {
      out += esc(parts[i])
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
    } else if (i % 3 === 2) {
      out += `<pre><code>${esc(parts[i])}</code></pre>`;
    }
  }
  return out;
}