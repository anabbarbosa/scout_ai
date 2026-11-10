// A small Markdown renderer for the weekly summaries (guide Step 6): headings, paragraphs,
// blockquotes, ordered and unordered lists (one level of nesting), tables, bold, italics,
// links and hard line breaks. Signal text comes from competitor websites, so everything is
// escaped first and only http(s) links are kept: no raw HTML ever reaches the page.

const escape = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function inline(raw) {
  let html = escape(raw);
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, url) =>
    /^https?:\/\//i.test(url)
      ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
      : label,
  );
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*\w])[*_]([^*_]+?)[*_](?=[^*\w]|$)/g, "$1<em>$2</em>");
  return html;
}

function cells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function renderMarkdown(source) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${inline(quote.join(" "))}</blockquote>`);
      continue;
    }
    if (line.trim().startsWith("|") && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1] || "")) {
      const aligns = cells(lines[i + 1]).map((c) => (c.endsWith(":") ? "right" : "left"));
      const head = cells(line)
        .map((c, n) => `<th style="text-align:${aligns[n] || "left"}">${inline(c)}</th>`)
        .join("");
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(
          "<tr>" +
            cells(lines[i++])
              .map((c, n) => `<td style="text-align:${aligns[n] || "left"}">${inline(c)}</td>`)
              .join("") +
            "</tr>",
        );
      }
      out.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`);
      continue;
    }
    if (/^(\d+\.|-)\s/.test(line)) {
      const ordered = /^\d+\./.test(line);
      const items = [];
      while (i < lines.length && lines[i].trim() && !/^#|^>|^\|/.test(lines[i])) {
        const current = lines[i];
        const top = /^(\d+\.|-)\s+(.*)$/.exec(current);
        const nested = /^\s+-\s+(.*)$/.exec(current);
        if (top && !/^\s/.test(current)) items.push({ text: [top[2]], children: [] });
        else if (nested && items.length) items.at(-1).children.push(nested[1]);
        else if (items.length) {
          const target = items.at(-1).children.length ? items.at(-1).children : items.at(-1).text;
          const last = target.length - 1;
          target[last] = `${target[last]}\n${current.trim()}`;
        }
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      const body = items
        .map((item) => {
          const text = item.text.map(breaks).join("<br>");
          const kids = item.children.length
            ? `<ul>${item.children.map((c) => `<li>${breaks(c)}</li>`).join("")}</ul>`
            : "";
          return `<li>${text}${kids}</li>`;
        })
        .join("");
      out.push(`<${tag}>${body}</${tag}>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^(#|>|\||\d+\.\s|-\s)/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    out.push(`<p>${breaks(paragraph.join("\n"))}</p>`);
  }
  return out.join("\n");
}

// A line ending in two spaces is a hard break; other newlines are spaces.
function breaks(text) {
  return text
    .split(/ {2,}\n/)
    .map((part) => inline(part.replace(/\n\s*/g, " ")))
    .join("<br>");
}
