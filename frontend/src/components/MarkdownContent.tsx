import React from "react";

/**
 * Normalize escaped Markdown strings returned by LLM APIs or double-encoded payloads
 * without corrupting fenced code blocks.
 */
export function normalizeMarkdownInput(raw: string): string {
  const crlfNormalized = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  // If literal "\n" sequences appear outside actual newlines, convert them to real newlines.
  const hasRealNewlines = crlfNormalized.includes("\n");
  const withNewlines = !hasRealNewlines && crlfNormalized.includes("\\n")
    ? crlfNormalized.replace(/\\n/g, "\n").replace(/\\t/g, "  ")
    : crlfNormalized.replace(/\\n(?=\s*(?:[#>*-]|\d+\.|\|))/g, "\n");

  // Unescape markdown punctuation outside fenced code blocks
  const segments = withNewlines.split(/(```[\s\S]*?```)/g);
  return segments
    .map((segment) => {
      if (segment.startsWith("```") && segment.endsWith("```")) {
        return segment;
      }
      return segment.replace(/\\([\\*_#`|\-[\]()>])/g, "$1");
    })
    .join("");
}

function isSafeHref(url: string): boolean {
  const trimmed = url.trim();
  return (
    trimmed.startsWith("https://") ||
    trimmed.startsWith("http://") ||
    trimmed.startsWith("/")
  );
}

function parseTableCells(line: string): string[] {
  const stripped = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return stripped.split("|").map((cell) => cell.trim());
}

function isTableSeparator(line: string): boolean {
  const cells = parseTableCells(line);
  return (
    cells.length > 0 &&
    cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  );
}

function parseTableAlignments(line: string): Array<"left" | "center" | "right"> {
  return parseTableCells(line).map((cell) => {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return "left";
  });
}

/**
 * Render inline formatting: inline code, links, bold, italic.
 * Splits on inline code first so identifiers like `subscription_charged` are preserved verbatim.
 */
function renderInline(text: string): React.ReactNode {
  const codeSegments = text.split(/(`[^`]+`)/g);
  return codeSegments.map((seg, codeIdx) => {
    if (seg.startsWith("`") && seg.endsWith("`") && seg.length >= 2) {
      return <code key={`c-${codeIdx}`}>{seg.slice(1, -1)}</code>;
    }

    // Tokenize links, bold (**...** or __...__), and italic (*...* or space-bounded _..._)
    const tokenRegex =
      /(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|(?<=^|\s)_[^_\n]+_(?=\s|[.,;:!?]|$))/g;
    const parts = seg.split(tokenRegex);

    return parts.map((part, idx) => {
      const k = `${codeIdx}-${idx}`;
      if (!part) return null;

      if (part.startsWith("[") && part.includes("](") && part.endsWith(")")) {
        const match = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (match) {
          if (isSafeHref(match[2])) {
            return (
              <a
                key={k}
                href={match[2].trim()}
                target="_blank"
                rel="noopener noreferrer"
              >
                {match[1]}
              </a>
            );
          }
          return match[1];
        }
      }

      if (
        (part.startsWith("**") && part.endsWith("**") && part.length > 4) ||
        (part.startsWith("__") && part.endsWith("__") && part.length > 4)
      ) {
        return <strong key={k}>{part.slice(2, -2)}</strong>;
      }

      if (
        (part.startsWith("*") && part.endsWith("*") && part.length > 2) ||
        (part.startsWith("_") && part.endsWith("_") && part.length > 2)
      ) {
        return <em key={k}>{part.slice(1, -1)}</em>;
      }

      return part;
    });
  });
}

export function MarkdownContent({ content }: { content: string }) {
  const normalized = normalizeMarkdownInput(content);
  const lines = normalized.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.trimStart().startsWith("```")) {
      const lang = line.trimStart().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push(
        <pre key={key++}>
          <code className={lang ? `language-${lang}` : undefined}>
            {codeLines.join("\n")}
          </code>
        </pre>
      );
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(?:---+|===+|\*\*\*+)\s*$/.test(line.trim())) {
      blocks.push(<hr key={key++} className="md-hr" />);
      i++;
      continue;
    }

    // Headings
    const headingMatch = line.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const body = renderInline(headingMatch[2].trim());
      if (level === 1) blocks.push(<h1 key={key++}>{body}</h1>);
      else if (level === 2) blocks.push(<h2 key={key++}>{body}</h2>);
      else if (level === 3) blocks.push(<h3 key={key++}>{body}</h3>);
      else blocks.push(<h4 key={key++}>{body}</h4>);
      i++;
      continue;
    }

    // Pipe table (header + separator + body rows)
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const headers = parseTableCells(line);
      const alignments = parseTableAlignments(lines[i + 1]);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(parseTableCells(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key++} className="table-wrap md-table-wrap">
          <table>
            <thead>
              <tr>
                {headers.map((h, colIdx) => (
                  <th
                    key={colIdx}
                    style={{ textAlign: alignments[colIdx] ?? "left" }}
                  >
                    {renderInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr key={rowIdx}>
                  {headers.map((_, colIdx) => {
                    const align = alignments[colIdx] ?? "left";
                    return (
                      <td
                        key={colIdx}
                        className={align === "right" ? "tabular" : undefined}
                        style={{ textAlign: align }}
                      >
                        {renderInline(row[colIdx] ?? "")}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Blockquote
    if (line.startsWith("> ") || line === ">") {
      const quoteLines: string[] = [];
      while (i < lines.length && (lines[i].startsWith("> ") || lines[i] === ">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={key++}>{renderInline(quoteLines.join(" "))}</blockquote>
      );
      continue;
    }

    // Unordered list
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        const text = lines[i].replace(/^\s*[-*•]\s+/, "");
        items.push(<li key={i}>{renderInline(text)}</li>);
        i++;
      }
      blocks.push(<ul key={key++}>{items}</ul>);
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const text = lines[i].replace(/^\s*\d+\.\s+/, "");
        items.push(<li key={i}>{renderInline(text)}</li>);
        i++;
      }
      blocks.push(<ol key={key++}>{items}</ol>);
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !/^(?:#{1,4}\s+|>\s?|---+$|===+$|\*\*\*+$|\s*[-*•]\s+|\s*\d+\.\s+)/.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1]))
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push(<p key={key++}>{renderInline(paraLines.join(" "))}</p>);
    }
  }

  return <div className="msg-content">{blocks}</div>;
}
