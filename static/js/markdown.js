export function normalizeMarkdownSource(value) {
  return String(value || "").replace(/\\([*_`~])/g, "$1");
}

export function renderMarkdown(value) {
  const source = normalizeMarkdownSource(value);
  const markedEngine = window.marked;
  const sanitizer = window.DOMPurify;
  if (markedEngine?.parse && sanitizer?.sanitize) {
    try {
      const rawHtml = markedEngine.parse(source, {
        gfm: true,
        breaks: true,
      });
      if (hasUnresolvedMarkdown(rawHtml)) {
        return sanitizer.sanitize(renderMarkdownFallback(source));
      }
      return sanitizer.sanitize(rawHtml);
    } catch (error) {
      console.warn("Markdown engine failed; falling back to local parser.", error);
    }
  }
  return renderMarkdownFallback(source);
}

export function hasUnresolvedMarkdown(value) {
  const html = String(value || "");
  return /\*\*[^*\n]+?\*\*/u.test(html) || /__[^_\n]+?__/u.test(html);
}

export function renderMarkdownFallback(value) {
  const lines = String(value || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let codeLines = [];
  let inCodeBlock = false;

  const closeParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) {
      return;
    }
    html.push(`</${listType}>`);
    listType = "";
  };
  const closeCodeBlock = () => {
    if (!inCodeBlock) {
      return;
    }
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
    inCodeBlock = false;
  };

  let tableRows = [];
  let inTable = false;

  const flushTable = () => {
    if (!tableRows.length) return;
    const hasSep = tableRows.length >= 2 && tableRows[1].every(cell => /^-{2,}:?-{0,}$/.test(cell.trim()));
    const thead = hasSep
      ? `<thead><tr>${tableRows[0].map(c => `<th>${renderInlineMarkdown(c)}</th>`).join("")}</tr></thead>`
      : "";
    const bodyStart = hasSep ? 2 : 0;
    const bodyRows = tableRows.slice(bodyStart);
    const tbody = bodyRows.length
      ? `<tbody>${bodyRows.map(row => `<tr>${row.map(c => `<td>${renderInlineMarkdown(c)}</td>`).join("")}</tr>`).join("")}</tbody>`
      : "";
    html.push(`<table>${thead}${tbody}</table>`);
    tableRows = [];
    inTable = false;
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCodeBlock) {
        closeCodeBlock();
      } else {
        closeParagraph();
        closeList();
        inCodeBlock = true;
        codeLines = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      closeParagraph();
      closeList();
      if (inTable) flushTable();
      continue;
    }

    // Table row detection
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      if (!inTable) {
        closeParagraph();
        closeList();
        inTable = true;
        tableRows = [];
      }
      const cells = trimmed.slice(1, -1).split("|").map(c => c.trim());
      tableRows.push(cells);
      continue;
    }
    if (inTable) {
      flushTable();
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/u);
    if (heading) {
      closeParagraph();
      closeList();
      const level = Math.min(6, heading[1].length + 2);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/u);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/u);
    if (unordered || ordered) {
      closeParagraph();
      const nextType = ordered ? "ol" : "ul";
      if (listType !== nextType) {
        closeList();
        html.push(`<${nextType}>`);
        listType = nextType;
      }
      html.push(`<li>${renderInlineMarkdown((ordered || unordered)[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }

  closeCodeBlock();
  closeParagraph();
  closeList();
  if (inTable) flushTable();
  return html.join("") || escapeHtml(value);
}

export function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/_([^_]+)_/g, "<em>$1</em>");
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function stripMarkdown(value) {
  return normalizeMarkdownSource(value)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/[>#*_~|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
