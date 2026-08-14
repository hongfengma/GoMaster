import { useMemo } from "react";

// 轻量、安全的 Markdown -> HTML 渲染（讲解文本足够；无需引入 react-markdown 重依赖）。
// 先转义 HTML 再套用有限 Markdown 语法，避免注入。
function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));
}

function inline(t: string): string {
  return escapeHtml(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

export default function MarkdownView({ text }: { text: string }) {
  const html = useMemo(() => {
    const lines = text.split(/\r?\n/);
    let out = "";
    let inList = false;
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      if (li) {
        if (!inList) {
          out += "<ul>";
          inList = true;
        }
        out += "<li>" + inline(li[1]) + "</li>";
        continue;
      } else if (inList) {
        out += "</ul>";
        inList = false;
      }
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) {
        const lv = h[1].length;
        out += `<h${lv}>${inline(h[2])}</h${lv}>`;
        continue;
      }
      const q = line.match(/^>\s?(.*)$/);
      if (q) {
        out += `<blockquote>${inline(q[1])}</blockquote>`;
        continue;
      }
      if (line.trim() === "") continue;
      out += "<p>" + inline(line) + "</p>";
    }
    if (inList) out += "</ul>";
    return out;
  }, [text]);

  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
