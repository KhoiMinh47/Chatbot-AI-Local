"use client";

/**
 * Phase 8 Safe Markdown Renderer.
 *
 * Renders assistant answers containing basic Markdown structures (headers, bold,
 * italics, lists, tables, inline code, code blocks) safely into React elements
 * without using dangerouslySetInnerHTML, eliminating XSS vulnerabilities by design.
 *
 * It also renders stable chunk-bound citation tokens like
 * `[CITE:C0123456789abcdef0123456789abcdef]` as clickable UI components that
 * trigger `onCitationClick`.
 */

import React, { useMemo } from "react";

interface MarkdownProps {
  content: string;
  onCitationClick?: (citationId: string) => void;
}

export function Markdown({ content, onCitationClick }: MarkdownProps) {
  const renderedBlocks = useMemo(() => {
    if (!content) return null;

    // Split content into blocks by double newlines or single newlines that mark blocks
    const rawBlocks = content.split(/\n\s*\n/);
    const elements: React.ReactNode[] = [];
    let key = 0;

    let inCodeBlock = false;
    let codeLanguage = "";
    let codeContent: string[] = [];

    for (const block of rawBlocks) {
      const trimmed = block.trim();
      if (!trimmed) continue;

      // Handle Code Blocks
      if (trimmed.startsWith("```")) {
        if (inCodeBlock) {
          // Close code block
          elements.push(
            <pre
              key={key++}
              className="my-4 overflow-x-auto rounded-lg border border-[#28433b] bg-[#0d1916]/80 p-4 font-mono text-sm text-emerald-200"
            >
              <code className={codeLanguage ? `language-${codeLanguage}` : ""}>
                {codeContent.join("\n")}
              </code>
            </pre>,
          );
          inCodeBlock = false;
          codeContent = [];
        } else {
          // Open code block
          inCodeBlock = true;
          const match = trimmed.match(/^```(\w*)/);
          codeLanguage = match ? (match[1] ?? "") : "";
          const codeLines = trimmed.split("\n").slice(1);
          // If the block contains the end marker as well
          const lastLine = codeLines[codeLines.length - 1];
          if (lastLine?.endsWith("```")) {
            codeLines[codeLines.length - 1] = lastLine.slice(0, -3);
            elements.push(
              <pre
                key={key++}
                className="my-4 overflow-x-auto rounded-lg border border-[#28433b] bg-[#0d1916]/80 p-4 font-mono text-sm text-emerald-200"
              >
                <code
                  className={codeLanguage ? `language-${codeLanguage}` : ""}
                >
                  {codeLines.join("\n")}
                </code>
              </pre>,
            );
            inCodeBlock = false;
          } else {
            codeContent.push(...codeLines);
          }
        }
        continue;
      }

      if (inCodeBlock) {
        codeContent.push(block);
        continue;
      }

      // Handle Headers
      if (trimmed.startsWith("#")) {
        const match = trimmed.match(/^(#{1,6})\s+(.*)$/s);
        if (match) {
          const level = match[1]?.length ?? 1;
          const textContent = match[2] ?? "";
          const Tag = `h${level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
          const headerClasses = {
            h1: "text-3xl font-bold tracking-tight text-white mt-6 mb-4",
            h2: "text-2xl font-bold tracking-tight text-white mt-5 mb-3",
            h3: "text-xl font-semibold tracking-tight text-white mt-4 mb-2",
            h4: "text-lg font-semibold tracking-tight text-white mt-3 mb-2",
            h5: "text-base font-semibold text-slate-200 mt-2 mb-1",
            h6: "text-sm font-semibold text-slate-300 mt-2 mb-1",
          }[Tag];

          elements.push(
            <Tag key={key++} className={headerClasses}>
              {renderInline(textContent, onCitationClick)}
            </Tag>,
          );
          continue;
        }
      }

      // Handle Bullet Lists
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        const lines = trimmed.split("\n");
        const listItems = lines.map((line, idx) => {
          const itemText = line.replace(/^[-*]\s+/, "");
          return (
            <li key={idx} className="ml-4 list-disc pl-1 text-slate-300">
              {renderInline(itemText, onCitationClick)}
            </li>
          );
        });
        elements.push(
          <ul key={key++} className="my-3 space-y-1.5">
            {listItems}
          </ul>,
        );
        continue;
      }

      // Handle Numbered Lists
      if (/^\d+\.\s+/.test(trimmed)) {
        const lines = trimmed.split("\n");
        const listItems = lines.map((line, idx) => {
          const itemText = line.replace(/^\d+\.\s+/, "");
          return (
            <li key={idx} className="ml-4 list-decimal pl-1 text-slate-300">
              {renderInline(itemText, onCitationClick)}
            </li>
          );
        });
        elements.push(
          <ol key={key++} className="my-3 space-y-1.5">
            {listItems}
          </ol>,
        );
        continue;
      }

      // Handle Tables
      if (trimmed.includes("|") && trimmed.split("\n")[1]?.includes("-")) {
        const lines = trimmed.split("\n");
        const headerRow = lines[0];
        const bodyRows = lines.slice(2);

        if (headerRow) {
          const headers = headerRow
            .split("|")
            .map((h) => h.trim())
            .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);

          const rows = bodyRows
            .map((row) =>
              row
                .split("|")
                .map((cell) => cell.trim())
                .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1),
            )
            .filter((row) => row.length > 0);

          elements.push(
            <div
              key={key++}
              className="my-4 overflow-x-auto rounded-lg border border-[#28433b]"
            >
              <table className="w-full border-collapse text-left text-sm text-slate-300">
                <thead className="bg-[#0d1916] text-white">
                  <tr>
                    {headers.map((h, idx) => (
                      <th
                        key={idx}
                        className="border-b border-[#28433b] px-4 py-2 font-semibold"
                      >
                        {renderInline(h, onCitationClick)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIdx) => (
                    <tr
                      key={rowIdx}
                      className={
                        rowIdx % 2 === 0 ? "bg-white/5" : "bg-transparent"
                      }
                    >
                      {row.map((cell, cellIdx) => (
                        <td
                          key={cellIdx}
                          className="border-b border-[#28433b]/40 px-4 py-2"
                        >
                          {renderInline(cell, onCitationClick)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>,
          );
          continue;
        }
      }

      // Default to Paragraph
      elements.push(
        <p key={key++} className="mb-4 leading-7 text-balance text-slate-300">
          {renderInline(trimmed, onCitationClick)}
        </p>,
      );
    }

    return elements;
  }, [content, onCitationClick]);

  return <div className="markdown-content">{renderedBlocks}</div>;
}

// ------------------------------------------------------------ inline helper

function renderInline(
  text: string,
  onCitationClick?: (citationId: string) => void,
): React.ReactNode[] {
  // Regex to match markdown links, formatting, and stable chunk-bound citation IDs.
  // We match inline code (`code`), bold (**bold** or __bold__), italic (*italic* or _italic_),
  // citations ([CITE:C<uuid-hex>]), and standard markdown links ([text](url))
  const tokenRegex =
    /(`[^`]+`|\*\*[^*]+\*\*|_[^_]+_|\*[^*]+\*|\[CITE:C[0-9a-f]{32}\]|\[[^\]]+\]\([^)]+\))/g;

  const parts = text.split(tokenRegex);
  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={idx}
          className="rounded border border-[#28433b]/40 bg-[#0d1916] px-1.5 py-0.5 font-mono text-xs text-emerald-200"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={idx} className="font-bold text-white">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={idx} className="text-slate-200 italic">
          {part.slice(1, -1)}
        </em>
      );
    }
    if (part.startsWith("_") && part.endsWith("_")) {
      return (
        <em key={idx} className="text-slate-200 italic">
          {part.slice(1, -1)}
        </em>
      );
    }
    if (part.startsWith("[CITE:") && part.endsWith("]")) {
      const citationId = part.slice(6, -1);
      return (
        <button
          key={idx}
          type="button"
          onClick={() => onCitationClick?.(citationId)}
          className="mx-0.5 inline-flex items-center justify-center rounded bg-emerald-300/10 px-1 py-0.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-300/20 focus:ring-1 focus:ring-emerald-300 focus:outline-none"
          aria-label={`Xem nguồn trích dẫn ${citationId}`}
        >
          Nguồn
        </button>
      );
    }
    if (part.startsWith("[") && part.includes("](")) {
      const match = part.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (match) {
        const linkText = match[1] ?? "";
        const linkUrl = match[2] ?? "";
        return (
          <a
            key={idx}
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-300 underline transition-colors hover:text-emerald-200"
          >
            {linkText}
          </a>
        );
      }
    }
    return part;
  });
}
